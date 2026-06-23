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

# Nuevo formato Redsys (Busca el número de cliente en la misma línea del importe)
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
# LECTOR PDF 2: NUEVO FORMATO REDSYS (CON COMENTARIOS DE CONTROL)
# ==========================================================
def leer_pdf_tpv_redsys(pdf):
    registros = []
    
    # Expresiones regulares independientes para mayor precisión
    patron_importe = re.compile(r"(\d{1,3}(?:\.\d{3})*,\d{2})\s*Euros", re.IGNORECASE)
    patron_ref = re.compile(r"\b\d{5}\b")

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            texto = page.extract_text()
            if not texto:
                continue

            # Separamos por bloques de comillas dobles (que es como Redsys agrupa las filas de la tabla)
            # Si no hay comillas, separamos por líneas estándar (\n)
            if '"' in texto:
                filas = [f.strip() for f in texto.split('"') if f.strip()]
            else:
                filas = [f.strip() for f in texto.split('\n') if f.strip()]

            for fila in filas:
                # Normalizamos espacios y saltos de línea dentro de la misma fila para que sea lineal
                fila_limpia = " ".join(fila.split())
                
                # 1. Buscamos el importe seguido de Euros
                m_imp = patron_importe.search(fila_limpia)
                if m_imp:
                    importe_str = m_imp.group(1)
                    importe = float(importe_str.replace(".", "").replace(",", "."))
                    
                    # 2. Verificamos que esté AUTORIZADA y no DENEGADA
                    fila_upper = fila_limpia.upper()
                    if "AUTORIZADA" in fila_upper and "DENEGADA" not in fila_upper:
                        
                        # 3. Extraemos TODOS los números de 5 dígitos de la fila
                        todos_los_cinco_digitos = patron_ref.findall(fila_limpia)
                        
                        if todos_los_cinco_digitos:
                            # La referencia del cliente/factura es siempre el ÚLTIMO número de 5 dígitos de la fila
                            cliente_ref = todos_los_cinco_digitos[-1]
                            
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

    for _, d
