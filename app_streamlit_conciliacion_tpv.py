import streamlit as st
import pandas as pd
import re
from io import BytesIO
from datetime import datetime
import pdfplumber

st.set_page_config(page_title="Comprobación COBROS TPV", layout="wide")
st.title("Comprobación COBROS TPV")

# ==========================================================
# SELECTORES DE ARCHIVOS (Barra Lateral)
# ==========================================================
st.sidebar.header("Carga de Documentos")

# SE MANTIENE EL MÉTODO 1 ORIGINAL (Formato antiguo línea a línea)
pdf_files_antiguos = st.sidebar.file_uploader(
    "1. PDFs Formato Original/Antiguo (Varios a la vez)", 
    type=["pdf"], 
    accept_multiple_files=True
)

excel_file = st.sidebar.file_uploader("2. Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==========================================================
# NUEVO MÉTODO 2: PEGAR DATOS DESDE EL CHAT (Para formato Redsys)
# ==========================================================
st.markdown("### 📋 Entrada de datos de Cobros TPV")
st.info("💡 **¿Tienes un PDF con el formato nuevo de Redsys?** Pásamelo por nuestro chat. Cuando te devuelva la tabla limpia, selecciónala, cópiala y pégala en el cuadro de texto de abajo. Si estás usando el **formato antiguo**, simplemente súbelo a la barra lateral.")

datos_pegados = st.text_area(
    "Pega aquí la tabla de cobros de Redsys generada por la IA (opcional):",
    height=180,
    placeholder="Cliente\tImporte Cobrado\n27877\t391,13\n17368\t111,80..."
)

# ==========================================================
# LECTOR PDF 1: FORMATO ORIGINAL/ANTIGUO (MÉTODO INICIAL)
# ==========================================================
def leer_pdf_tpv_antiguo(pdf):
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
                            "REF_TPV": str(ref),
                            "IMP_TPV": float(importe)
                        })

                i += 1

    return pd.DataFrame(registros)

# ==========================================================
# PROCESADOR DE TEXTO COPIADO Y PEGADO (MODIFICADO)
# ==========================================================
def procesar_tabla_pegada(texto):
    registros = []
    if not texto.strip():
        return pd.DataFrame()
        
    lineas = texto.strip().split("\n")
    
    for linea in lineas:
        linea_limpia = linea.replace("|", " ").strip()
        
        if "CLIENTE" in linea_limpia.upper() or "IMPORTE" in linea_limpia.upper() or "---" in linea_limpia:
            continue
            
        valores = linea_limpia.split()
        if not valores:
            continue
            
        cliente = None
        importe = None
        
        # Detectar el cliente (Cualquier número largo, priorizando el que no tiene formato de importe)
        for v in valores:
            v_limpio = re.sub(r"[^\d]", "", v)
            if v_limpio and "," not in v and "." not in v:
                cliente = v_limpio
                break
        
        # Si no se detectó así, tomamos el primer bloque numérico largo que encontremos
        if not cliente:
            for v in valores:
                v_limpio = re.sub(r"[^\d]", "", v)
                if len(v_limpio) >= 5:
                    cliente = v_limpio
                    break
                
        # Detectar el importe numérico con decimales
        for v in valores:
            v_num = v.replace("€", "").replace(" ", "").strip()
            if re.search(r"\d+[\.,]\d+", v_num) or (v_num.isdigit() and int(v_num) > 0):
                try:
                    if "," in v_num and "." in v_num:
                        v_num = v_num.replace(".", "")
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
# UNIFICACIÓN DE FUENTES DE DATOS (PDFs Antiguos + Texto Pegado)
# ==========================================================
lista_dfs = []

# 1. Añadimos datos si se han subido PDFs antiguos
if pdf_files_antiguos:
    for pdf in pdf_files_antiguos:
        df_individual = leer_pdf_tpv_antiguo(pdf)
        if not df_individual.empty:
            lista_dfs.append(df_individual)

# 2. Añadimos datos si se ha pegado texto en el cuadro
if datos_pegados.strip():
    df_pegado = procesar_tabla_pegada(datos_pegados)
    if not df_pegado.empty:
        lista_dfs.append(df_pegado)

