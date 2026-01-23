import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Conciliación TPV", layout="wide")
st.title("Conciliación de cobros TPV vs Albaranes")

pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])
excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==========================================================
# LECTOR PDF
# ==========================================================
def leer_pdf_tpv(pdf):
    registros = []
    terminal_actual = ""

    patron_importe = re.compile(r"\d+\.\d{2}")
    patron_ref = re.compile(r"\b\d{5}\b")

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            texto = page.extract_text()
            if not texto:
                continue

            lineas = [l.strip() for l in texto.split("\n") if l.strip()]
            i = 0

            while i < len(lineas):
                linea = lineas[i]

                # Terminal
                if "/" in linea and sum(c.isdigit() for c in linea) >= 9:
                    nums = re.findall(r"\d+", linea)
                    if len(nums) >= 1:
                        if len(nums) >= 2:
                            terminal_actual = nums[1]
                        elif i + 1 < len(lineas) and lineas[i + 1].isdigit():
                            terminal_actual = lineas[i + 1]

                # Importe
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
                            "REFERENCIA_TPV": ref,
                            "IMPORTE_TPV": importe,
                            "TERMINAL_TPV": terminal_actual
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

    # TPV por referencia
    tpv_ref = df_tpv.groupby("REFERENCIA_TPV", as_index=False).agg({
        "IMPORTE_TPV": "sum",
        "TERMINAL_TPV": "first"
    })

    # Cruce
    df_res = df_alb.merge(
        tpv_ref,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="REFERENCIA_TPV"
    )

    df_res = df_res.merge(
        tot_cliente,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="CLIENTE"
    )

    df_res["ESTADO COBRO"] = "NO COBRADO"
    df_res["OBSERVACIONES"] = ""

    # Coincidencia individual correcta
    mask_ind_ok = df_res["IMPORTE_TPV"].notna() & (abs(df_res["IMPORTE_ALBARAN"] - df_res["IMPORTE_TPV"]) < 0.01)
    df_res.loc[mask_ind_ok, "ESTADO COBRO"] = "COBRADO"
    df_res.loc[mask_ind_ok, "OBSERVACIONES"] = "Cobro individual correcto"

    # Coincidencia por total cliente con referencia correcta
    mask_total_ok = (
        df_res["IMPORTE_TPV"].notna() &
        (~mask_ind_ok) &
        (abs(df_res["TOTAL_CLIENTE"] - df_res["IMPORTE_TPV"]) < 0.01)
    )

    df_res.loc[mask_total_ok, "ESTADO COBRO"] = "COBRADO"
    df_res.loc[mask_total_ok, "OBSERVACIONES"] = df_res[mask_total_ok].apply(
        lambda r: f"Cobrado {r['IMPORTE_TPV']:.2f} (total de {int(r['NUM_ALBARANES'])} albaranes)",
        axis=1
    )

    # Buscar coincidencias por importe con referencia incorrecta
    for idx, row in df_res[df_res["ESTADO COBRO"] == "NO COBRADO"].iterrows():
        total = row["TOTAL_CLIENTE"]
        importe_ind = row["IMPORTE_ALBARAN"]
        cliente = row["Venta a-Nº cliente"]

        candidatos = df_tpv[
            (abs(df_tpv["IMPORTE_TPV"] - importe_ind) < 0.01) |
            (abs(df_tpv["IMPORTE_TPV"] - total) < 0.01)
        ]

        if len(candidatos) == 1:
            tpv = candidatos.iloc[0]
            df_res.at[idx, "IMPORTE_TPV"] = tpv["IMPORTE_TPV"]
            df_res.at[idx, "TERMINAL_TPV"] = tpv["TERMINAL_TPV"]
            df_res.at[idx, "ESTADO COBRO"] = "COBRADO"

            if abs(tpv["IMPORTE_TPV"] - importe_ind) < 0.01:
                df_res.at[idx, "OBSERVACIONES"] = f"Cobrado {tpv['IMPORTE_TPV']:.2f} – posible error de referencia (TPV: {tpv['REFERENCIA_TPV']})"
            else:
                df_res.at[idx, "OBSERVACIONES"] = f"Cobrado {tpv['IMPORTE_TPV']:.2f} (total de {int(row['NUM_ALBARANES'])} albaranes) – posible error de referencia (TPV: {tpv['REFERENCIA_TPV']})"

        elif len(candidatos) > 1:
            df_res.at[idx, "OBSERVACIONES"] = "Hay varios cobros TPV con este importe, revisar manualmente"
        else:
            df_res.at[idx, "OBSERVACIONES"] = "Sin cobro TPV"

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
