import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Conciliación TPV vs Albaranes", layout="wide")
st.title("📊 Conciliación TPV vs Albaranes")

# ==========================================================
# BARRA LATERAL (SIDEBAR)
# ==========================================================
with st.sidebar:
    st.header("Carga de archivos")
    pdf_file = st.file_uploader("obi 1. Sube el PDF de TPV", type=["pdf"])
    excel_file = st.file_uploader("2. Sube el Excel de Albaranes", type=["xlsx", "xls"])
    st.markdown("---")
    st.markdown("**Configuración de columnas Excel:**")
    col_cliente = st.text_input("Columna ID Cliente", "Venta a-Nº cliente")
    col_importe = st.text_input("Columna Importe", "Importe envío IVA incluido")

# ==========================================================
# FUNCIONES AUXILIARES
# ==========================================================
def leer_pdf_tpv(pdf):
    registros = []
    # Flexibilizamos ref a entre 4 y 12 dígitos por si cambia el formato
    patron_importe = re.compile(r"\b\d+\.\d{2}\b")
    patron_ref = re.compile(r"\b\d{4,12}\b") 
    patron_resultado = re.compile(r"\b(AUTORIZADA|DENEGADA)\b")

    try:
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

                        # Buscamos en las siguientes 10 líneas
                        for j in range(i, min(i + 10, len(lineas))):
                            if not ref:
                                m_ref = patron_ref.search(lineas[j])
                                if m_ref: ref = m_ref.group()
                            
                            if not resultado:
                                m_res = patron_resultado.search(lineas[j])
                                if m_res: resultado = m_res.group()
                        
                        # Solo guardamos si está autorizada y tenemos referencia
                        if ref and resultado == "AUTORIZADA":
                            registros.append({
                                "REF_TPV": ref, # Se mantiene como string para evitar perder ceros
                                "IMP_TPV": importe
                            })
                    i += 1
        return pd.DataFrame(registros)
    except Exception as e:
        st.error(f"Error al leer el PDF: {e}")
        return pd.DataFrame()

def limpiar_importe_excel(v):
    if pd.isna(v): return 0.0
    try:
        # Si ya es float/int, lo devuelve, si es string reemplaza coma
        if isinstance(v, (float, int)): return float(v)
        return float(str(v).replace(",", ".").replace("€", "").strip())
    except:
        return 0.0

def autoajustar_columnas(writer, df, sheet_name):
    worksheet = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns):
        # Calculamos longitud máxima entre encabezado y contenido
        max_len = max(
            df[col].astype(str).map(len).max() if not df[col].empty else 0,
            len(str(col))
        ) + 2
        worksheet.column_dimensions[chr(65 + i)].width = min(max_len, 50) # Límite de 50 para no hacerlas gigantes

# ==========================================================
# LÓGICA PRINCIPAL
# ==========================================================

