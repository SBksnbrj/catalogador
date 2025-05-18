import streamlit as st
import pandas as pd
import datetime
import os
import json
import re
from openai import OpenAI
from io import BytesIO
from pydantic import BaseModel, Field
from typing import List
from enum import Enum
import plotly.express as px

# Configuración de la API Key
key_ = st.secrets["llm"]["key_"]
client = OpenAI(api_key=key_)

st.title("Catalogador de Múltiples Tablas - v1.0")

# 1. Subida de múltiples archivos
today = datetime.date.today().isoformat()

class tipo_dato(str, Enum):
    texto, numero, fecha = "texto", "numero", "fecha"

class Column(BaseModel):
    name: str  # Nombre de la columna
    description: str  # Breve descripción del significado de la columna
    type: tipo_dato

class TableMetadata(BaseModel):
    table_description: str  # Descripción general de la tabla (máx 500 caracteres)
    columns: List[Column]

TableMetadata.model_rebuild()  # This is required to enable recursive types

@st.cache_data(show_spinner=False)
def procesar_archivos(files, fecha):
    metadatos_list = []
    diccionarios_list = []
    table_names = []

    for idx, uploaded_file in enumerate(files):
        file_name = uploaded_file.name
        file_format = file_name.split('.')[-1].lower()
        df = None
        if file_format == "csv":
            df = pd.read_csv(uploaded_file)
        elif file_format in ["xls", "xlsx"]:
            df = pd.read_excel(uploaded_file)
        else:
            continue
        if df is not None:
            muestra_tabla = df.sample(min(10, len(df)), random_state=1).to_dict(orient="list")
            prompt_dict = f"""
            Muestra de la tabla (formato JSON):
            {json.dumps(muestra_tabla, ensure_ascii=False)}
            """
            response = client.responses.parse(
                model="gpt-4o-mini",
                input=[
                    {"role": "system", "content": "Eres un experto catalogador de datos. Analiza la siguiente muestra de una tabla y responde en **español**"},
                    {"role": "user", "content": prompt_dict}
                ],
                text_format=TableMetadata,
            )
            dict_ia = response.output_parsed.dict()
            if file_format in ["xls", "xlsx"]:
                sheet_name = uploaded_file.name.split('.')[0]
            else:
                sheet_name = file_name.split('.')[0]
            table_id = f"T{str(idx+1).zfill(3)}"
            metadatos = {
                "table_id": table_id,
                "table_name": sheet_name,
                "table_description": dict_ia.get("table_description", ""),
                "format": file_format,
                "date_modified": fecha,
                "date_register": fecha,
                # Los siguientes campos quedan en blanco para edición manual:
                "data_privacy": "",
                "data_steward_operativo_contact": "",
                "data_steward_ejecutivo_contact": "",
                "domain": "",
                "data_owner_area": "",
                "location_path": "",
                "periodicity": "",
                "table_status": ""
            }
            metadatos_list.append(metadatos)
            for i, col in enumerate(dict_ia.get("columns", [])):
                id_atributo = f"a{str(i+1).zfill(3)}"
                diccionarios_list.append({
                    "table_id": table_id,
                    "id_atributo": id_atributo,
                    "Atributo": col.get("name", ""),
                    "Descripción": col.get("description", ""),
                    "Tipo de dato": col.get("type", "").replace("tipo_dato.", ""),
                })
            table_names.append(sheet_name)
    return metadatos_list, diccionarios_list, table_names

uploaded_files = st.file_uploader("Sube tus archivos de datos (Excel, CSV, etc.)", type=["csv", "xlsx"], accept_multiple_files=True)

# Para almacenar resultados
metadatos_list = []
diccionarios_list = []
table_names = []

