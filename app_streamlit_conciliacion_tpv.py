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
                            "REFERENCIA_TPV": ref,
                            "IMPORTE_TPV": importe
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
# VISTA PREVIA PDF
# ==========================================================
if pdf_file:
    st.subheader("Vista previa cobros TPV (solo AUTORIZADOS)")
    df_pdf = leer_pdf_tpv(pdf_file)
    df_prev = df_pdf.copy()
    df_prev["IMPORTE_TPV"] = df_prev["IMPORTE_TPV"].apply(formato_coma)
    st.dataframe(df_prev, use_container_width=True)

# ==========================================================
# CONCILIACIÓN
# ==========================================================
if pdf_file and excel_file:

    df_tpv = leer_pdf_tpv(pdf_file)
    df_alb = pd.read_excel(excel_file)

    df_alb["Venta a-Nº cliente"] = df_alb["Venta a-Nº cliente"].astype(str)
    df_alb["IMPORTE_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(limpiar_importe_excel)
    df_alb["Fecha envío"] = pd.to_datetime(df_alb["Fecha envío"], errors="coerce").dt.strftime("%d/%m/%Y")

    # Totales por cliente
    tot_cliente = df_alb.groupby("Venta a-Nº cliente")["IMPORTE_ALBARAN"].agg(["sum", "count"]).reset_index()
    tot_cliente.columns = ["CLIENTE", "TOTAL_CLIENTE", "NUM_ALBARANES"]
    # ==========================================

# DETECCIÓN DE DOBLES COBROS DISTINTOS MISMA REFERENCIA
# ==========================================
duplicados_ref = (
    df_tpv.groupby("REFERENCIA_TPV")["IMPORTE_TPV"]
    .nunique()
    .reset_index()
)

refs_sospechosas = duplicados_ref[duplicados_ref["IMPORTE_TPV"] > 1]["REFERENCIA_TPV"].tolist()

reubicaciones = []

for r in reubicaciones:
    mask = df_res["Venta a-Nº cliente"] == r["REFERENCIA_CORRECTA"]

    df_res.loc[mask, "OBSERVACIONES"] = (
        f"Cobrado {r['IMPORTE']:.2f}".replace(".", ",") +
        f" (total de {int(df_res.loc[mask, 'NUM_ALBARANES'].iloc[0])} albaranes) – "
        f"posible error de referencia (TPV: {r['REFERENCIA_ORIGEN']})"
    )

for ref in refs_sospechosas:
    cobros_ref = df_tpv[df_tpv["REFERENCIA_TPV"] == ref]

    for _, cobro in cobros_ref.iterrows():
        importe = cobro["IMPORTE_TPV"]

        posibles = tot_cliente[abs(tot_cliente["TOTAL_CLIENTE"] - importe) < 0.01]

        if not posibles.empty:
            cliente_correcto = posibles.iloc[0]["CLIENTE"]

            reubicaciones.append({
                "REFERENCIA_ORIGEN": ref,
                "REFERENCIA_CORRECTA": cliente_correcto,
                "IMPORTE": importe
            })

    # TPV por referencia
    tpv_ref = df_tpv.groupby("REFERENCIA_TPV", as_index=False)["IMPORTE_TPV"].sum()

    # Duplicados exactos
    duplicados = df_tpv.groupby(["REFERENCIA_TPV", "IMPORTE_TPV"]).size().reset_index(name="VECES")
    duplicados = duplicados[duplicados["VECES"] > 1]

    # Cruce principal
    df_res = df_alb.merge(
        tpv_ref,
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

    mask_ref = df_res["IMPORTE_TPV"].notna()
    df_res.loc[mask_ref, "ESTADO COBRO"] = "COBRADO"
    df_res.loc[mask_ref, "DIF_TOTAL"] = df_res["IMPORTE_TPV"] - df_res["TOTAL_CLIENTE"]

    for idx, row in df_res[mask_ref].iterrows():
        dif = row["DIF_TOTAL"]

        if abs(dif) < 0.01:
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado {formato_coma(row['IMPORTE_TPV'])} (total de {int(row['NUM_ALBARANES'])} albaranes)"
        elif dif > 0:
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de más {formato_coma(row['IMPORTE_TPV'])} – posible cobro albaranes atrasados"
        else:
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de menos {formato_coma(row['IMPORTE_TPV'])} – posible abono pendiente"

    # Coincidencia por total con referencia errónea
    for idx, row in df_res[df_res["ESTADO COBRO"] == "NO COBRADO"].iterrows():
        total = row["TOTAL_CLIENTE"]
        candidato = df_tpv[abs(df_tpv["IMPORTE_TPV"] - total) < 0.01]

        if len(candidato) == 1:
            tpv = candidato.iloc[0]
            df_res.at[idx, "IMPORTE_TPV"] = tpv["IMPORTE_TPV"]
            df_res.at[idx, "REFERENCIA_TPV"] = tpv["REFERENCIA_TPV"]
            df_res.at[idx, "ESTADO COBRO"] = "COBRADO"
            df_res.at[idx, "OBSERVACIONES"] = (
                f"Cobrado {formato_coma(tpv['IMPORTE_TPV'])} "
                f"(total de {int(row['NUM_ALBARANES'])} albaranes) – posible error de referencia (TPV: {tpv['REFERENCIA_TPV']})"
            )

    # Aviso duplicados
    for _, d in duplicados.iterrows():
        mask = (df_res["REFERENCIA_TPV"] == d["REFERENCIA_TPV"]) & (df_res["IMPORTE_TPV"] == d["IMPORTE_TPV"])
        df_res.loc[mask, "OBSERVACIONES"] += " | POSIBLE COBRO DUPLICADO"

    # Formato hoja 1
    df_vista = df_res.copy()
    df_vista["IMPORTE_ALBARAN"] = df_vista["IMPORTE_ALBARAN"].apply(formato_coma)
    df_vista["IMPORTE_TPV"] = df_vista["IMPORTE_TPV"].apply(formato_coma)
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
        (~df_sin["REFERENCIA_TPV"].isin(refs_excel)) &
        (~df_sin["IMPORTE_TPV"].round(2).isin(totales_excel))
    ]

    df_sin["IMPORTE_TPV"] = df_sin["IMPORTE_TPV"].apply(formato_coma)

    # ==========================================================
    # DESCARGA EXCEL CON DOS HOJAS
    # ==========================================================
    buffer = BytesIO()
    st.markdown("### Nombre del archivo de descarga")
    nombre_excel = st.text_input("Escribe el nombre del Excel (sin .xlsx)", "conciliacion_tpv")

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_vista.to_excel(writer, index=False, sheet_name="Conciliación albaranes")
        df_sin.to_excel(writer, index=False, sheet_name="Cobros sin albarán")

    buffer.seek(0)

    st.download_button(
        f"Descargar conciliación en Excel ({nombre_excel}.xlsx)",
        data=buffer,
        file_name=f"{nombre_excel}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Sube el PDF y el Excel para comenzar la comprobación.")
