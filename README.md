# 📊 Conciliación de cobros TPV vs Albaranes (Streamlit)

Aplicación desarrollada en **Streamlit** para conciliar automáticamente los cobros realizados mediante **TPV** con los **albaranes repartidos**, detectando:
- Clientes cobrados
- Clientes no cobrados
- Diferencias de importe
- Errores por referencias mal escritas en el TPV

Pensada para control diario/semanal en empresas de reparto.

---

## 🚀 Funcionalidades

✔ Subida de **PDF de cobros TPV**  
✔ Subida de **Excel de albaranes**  
✔ Marcado automático de:
- `COBRADO`
- `NO COBRADO`

✔ Comparación de importes  
✔ Detección automática de:
- Referencias TPV mal escritas
- Errores humanos al teclear el cliente
- Cobros cruzados

✔ Descarga del resultado en **Excel**

---

## 📂 Archivos de entrada

### 1️⃣ PDF de cobros TPV
Debe contener una tabla con al menos:
- **REFERENCIA** → número de cliente informado en el cobro
- **IMPORTE** → importe cobrado  
Formato decimal:  
- Decimales con **punto** (ej: `123.45`)

---

### 2️⃣ Excel de albaranes
Debe contener las siguientes columnas:
- **Venta a-Nº cliente**
- **Importe envío IVA incluido**  
Formato decimal:
- Decimales con **coma** (ej: `123,45`)

---

## 🧠 Lógica de conciliación

1. Se agrupan los cobros TPV por cliente
2. Se cruzan con los albaranes
3. Para cada albarán:
   - Si existe cobro → **COBRADO**
   - Si no existe → **NO COBRADO**
4. Si no está cobrado:
   - Se busca un cobro TPV con **el mismo importe**
   - Se calcula la **similitud del número de cliente**
   - Se clasifica el error automáticamente

---

## 🏷️ Interpretación de OBSERVACIONES

- **Sin cobro TPV**  
  → El cliente realmente no está cobrado

- **Importe no coincide**  
  → El cliente está cobrado, pero el importe es distinto

- **Alta prob. ref. mal escrita (TPV: XXXXX, similitud XX%)**  
  → Error humano casi seguro al introducir el cliente en el TPV

- **Cobro TPV con mismo importe (ref distinta)**  
  → Cobro existente, pero cliente incorrecto o cruzado

---

## 🖥️ Instalación

### Requisitos
- Python 3.9 o superior

### Instalar dependencias
```bash
pip install streamlit pandas pdfplumber openpyxl