# Consolidamos toda la entrada de TPV detectada
if lista_dfs:
    df_pdf = pd.concat(lista_dfs, ignore_index=True)
    df_pdf = df_pdf.drop_duplicates(subset=["REF_TPV", "IMP_TPV"], keep="first")
else:
    df_pdf = pd.DataFrame()

# Mostrar la vista previa unificada
if not df_pdf.empty:
    st.subheader("👀 Vista previa de todos los cobros TPV reconocidos")
    df_prev = df_pdf.copy()
    df_prev["IMP_TPV"] = df_prev["IMP_TPV"].apply(formato_coma)
    st.dataframe(df_prev, use_container_width=True)
elif pdf_files_antiguos or datos_pegados.strip():
    st.error("⚠️ No se han detectado cobros válidos. Verifica los PDFs o el formato del texto pegado.")

# ==========================================================
# PROCESO DE CONCILIACIÓN CON EL EXCEL DE ALBARANES
# ==========================================================
if excel_file and not df_pdf.empty:

    df_tpv = df_pdf.copy()
    df_alb = pd.read_excel(excel_file, dtype={"Venta a-Nº cliente": str})

    df_alb["IMP_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(limpiar_importe_excel)
    df_alb["IMP_ALBARAN"] = pd.to_numeric(df_alb["IMP_ALBARAN"], errors="coerce")
    df_tpv["IMP_TPV"] = pd.to_numeric(df_tpv["IMP_TPV"], errors="coerce")

    tot_cliente = df_alb.groupby("Venta a-Nº cliente")["IMP_ALBARAN"].agg(["sum", "count"]).reset_index()
    tot_cliente.columns = ["CLIENTE", "TOTAL_CLIENTE", "NUM_ALBARANES"]

    tpv_ref = df_tpv.groupby("REF_TPV", as_index=False)["IMP_TPV"].sum()

    duplicados = df_tpv.groupby(["REF_TPV", "IMP_TPV"]).size().reset_index(name="VECES")
    duplicados = duplicados[duplicados["VECES"] > 1]

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

    for idx, row in df_res[mask_ref].iterrows():
        dif = row["DIF_TOTAL"]

        if abs(dif) < 0.01:
            df_res.at[idx, "DIF_TOTAL"] = 0.0
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado {formato_coma(row['IMP_TPV'])} (total de {int(row['NUM_ALBARANES'])} albaranes)"
        elif dif > 0:
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de más {formato_coma(row['IMP_TPV'])} – posible cobro albaranes atrasados"
        else:
            df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de menos {formato_coma(row['IMP_TPV'])} – posible abono pendiente"

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

    for _, d in duplicados.iterrows():
        mask = (df_res["REF_TPV"] == d["REF_TPV"]) & (df_res["IMP_TPV"] == d["IMP_TPV"])
        df_res.loc[mask, "OBSERVACIONES"] += " | POSIBLE COBRO DUPLICADO"

    # NUEVO: Marcar las referencias del TPV que no tengan exactamente 5 dígitos
    for idx, row in df_res[df_res["REF_TPV"].notna()].iterrows():
        if len(str(row["REF_TPV"])) != 5:
            df_res.at[idx, "OBSERVACIONES"] = str(df_res.at[idx, "OBSERVACIONES"]) + " | REFERENCIA TPV ERRÓNEA (No tiene 5 dígitos)"

    df_vista = df_res.copy()
    df_vista["IMP_ALBARAN"] = df_vista["IMP_ALBARAN"].apply(formato_coma)
    df_vista["IMP_TPV"] = df_vista["IMP_TPV"].apply(formato_coma)
    df_vista["TOTAL_CLIENTE"] = df_vista["TOTAL_CLIENTE"].apply(formato_coma)
    df_vista["DIF_TOTAL"] = df_vista["DIF_TOTAL"].apply(formato_coma)

    st.subheader("📊 Resultado de la conciliación")
    st.dataframe(df_vista, use_container_width=True)

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
