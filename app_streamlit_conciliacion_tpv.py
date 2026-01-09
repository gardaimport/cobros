import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Conciliación cobros TPV", layout="wide")

st.title("Conciliación de cobros TPV vs Albaranes")

st.markdown("""
Esta aplicación permite:
- Subir un **PDF de cobros TPV**
- Extraer **Comercio / Terminal, Referencia e Importe**
- Convertir el PDF a **Excel**
- Conciliar con el **Excel de albaranes**
- Descargar resultado con **coma decimal y sin separador de miles**
""")

# ==========================
# CARGA DE ARCHIVOS
# ==========================
pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])
excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==========================
# FUNCIONES
# ==========================
def pdf_a_tabla_excel_linea(pdf):
    """
    Extrae:
    - Comercio/Terminal
    - Referencia (5 dígitos)
    - Importe con punto decimal
    """
    registros = []
    comercio_actual = None

    patron_comercio = re.compile(r'Comercio\s*/\s*Terminal[:\s]+(.+)', re.IGNORECASE)
    patron_linea = re.compile(r'(?P<importe>\d+\.\d{2}).*?(?P<ref>\d{5})')

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            text = page.extract_text()
            if not text:
                continue

            for linea in text.split("\n"):
                # Detectar comercio / terminal
                m_com = patron_comercio.search(linea)
                if m_com:
                    comercio_actual = m_com.group(1).strip()

                # Detectar importe + referencia
                m = patron_linea.search(linea)
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

    return buffer, df


def limpiar_importe(valor, origen):
    try:
        v = str(valor).replace("€", "").strip()
        if origen == "pdf":
            return float(v)
        if origen == "excel":
            return float(v.replace(",", "."))
    except:
        return None


def similitud(a, b):
    a, b = str(a), str(b)
    coincidencias = sum(1 for x, y in zip(a, b) if x == y)
    return coincidencias / max(len(a), len(b))


# ==========================
# PREVISUALIZACIÓN PDF
# ==========================
if pdf_file:
    st.subheader("Vista previa del PDF convertido a tabla")

    buffer_pdf, df_pdf = pdf_a_tabla_excel_linea(pdf_file)

    df_vista_pdf = df_pdf.copy()
    df_vista_pdf["IMPORTE"] = df_vista_pdf["IMPORTE"].apply(
        lambda x: f"{x:.2f}".replace(".", ",")
    )

    st.dataframe(df_vista_pdf, use_container_width=True)

    st.download_button(
        "Descargar Excel del PDF",
        data=buffer_pdf,
        file_name="pdf_tpv_convertido.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ==========================
# CONCILIACIÓN
# ==========================
if pdf_file and excel_file:
    st.success("Archivos cargados. Realizando conciliación...")

    df_tpv = df_pdf.copy()
    df_tpv["REFERENCIA"] = df_tpv["REFERENCIA"].astype(str)
    df_tpv["IMPORTE_TPV"] = df_tpv["IMPORTE"].apply(lambda x: limpiar_importe(x, "pdf"))

    df_alb = pd.read_excel(excel_file)
    df_alb["Venta a-Nº cliente"] = df_alb["Venta a-Nº cliente"].astype(str)
    df_alb["IMPORTE_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(
        lambda x: limpiar_importe(x, "excel")
    )

    tpv_agrupado = df_tpv.groupby(
        ["REFERENCIA", "COMERCIO_TERMINAL"],
        as_index=False
    )["IMPORTE_TPV"].sum()

    df_resultado = df_alb.merge(
        tpv_agrupado,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="REFERENCIA"
    )

    df_resultado["ESTADO COBRO"] = "NO COBRADO"
    df_resultado.loc[df_resultado["IMPORTE_TPV"].notna(), "ESTADO COBRO"] = "COBRADO"

    df_resultado["DIFERENCIA"] = (
        df_resultado["IMPORTE_ALBARAN"] - df_resultado["IMPORTE_TPV"]
    )

    df_resultado["OBSERVACIONES"] = ""
    df_resultado.loc[
        df_resultado["ESTADO COBRO"] == "NO COBRADO",
        "OBSERVACIONES"
    ] = "Sin cobro TPV"

    df_resultado.loc[
        (df_resultado["ESTADO COBRO"] == "COBRADO") &
        (df_resultado["DIFERENCIA"].abs() > 0.01),
        "OBSERVACIONES"
    ] = "Importe no coincide"

    # Vista Streamlit con coma decimal
    df_vista = df_resultado.copy()
    for col in ["IMPORTE_ALBARAN", "IMPORTE_TPV", "DIFERENCIA"]:
        if col in df_vista:
            df_vista[col] = df_vista[col].apply(
                lambda x: "" if pd.isna(x) else f"{x:.2f}".replace(".", ",")
            )

    st.subheader("Resultado de la conciliación")
    st.dataframe(df_vista, use_container_width=True)

    # Exportación final
    df_export = df_resultado.copy()
    for col in ["IMPORTE_ALBARAN", "IMPORTE_TPV", "DIFERENCIA"]:
        if col in df_export:
            df_export[col] = df_export[col].apply(
                lambda x: "" if pd.isna(x) else f"{x:.2f}".replace(".", ",")
            )

    buffer_out = BytesIO()
    df_export.to_excel(buffer_out, index=False, engine="openpyxl")
    buffer_out.seek(0)

    st.download_button(
        "Descargar conciliación en Excel",
        data=buffer_out,
        file_name="conciliacion_tpv.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Sube ambos archivos para iniciar la conciliación")
