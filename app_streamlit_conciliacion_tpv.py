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
# LECTOR PDF COMPLETO
# ==================================================
def leer_pdf_tpv(pdf):
    registros = []
    comercio = ""
    terminal = ""

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

                # Comercio / Terminal
                if "/" in linea and sum(c.isdigit() for c in linea) >= 9:
                    nums = re.findall(r'\d+', linea)
                    if len(nums) >= 1:
                        comercio = nums[0]
                        if len(nums) >= 2:
                            terminal = nums[1]
                        elif i + 1 < len(lineas) and lineas[i + 1].isdigit():
                            terminal = lineas[i + 1]

                # Movimiento
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
                            "REFERENCIA": ref,
                            "IMPORTE_TPV": importe,
                            "TERMINAL_TPV": terminal
                        })

                i += 1

    return pd.DataFrame(registros)

def limpiar_importe_excel(v):
    try:
        return float(str(v).replace(",", "."))
    except:
        return None

# ==================================================
# PROCESO
# ==================================================
if pdf_file and excel_file:
    df_tpv = leer_pdf_tpv(pdf_file)
    df_alb = pd.read_excel(excel_file)

    df_alb["Venta a-Nº cliente"] = df_alb["Venta a-Nº cliente"].astype(str)
    df_alb["IMPORTE_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(limpiar_importe_excel)

    # Totales por cliente (albaranes)
    totales_cliente = df_alb.groupby("Venta a-Nº cliente")["IMPORTE_ALBARAN"].agg(["sum", "count"]).reset_index()
    totales_cliente.columns = ["CLIENTE", "TOTAL_CLIENTE", "NUM_ALBARANES"]

    # Totales TPV por referencia
    tpv_por_ref = df_tpv.groupby("REFERENCIA", as_index=False).agg({
        "IMPORTE_TPV": "sum",
        "TERMINAL_TPV": "first"
    })

    df_res = df_alb.merge(
        tpv_por_ref,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="REFERENCIA"
    )

    df_res = df_res.merge(
        totales_cliente,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="CLIENTE"
    )

    df_res["ESTADO COBRO"] = "NO COBRADO"
    df_res["OBSERVACIONES"] = ""

    # Coincidencia directa
    mask_directo = df_res["IMPORTE_TPV"].notna() & (abs(df_res["IMPORTE_ALBARAN"] - df_res["IMPORTE_TPV"]) < 0.01)
    df_res.loc[mask_directo, "ESTADO COBRO"] = "COBRADO"
    df_res.loc[mask_directo, "OBSERVACIONES"] = "Cobro individual correcto"

    # Coincidencia por total cliente
    mask_total = (
        df_res["IMPORTE_TPV"].notna() &
        (~mask_directo) &
        (abs(df_res["TOTAL_CLIENTE"] - df_res["IMPORTE_TPV"]) < 0.01)
    )

    df_res.loc[mask_total, "ESTADO COBRO"] = "COBRADO"
    df_res.loc[mask_total, "OBSERVACIONES"] = df_res[mask_total].apply(
        lambda r: f"Cobrado {r['IMPORTE_TPV']:.2f} (total de {int(r['NUM_ALBARANES'])} albaranes) – posible error de referencia",
        axis=1
    )

    # Sin cobro
    df_res.loc[df_res["IMPORTE_TPV"].isna(), "OBSERVACIONES"] = "Sin cobro TPV"

    # Formato visual
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
    st.info("Sube el PDF y el Excel para comenzar.")
