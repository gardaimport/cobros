import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Conciliación TPV", layout="wide")
st.title("Conciliación cobros TPV vs Albaranes")

pdf_file = st.file_uploader("Sube el PDF TPV", type=["pdf"])
excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==========================
# LECTOR PDF ROBUSTO
# ==========================
def leer_pdf_tpv(pdf, debug=False):
    registros = []
    comercio_terminal_actual = ""

    patron_importe = re.compile(r'\d+\.\d{2}')
    patron_ref = re.compile(r'\b\d{5}\b')

    debug_lineas = []

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            text = page.extract_text()
            if not text:
                continue

            lineas = [l.strip() for l in text.split("\n") if l.strip()]
            debug_lineas.extend(lineas)

            i = 0
            while i < len(lineas):

                linea = lineas[i]

                # ==========================
                # COMERCIO / TERMINAL (ROBUSTO)
                # ==========================
                if "/" in linea and sum(c.isdigit() for c in linea) >= 9:
                    numeros = re.findall(r'\d+', linea)

                    if len(numeros) >= 1:
                        comercio = numeros[0]
                        terminal = None

                        # ¿Terminal en la misma línea?
                        if len(numeros) >= 2:
                            terminal = numeros[1]

                        # ¿Terminal en la siguiente?
                        elif i + 1 < len(lineas):
                            if lineas[i + 1].isdigit():
                                terminal = lineas[i + 1]

                        if terminal:
                            comercio_terminal_actual = f"{comercio} / {terminal}"

                # ==========================
                # IMPORTE
                # ==========================
                m_imp = patron_importe.search(linea)
                if m_imp:
                    importe = float(m_imp.group())

                    ref = None
                    for j in range(i, min(i + 6, len(lineas))):
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

    df = pd.DataFrame(registros)
    return df, debug_lineas


def limpiar_importe_excel(v):
    try:
        return float(str(v).replace(",", "."))
    except:
        return None


# ==========================
# PDF → TABLA + DEBUG
# ==========================
if pdf_file:
    st.subheader("PDF convertido a tabla")

    df_pdf, debug_lineas = leer_pdf_tpv(pdf_file, debug=True)

    df_vista_pdf = df_pdf.copy()
    df_vista_pdf["IMPORTE"] = df_vista_pdf["IMPORTE"].apply(
        lambda x: f"{x:.2f}".replace(".", ",")
    )

    st.dataframe(df_vista_pdf, use_container_width=True)

    # ===== DEBUG REAL =====
    with st.expander("🔍 Ver texto REAL leído del PDF (diagnóstico)"):
        st.write(debug_lineas)

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
    st.success("Conciliando…")

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

    st.subheader("Resultado conciliación")

    df_vista = df_res.copy()
    for c in ["IMPORTE_ALBARAN", "IMPORTE_TPV", "DIFERENCIA"]:
        if c in df_vista:
            df_vista[c] = df_vista[c].apply(
                lambda x: "" if pd.isna(x) else f"{x:.2f}".replace(".", ",")
            )

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
