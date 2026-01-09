import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Conciliación cobros TPV", layout="wide")
st.title("Conciliación cobros TPV vs Albaranes")

st.markdown("""
- Extrae **Comercio / Terminal, Referencia e Importe** desde PDF TPV
- Convierte el PDF a Excel
- Concilia con Excel de albaranes
- Permite filtrar por **Comercio / Terminal**
- Exporta Excel con **coma decimal y sin separador de miles**
""")

# ==========================
# SUBIDA DE ARCHIVOS
# ==========================
pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])
excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==========================
# LECTOR PDF REAL (CLAVE)
# ==========================
def leer_pdf_tpv(pdf):
    registros = []

    patron_comercio = re.compile(r'^\d{9}\s*/$')       # 354015505/
    patron_terminal = re.compile(r'^\d{1,3}$')        # 10
    patron_importe = re.compile(r'\d+\.\d{2}')        # 153.49
    patron_ref = re.compile(r'\b\d{5}\b')             # 28637

    comercio_terminal_actual = ""

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            text = page.extract_text()
            if not text:
                continue

            lineas = [l.strip() for l in text.split("\n") if l.strip()]
            i = 0

            while i < len(lineas) - 1:

                # --- Comercio / Terminal en dos líneas ---
                if patron_comercio.match(lineas[i]) and patron_terminal.match(lineas[i + 1]):
                    comercio = lineas[i].replace("/", "")
                    terminal = lineas[i + 1]
                    comercio_terminal_actual = f"{comercio} / {terminal}"
                    i += 2
                    continue

                # --- Importe ---
                m_importe = patron_importe.search(lineas[i])
                if m_importe:
                    importe = float(m_importe.group())

                    # Buscar referencia cerca
                    ref = None
                    for j in range(i, min(i + 5, len(lineas))):
                        m_ref = patron_ref.search(lineas[j])
                        if m_ref:
                            ref = m_ref.group()
                            break

                    if ref:
                        registros.append({
                            "COMERCIO_TERMINAL": comercio_terminal_actual,
                            "REFERENCIA": ref,
                            "IMPORTE": importe
                        })

                i += 1

    return pd.DataFrame(registros)

# ==========================
# LIMPIEZA IMPORTES EXCEL
# ==========================
def limpiar_importe_excel(v):
    try:
        return float(str(v).replace(",", "."))
    except:
        return None

# ==========================
# PDF → TABLA
# ==========================
if pdf_file:
    st.subheader("PDF convertido a tabla")

    df_pdf = leer_pdf_tpv(pdf_file)

    df_vista_pdf = df_pdf.copy()
    df_vista_pdf["IMPORTE"] = df_vista_pdf["IMPORTE"].apply(
        lambda x: f"{x:.2f}".replace(".", ",")
    )

    st.dataframe(df_vista_pdf, use_container_width=True)

    buffer_pdf = BytesIO()
    df_vista_pdf.to_excel(buffer_pdf, index=False, engine="openpyxl")
    buffer_pdf.seek(0)

    st.download_button(
        "Descargar Excel del PDF",
        data=buffer_pdf,
        file_name="tpv_pdf_convertido.xlsx",
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
    # FILTRO COMERCIO
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
        "Descargar conciliación en Excel",
        data=buffer_out,
        file_name="conciliacion_tpv.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
