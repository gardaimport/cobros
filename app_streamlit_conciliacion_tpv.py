import streamlit as st
import pandas as pd
import re
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Comprobación COBROS TPV", layout="wide")
st.title("Comprobación COBROS TPV")

# ==========================================================
# SELECTORES DE ARCHIVOS (Barra Lateral)
# ==========================================================
st.sidebar.header("Carga de Documentos")
excel_file = st.sidebar.file_uploader("1. Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==========================================================
# SECCIÓN PRINCIPAL: PEGAR DATOS DEL ASISTENTE (GEMINI)
# ==========================================================
st.markdown("### 📋 Entrada de datos de Cobros TPV")
st.info("Pásale el PDF de Redsys a Gemini en nuestro chat. Cuando te devuelva la tabla limpia, selecciónala, cópiala y pégala en el cuadro de texto de abajo.")

# Cuadro de texto grande para pegar la tabla de texto o markdown
datos_pegados = st.text_area(
    "Pega aquí la tabla de cobros generada por la IA:",
    height=250,
    placeholder="Cliente\tImporte Cobrado\n27877\t391,13\n17368\t111,80..."
)

# ==========================================================
# PROCESADOR DE TEXTO PEGADO
# ==========================================================
def procesar_tabla_pegada(texto):
    registros = []
    if not texto.strip():
        return pd.DataFrame()
        
    lineas = texto.strip().split("\n")
    
    for linea in lineas:
        # Limpiamos caracteres típicos de las tablas de Markdown (como |, con espacios, etc.)
        linea_limpia = linea.replace("|", " ").strip()
        
        # Saltamos líneas que sean cabeceras o separadores de tabla (---)
        if "CLIENTE" in linea_limpia.upper() or "IMPORTE" in linea_limpia.upper() or "---" in linea_limpia:
            continue
            
        # Buscamos cualquier número de 5 dígitos (Cliente) y cantidades con coma o punto decimal
        valores = linea_limpia.split()
        if not valores:
            continue
            
        cliente = None
        importe = None
        
        # Buscamos el cliente (5 dígitos)
        for v in valores:
            v_limpio = re.sub(r"[^\d]", "", v) # Nos quedamos solo con los números por si tiene asteriscos **
            if len(v_limpio) == 5:
                cliente = v_limpio
                break
                
        # Buscamos el importe (número que tenga decimales, o que contenga comas/puntos)
        for v in valores:
            # Quitamos el símbolo de € si lo lleva para no interferir
            v_num = v.replace("€", "").replace(" ", "").strip()
            # Validamos si parece un número contable (con coma o punto)
            if re.search(r"\d+[\.,]\d+", v_num) or (v_num.isdigit() and int(v_num) > 0):
                try:
                    # Convertimos formato europeo (391,13) a float de Python (391.13)
                    if "," in v_num and "." in v_num:
                        v_num = v_num.replace(".", "") # Quitar puntos de millar
                    v_num = v_num.replace(",", ".")
                    importe = float(v_num)
                except ValueError:
                    continue
                    
        if cliente and importe is not None:
            registros.append({
                "REF_TPV": str(cliente),
                "IMP_TPV": float(importe)
            })
            
    return pd.DataFrame(registros)

# ==========================================================
# UTILIDADES DE FORMATO
# ==========================================================
def limpiar_importe_excel(v):
    try:
        return float(str(v).replace(",", "."))
    except:
        return None

def formato_coma(x):
    try:
        return "" if pd.isna(x) else f"{float(x):.2f}".replace(".", ",")
    except:
        return ""

# ==========================================================
# PROCESAMIENTO Y UNIFICACIÓN DE DATOS
# ==========================================================
df_pdf = pd.DataFrame()

if datos_pegados:
    df_pdf = procesar_tabla_pegada(datos_pegados)
    
    if not df_pdf.empty:
        df_pdf = df_pdf.drop_duplicates(subset=["REF_TPV", "IMP_TPV"], keep="first")
        st.subheader("👀 Vista previa de cobros reconocidos")
        df_prev = df_pdf.copy()
        df_prev["IMP_TPV"] = df_prev["IMP_TPV"].apply(formato_coma)
        st.dataframe(df_prev, use_container_width=True)
    else:
        st.error("⚠️ No se ha podido reconocer ningún formato de cliente/importe válido en el texto pegado. Revisa que incluya los 5 dígitos del cliente y el importe.")

# ==========================================================
# PROCESO DE CONCILIACIÓN CON EXCEL
# ==========================================================
if excel_file and not df_pdf.empty:

    df_tpv = df_pdf.copy()
    df_alb = pd.read_excel(excel_file, dtype={"Venta a-Nº cliente": str})

    df_alb["IMP_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(limpiar_importe_excel)
    df_alb["IMP_ALBARAN"] = pd.to_numeric(df_alb["IMP_ALBARAN"], errors="coerce")
    df_tpv["IMP_TPV"] = pd.to_numeric(df_tpv["IMP_TPV"], errors="coerce")

    # Agrupamos albaranes por cliente
    tot_cliente = df_alb.groupby("Venta a-Nº cliente")["IMP_ALBARAN"].agg(["sum", "count"]).reset_index()
    tot_cliente.columns = ["CLIENTE", "TOTAL_CLIENTE", "NUM_ALBARANES"]

    tpv_ref = df_tpv.groupby("REF_TPV", as_index=False)["IMP_TPV"].sum()

    duplicados = df_tpv.groupby(["REF_TPV", "IMP_TPV"]).size().reset_index(name="VECES")
    duplicados = duplicados[duplicados["VECES"] > 1]

    # Cruce de datos
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
    df_res["DIF_TOTAL"] = 0.0

    mask_ref = df_res["IMP_TPV"].notna()
    df_res.loc[mask_ref, "ESTADO COBRO"] = "COBRADO"

    df_res.loc[mask_ref, "DIF_TOTAL"] = (
        df_res.loc[mask_ref, "IMP_TPV"].astype(float) -
        df_res.loc[mask_ref, "TOTAL_CLIENTE"].astype(float)
    )

    # Análisis de diferencias de importes
    for idx, row in df_res[mask_ref].iterrows():
        dif = row["DIF_TOTAL"]

        if abs(dif) < 0.01:
            df_res.at[idx, "DIF_TOTAL"] = 0.0
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado {formato_coma(row['IMP_TPV'])} (total de {int(row['NUM_ALBARANES'])} albaranes)"
        elif dif > 0:
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de más {formato_coma(row['IMP_TPV'])} – posible cobro albaranes atrasados"
        else:
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de menos {formato_coma(row['IMP_TPV'])} – posible abono pendiente"

    # Buscar posibles errores de referencia (Coincidencia por importe exacto)
    for idx, row in df_res[df_res["ESTADO COBRO"] == "NO COBRADO"].iterrows():
        total = row["TOTAL_CLIENTE"]
        candidato = df_tpv[abs(df_tpv["IMP_TPV"] - total) < 0.01]

        if len(candidato) == 1:
            tpv = candidato.iloc[0]
            df_res.at[idx, "IMP_TPV"] = tpv["IMP_TPV"]
            df_res.at[idx, "REF_TPV"] = tpv["REF_TPV"]
            df_res.at[idx, "ESTADO COBRO"] = "COBRADO"
            df_res.at[idx, "DIF_TOTAL"] = 0.0
            df_res.at[idx, "OBSERVACIONES"] = (
                f"Cobrado {formato_coma(tpv['IMP_TPV'])} "
                f"(total de {int(row['NUM_ALBARANES'])} albaranes) – posible error de referencia (TPV: {tpv['REF_TPV']})"
            )

    # Alertas de cobros duplicados en lo pegado
    for _, d in duplicados.iterrows():
        mask = (df_res["REF_TPV"] == d["REF_TPV"]) & (df_res["IMP_TPV"] == d["IMP_TPV"])
        df_res.loc[mask, "OBSERVACIONES"] += " | POSIBLE COBRO DUPLICADO"

    df_vista = df_res.copy()
    df_vista["IMP_ALBARAN"] = df_vista["IMP_ALBARAN"].apply(formato_coma)
    df_vista["IMP_TPV"] = df_vista["IMP_TPV"].apply(formato_coma)
    df_vista["TOTAL_CLIENTE"] = df_vista["TOTAL_CLIENTE"].apply(formato_coma)
    df_vista["DIF_TOTAL"] = df_vista["DIF_TOTAL"].apply(formato_coma)

    st.subheader("📊 Resultado de la conciliación")
    st.dataframe(df_vista, use_container_width=True)

    # Identificar cobros en TPV que no se asocian a ningún cliente del Excel
    refs_excel = set(df_alb["Venta a-Nº cliente"].astype(str))
    totales_excel = set(tot_cliente["TOTAL_CLIENTE"].round(2))

    df_sin = df_tpv.copy()
    df_sin = df_sin[
        (~df_sin["REF_TPV"].isin(refs_excel)) &
        (~df_sin["IMP_TPV"].round(2).isin(totales_excel))
    ]

    df_sin["IMP_TPV"] = df_sin["IMP_TPV"].apply(formato_coma)

    # ==========================================================
    # DESCARGA DEL EXCEL RESULTANTE
    # ==========================================================
    buffer = BytesIO()

    st.markdown("### 💾 Descargar Informe")
    nombre_excel = st.text_input("Escribe el nombre del Excel (sin .xlsx)", "conciliacion_tpv")

    fecha_hora = datetime.now().strftime("%d-%m-%Y_%H-%M")
    nombre_final = f"{nombre_excel}_{fecha_hora}"

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_vista.to_excel(writer, index=False, sheet_name="Conciliación albaranes")
        df_sin.to_excel(writer, index=False, sheet_name="Cobros sin albarán")

        for sheet, df in {"Conciliación albaranes": df_vista, "Cobros sin albarán": df_sin}.items():
            ws = writer.sheets[sheet]
            for i, col in enumerate(df.columns, 1):
                valores = df[col].fillna("").astype(str)
                max_len = max(valores.apply(len).max(), len(col)) + 2
                
                if i <= 26:
                    col_letter = chr(64 + i)
                else:
                    col_letter = chr(64 + (i // 26)) + chr(64 + (i % 26))
                    
                ws.column_dimensions[col_letter].width = max_len

    buffer.seek(0)

    st.download_button(
        f"Descargar conciliación en Excel ({nombre_final}.xlsx)",
        data=buffer,
        file_name=f"{nombre_final}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    if not excel_file:
        st.info("ℹ️ Sube el Excel de albaranes en la barra lateral para cruzar los datos.")
