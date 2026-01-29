import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Comprobación COBROS TPV", layout="wide")
st.title("Comprobación COBROS TPV")

pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])
excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"])

def leer_pdf_tpv(pdf):
    registros = []
    # Tu patrón original de 5 dígitos para la columna "Referencia"
    patron_ref = re.compile(r"\b\d{5}\b") 
    patron_importe = re.compile(r"\b\d+\.\d{2}\b")
    patron_resultado = re.compile(r"\b(AUTORIZADA|DENEGADA)\b")

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            texto = page.extract_text()
            if not texto: continue
            lineas = [l.strip() for l in texto.split("\n") if l.strip()]
            
            i = 0
            while i < len(lineas):
                linea = lineas[i]
                m_imp = patron_importe.search(linea)
                if m_imp:
                    importe = float(m_imp.group())
                    ref = None
                    resultado = None
                    # Buscamos en el bloque cercano (8 líneas)
                    for j in range(max(0, i-2), min(i + 8, len(lineas))):
                        if not ref:
                            m_ref = patron_ref.search(lineas[j])
                            if m_ref: ref = m_ref.group()
                        if not resultado:
                            m_res = patron_resultado.search(lineas[j])
                            if m_res: resultado = m_res.group()

                    if ref and resultado == "AUTORIZADA":
                        registros.append({"REFERENCIA_TPV": str(ref), "IMPORTE_TPV": importe})
                i += 1
    return pd.DataFrame(registros).drop_duplicates()

def formato_coma(x):
    return "" if pd.isna(x) or x == "" else f"{x:.2f}".replace(".", ",")

# ==========================================================
# PROCESAMIENTO
# ==========================================================
if pdf_file and excel_file:
    # 1. Cargar Excel (Manteniendo todas las columnas necesarias)
    df_alb = pd.read_excel(excel_file)
    # Normalizar columna cliente a string sin .0
    df_alb["Venta a-Nº cliente"] = df_alb["Venta a-Nº cliente"].astype(str).str.replace(".0", "", regex=False)
    
    # 2. Leer PDF
    df_tpv = leer_pdf_tpv(pdf_file)
    
    # 3. Preparar datos para el cruce
    df_alb["IMPORTE_ALBARAN"] = pd.to_numeric(df_alb["Importe envío IVA incluido"], errors='coerce').fillna(0)
    
    # Totales por cliente (para saber cuánto debe pagar en total)
    tot_cliente = df_alb.groupby("Venta a-Nº cliente")["IMPORTE_ALBARAN"].sum().reset_index()
    tot_cliente.columns = ["Venta a-Nº cliente", "TOTAL_CLIENTE"]

    # 4. Cruzar Albaranes con Cobros
    # Primero unimos los albaranes con el total que el cliente debe
    df_res = df_alb.merge(tot_cliente, on="Venta a-Nº cliente", how="left")
    
    # Luego unimos con lo que realmente se extrajo del PDF (TPV)
    df_res = df_res.merge(df_tpv, left_on="Venta a-Nº cliente", right_on="REFERENCIA_TPV", how="left")

    # 5. Lógica de Estado
    df_res["ESTADO COBRO"] = "❌ NO COBRADO"
    mask_cobrado = df_res["IMPORTE_TPV"].notna()
    df_res.loc[mask_cobrado, "ESTADO COBRO"] = "✅ COBRADO"
    
    # Calcular diferencia si hay cobro
    df_res["DIFERENCIA"] = 0.0
    df_res.loc[mask_cobrado, "DIFERENCIA"] = df_res["IMPORTE_TPV"] - df_res["TOTAL_CLIENTE"]

    # 6. Limpieza final de columnas para la vista
    columnas_finales = [
        "Venta a-Nº cliente", 
        "Nombre dirección de envío", # Restaurada
        "Nº", # Nº de albarán
        "Importe envío IVA incluido", 
        "IMPORTE_TPV", 
        "ESTADO COBRO",
        "DIFERENCIA"
    ]
    
    df_vista = df_res[columnas_finales].copy()

    # Formatear números para leer mejor en pantalla
    for col in ["IMPORTE_TPV", "DIFERENCIA"]:
        df_vista[f"{col}_FORM"] = df_vista[col].apply(formato_coma)

    st.subheader("Resultado de la conciliación")
    st.dataframe(df_vista, use_container_width=True)

    # Exportación
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_vista.to_excel(writer, index=False, sheet_name="Conciliación")
    
    st.download_button("Descargar Excel", buffer.getvalue(), "conciliacion.xlsx")

else:
    st.info("Sube los archivos para empezar.")
