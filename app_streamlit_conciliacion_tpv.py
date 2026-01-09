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

    patron_comercio_terminal = re.compile(r'^\d{9}\s*/$')
    patron_importe = re.compile(r'(\d+\.\d{2})')
    patron_referencia = re.compile(r'\b(\d{5})\b')

    comercio_terminal_actual = ""

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            text = page.extract_text()
            if not text:
                continue

            lineas = [l.strip() for l in text.split("\n") if l.strip()]

            i = 0
            while i < len(lineas) - 1:

                # --- COMERCIO / TERMINAL (2 líneas) ---
                if patron_comercio_terminal.match(lineas[i]):
                    comercio = lineas[i].replace("/", "").strip()
                    terminal = lineas[i + 1].strip()
                    comercio_terminal_actual = f"{comercio} / {terminal}"
                    i += 2
                    continue

                # --- IMPORTE ---
                m_importe = patron_importe.search(lineas[i])
                if m_importe:
                    importe = float(m_importe.group(1))

                    # Buscar referencia en las siguientes líneas
                    ref = None
                    for j in range(i, min(i + 4, len(lineas))):
                        m_ref = patron_referencia.search(lineas[j])
                        if m_ref:
                            ref = m_ref.group(1)
                            break

                    if ref:
                        registros.append({
                            "COMERCIO_TERMINAL": comercio_terminal_actual,
                            "REFERENCIA": ref,
                            "IMPORTE": importe
                        })

                i += 1

    return pd.DataFrame(registros)


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
