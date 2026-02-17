import streamlit as st
import pandas as pd
import pdfplumber
import re
from io import BytesIO

st.set_page_config(page_title="Comprobación COBROS TPV", layout="wide")
st.title("Comprobación COBROS TPV")

tab1, tab2 = st.tabs(["Conciliación TPV (actual)", "Conciliación por comprobantes bancarios"])

# ==========================================================
# FUNCIONES COMUNES
# ==========================================================
def limpiar_importe_excel(v):
    try:
        return float(str(v).replace(",", "."))
    except:
        return None

def formato_coma(x):
    return "" if pd.isna(x) else f"{x:.2f}".replace(".", ",")

def autoajustar_columnas(writer, df, sheet_name):
    worksheet = writer.sheets[sheet_name]
    for i, col in enumerate(df.columns):
        max_len = max(
            df[col].astype(str).map(len).max(),
            len(col)
        ) + 2
        worksheet.column_dimensions[chr(65 + i)].width = max_len

# ==========================================================
# LECTOR PDF TPV (ACTUAL)
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
                            "REF_TPV": ref,
                            "IMP_TPV": importe
                        })

                i += 1

    return pd.DataFrame(registros)

# ==========================================================
# LECTOR PDF COMPROBANTES BANCARIOS
# ==========================================================
def leer_pdf_banco(pdf):
    registros = []

    # 5 dígitos antes de "Devolución" y el importe después de "Autorización"
    patron_linea = re.compile(
        r"(\d{5}).*?Devoluci[oó]n.*?Autorizaci[oó]n.*?(\d+[,\.]\d{2})",
        re.IGNORECASE
    )

    with pdfplumber.open(pdf) as pdf_doc:
        for page in pdf_doc.pages:
            texto = page.extract_text()
            if not texto:
                continue

            lineas = [l.strip() for l in texto.split("\n") if l.strip()]

            for linea in lineas:
                match = patron_linea.search(linea)

                if match:
                    ref = match.group(1)
                    importe = limpiar_importe_excel(match.group(2))

                    registros.append({
                        "REF_TPV": ref,
                        "IMP_TPV": importe
                    })

    if registros:
        return pd.DataFrame(registros)
    else:
        return pd.DataFrame(columns=["REF_TPV", "IMP_TPV"])

