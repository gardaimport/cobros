import streamlit as st
import pandas as pd
import pdfplumber
from io import BytesIO

st.set_page_config(page_title="Comprobación COBROS TPV", layout="wide")
st.title("Comprobación COBROS TPV")

st.markdown("""
Sube el PDF de movimientos del TPV.  
Se mostrará una vista previa y podrás descargarlo convertido a Excel.
""")

pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])


def leer_pdf_tpv_completo(pdf):
    registros = []

    with pdfplumber.open(pdf) as pdf_doc:
        texto = "\n".join(page.extract_text() or "" for page in pdf_doc.pages)

    lineas = [l.strip() for l in texto.split("\n") if l.strip()]

    i = 0
    while i < len(lineas):
        if lineas[i].startswith("VENTA"):
            try:
                comercio = lineas[i+1].replace("/", "").strip()
                terminal = lineas[i+2].strip()
                importe = float(lineas[i+3])
                fecha = lineas[i+4]
                hora = lineas[i+5].split(".")[0]
                resultado = lineas[i+7]
                referencia = lineas[i+8] if lineas[i+8].isdigit() and len(lineas[i+8]) == 5 else ""

                registros.append({
                    "FECHA_HORA_TPV": f"{fecha} {hora}",
                    "TERMINAL_TPV": terminal,
                    "REFERENCIA_TPV": referencia,
                    "IMPORTE_TPV": importe,
                    "RESULTADO": resultado
                })

                i += 10
            except:
                i += 1
        else:
            i += 1

    return pd.DataFrame(registros)


if pdf_file:
    st.success("PDF cargado correctamente")

    df_pdf = leer_pdf_tpv_completo(pdf_file)

    if df_pdf.empty:
        st.error("No se han podido detectar operaciones en el PDF.")
    else:
        st.subheader("Vista previa del PDF convertido a tabla")
        st.dataframe(df_pdf, use_container_width=True)

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
