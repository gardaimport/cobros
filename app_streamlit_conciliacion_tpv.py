import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Comprobación COBROS TPV", layout="wide")
st.title("Comprobación COBROS TPV")

# =========================
# SUBIDA DE ARCHIVOS
# =========================
pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])
excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx"])

if pdf_file and excel_file:

    # =========================
    # LEER PDF
    # =========================
    movimientos = []

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            texto = page.extract_text()
            if texto:
                lineas = texto.split("\n")
                for linea in lineas:
                    # Busca patrón: referencia + importe
                    match = re.search(r"(\d{4,})\s+(-?\d+,\d{2})", linea)
                    if match:
                        referencia = match.group(1).strip()
                        importe = float(match.group(2).replace(",", "."))
                        movimientos.append({
                            "REFERENCIA": referencia,
                            "IMPORTE": importe
                        })

    df_tpv = pd.DataFrame(movimientos)

    # =========================
    # LEER EXCEL (CLIENTES)
    # =========================
    df_excel = pd.read_excel(excel_file, dtype=str)  # 👈 TODO como texto para mantener ceros

    df_excel.columns = df_excel.columns.str.strip()

    # Normalizamos nombres esperados
    if "REFERENCIA" not in df_excel.columns:
        st.error("El Excel debe contener la columna REFERENCIA")
        st.stop()

    if "TOTAL" not in df_excel.columns:
        st.error("El Excel debe contener la columna TOTAL")
        st.stop()

    # Convertimos total a número
    df_excel["TOTAL"] = (
        df_excel["TOTAL"]
        .str.replace(",", ".", regex=False)
        .astype(float)
    )

    # Creamos columna FECHA ENVIO si no existe
    if "FECHA ENVIO" not in df_excel.columns:
        df_excel["FECHA ENVIO"] = ""

    # =========================
    # AGRUPAR COBROS TPV POR REFERENCIA
    # =========================
    tpv_agrupado = df_tpv.groupby("REFERENCIA")["IMPORTE"].sum().reset_index()

    # =========================
    # CRUCE PRINCIPAL
    # =========================
    df_resultado = df_excel.merge(
        tpv_agrupado,
        on="REFERENCIA",
        how="left"
    )

    df_resultado.rename(columns={"IMPORTE": "COBRADO"}, inplace=True)

    # =========================
    # DETECCIÓN DE ESTADOS
    # =========================
    observaciones = []

    for i, row in df_resultado.iterrows():
        total = row["TOTAL"]
        cobrado = row["COBRADO"]

        if pd.isna(cobrado):
            observaciones.append("NO COBRADO")
        elif round(total, 2) == round(cobrado, 2):
            observaciones.append("OK")
        else:
            observaciones.append("DIFERENCIA")

    df_resultado["OBSERVACIONES"] = observaciones

    # =========================
    # DETECTAR POSIBLE DOBLE COBRO MISMO CLIENTE
    # =========================
    duplicados = df_tpv.groupby("REFERENCIA").filter(lambda x: len(x) > 1)

    for ref in duplicados["REFERENCIA"].unique():
        importes = duplicados[duplicados["REFERENCIA"] == ref]["IMPORTE"].tolist()

        if len(set(importes)) > 1:
            df_resultado.loc[
                df_resultado["REFERENCIA"] == ref,
                "OBSERVACIONES"
            ] = "2 COBROS DISTINTOS MISMO CLIENTE"

    # =========================
    # DETECTAR POSIBLE ERROR DE REFERENCIA POR IMPORTE
    # =========================
    for i, row in df_resultado.iterrows():
        if row["OBSERVACIONES"] == "NO COBRADO":

            posibles = df_tpv[
                df_tpv["IMPORTE"].round(2) == round(row["TOTAL"], 2)
            ]

            if not posibles.empty:
                ref_posible = posibles.iloc[0]["REFERENCIA"]

                df_resultado.at[i, "OBSERVACIONES"] = (
                    f"POSIBLE ERROR REFERENCIA → COBRADO EN {ref_posible}"
                )

    # =========================
    # MOSTRAR RESULTADO
    # =========================
    st.dataframe(df_resultado, use_container_width=True)

    # =========================
    # DESCARGA EXCEL
    # =========================
    nombre_archivo = st.text_input(
        "Nombre del archivo de salida",
        value="resultado_cobros.xlsx"
    )

    output = BytesIO()
    df_resultado.to_excel(output, index=False)
    output.seek(0)

    st.download_button(
        label="Descargar Excel",
        data=output,
        file_name=nombre_archivo,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
