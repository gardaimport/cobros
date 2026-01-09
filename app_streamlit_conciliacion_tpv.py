import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Conciliación cobros TPV", layout="wide")
st.title("Conciliación de cobros TPV vs Albaranes")

# ==========================
# SUBIDA DE ARCHIVOS
# ==========================
pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])
excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==========================
# FUNCIONES
# ==========================
def pdf_a_tabla_excel(pdf):
    registros = []
    comercio_actual = ""

    patron_importe_ref = re.compile(r'(?P<importe>\d+\.\d{2}).*?(?P<ref>\d{5})')

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            text = page.extract_text()
            if not text:
                continue

            lineas = text.split("\n")

            for i, linea in enumerate(lineas):
                linea_limpia = linea.strip()

                # --- DETECCIÓN COMERCIO / TERMINAL ---
                if (
                    "comercio" in linea_limpia.lower()
                    and "terminal" in linea_limpia.lower()
                ):
                    valor = re.sub(
                        r'(?i).*comercio\s*/?\s*terminal[:\s]*',
                        '',
                        linea_limpia
                    ).strip()

                    # Si no hay valor, usar la línea siguiente
                    if not valor and i + 1 < len(lineas):
                        valor = lineas[i + 1].strip()

                    comercio_actual = valor

                # --- DETECCIÓN IMPORTE + REFERENCIA ---
                m = patron_importe_ref.search(linea_limpia)
                if m:
                    registros.append({
                        "COMERCIO_TERMINAL": comercio_actual,
                        "REFERENCIA": m.group("ref"),
                        "IMPORTE": float(m.group("importe"))
                    })

    df = pd.DataFrame(registros)

    buffer = BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)

    return df, buffer


def limpiar_importe_excel(valor):
    try:
        return float(str(valor).replace(",", "."))
    except:
        return None


# ==========================
# PREVISUALIZACIÓN PDF
# ==========================
if pdf_file:
    st.subheader("PDF convertido a tabla")
    df_pdf, buffer_pdf = pdf_a_tabla_excel(pdf_file)

    df_vista_pdf = df_pdf.copy()
    df_vista_pdf["IMPORTE"] = df_vista_pdf["IMPORTE"].apply(
        lambda x: f"{x:.2f}".replace(".", ",")
    )

    st.dataframe(df_vista_pdf, use_container_width=True)

    st.download_button(
        "Descargar Excel del PDF",
        data=buffer_pdf,
        file_name="tpv_convertido.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ==========================
# CONCILIACIÓN
# ==========================
if pdf_file and excel_file:
    st.success("Archivos cargados. Ejecutando conciliación…")

    df_tpv = df_pdf.copy()
    df_tpv["REFERENCIA"] = df_tpv["REFERENCIA"].astype(str)

    df_alb = pd.read_excel(excel_file)
    df_alb["Venta a-Nº cliente"] = df_alb["Venta a-Nº cliente"].astype(str)
    df_alb["IMPORTE_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(
        limpiar_importe_excel
    )

    tpv_agrupado = df_tpv.groupby(
        ["REFERENCIA", "COMERCIO_TERMINAL"],
        as_index=False
    )["IMPORTE"].sum()

    df_res = df_alb.merge(
        tpv_agrupado,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="REFERENCIA"
    )

    df_res.rename(columns={"IMPORTE": "IMPORTE_TPV"}, inplace=True)

    df_res["ESTADO COBRO"] = "NO COBRADO"
    df_res.loc[df_res["IMPORTE_TPV"].notna(), "ESTADO COBRO"] = "COBRADO"

    df_res["DIFERENCIA"] = df_res["IMPORTE_ALBARAN"] - df_res["IMPORTE_TPV"]

    df_res["OBSERVACIONES"] = ""
    df_res.loc[df_res["IMPORTE_TPV"].isna(), "OBSERVACIONES"] = "Sin cobro TPV"
    df_res.loc[
        (df_res["IMPORTE_TPV"].notna()) &
        (df_res["DIFERENCIA"].abs() > 0.01),
        "OBSERVACIONES"
    ] = "Importe distinto"

    # ==========================
    # FILTRO COMERCIO / TERMINAL
    # ==========================
    st.subheader("Filtro por Comercio / Terminal")

    opciones = ["Todos"] + sorted(
        df_res["COMERCIO_TERMINAL"].dropna().unique().tolist()
    )

    sel = st.selectbox("Selecciona comercio", opciones)

    if sel != "Todos":
        df_res = df_res[df_res["COMERCIO_TERMINAL"] == sel]

    # ==========================
    # VISTA FINAL
    # ==========================
    df_vista = df_res.copy()
    for c in ["IMPORTE_ALBARAN", "IMPORTE_TPV", "DIFERENCIA"]:
        if c in df_vista:
            df_vista[c] = df_vista[c].apply(
                lambda x: "" if pd.isna(x) else f"{x:.2f}".replace(".", ",")
            )

    st.subheader("Resultado conciliación")
    st.dataframe(df_vista, use_container_width=True)

    buffer_out = BytesIO()
    df_vista.to_excel(buffer_out, index=False, engine="openpyxl")
    buffer_out.seek(0)

    st.download_button(
        "Descargar conciliación",
        data=buffer_out,
        file_name="conciliacion_tpv.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
