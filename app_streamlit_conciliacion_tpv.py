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

                m_imp = patron_importe.search(linea)
                if m_imp:
                    importe = float(m_imp.group())
                    ref = None
                    resultado = None

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
                            "REF_TPV": ref,
                            "IMP_TPV": importe
                        })

                i += 1

    return pd.DataFrame(registros)

def limpiar_importe_excel(v):
    try:
        return float(str(v).replace(",", "."))
    except:
        return None

def formato_coma(x):
    return "" if pd.isna(x) else f"{x:.2f}".replace(".", ",")

# ==========================================================
# AUTOAJUSTE COLUMNAS EXCEL
# ==========================================================
def autoajustar_columnas(writer, df, sheet_name):
    worksheet = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns):
        max_len = max(
            df[col].astype(str).map(len).max(),
            len(col)
        ) + 2
        worksheet.column_dimensions[chr(65 + i)].width = max_len

# ==========================================================
# VISTA PREVIA PDF
# ==========================================================
if pdf_file:
    st.subheader("Vista previa cobros TPV (solo AUTORIZADOS)")
    df_pdf = leer_pdf_tpv(pdf_file)
    df_prev = df_pdf.copy()
    df_prev["IMP_TPV"] = df_prev["IMP_TPV"].apply(formato_coma)
    st.dataframe(df_prev, use_container_width=True)

# ==========================================================
# CONCILIACIÓN
# ==========================================================
if pdf_file and excel_file:

    df_tpv = leer_pdf_tpv(pdf_file)

    # Mantener ceros iniciales
    df_alb = pd.read_excel(excel_file, dtype={"Venta a-Nº cliente": str})

    df_alb["IMP_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(limpiar_importe_excel)

    # Totales por cliente
    tot_cliente = df_alb.groupby("Venta a-Nº cliente")["IMP_ALBARAN"].agg(["sum", "count"]).reset_index()
    tot_cliente.columns = ["CLIENTE", "TOTAL_CLIENTE", "NUM_ALBARANES"]

    # TPV por referencia
    tpv_ref = df_tpv.groupby("REF_TPV", as_index=False)["IMP_TPV"].sum()

    # Duplicados exactos
    duplicados = df_tpv.groupby(["REF_TPV", "IMP_TPV"]).size().reset_index(name="VECES")
    duplicados = duplicados[duplicados["VECES"] > 1]

    # Cruce principal
    df_res = df_alb.merge(
        tpv_ref,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="REF_TPV"
    ).merge(
        tot_cliente,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="CLIENTE"
    )

    df_res["ESTADO COBRO"] = "NO COBRADO"
    df_res["OBSERVACIONES"] = ""

    mask_ref = df_res["IMP_TPV"].notna()
    df_res.loc[mask_ref, "ESTADO COBRO"] = "COBRADO"
    df_res.loc[mask_ref, "DIF_TOTAL"] = df_res["IMP_TPV"] - df_res["TOTAL_CLIENTE"]

    for idx, row in df_res[mask_ref].iterrows():
        dif = row["DIF_TOTAL"]

        if abs(dif) < 0.01:
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado {formato_coma(row['IMP_TPV'])} (total de {int(row['NUM_ALBARANES'])} albaranes)"
        elif dif > 0:
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de más {formato_coma(row['IMP_TPV'])} – posible cobro albaranes atrasados"
        else:
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de menos {formato_coma(row['IMP_TPV'])} – posible abono pendiente"

    # Coincidencia por total con referencia errónea
    for idx, row in df_res[df_res["ESTADO COBRO"] == "NO COBRADO"].iterrows():
        total = row["TOTAL_CLIENTE"]
        candidato = df_tpv[abs(df_tpv["IMP_TPV"] - total) < 0.01]

        if len(candidato) == 1:
            tpv = candidato.iloc[0]
            df_res.at[idx, "IMP_TPV"] = tpv["IMP_TPV"]
            df_res.at[idx, "REF_TPV"] = tpv["REF_TPV"]
            df_res.at[idx, "ESTADO COBRO"] = "COBRADO"
            df_res.at[idx, "OBSERVACIONES"] = (
                f"Cobrado {formato_coma(tpv['IMP_TPV'])} "
                f"(total de {int(row['NUM_ALBARANES'])} albaranes) – posible error de referencia (TPV: {tpv['REF_TPV']})"
            )

    # Aviso duplicados
    for _, d in duplicados.iterrows():
        mask = (df_res["REF_TPV"] == d["REF_TPV"]) & (df_res["IMP_TPV"] == d["IMP_TPV"])
        df_res.loc[mask, "OBSERVACIONES"] += " | POSIBLE COBRO DUPLICADO"

    # Formato hoja 1
    df_vista = df_res.copy()
    df_vista["IMP_ALBARAN"] = df_vista["IMP_ALBARAN"].apply(formato_coma)
    df_vista["IMP_TPV"] = df_vista["IMP_TPV"].apply(formato_coma)
    df_vista["TOTAL_CLIENTE"] = df_vista["TOTAL_CLIENTE"].apply(formato_coma)

    st.subheader("Resultado conciliación")
    st.dataframe(df_vista, use_container_width=True)

    # ==========================================================
    # HOJA 2: COBROS SIN ALBARÁN
    # ==========================================================
    refs_excel = set(df_alb["Venta a-Nº cliente"].astype(str))
    totales_excel = set(tot_cliente["TOTAL_CLIENTE"].round(2))

    df_sin = df_tpv.copy()
    df_sin = df_sin[
        (~df_sin["REF_TPV"].isin(refs_excel)) &
        (~df_sin["IMP_TPV"].round(2).isin(totales_excel))
    ]

    df_sin["IMP_TPV"] = df_sin["IMP_TPV"].apply(formato_coma)

    # ==========================================================
    # DESCARGA EXCEL CON AUTOAJUSTE
    # ==========================================================
    buffer = BytesIO()
    st.markdown("### Nombre del archivo de descarga")
    nombre_excel = st.text_input("Escribe el nombre del Excel (sin .xlsx)", "conciliacion_tpv")

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_vista.to_excel(writer, index=False, sheet_name="Conciliación albaranes")
        df_sin.to_excel(writer, index=False, sheet_name="Cobros sin albarán")

        autoajustar_columnas(writer, df_vista, "Conciliación albaranes")
        autoajustar_columnas(writer, df_sin, "Cobros sin albarán")

    buffer.seek(0)

    st.download_button(
        f"Descargar conciliación en Excel ({nombre_excel}.xlsx)",
        data=buffer,
        file_name=f"{nombre_excel}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Sube el PDF y el Excel para comenzar la comprobación.")
