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
import openpyxl

# Configuración de la API Key
key_ = st.secrets["llm"]["key_"]
client = OpenAI(api_key=key_)

st.title("Catalogador de Múltiples Tablas - v1.0")



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
def procesar_archivos(files, selected_sheets_per_file, user_context):
    metadatos_list = []
    diccionarios_list = []
    table_names = []
    fecha = str(datetime.date.today())
    for idx, uploaded_file in enumerate(files):
        file_name = uploaded_file.name
        file_format = file_name.split('.')[-1].lower()
        if file_format in ["xls", "xlsx"]:
            xls = pd.ExcelFile(uploaded_file)
            all_sheets = xls.sheet_names
            tiene_metadatos = "METADATOS" in [s.upper() for s in all_sheets]
            tiene_diccionario = "DICCIONARIO" in [s.upper() for s in all_sheets]
            sheets_to_analyze = selected_sheets_per_file.get(file_name, [])
            for sheet_name in sheets_to_analyze:
                df = pd.read_excel(uploaded_file, sheet_name=sheet_name)
                df = df.where(pd.notnull(df), None)
                df = df.replace({pd.NaT: None})
                df = df.astype(object).where(pd.notnull(df), None)
                df = df.map(lambda x: str(x) if isinstance(x, pd.Timestamp) else x)
                table_id = f"T{str(len(metadatos_list)+1).zfill(3)}"
                if not tiene_metadatos:
                    muestra_tabla = df.sample(min(10, len(df)), random_state=1).to_dict(orient="list")
                    # --- Incluir contexto del usuario en el prompt del sistema ---
                    system_msg = "Eres un experto catalogador de datos. Analiza la siguiente muestra de una tabla y responde en **español**."
                    if user_context and user_context.strip():
                        system_msg += f"\n\nContexto adicional proporcionado por el usuario para mejorar la catalogación: {user_context.strip()}"
                    prompt_dict = f"""
                    Muestra de la tabla (formato JSON):
                    {json.dumps(muestra_tabla, ensure_ascii=False)}
                    """
                    response = client.responses.parse(
                        model="gpt-4o-mini",
                        input=[
                            {"role": "system", "content": system_msg},
                            {"role": "user", "content": prompt_dict}
                        ],
                        text_format=TableMetadata,
                    )
                    dict_ia = response.output_parsed.dict()
                    metadatos = {
                        "file_name": file_name,
                        "table_id": table_id,
                        "table_name": sheet_name,
                        "table_description": dict_ia.get("table_description", ""),
                        "format": file_format,
                        "date_modified": fecha,
                        "date_register": fecha,
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
                if not tiene_diccionario:
                    if 'dict_ia' not in locals():
                        muestra_tabla = df.sample(min(10, len(df)), random_state=1).to_dict(orient="list")
                        system_msg = "Eres un experto catalogador de datos. Analiza la siguiente muestra de una tabla y responde en **español**."
                        if user_context and user_context.strip():
                            system_msg += f"\n\nContexto adicional proporcionado por el usuario para mejorar la catalogación: {user_context.strip()}"
                        prompt_dict = f"""
                        Muestra de la tabla (formato JSON):
                        {json.dumps(muestra_tabla, ensure_ascii=False)}
                        """
                        response = client.responses.parse(
                            model="gpt-4o-mini",
                            input=[
                                {"role": "system", "content": system_msg},
                                {"role": "user", "content": prompt_dict}
                            ],
                            text_format=TableMetadata,
                        )
                        dict_ia = response.output_parsed.dict()
                    for i, col in enumerate(dict_ia.get("columns", [])):
                        id_atributo = f"a{str(i+1).zfill(3)}"
                        diccionarios_list.append({
                            "file_name": file_name,
                            "table_name": sheet_name,
                            "table_id": table_id,
                            "id_atributo": id_atributo,
                            "Atributo": col.get("name", ""),
                            "Descripción": col.get("description", ""),
                            "Tipo de dato": col.get("type", "").replace("tipo_dato.", ""),
                        })
                table_names.append(sheet_name)
        else:
            # CSV u otros formatos
            df = pd.read_csv(uploaded_file)
            # Reemplazar NaT, NaN y Timestamps por string vacío para evitar problemas de serialización
            df = df.where(pd.notnull(df), None)
            df = df.replace({pd.NaT: None})
            for col in df.columns:
                if pd.api.types.is_datetime64_any_dtype(df[col]):
                    df[col] = df[col].astype(str).replace("NaT", "")
            df = df.astype(object).where(pd.notnull(df), None)
            sheet_name = file_name.split('.')[0]
            table_id = f"T{str(len(metadatos_list)+1).zfill(3)}"
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
            metadatos = {
                "file_name": file_name,  # NUEVO: nombre de archivo al inicio
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
                    "file_name": file_name,  # NUEVO: nombre de archivo al inicio
                    "table_name": sheet_name,  # NUEVO: nombre de tabla al inicio
                    "table_id": table_id,
                    "id_atributo": id_atributo,
                    "Atributo": col.get("name", ""),
                    "Descripción": col.get("description", ""),
                    "Tipo de dato": col.get("type", "").replace("tipo_dato.", ""),
                })
            table_names.append(sheet_name)
    return metadatos_list, diccionarios_list, table_names