if pdf_file and excel_file:
    # 1. PROCESAR PDF
    with st.spinner('Leyendo PDF...'):
        df_tpv = leer_pdf_tpv(pdf_file)
    
    if df_tpv.empty:
        st.warning("No se encontraron cobros AUTORIZADOS en el PDF o el formato no coincide.")
        st.stop()

    # 2. PROCESAR EXCEL
    try:
        df_alb = pd.read_excel(excel_file, dtype={col_cliente: str})
        
        # Validar columnas
        if col_cliente not in df_alb.columns or col_importe not in df_alb.columns:
            st.error(f"Error: No se encuentran las columnas '{col_cliente}' o '{col_importe}' en el Excel.")
            st.info(f"Columnas detectadas: {list(df_alb.columns)}")
            st.stop()

        df_alb["IMP_ALBARAN"] = df_alb[col_importe].apply(limpiar_importe_excel)
    except Exception as e:
        st.error(f"Error al leer el Excel: {e}")
        st.stop()

    # 3. AGREGACIONES
    # Totales por cliente (Excel)
    tot_cliente = df_alb.groupby(col_cliente)["IMP_ALBARAN"].agg(["sum", "count"]).reset_index()
    tot_cliente.columns = ["CLIENTE", "TOTAL_CLIENTE", "NUM_ALBARANES"]

    # TPV por referencia (PDF) - Agrupamos por si hay 2 cobros a la misma ref
    tpv_agrupado = df_tpv.groupby("REF_TPV", as_index=False)["IMP_TPV"].sum()

    # 4. CRUCE DE DATOS (CONCILIACIÓN)
    df_res = tot_cliente.merge(
        tpv_agrupado,
        how="outer", # Outer para detectar también lo que está en TPV pero no en Excel
        left_on="CLIENTE",
        right_on="REF_TPV",
        indicator=True # Nos dice si el dato vino de left_only, right_only o both
    )

    # 5. LÓGICA DE ESTADOS Y OBSERVACIONES
    df_res["ESTADO"] = "PENDIENTE"
    df_res["OBSERVACIONES"] = ""
    df_res["DIFERENCIA"] = df_res["IMP_TPV"].fillna(0) - df_res["TOTAL_CLIENTE"].fillna(0)

    # Rellenar NaNs para cálculos
    df_res["REF_TPV"] = df_res["REF_TPV"].fillna(df_res["CLIENTE"])
    
    for idx, row in df_res.iterrows():
        # Caso 1: Coincidencia exacta o diferencia mínima (céntimos)
        if row["_merge"] == "both":
            if abs(row["DIFERENCIA"]) < 0.02:
                df_res.at[idx, "ESTADO"] = "OK"
                df_res.at[idx, "OBSERVACIONES"] = "Conciliado correctamente"
            elif row["DIFERENCIA"] > 0:
                df_res.at[idx, "ESTADO"] = "DIFERENCIA (+)"
                df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de MÁS ({row['DIFERENCIA']:.2f}€). Revisar albaranes atrasados."
            else:
                df_res.at[idx, "ESTADO"] = "DIFERENCIA (-)"
                df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de MENOS ({row['DIFERENCIA']:.2f}€). Posible impago parcial."
        
        # Caso 2: Está en Excel pero NO en TPV
        elif row["_merge"] == "left_only":
            # INTENTO DE RECUPERACIÓN: Buscar por importe exacto en los "huérfanos" del TPV
            # (Aquellos que están en right_only)
            posible_match = df_res[
                (df_res["_merge"] == "right_only") & 
                (abs(df_res["IMP_TPV"] - row["TOTAL_CLIENTE"]) < 0.02)
            ]
            
            if not posible_match.empty:
                # Encontramos un importe idéntico con otra referencia
                ref_erronea = posible_match.iloc[0]["REF_TPV"]
                df_res.at[idx, "ESTADO"] = "OK (REF ERROR)"
                df_res.at[idx, "OBSERVACIONES"] = f"Cobrado con referencia incorrecta: {ref_erronea}"
                df_res.at[idx, "IMP_TPV"] = row["TOTAL_CLIENTE"]
                df_res.at[idx, "DIFERENCIA"] = 0
                
                # Marcar el registro huérfano para borrarlo o marcarlo como usado
                # (Para simplificar visualización, en este script simple no lo borramos del dataframe final
                # pero lo notamos en observaciones).
            else:
                df_res.at[idx, "ESTADO"] = "NO COBRADO"
                df_res.at[idx, "OBSERVACIONES"] = "Falta cobro en TPV"

        # Caso 3: Está en TPV pero NO en Excel (Cobros sin albarán)
        elif row["_merge"] == "right_only":
            df_res.at[idx, "ESTADO"] = "EXTRA"
            df_res.at[idx, "OBSERVACIONES"] = "Cobro en TPV sin cliente/albarán asociado en Excel"

    # Filtrar columnas para visualización final
    cols_finales = ["CLIENTE", "REF_TPV", "NUM_ALBARANES", "TOTAL_CLIENTE", "IMP_TPV", "DIFERENCIA", "ESTADO", "OBSERVACIONES"]
    df_final = df_res[cols_finales].copy()

    # Formatear números
    for col in ["TOTAL_CLIENTE", "IMP_TPV", "DIFERENCIA"]:
        df_final[col] = df_final[col].fillna(0).apply(lambda x: f"{x:.2f}".replace(".", ","))

    # ==========================================================
    # VISUALIZACIÓN EN PANTALLA
    # ==========================================================
    
    # Métricas
    total_tpv = df_tpv["IMP_TPV"].sum()
    total_excel = tot_cliente["TOTAL_CLIENTE"].sum()
    dif_global = total_tpv - total_excel

    c1, c2, c3 = st.columns(3)
    c1.metric("Total TPV (PDF)", f"{total_tpv:,.2f}€")
    c2.metric("Total Albaranes (Excel)", f"{total_excel:,.2f}€")
    c3.metric("Diferencia Global", f"{dif_global:,.2f}€", delta_color="inverse")

    st.markdown("### Detalle Conciliación")
    
    # Colorear filas según estado
    def color_estado(val):
        color = 'white'
        if val == "OK": color = '#d4edda' # Verde claro
        elif val == "NO COBRADO": color = '#f8d7da' # Rojo claro
        elif "DIFERENCIA" in val: color = '#fff3cd' # Amarillo
        elif "EXTRA" in val: color = '#cce5ff' # Azul
        return f'background-color: {color}; color: black'

    st.dataframe(
        df_final.style.applymap(color_estado, subset=['ESTADO']),
        use_container_width=True,
        height=600
    )

    # ==========================================================
    # DESCARGA
    # ==========================================================
    st.markdown("### Descargar Informe")
    col_izq, col_der = st.columns([2,1])
    nombre_excel = col_izq.text_input("Nombre del archivo", "conciliacion_diaria")
    
    if col_der.button("Preparar descarga"):
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            # Hoja 1: Todo junto
            df_final.to_excel(writer, index=False, sheet_name="Conciliación Global")
            autoajustar_columnas(writer, df_final, "Conciliación Global")
            
            # Hoja 2: Solo incidencias
            df_incidencias = df_final[df_final["ESTADO"] != "OK"]
            df_incidencias.to_excel(writer, index=False, sheet_name="Incidencias")
            autoajustar_columnas(writer, df_incidencias, "Incidencias")

        buffer.seek(0)
        st.download_button(
            label="💾 Descargar Excel",
            data=buffer,
            file_name=f"{nombre_excel}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

else:
    st.info("👋 Por favor, sube ambos archivos en la barra lateral para comenzar.")
