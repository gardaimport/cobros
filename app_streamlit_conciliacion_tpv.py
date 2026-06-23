import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO
from datetime import datetime

st.set_page_config(page_title="Comprobación COBROS TPV", layout="wide")
st.title("Comprobación COBROS TPV")

# ==========================================================
# SELECTORES DE ARCHIVOS (Barra Lateral)
# ==========================================================
st.sidebar.header("Carga de Documentos")

# Formato original (Busca referencias línea a línea)
pdf_files_antiguos = st.sidebar.file_uploader(
    "1. PDFs Formato Original (Varios a la vez)", 
    type=["pdf"], 
    accept_multiple_files=True
)

# Nuevo formato Redsys / Listado de Operaciones
pdf_files_redsys = st.sidebar.file_uploader(
    "2. PDFs Formato Redsys / Factura Cliente (Varios a la vez)", 
    type=["pdf"], 
    accept_multiple_files=True
)

excel_file = st.sidebar.file_uploader("3. Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==========================================================
# LECTOR PDF 1: FORMATO ORIGINAL
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
                            "REF_TPV": str(ref),
                            "IMP_TPV": float(importe)
                        })

                i += 1

    return pd.DataFrame(registros)

# ==========================================================
# LECTOR PDF 2: NUEVO FORMATO REDSYS (BLOQUES ENTRECOMILLADOS)
# ==========================================================
def leer_pdf_tpv_redsys(pdf):
    registros = []
    
    # Patrones de búsqueda dentro de cada bloque separado
    patron_importe = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*Euros", re.IGNORECASE)
    patron_ref = re.compile(r"\b\d{5}\b")

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            texto = page.extract_text()
            if not texto:
                continue

            # Rompemos el texto usando las comillas dobles (cada bloque es una transacción de la tabla)
            bloques = texto.split('"')
            
            for bloque in bloques:
                # Limpiamos saltos de línea internos para convertir el bloque en una sola línea continua de texto
                bloque_limpio = " ".join(bloque.split())
                
                # 1. Buscamos si en este bloque exacto existe un importe seguido de la palabra Euros
                m_imp = patron_importe.search(bloque_limpio)
                if m_imp:
                    importe_str = m_imp.group(1)
                    importe = float(importe_str.replace(".", "").replace(",", "."))
                    
                    # 2. Comprobamos si la transacción está AUTORIZADA (ej: 'D. Autorizada' o 'Autorizada') y no DENEGADA
                    bloque_upper = bloque_limpio.upper()
                    if "AUTORIZADA" in bloque_upper and "DENEGADA" not in bloque_upper:
                        
                        # 3. Extraemos todos los números de 5 dígitos de este bloque específico
                        referencias = patron_ref.findall(bloque_limpio)
                        if referencias:
                            # La columna Núm. Factura es siempre el ÚLTIMO número de 5 dígitos del bloque
                            cliente_ref = referencias[-1]
                            
                            registros.append({
                                "REF_TPV": str(cliente_ref),
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
lista_dfs = []

if pdf_files_antiguos:
    for pdf in pdf_files_antiguos:
        df_individual = leer_pdf_tpv(pdf)
        if not df_individual.empty:
            lista_dfs.append(df_individual)

if pdf_files_redsys:
    for pdf in pdf_files_redsys:
        df_individual = leer_pdf_tpv_redsys(pdf)
        if not df_individual.empty:
            lista_dfs.append(df_individual)

if lista_dfs:
    df_pdf = pd.concat(lista_dfs, ignore_index=True)
    df_pdf = df_pdf.drop_duplicates(subset=["REF_TPV", "IMP_TPV"], keep="first")
else:
    df_pdf = pd.DataFrame()

if not df_pdf.empty:
    st.subheader("Vista previa cobros TPV unificados (solo AUTORIZADOS)")
    df_prev = df_pdf.copy()
    df_prev["IMP_TPV"] = df_prev["IMP_TPV"].apply(formato_coma)
    st.dataframe(df_prev, use_container_width=True)
elif pdf_files_antiguos or pdf_files_redsys:
    st.warning("No se han detectado cobros válidos en los archivos PDF aportados.")

# ==========================================================
# PROCESO DE CONCILIACIÓN
# ==========================================================
if (pdf_files_antiguos or pdf_files_redsys) and excel_file and not df_pdf.empty:

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

    # Alertas de cobros duplicados en el PDF
    for _, d in duplicados.iterrows():
        mask = (df_res["REF_TPV"] == d["REF_TPV"]) & (df_res["IMP_TPV"] == d["IMP_TPV"])
        df_res.loc[mask, "OBSERVACIONES"] += " | POSIBLE COBRO DUPLICADO"

    df_vista = df_res.copy()
    df_vista["IMP_ALBARAN"] = df_vista["IMP_ALBARAN"].apply(formato_coma)
    df_vista["IMP_TPV"] = df_vista["IMP_TPV"].apply(formato_coma)
    df_vista["TOTAL_CLIENTE"] = df_vista["TOTAL_CLIENTE"].apply(formato_coma)
    df_vista["DIF_TOTAL"] = df_vista["DIF_TOTAL"].apply(formato_coma)

    st.subheader("Resultado conciliación")
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

    st.markdown("### Nombre del archivo de descarga")
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
                col_letter = chr(64 + i) if i <= 26 else f"A{chr(64 + i - 26)}"
                ws.column_dimensions[col_letter].width = max_len

    buffer.seek(0)

    st.download_button(
        f"Descargar conciliación en Excel ({nombre_final}.xlsx)",
        data=buffer,
        file_name=f"{nombre_final}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Sube al menos un formato de PDF de cobros junto al Excel de albaranes para iniciar la comprobación.")