# --- NUEVO: Solo Excel, cachear lectura de hojas y separar selección de pestañas del procesamiento ---
@st.cache_data(show_spinner=False)
def get_excel_sheets(uploaded_file):
    xls = pd.ExcelFile(uploaded_file)
    return xls.sheet_names

uploaded_files = st.file_uploader("Sube tus archivos de datos (solo Excel .xlsx, .xls)", type=["xlsx", "xls"], accept_multiple_files=True)

selected_sheets_per_file = {}
# NUEVO: Cuadro de texto para contexto de catalogación
user_context = ""
if uploaded_files and len(uploaded_files) > 0:
    user_context = st.text_area(
        "Agrega aquí contexto adicional para la catalogación de las tablas (por ejemplo: propósito del archivo, reglas de negocio, definiciones, aclaraciones, etc.)",
        help="Este texto será enviado al modelo para mejorar la descripción de las tablas y atributos."
    )
    for idx, uploaded_file in enumerate(uploaded_files):
        file_name = uploaded_file.name
        all_sheets = get_excel_sheets(uploaded_file)
        sheets_to_show = [s for s in all_sheets if s.upper() not in ["METADATOS", "DICCIONARIO"]]
        key = f"sheets_{file_name}_{idx}"
        selected = st.multiselect(
            f"Selecciona las pestañas a analizar del archivo '{file_name}':",
            sheets_to_show,
            default=sheets_to_show,
            key=key
        )
        selected_sheets_per_file[file_name] = selected
    # --- Botón para procesar archivos ---
    if st.button("Procesar archivos seleccionados"):
        metadatos_list, diccionarios_list, table_names = procesar_archivos(uploaded_files, selected_sheets_per_file, user_context)
        st.session_state['metadatos_list'] = metadatos_list
        st.session_state['diccionarios_list'] = diccionarios_list
        st.session_state['table_names'] = table_names
else:
    metadatos_list = []
    diccionarios_list = []
    table_names = []

