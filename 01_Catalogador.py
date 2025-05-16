import streamlit as st
import pandas as pd
import datetime
import os
import json
import re
from openai import OpenAI

# Configuración de la API Key
key_ = st.secrets["llm"]["key_"]
client = OpenAI(api_key=key_)

st.title("Catalogador de Datos - Chatbot")

# 1. Subida de archivo
today = datetime.date.today().isoformat()
uploaded_file = st.file_uploader("Sube tu archivo de datos (Excel, CSV, etc.)", type=["csv", "xlsx"])

if uploaded_file:
    file_name = uploaded_file.name
    file_format = file_name.split('.')[-1].lower()
    df = None
    if file_format == "csv":
        df = pd.read_csv(uploaded_file)
    elif file_format in ["xls", "xlsx"]:
        df = pd.read_excel(uploaded_file)
    else:
        st.error("Formato no soportado.")

    if df is not None:
        st.write("Vista previa de la tabla:")
        st.dataframe(df.head())

        # 2. Preguntar al usuario por los metadatos requeridos
        domain = st.text_input("Dominio › Subdominio (ej.: Finanzas › Créditos):")
        data_owner_area = st.selectbox("Gerencia o Jefatura propietaria de los datos:", ["Comercial",
                                            "Coordinación Institucional",
                                            "Coordinación Parlamentaria",
                                            "Cumplimiento y Ética",
                                            "Evaluación, Analítica y Sostenibilidad",
                                            "Gestión Humana",
                                            "Imagen Institucional y Comunicaciones",
                                            "Seguridad Estratégica",
                                            "SRC",
                                            "GAF - Contabilidad ",
                                            "GAF - Logística ",
                                            "GAF - Planificación Estratégica ",
                                            "GTO - Centro de Experiencia ",
                                            "GTO - Soluciones de Seguridad Física ",
                                            "GTO - Soluciones Digitales ",
                                            "GTO - Soluciones Tecnológicas ",
                                            "GTO - TI ",
                                            "GAF",
                                            "GTO"])

        # Validación de correos electrónicos
        def es_email_valido(email):
            patron = r"^[\w\.-]+@asbanc.com.pe"
            return re.match(patron, email) is not None

        data_steward_operativo_contact = st.text_input("Correo del data steward operativo:")
        if data_steward_operativo_contact and not es_email_valido(data_steward_operativo_contact):
            st.error("El correo del data steward operativo no es válido.")
        data_steward_ejecutivo_contact = st.text_input("Correo del data steward ejecutivo:")
        if data_steward_ejecutivo_contact and not es_email_valido(data_steward_ejecutivo_contact):
            st.error("El correo del data steward ejecutivo no es válido.")

        data_privacy = st.selectbox("Privacidad de los datos:", ["Abierto", "Personales", "Cerrado"])
        location_path = st.text_input("Ruta o ubicación del archivo:")
        periodicity = st.selectbox("Frecuencia de actualización:", ["Tiempo real", "Diaria", "Semanal", "Mensual", "Trimestral", "Semestral", "Anual", "Ad hoc (sin frecuencia fija)", "Sin necesidad de actualizar"])
        table_status = st.selectbox("Estado de la tabla:", ["Activa", "Desactivada"])

        # 3. Inferir metadatos con IA
        if st.button("Catalogar tabla"):
            if (not es_email_valido(data_steward_operativo_contact)) or (not es_email_valido(data_steward_ejecutivo_contact)):
                st.error("Por favor, ingresa correos electrónicos válidos para ambos stewards antes de continuar.")
            else:
                # 6. Inferir descripción general y diccionario de datos en una sola consulta a la IA
                columnas = list(df.columns)
                muestra_tabla = df.sample(min(10, len(df)), random_state=1).to_dict(orient="list")
                prompt_dict = f"""
Eres un experto catalogador de datos. Analiza la siguiente muestra de una tabla y responde en formato JSON con:
- 'table_description': descripción general de la tabla (máx 500 caracteres)
- 'columns': una lista de objetos, uno por cada columna, con los campos:
    - 'name': nombre de la columna
    - 'description': breve descripción del significado de la columna
    - 'type': tipo de dato (elige entre: texto, número, fecha, booleano, etc.)

Muestra de la tabla (formato JSON):
{json.dumps(muestra_tabla, ensure_ascii=False)}
"""
                response_dict = client.chat.completions.create(
                    model="gpt-4o-mini",
                    response_format={"type": 'json_object'},
                    messages=[{"role": "system", "content": "Eres un experto catalogador de datos."},
                              {"role": "user", "content": prompt_dict}],
                    temperature=0
                )
                try:
                    dict_ia = json.loads(response_dict.choices[0].message.content)
                except Exception:
                    st.error("No se pudo interpretar la respuesta de la IA para el diccionario de datos.")
                    dict_ia = {"table_description": "", "columns": []}

                # 4. Consolidar todos los metadatos
                if file_format in ["xls", "xlsx"]:
                    sheet_name = uploaded_file.sheet_names[0] if hasattr(uploaded_file, 'sheet_names') else file_name.split('.')[0]
                else:
                    sheet_name = file_name.split('.')[0]

                metadatos = {
                    "domain": domain,
                    "id_table": 1, #metadatos_ia_json.get("id_table", ""),
                    "table_description": dict_ia.get("table_description", ""),
                    "table_name": sheet_name, # metadatos_ia_json.get("table_name", sheet_name),
                    "data_owner_area": data_owner_area,
                    "data_steward_operativo_contact": data_steward_operativo_contact,
                    "data_privacy": data_privacy,
                    "format": file_format,
                    "location_path": location_path,
                    "source_type": "file",
                    "date_modified": today,
                    "date_register": today,
                    "periodicity": periodicity,
                    "table_status": table_status,
                    "data_steward_ejecutivo_contact": data_steward_ejecutivo_contact
                }

                # 5. Mostrar tabla final de metadatos
                st.subheader("Metadatos consolidados")
                st.dataframe(pd.DataFrame([metadatos]))
                st.info("Copia y pega la tabla de metadatos donde lo necesites.")

                # 7. Mostrar tabla de atributos (diccionario de datos)
                atributos = []
                for col in dict_ia.get("columns", []):
                    atributos.append({
                        "Atributo": col.get("name", ""),
                        "Descripción": col.get("description", ""),
                        "Tipo de dato": col.get("type", "")
                    })
                st.subheader("Diccionario de datos de la tabla")
                st.dataframe(pd.DataFrame(atributos))
                st.info("Copia y pega el diccionario de datos donde lo necesites.")
