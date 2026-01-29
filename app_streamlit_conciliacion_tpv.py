import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Comprobación COBROS TPV", layout="wide")

# Estilo para las métricas
st.markdown("""
    <style>
    [data-testid="stMetricValue"] { font-size: 25px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🚀 Comprobación COBROS TPV")

# ==========================================================
# FUNCIONES DE PROCESAMIENTO
# ==========================================================

def leer_pdf_tpv(pdf):
    registros = []
    # Patrones actualizados según tu estructura de PDF
    patron_importe = re.compile(r"\b\d+\.\d{2}\b")
    # Buscamos la referencia que suele estar al final de cada bloque de operación
    patron_ref = re.compile(r"\b\d{4,6}\b") 
    patron_resultado = re.compile(r"\b(AUTORIZADA|DENEGADA)\b")

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            texto = page.extract_text()
            if not texto: continue

            lineas = [l.strip() for l in texto.split("\n") if l.strip()]
            for i, linea in enumerate(lineas):
                m_imp = patron_importe.search(linea)
                if m_imp:
                    importe = float(m_imp.group())
                    ref = None
                    resultado = None

                    # Miramos líneas cercanas para capturar la referencia y el estado
                    bloque_busqueda = lineas[max(0, i-2):min(i+8, len(lineas))]
                    for texto_busqueda in bloque_busqueda:
                        if not ref:
                            m_ref = patron_ref.search(texto_busqueda)
                            if m_ref: ref = m_ref.group()
                        if not resultado:
                            m_res = patron_resultado.search(texto_busqueda)
                            if m_res: resultado = m_res.group()

                    if ref and resultado == "AUTORIZADA":
                        registros.append({"REFERENCIA_TPV": str(ref), "IMPORTE_TPV": importe})

    return pd.DataFrame(registros).drop_duplicates()

def limpiar_referencia(ref):
    """Limpia códigos de cliente como 1234.0 o '1234'"""
    if pd.isna(ref): return ""
    return str(ref).split('.')[0].strip()

def formato_euro(x):
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".") if pd.notna(x) else "-"

# ==========================================================
# CARGA DE ARCHIVOS
# ==========================================================
col1, col2 = st.columns(2)
with col1:
    pdf_file = st.file_uploader("📂 Sube el PDF de cobros TPV", type=["pdf"])
with col2:
    excel_file = st.file_uploader("📊 Sube el Excel de albaranes", type=["xlsx", "xls"])

if pdf_file and excel_file:
    # 1. Leer Datos
    df_tpv = leer_pdf_tpv(pdf_file)
    df_alb = pd.read_excel(excel_file)
    
    # 2. Limpieza de Excel
    # Buscamos las columnas exactas de tu archivo
    col_cliente = "Venta a-Nº cliente"
    col_importe = "Importe envío IVA incluido"
    
    df_alb[col_cliente] = df_alb[col_cliente].apply(limpiar_referencia)
    df_alb["IMPORTE_ALBARAN"] = pd.to_numeric(df_alb[col_importe], errors='coerce').fillna(0)
    
    # 3. Agrupar albaranes por cliente para la conciliación
    resumen_alb = df_alb.groupby(col_cliente).agg({
        "IMPORTE_ALBARAN": "sum",
        "Nº": "count"
    }).reset_index()
    resumen_alb.columns = ["CLIENTE", "TOTAL_DEBIDO", "CANT_ALBARANES"]

    # 4. Agrupar TPV (por si hay varios cobros al mismo cliente)
    resumen_tpv = df_tpv.groupby("REFERENCIA_TPV")["IMPORTE_TPV"].sum().reset_index()

    # 5. Cruce Principal
    df_final = resumen_alb.merge(resumen_tpv, left_on="CLIENTE", right_on="REFERENCIA_TPV", how="outer")
    
    # Rellenar nulos
    df_final["CLIENTE"] = df_final["CLIENTE"].fillna(df_final["REFERENCIA_TPV"])
    df_final["TOTAL_DEBIDO"] = df_final["TOTAL_DEBIDO"].fillna(0)
    df_final["IMPORTE_TPV"] = df_final["IMPORTE_TPV"].fillna(0)
    
    # 6. Lógica de Estados
    def determinar_estado(row):
        dif = row["IMPORTE_TPV"] - row["TOTAL_DEBIDO"]
        if row["IMPORTE_TPV"] == 0: return "❌ NO COBRADO"
        if abs(dif) < 0.02: return "✅ CUADRA"
        if dif > 0: return "⚠️ COBRADO DE MÁS"
        return "📉 COBRADO DE MENOS"

    df_final["ESTADO"] = df_final.apply(determinar_estado, axis=1)
    df_final["DIFERENCIA"] = df_final["IMPORTE_TPV"] - df_final["TOTAL_DEBIDO"]

    # ==========================================================
    # VISUALIZACIÓN
    # ==========================================================
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Albaranes", formato_euro(df_final["TOTAL_DEBIDO"].sum()))
    m2.metric("Total TPV", formato_euro(df_final["IMPORTE_TPV"].sum()))
    m3.metric("Diferencia Global", formato_euro(df_final["IMPORTE_TPV"].sum() - df_final["TOTAL_DEBIDO"].sum()))

    st.subheader("📋 Resultado de la Conciliación")
    
    # Aplicar formato para visualización
    df_show = df_final.copy()
    for col in ["TOTAL_DEBIDO", "IMPORTE_TPV", "DIFERENCIA"]:
        df_show[col] = df_show[col].apply(formato_euro)

    st.dataframe(df_show.sort_values("ESTADO"), use_container_width=True)

    # Botón de Descarga
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_final.to_excel(writer, index=False, sheet_name="Conciliacion")
    
    st.download_button(
        label="📥 Descargar Excel de Resultados",
        data=buffer.getvalue(),
        file_name="resultado_conciliacion.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("👋 Por favor, sube ambos archivos para procesar la conciliación.")
