import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Comprobación COBROS TPV", layout="wide")
st.title("Comprobación COBROS TPV")

pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])
excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==========================================================
# LECTOR PDF
# ==========================================================
def leer_pdf_tpv(pdf):
    registros = []

    patron_importe = re.compile(r"\b\d+\.\d{2}\b")
    patron_ref = re.compile(r"\b\d{5}\b")
    patron_resultado = re.compile(r"\b(AUTORIZADA|DENEGADA)\b")

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            texto = page.extract_text()
            if not texto:
                continue

            lineas = [l.strip() for l in texto.split("\n") if l.strip()]
            i = 0
            while i < len(lineas):
                linea = lineas[i]
                # Detectar importe
                m_imp = patron_importe.search(linea)
                if m_imp:
                    importe = float(m_imp.group())
                    ref = None
                    resultado = None
                    # Buscar referencia y resultado en las siguientes líneas
                    for j in range(i, min(i + 10, len(lineas))):
                        if not ref:
                            m_ref = patron_ref.search(lineas[j])
                            if m_ref:
                                ref = m_ref.group()
                        if not resultado:
                            m_res = patron_resultado.search(lineas[j])
                            if m_res:
                                resultado = m_res.group()
                    if ref and resultado == "AUTORIZADA":
                        registros.append({
                            "REFERENCIA_TPV": ref,
                            "IMPORTE_TPV": importe,
                            "RESULTADO_TPV": resultado
                        })
                i += 1
    return pd.DataFrame(registros)


def limpiar_importe_excel(v):
    try:
        return float(str(v).replace(",", "."))
    except:
        return None

# ==========================================================
# VISTA PREVIA PDF
# ==========================================================
if pdf_file:
    st.subheader("Vista previa cobros TPV")
    df_pdf = leer_pdf_tpv(pdf_file)
    df_preview = df_pdf.copy()
    df_preview["IMPORTE_TPV"] = df_preview["IMPORTE_TPV"].apply(lambda x: f"{x:.2f}".replace(".", ","))
    st.dataframe(df_preview, use_container_width=True)

# ==========================================================
# CONCILIACIÓN
# ==========================================================
if pdf_file and excel_file:

    df_tpv = leer_pdf_tpv(pdf_file)
    df_alb = pd.read_excel(excel_file)

    df_alb["Venta a-Nº cliente"] = df_alb["Venta a-Nº cliente"].astype(str)
    df_alb["IMPORTE_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(limpiar_importe_excel)

    # Totales por cliente
    tot_cliente = df_alb.groupby("Venta a-Nº cliente")["IMPORTE_ALBARAN"].agg(["sum", "count"]).reset_index()
    tot_cliente.columns = ["CLIENTE", "TOTAL_CLIENTE", "NUM_ALBARANES"]

    # Cruce básico por referencia
    df_res = df_alb.merge(
        df_tpv.groupby("REFERENCIA_TPV", as_index=False)["IMPORTE_TPV"].sum(),
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="REFERENCIA_TPV"
    ).merge(
        tot_cliente,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="CLIENTE"
    )

    df_res["ESTADO COBRO"] = "NO COBRADO"
    df_res["OBSERVACIONES"] = ""

    # Cobro exacto por referencia
    mask_ref_ok = df_res["IMPORTE_TPV"].notna()
    df_res.loc[mask_ref_ok, "ESTADO COBRO"] = "COBRADO"

    # Calculamos diferencia con total cliente
    def observaciones_total(row):
        diff = row["IMPORTE_TPV"] - row["TOTAL_CLIENTE"]
        texto = f"Cobrado {row['IMPORTE_TPV']:.2f} (total de {int(row['NUM_ALBARANES'])} albaranes)"
        if abs(diff) > 0.01:
            if diff > 0:
                texto += " – posible cobro albaranes atrasados"
            else:
                texto += " – posible abono pendiente"
        # Revisar duplicados exactos
        duplicados = df_tpv[(df_tpv["REFERENCIA_TPV"] == row["Venta a-Nº cliente"]) &
                            (df_tpv["IMPORTE_TPV"] == row["IMPORTE_TPV"])]
        if len(duplicados) > 1:
            texto += " – cobro duplicado, revisar"
        return texto

    df_res.loc[mask_ref_ok, "OBSERVACIONES"] = df_res[mask_ref_ok].apply(observaciones_total, axis=1)

    # Formato final
    df_vista = df_res.copy()
    for c in ["IMPORTE_ALBARAN", "IMPORTE_TPV", "TOTAL_CLIENTE"]:
        df_vista[c] = df_vista[c].apply(lambda x: "" if pd.isna(x) else f"{x:.2f}".replace(".", ","))

    st.subheader("Resultado conciliación")
    st.dataframe(df_vista, use_container_width=True)

    buffer = BytesIO()
    df_vista.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)

    st.download_button(
        "Descargar conciliación en Excel",
        data=buffer,
        file_name="conciliacion_tpv.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Sube el PDF y el Excel para comenzar la conciliación.")