# --- Mostrar resultados si existen en session_state ---
if 'metadatos_list' in st.session_state and st.session_state['metadatos_list']:
    metadatos_list = st.session_state['metadatos_list']
    diccionarios_list = st.session_state['diccionarios_list']
    table_names = st.session_state['table_names']
    st.subheader("Completitud de metadatos por tabla")
    import streamlit as st
    from streamlit import column_config
    metadatos_df = pd.DataFrame(metadatos_list)
    # Mostrar solo la parte de usuario para los correos en el editor
    for col in ["data_steward_operativo_contact", "data_steward_ejecutivo_contact"]:
        metadatos_df[col] = metadatos_df[col].str.replace("@asbanc.com.pe", "", regex=False)
    # --- GESTIÓN DE ESTADO PARA METADATOS ---
    if 'metadatos_edit_df' not in st.session_state:
        st.session_state['metadatos_edit_df'] = metadatos_df.copy()

    def guardar_metadatos():
        st.session_state['metadatos_edit_df'] = st.session_state['meta_editor']

    metadatos_edit = st.data_editor(
        st.session_state['metadatos_edit_df'],
        num_rows="static",
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
    table_id_selected = metadatos_df.loc[metadatos_df["table_name"] == selected_table, "table_id"].values[0]
    diccionario_df = pd.DataFrame([d for d in diccionarios_list if d["table_id"] == table_id_selected])
    # --- GESTIÓN DE ESTADO PARA DICCIONARIO DE DATOS ---
    if 'diccionario_edit_dict' not in st.session_state:
        st.session_state['diccionario_edit_dict'] = {}
    if table_id_selected not in st.session_state['diccionario_edit_dict']:
        st.session_state['diccionario_edit_dict'][table_id_selected] = diccionario_df.copy()
    # Si por error hay una lista, conviértela a DataFrame
    if not isinstance(st.session_state['diccionario_edit_dict'][table_id_selected], pd.DataFrame):
        st.session_state['diccionario_edit_dict'][table_id_selected] = pd.DataFrame(st.session_state['diccionario_edit_dict'][table_id_selected])

    def guardar_diccionario():
        changes = st.session_state.get(f'diccionario_editor_{selected_table}', {})
        df = st.session_state['diccionario_edit_dict'][table_id_selected].copy()
        # Aplicar cambios de edición
        for idx, row_changes in changes.get('edited_rows', {}).items():
            for col, val in row_changes.items():
                df.at[idx, col] = val
        # Agregar filas nuevas
        for row in changes.get('added_rows', []):
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        # Eliminar filas
        if changes.get('deleted_rows'):
            df = df.drop(changes['deleted_rows']).reset_index(drop=True)
        st.session_state['diccionario_edit_dict'][table_id_selected] = df

    diccionario_edit = st.data_editor(
        st.session_state['diccionario_edit_dict'][table_id_selected],
        use_container_width=True,
        num_rows="static",
        key=f"diccionario_editor_{selected_table}",
        column_config={
            "id_atributo": st.column_config.TextColumn("ID de atributo", disabled=True),
            "Tipo de dato": st.column_config.SelectboxColumn(
                "Tipo de dato",
                options=["texto", "numero", "fecha"]
            )
        },
        on_change=guardar_diccionario
    )

    # Al descargar, usar los datos editados
    def to_excel(metadatos, diccionarios_dict, diccionarios_list, metadatos_df):
        metadatos = metadatos.copy()
        # Eliminar columna de completitud si existe
        if '% Completitud' in metadatos.columns:
            metadatos = metadatos.drop(columns=['% Completitud'])
        for col in ["data_steward_operativo_contact", "data_steward_ejecutivo_contact"]:
            metadatos[col] = metadatos[col].astype(str).str.strip() + "@asbanc.com.pe"
        # --- Concatenar todos los diccionarios, editados o no ---
        diccionarios_all = []
        for idx, row in metadatos_df.iterrows():
            table_id = row['table_id']
            if table_id in diccionarios_dict:
                df_dic = diccionarios_dict[table_id]
            else:
                # Si nunca fue editado, usar el original
                df_dic = pd.DataFrame([d for d in diccionarios_list if d["table_id"] == table_id])
            diccionarios_all.append(df_dic)
        diccionarios_concat = pd.concat(diccionarios_all, ignore_index=True)
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            metadatos.to_excel(writer, index=False, sheet_name='Metadatos')
            diccionarios_concat.to_excel(writer, index=False, sheet_name='Diccionario')
        output.seek(0)
        return output

    if st.button("Descargar metadatos y diccionarios consolidados"):
        excel_bytes = to_excel(metadatos_edit, st.session_state['diccionario_edit_dict'], diccionarios_list, metadatos_df)
        st.download_button(
            label="Descargar Excel",
            data=excel_bytes,
            file_name="catalogo_metadatos_diccionario.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
