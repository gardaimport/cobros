import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Conciliación cobros TPV", layout="wide")

st.title("Conciliación de cobros TPV vs Albaranes")

st.markdown("""
Esta aplicación permite:
- Subir un **PDF de cobros TPV** (con columnas *REFERENCIA* e *IMPORTE*)
- Subir un **Excel de albaranes repartidos**
- Marcar qué clientes están **cobrados / no cobrados**
- Detectar **diferencias de importe** o **referencias mal escritas**
""")

# ==========================
# CARGA DE ARCHIVOS
# ==========================
pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])
excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"])

# ==========================
# FUNCIONES
# ==========================
def leer_pdf_tpv(pdf):
    """Extrae REFERENCIA e IMPORTE de PDF TPV"""
    registros = []
    with pdfplumber.open(pdf) as pdf_doc:
        texto = "\n".join(page.extract_text() or "" for page in pdf_doc.pages)

    # Patrón flexible: importe seguido de referencia
    patron = re.compile(
        r"(?P<importe>\d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2}))\D+(?P<ref>\d{3,6})\b"
    )

    for m in patron.finditer(texto):
        imp = m.group("importe").replace(".", "").replace(",", ".")
        registros.append({
            "REFERENCIA": m.group("ref").strip(),
            "IMPORTE_TPV": float(imp)
        })

    return pd.DataFrame(registros)


def limpiar_importe(valor, origen="auto"):
    """Convierte importe a float de manera segura"""
    try:
        v = str(valor).replace("€", "").strip()
        if origen == "pdf":
            v = v.replace(",", "")
        elif origen == "excel":
            v = v.replace(".", "").replace(",", ".")
        else:
            if v.count(",") == 1 and v.count(".") == 0:
                v = v.replace(",", ".")
            elif v.count(".") > 1:
                v = v.replace(".", "")
        return float(v)
    except:
        return None


def similitud(a, b):
    """Similitud de cadenas basada en coincidencia de caracteres"""
    a, b = str(a), str(b)
    coincidencias = sum(1 for x, y in zip(a, b) if x == y)
    return coincidencias / max(len(a), len(b))

# ==========================
# PROCESAMIENTO
# ==========================
if pdf_file and excel_file:
    st.success("Archivos cargados correctamente")

    # Leer PDF
    df_tpv = leer_pdf_tpv(pdf_file)
    df_tpv = df_tpv.rename(columns=str.upper)
    df_tpv["REFERENCIA"] = df_tpv["REFERENCIA"].astype(str).str.strip()
    df_tpv["IMPORTE_TPV"] = df_tpv["IMPORTE_TPV"].apply(lambda x: limpiar_importe(x, origen="pdf"))

    # Leer Excel
    df_alb = pd.read_excel(excel_file)
    df_alb["Venta a-Nº cliente"] = df_alb["Venta a-Nº cliente"].astype(str).str.strip()
    df_alb["IMPORTE_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(lambda x: limpiar_importe(x, origen="excel"))

    # Agrupar TPV por cliente
    tpv_agrupado = df_tpv.groupby("REFERENCIA", as_index=False)["IMPORTE_TPV"].sum()

    # Cruce de datos
    df_resultado = df_alb.merge(
        tpv_agrupado,
        how="left",
        left_on="Venta a-Nº cliente",
        right_on="REFERENCIA"
    )

    # Lógica de conciliación
    df_resultado["ESTADO COBRO"] = "NO COBRADO"
    df_resultado.loc[df_resultado["IMPORTE_TPV"].notna(), "ESTADO COBRO"] = "COBRADO"

    df_resultado["DIFERENCIA"] = df_resultado["IMPORTE_ALBARAN"] - df_resultado["IMPORTE_TPV"]
    df_resultado["OBSERVACIONES"] = ""

    df_resultado.loc[df_resultado["ESTADO COBRO"] == "NO COBRADO", "OBSERVACIONES"] = "Sin cobro TPV"
    df_resultado.loc[
        (df_resultado["ESTADO COBRO"] == "COBRADO") & (df_resultado["DIFERENCIA"].abs() > 0.01),
        "OBSERVACIONES"
    ] = "Importe no coincide (posible referencia mal escrita)"

    # Detección de referencias mal escritas
    for idx, row in df_resultado.iterrows():
        if row["ESTADO COBRO"] == "NO COBRADO":
            importe = row["IMPORTE_ALBARAN"]
            cliente = row["Venta a-Nº cliente"]

            candidatos = df_tpv[df_tpv["IMPORTE_TPV"].sub(importe).abs() < 0.01].copy()
            if not candidatos.empty:
                candidatos["SIMILITUD"] = candidatos["REFERENCIA"].apply(lambda x: similitud(cliente, x))
                mejor = candidatos.sort_values("SIMILITUD", ascending=False).iloc[0]
                if mejor["SIMILITUD"] >= 0.6:
                    df_resultado.at[idx, "OBSERVACIONES"] = (
                        f"Alta prob. ref. mal escrita (TPV: {mejor['REFERENCIA']}, similitud {mejor['SIMILUD']:.0%})"
                    )
                else:
                    df_resultado.at[idx, "OBSERVACIONES"] = (
                        f"Cobro TPV con mismo importe (ref distinta: {mejor['REFERENCIA']})"
                    )

    # ==========================
    # RESULTADOS CON ESTILOS
    # ==========================
    st.subheader("Resultado de la conciliación")

    def colorear_filas(row):
        if row["ESTADO COBRO"] == "NO COBRADO":
            return ['background-color: #fdd']*len(row)  # rojo claro
        elif abs(row["DIFERENCIA"]) > 0.01:
            return ['background-color: #ffd']*len(row)  # amarillo claro
        else:
            return ['']*len(row)

    st.dataframe(df_resultado.style.apply(colorear_filas, axis=1), use_container_width=True)

    # ==========================
    # DESCARGA CORRECTA
    # ==========================
    buffer = BytesIO()
    output = df_resultado.copy()
    output.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)

    st.download_button(
        label="Descargar resultado en Excel",
        data=buffer,
        file_name="conciliacion_tpv.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

else:
    st.info("Por favor, sube ambos archivos para iniciar la conciliación")
