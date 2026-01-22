import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Conciliación TPV", layout="wide")
st.title("Conciliación cobros TPV vs Albaranes")

pdf_file = st.file_uploader("Sube el PDF TPV", type=["pdf"])
excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==================================================
# LECTOR PDF COMPLETO (UNA FILA = UN MOVIMIENTO)
# ==================================================
def leer_pdf_tpv(pdf):
    registros = []
    comercio = ""
    terminal = ""

    patron_fecha = re.compile(r'\d{4}-\d{2}-\d{2}')
    patron_hora = re.compile(r'\d{2}:\d{2}:\d{2}')
    patron_importe = re.compile(r'\d+\.\d{2}')
    patron_ref = re.compile(r'\b\d{5}\b')

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            text = page.extract_text()
            if not text:
                continue

            lineas = [l.strip() for l in text.split("\n") if l.strip()]
            i = 0

            while i < len(lineas):

                linea = lineas[i]

                # -------------------------------
                # COMERCIO / TERMINAL (ROBUSTO)
                # -------------------------------
                if "/" in linea and sum(c.isdigit() for c in linea) >= 9:
                    nums = re.findall(r'\d+', linea)
                    if len(nums) >= 1:
                        comercio = nums[0]
                        if len(nums) >= 2:
                            terminal = nums[1]
                        elif i + 1 < len(lineas) and lineas[i + 1].isdigit():
                            terminal = lineas[i + 1]

                # -------------------------------
                # MOVIMIENTO TPV
                # -------------------------------
                m_imp = patron_importe.search(linea)
                if m_imp:
                    importe = float(m_imp.group())

                    fecha = ""
                    hora = ""
                    referencia = ""

                    # Buscar datos alrededor
                    for j in range(i, min(i + 6, len(lineas))):
                        if not fecha:
                            m_f = patron_fecha.search(lineas[j])
                            if m_f:
                                fecha = m_f.group()

                        if not hora:
                            m_h = patron_hora.search(lineas[j])
                            if m_h:
                                hora = m_h.group()

                        if not referencia:
                            m_r = patron_ref.search(lineas[j])
                            if m_r:
                                referencia = m_r.group()

                    if referencia:
                        registros.append({
                            "FECHA": fecha,
                            "HORA": hora,
                            "COMERCIO": comercio,
                            "TERMINAL_TPV": terminal,
                            "REFERENCIA": referencia,
                            "IMPORTE_TPV": importe,
                            "LINEA_ORIGEN": linea
                        })

                i += 1

    return pd.DataFrame(registros)


def limpiar_importe_excel(v):
    try:
        return float(str(v).replace(",", "."))
    except:
        return None


# ==================================================
# PDF → TABLA COMPLETA
# ==================================================
if pdf_file:
    st.subheader("PDF convertido a tabla completa")

    df_pdf = leer_pdf_tpv(pdf_file)

    df_vista_pdf = df_pdf.copy()
    df_vista_pdf["IMPORTE_TPV"] = df_vista_pdf["IMPORTE_TPV"].apply(
        lambda x: f"{x:.2f}".replace(".", ",")
    )

    st.dataframe(df_vista_pdf, use_container_width=True)

    buffer_pdf = BytesIO()
    df_vista_pdf.to_excel(buffer_pdf, index=False, engine="openpyxl")
    buffer_pdf.seek(0)

    st.download_button(
        "Descargar Excel completo del PDF",
        data=buffer_pdf,
        file_name="tpv_pdf_completo.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ==================================================
# CONCILIACIÓN
# ==================================================
if pdf_file and excel_file:
    st.success("Ejecutando conciliación…")

    df_tpv = df_pdf.copy()
    df_tpv["REFERENCIA"] = df_tpv["REFERENCIA"].astype(str)

    df_alb = pd.read_excel(excel_file)
    df_alb["Venta a-Nº cliente"] = df_alb["Venta a-Nº cliente"].astype(str)
    df_alb["IMPORTE_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(
        limpiar_importe_excel
    )

    # Agrupar TPV (si un cliente paga varias veces)
    tpv_agrupado = df_tpv.groupby(
        ["REFERENCIA", "TERMINAL_TPV"],
        as_index=False
    )["IMPORTE_TPV"].sum()

    df_res = df_alb.merge(
        tpv_agrupado,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="REFERENCIA"
    )

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

    # Formato final
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