if uploaded_files and len(uploaded_files) > 0:
    metadatos_list, diccionarios_list, table_names = procesar_archivos(uploaded_files, today)
    st.subheader("Completitud de metadatos por tabla")
    import streamlit as st
    from streamlit import column_config
    metadatos_df = pd.DataFrame(metadatos_list)
    # Mostrar solo la parte de usuario para los correos en el editor
    for col in ["data_steward_operativo_contact", "data_steward_ejecutivo_contact"]:
        metadatos_df[col] = metadatos_df[col].str.replace("@asbanc.com.pe", "", regex=False)
    # Editor de metadatos
    metadatos_edit = st.data_editor(
        metadatos_df,
        num_rows="dynamic",
        key="meta_editor",
        column_config={
            "data_owner_area": st.column_config.SelectboxColumn(
                "Gerencia o Jefatura propietaria de los datos",
                options=[
                    "Comercial",
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
                    "GTO"
                ]
            ),
            "data_privacy": st.column_config.SelectboxColumn(
                "Privacidad de los datos",
                options=["Abierto", "Personales", "Cerrado"]
            ),
            "periodicity": st.column_config.SelectboxColumn(
                "Frecuencia de actualización",
                options=[
                    "Tiempo real", "Diaria", "Semanal", "Mensual", "Trimestral", "Semestral", "Anual", "Ad hoc (sin frecuencia fija)", "Sin necesidad de actualizar"
                ]
            ),
            "table_status": st.column_config.SelectboxColumn(
                "Estado de la tabla",
                options=["Activa", "Desactivada"]
            ),
            "data_steward_operativo_contact": st.column_config.TextColumn(
                "Usuario del data steward operativo (sin @asbanc.com.pe)",
                help="Solo el usuario, el dominio se agregará automáticamente"
            ),
            "data_steward_ejecutivo_contact": st.column_config.TextColumn(
                "Usuario del data steward ejecutivo (sin @asbanc.com.pe)",
                help="Solo el usuario, el dominio se agregará automáticamente"
            ),
            "domain": st.column_config.TextColumn(
                "Dominio › Subdominio (ej.: Finanzas › Créditos)"
            ),
            "location_path": st.column_config.TextColumn(
                "Ruta o ubicación del archivo"
            )
        }
    )
    # --- GRAFICO DE COMPLETITUD ---
    campos_a_evaluar = [
        "table_id", "table_name", "table_description", "format", "date_modified", "date_register",
        "data_privacy", "data_steward_operativo_contact", "data_steward_ejecutivo_contact", "domain",
        "data_owner_area", "location_path", "periodicity", "table_status"
    ]
    completitud = []
    vacios_dict = {}
    for idx, row in metadatos_edit.iterrows():
        total = len(campos_a_evaluar)
        vacios = [campo for campo in campos_a_evaluar if not str(row[campo]).strip()]
        llenos = total - len(vacios)
        pct = round(100 * llenos / total, 1)
        completitud.append(pct)
        vacios_dict[row["table_id"]] = vacios
    metadatos_edit["% Completitud"] = completitud
    metadatos_edit_sorted = metadatos_edit.sort_values("% Completitud")
    # Tooltip personalizado con campos vacíos
    hovertext = [
        f"Tabla: {row['table_name']}<br>Completitud: {row['% Completitud']}%<br>Vacíos: {', '.join(vacios_dict[row['table_id']]) if vacios_dict[row['table_id']] else 'Ninguno'}"
        for _, row in metadatos_edit_sorted.iterrows()
    ]
    fig = px.bar(
        metadatos_edit_sorted,
        y="table_name",
        x="% Completitud",
        orientation="h",
        text="% Completitud",
        title="Porcentaje de completitud de metadatos por tabla",
        labels={"table_name": "Tabla", "% Completitud": "% Completitud"},
        color="% Completitud",
        color_continuous_scale=["#ff0000", "#ffff00", "#00ff00"],  # Rojo → Amarillo → Verde
        range_color=[0, 100]
    )
    fig.update_traces(
        marker_line_color='black', marker_line_width=0,
        hovertemplate=hovertext
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.subheader("Diccionario de datos por tabla")
    selected_table = st.selectbox("Selecciona una tabla para ver su diccionario", table_names)
    diccionario_df = pd.DataFrame([d for d in diccionarios_list if d["table_id"] == metadatos_df.loc[metadatos_df["table_name"] == selected_table, "table_id"].values[0]])

    # Asignar un color distinto a cada valor de "Tipo de dato" NOT POSSIBLE RIGHT NOW
    # tipo_colores = {"texto": "#e6f7ff", "numero": "#e6ffe6", "fecha": "#fff5e6"}
    # def color_tipo(val):
    #     return f'background-color: {tipo_colores.get(val, "#ffffff")}'
    # diccionario_df_styled = diccionario_df.style.applymap(color_tipo, subset=["Tipo de dato"])
    diccionario_edit = st.data_editor(
        diccionario_df,
        use_container_width=True,
        num_rows="dynamic",
        key=f"diccionario_editor_{selected_table}",
        column_config={
            "id_atributo": st.column_config.TextColumn("ID de atributo", disabled=True),
            "Tipo de dato": st.column_config.SelectboxColumn(
                "Tipo de dato",
                options=["texto", "numero", "fecha"]
            )
        }
    )
    
    print(diccionario_df)

    # Al descargar, concatenar el dominio a los correos
    def to_excel(metadatos, diccionarios):
        metadatos = metadatos.copy()
        for col in ["data_steward_operativo_contact", "data_steward_ejecutivo_contact"]:
            metadatos[col] = metadatos[col].astype(str).str.strip() + "@asbanc.com.pe"
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            metadatos.to_excel(writer, index=False, sheet_name='Metadatos')
            pd.DataFrame(diccionarios).to_excel(writer, index=False, sheet_name='Diccionario')
        output.seek(0)
        return output

    if st.button("Descargar metadatos y diccionarios consolidados"):
        excel_bytes = to_excel(metadatos_edit, diccionarios_list)
        st.download_button(
            label="Descargar Excel",
            data=excel_bytes,
            file_name="catalogo_metadatos_diccionario.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
