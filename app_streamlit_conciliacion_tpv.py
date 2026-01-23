import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Comprobación COBROS TPV", layout="wide")
st.title("Comprobación COBROS TPV")

st.markdown("""
Sube el PDF de movimientos del TPV.  
La aplicación:
- Extrae todas las operaciones
- Detecta Fecha/Hora, Terminal, Referencia, Importe y Resultado
- Muestra una vista previa en tabla
- Permite descargar el PDF convertido a Excel
""")

pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])


def leer_pdf_tpv_completo(pdf):
    registros = []

    with pdfplumber.open(pdf) as pdf_doc:
        texto = "\n".join(page.extract_text() or "" for page in pdf_doc.pages)

    # Separar por operaciones (cada una empieza por VENTA /)
    bloques = re.split(r"\n(?=VENTA\s/)", texto)

    for bloque in bloques:
        # Fecha
        fecha = re.search(r"(\d{4}-\d{2}-\d{2})", bloque)
        # Hora
        hora = re.search(r"(\d{2}:\d{2}:\d{2})", bloque)
        # Importe
        importe = re.search(r"(\d+\.\d{2})", bloque)
        # Resultado
        resultado = re.search(r"(AUTORIZADA|DENEGADA)", bloque)
        # Referencia (5 dígitos)
        referencia = re.search(r"\n(\d{5})\n", bloque)
        # Terminal (número debajo del comercio)
        terminal = re.search(r"/\s*\n(\d+)\n", bloque)

        if fecha and hora and importe and resultado:
            registros.append({
                "FECHA_HORA_TPV": f"{fecha.group(1)} {hora.group(1)}" if hora else fecha.group(1),
                "TERMINAL_TPV": terminal.group(1) if terminal else "",
                "REFERENCIA_TPV": referencia.group(1) if referencia else "",
                "IMPORTE_TPV": float(importe.group(1)),
                "RESULTADO": resultado.group(1)
            })

    return pd.DataFrame(registros)


if pdf_file:
    st.success("PDF cargado correctamente")

    df_pdf = leer_pdf_tpv_completo(pdf_file)

    if df_pdf.empty:
        st.error("No se han podido detectar operaciones en el PDF.")
    else:
        st.subheader("Vista previa del PDF convertido a tabla")
        st.dataframe(df_pdf, use_container_width=True)

        # Exportar a Excel
        buffer = BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df_pdf.to_excel(writer, index=False, sheet_name="TPV")
        buffer.seek(0)

        st.download_button(
            label="Descargar Excel completo del PDF",
            data=buffer,
            file_name="tpv_convertido.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
else:
    st.info("Sube un PDF de movimientos TPV para comenzar.")