# ==========================================================
# 🟦 PESTAÑA 1 - TU SISTEMA ACTUAL (SIN CAMBIOS)
# ==========================================================
with tab1:

    pdf_file = st.file_uploader("Sube el PDF de cobros TPV", type=["pdf"])
    excel_file = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"])

    if pdf_file:
        st.subheader("Vista previa cobros TPV (solo AUTORIZADOS)")
        df_pdf = leer_pdf_tpv(pdf_file)
        df_prev = df_pdf.copy()
        df_prev["IMP_TPV"] = df_prev["IMP_TPV"].apply(formato_coma)
        st.dataframe(df_prev, use_container_width=True)

    if pdf_file and excel_file:

        df_tpv = leer_pdf_tpv(pdf_file)

        df_alb = pd.read_excel(excel_file, dtype={"Venta a-Nº cliente": str})
        df_alb["IMP_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(limpiar_importe_excel)

        tot_cliente = df_alb.groupby("Venta a-Nº cliente")["IMP_ALBARAN"].agg(["sum", "count"]).reset_index()
        tot_cliente.columns = ["CLIENTE", "TOTAL_CLIENTE", "NUM_ALBARANES"]

        tpv_ref = df_tpv.groupby("REF_TPV", as_index=False)["IMP_TPV"].sum()

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

        mask_ref = df_res["IMP_TPV"].notna()
        df_res.loc[mask_ref, "ESTADO COBRO"] = "COBRADO"
        df_res.loc[mask_ref, "DIF_TOTAL"] = df_res["IMP_TPV"] - df_res["TOTAL_CLIENTE"]

        for idx, row in df_res[mask_ref].iterrows():
            dif = row["DIF_TOTAL"]

            if abs(dif) < 0.01:
                df_res.at[idx, "OBSERVACIONES"] = f"Cobrado {formato_coma(row['IMP_TPV'])} (total de {int(row['NUM_ALBARANES'])} albaranes)"
            elif dif > 0:
                df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de más {formato_coma(row['IMP_TPV'])}"
            else:
                df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de menos {formato_coma(row['IMP_TPV'])}"

        df_vista = df_res.copy()
        df_vista["IMP_ALBARAN"] = df_vista["IMP_ALBARAN"].apply(formato_coma)
        df_vista["IMP_TPV"] = df_vista["IMP_TPV"].apply(formato_coma)
        df_vista["TOTAL_CLIENTE"] = df_vista["TOTAL_CLIENTE"].apply(formato_coma)

        st.subheader("Resultado conciliación")
        st.dataframe(df_vista, use_container_width=True)

# ==========================================================
# 🟩 PESTAÑA 2 - COMPROBANTES BANCARIOS (MARCA EN VIVO)
# ==========================================================
with tab2:

    st.subheader("Conciliación por comprobantes bancarios")

    excel_file_2 = st.file_uploader("Sube el Excel de albaranes", type=["xlsx", "xls"], key="excel2")

    pdf_files = st.file_uploader(
        "Añade comprobantes bancarios",
        type=["pdf"],
        accept_multiple_files=True,
        key="pdf_multi"
    )

    if "df_cobros_acumulados" not in st.session_state:
        st.session_state.df_cobros_acumulados = pd.DataFrame(columns=["REF_TPV", "IMP_TPV"])

    # ==========================================================
    # AÑADIR COBROS
    # ==========================================================
    if pdf_files:
        if st.button("Añadir comprobantes al acumulado"):
            nuevos = []
            for pdf in pdf_files:
                df_temp = leer_pdf_banco(pdf)
                nuevos.append(df_temp)

            if nuevos:
                df_nuevos = pd.concat(nuevos, ignore_index=True)
                st.session_state.df_cobros_acumulados = pd.concat(
                    [st.session_state.df_cobros_acumulados, df_nuevos],
                    ignore_index=True
                )
                st.success(f"Se han añadido {len(df_nuevos)} cobros al acumulado")

    if st.button("Limpiar cobros acumulados"):
        st.session_state.df_cobros_acumulados = pd.DataFrame(columns=["REF_TPV", "IMP_TPV"])
        st.warning("Cobros acumulados eliminados")

    # ==========================================================
    # PROCESO PRINCIPAL
    # ==========================================================
    if excel_file_2:

        df_alb = pd.read_excel(excel_file_2, dtype={"Venta a-Nº cliente": str})
        df_alb["IMP_ALBARAN"] = df_alb["Importe envío IVA incluido"].apply(limpiar_importe_excel)

        # Totales por cliente
        tot_cliente = df_alb.groupby("Venta a-Nº cliente")["IMP_ALBARAN"].agg(["sum", "count"]).reset_index()
        tot_cliente.columns = ["CLIENTE", "TOTAL_CLIENTE", "NUM_ALBARANES"]

        df_res = df_alb.merge(
            tot_cliente,
            how="left",
            left_on="Venta a-Nº cliente",
            right_on="CLIENTE"
        )

        df_res["IMP_TPV"] = None
        df_res["ESTADO COBRO"] = "NO COBRADO"
        df_res["OBSERVACIONES"] = ""

        # ==========================================================
        # APLICAR COBROS ACUMULADOS
        # ==========================================================
        if not st.session_state.df_cobros_acumulados.empty:

            tpv_ref = st.session_state.df_cobros_acumulados.groupby("REF_TPV", as_index=False)["IMP_TPV"].sum()

            df_res = df_res.merge(
                tpv_ref,
                how="left",
                left_on="Venta a-Nº cliente",
                right_on="REF_TPV",
                suffixes=("", "_TPV")
            )

            df_res["IMP_TPV"] = df_res["IMP_TPV_TPV"]
            df_res.drop(columns=["IMP_TPV_TPV", "REF_TPV"], inplace=True)

            mask_ref = df_res["IMP_TPV"].notna()
            df_res.loc[mask_ref, "ESTADO COBRO"] = "COBRADO"
            df_res.loc[mask_ref, "DIF_TOTAL"] = df_res["IMP_TPV"] - df_res["TOTAL_CLIENTE"]

            for idx, row in df_res[mask_ref].iterrows():
                dif = row["DIF_TOTAL"]

                if abs(dif) < 0.01:
                    df_res.at[idx, "OBSERVACIONES"] = f"Cobrado {formato_coma(row['IMP_TPV'])} (total de {int(row['NUM_ALBARANES'])} albaranes)"
                elif dif > 0:
                    df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de más {formato_coma(row['IMP_TPV'])}"
                else:
                    df_res.at[idx, "OBSERVACIONES"] = f"Cobrado de menos {formato_coma(row['IMP_TPV'])}"

        # ==========================================================
        # VISTA PREVIA EN VIVO
        # ==========================================================
        df_vista2 = df_res.copy()
        df_vista2["IMP_ALBARAN"] = df_vista2["IMP_ALBARAN"].apply(formato_coma)
        df_vista2["IMP_TPV"] = df_vista2["IMP_TPV"].apply(formato_coma)
        df_vista2["TOTAL_CLIENTE"] = df_vista2["TOTAL_CLIENTE"].apply(formato_coma)

        st.markdown("### Vista previa del Excel con cobros aplicados")
        st.dataframe(df_vista2, use_container_width=True)

        # ==========================================================
        # DESCARGA EXCEL FINAL
        # ==========================================================
        buffer = BytesIO()

        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df_vista2.to_excel(writer, index=False, sheet_name="Conciliación banco")
            autoajustar_columnas(writer, df_vista2, "Conciliación banco")

        buffer.seek(0)

        st.download_button(
            "Descargar Excel final",
            data=buffer,
            file_name="conciliacion_banco.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
