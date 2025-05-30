import streamlit as st
import pandas as pd
import datetime
import os
import json
import re
from openai import OpenAI
from io import BytesIO
from pydantic import BaseModel, Field
from typing import List, Dict
from enum import Enum
import plotly.express as px
import openpyxl

# Configuración de la API Key
key_ = st.secrets["llm"]["key_"]
client = OpenAI(api_key=key_)

st.title("Catalogador de Múltiples Tablas - v2.0")



class tipo_dato(str, Enum):
    texto, numero, fecha = "texto", "numero", "fecha"

class Column(BaseModel):
    name: str  # Nombre de la columna
    description: str  # Breve descripción del significado de la columna
    type: tipo_dato
    new_name: str | None = None  # Nuevo nombre sugerido en Pascal_Snake_Case y en base al contenido de la columna, o None si no hay recomendación
    reason: str | None = None  # Razón de la sugerencia del new_name, si aplica

class TableMetadata(BaseModel):
    table_description: str  # Descripción general de la tabla (máx 500 caracteres)
    columns: List[Column]

TableMetadata.model_rebuild()  # This is required to enable recursive types

# --- NUEVO: Función para verificar si la tabla tiene columna identificador único ---
def tiene_columna_id(df):
    for col in df.columns:
        if df[col].is_unique and df[col].notnull().all():
            return col
    return "No tiene"

# usar_ia = st.session_state.get("usar_ia", None)
# if usar_ia is None:
usar_ia = st.checkbox(
    f"¿Generar descripciones automáticas con IA para las tablas?",
    value=True,
    key=f"usar_ia"
)
# st.session_state["usar_ia"] = usar_ia

@st.cache_data(show_spinner=False)
def procesar_archivos(files, selected_sheets_per_file, user_context):
    metadatos_list = []
    diccionarios_list = []
    table_names = []
    fecha = str(datetime.date.today())
    for idx, uploaded_file in enumerate(files):
        file_name = uploaded_file.name
        file_format = file_name.split('.')[-1].lower()
        xls = pd.ExcelFile(uploaded_file)
        all_sheets = xls.sheet_names
        sheets_to_analyze = selected_sheets_per_file.get(file_name, [])
        for sheet_name in sheets_to_analyze:
            df = pd.read_excel(uploaded_file, sheet_name=sheet_name, dtype=str)
            df = df.where(pd.notnull(df), None)
            df = df.replace({pd.NaT: None})
            df = df.astype(object).where(pd.notnull(df), None)
            df = df.map(lambda x: str(x) if isinstance(x, pd.Timestamp) else x)
            table_id = f"T{str(len(metadatos_list)+1).zfill(3)}"
            muestra_tabla = df.sample(min(10, len(df)), random_state=1).to_dict(orient="list")
            # --- Incluir contexto del usuario en el prompt del sistema ---
            # --- Opción para usar IA o no ---
            
            if usar_ia:
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
            else:
                # Generar estructura vacía con los mismos keys
                dict_ia = {
                    "table_description": "",
                    "columns": [
                        {
                            "name": col,
                            "description": "",
                            "type": "",
                            "new_name": "",
                            "reason": ""
                        } for col in df.columns
                    ]
                }
            # --- Verificar si la tabla tiene columna identificador único ---
            nombre_id = tiene_columna_id(df)
            metadatos = {
                "file_name": file_name,
                "table_id": table_id,
                "table_name": sheet_name,
                "table_description": dict_ia.get("table_description", ""),
                "format": file_format,
                "date_modified": fecha,
                "date_register": fecha,
                "data_privacy": "Cerrado",
                "data_steward_operativo_contact": "",
                "data_steward_ejecutivo_contact": "",
                "domain": "",
                "data_owner_area": "",
                "location_path": "",
                "periodicity": "Ad hoc (sin frecuencia fija)",
                "table_status": "Activa",
                "Columna_ID": nombre_id,  # NUEVO: columna al final
            }
            metadatos_list.append(metadatos)
            # if 'dict_ia' not in locals():
            #     muestra_tabla = df.sample(min(10, len(df)), random_state=1).to_dict(orient="list")
            #     system_msg = "Eres un experto catalogador de datos. Analiza la siguiente muestra de una tabla y responde en **español**."
            #     if user_context and user_context.strip():
            #         system_msg += f"\n\nContexto adicional proporcionado por el usuario para mejorar la catalogación: {user_context.strip()}"
            #     prompt_dict = f"""
            #     Muestra de la tabla (formato JSON):
            #     {json.dumps(muestra_tabla, ensure_ascii=False)}
            #     """
            #     response = client.responses.parse(
            #         model="gpt-4o-mini",
            #         input=[
            #             {"role": "system", "content": system_msg},
            #             {"role": "user", "content": prompt_dict}
            #         ],
            #         text_format=TableMetadata,
            #     )
            #     dict_ia = response.output_parsed.dict()
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
                    "column_rename_suggestion": col.get("new_name", ""),
                    "reason": col.get("reason", ""),
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
                    "GAF - Contabilidad",
                    "GAF - Logística",
                    "GAF - Planificación Estratégica",
                    "GTO - Centro de Experiencia",
                    "GTO - Soluciones de Seguridad Física",
                    "GTO - Soluciones Digitales",
                    "GTO - Soluciones Tecnológicas",
                    "GTO - TI",
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
            metadatos.to_excel(writer, index=False, sheet_name='METADATOS')
            diccionarios_concat.to_excel(writer, index=False, sheet_name='DICCIONARIO')
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
    # --- INFORME MARKDOWN ---
    import io
    from datetime import date

    # Helper function to convert DataFrame to HTML table with black borders
    def df_to_html_table(df):
        if df.empty:
            return ""
        return df.to_html(index=False, border=1, classes="black-border-table", escape=False)

    # CSS for black borders
    st.markdown("""
    <style>
    .black-border-table, .black-border-table th, .black-border-table td {
        border: 2px solid black !important;
        border-collapse: collapse !important;
        padding: 4px 8px !important;
        text-align: left !important;
    }
    </style>
    """, unsafe_allow_html=True)

    df_file_tables = metadatos_edit[['file_name', 'table_name']].groupby('file_name').agg({'table_name':'nunique'}).reset_index().rename(columns={'table_name':'Nro_tablas'})
    tabla1_html = df_to_html_table(df_file_tables)

    df_file_table_attrs = pd.DataFrame(diccionarios_list).groupby(['file_name','table_name']).agg({'Atributo':'count'}).reset_index().rename(columns={'Atributo':'Nro_atributos'})
    tabla2_html = df_to_html_table(df_file_table_attrs)

    df_id = metadatos_edit[['file_name','table_name','Columna_ID']].rename(columns={'Columna_ID':'ID_identificador'})
    # Agregar estilos de color según el valor de ID_identificador
    def color_id(val):
        if val == "No tiene":
            return 'background-color: #ffcccc; border: 2px solid black !important;'  # rojo claro + borde negro
        else:
            return 'background-color: #ccffcc; border: 2px solid black !important;'  # verde claro + borde negro

    # Aplicar estilos solo a la columna ID_identificador
    styled_df_id = df_id.style.applymap(color_id, subset=['ID_identificador'])
    # Convertir a HTML con estilos embebidos y bordes negros
    tabla3_html = styled_df_id.to_html(
        index=False,
        border=1,
        classes="black-border-table",
        escape=False
    )
    # Asegurar que todos los bordes sean negros (sobrescribir posibles estilos por defecto)
    tabla3_html = tabla3_html.replace(
        '<table ',
        '<table style="border:2px solid black;border-collapse:collapse;" '
    ).replace(
        '<th ',
        '<th style="border:2px solid black;" '
    ).replace(
        '<td ',
        '<td style="border:2px solid black;" '
    )

    df_roles = metadatos_edit[['file_name','table_name','data_owner_area','data_steward_operativo_contact','data_steward_ejecutivo_contact']]
    tabla4_html = df_to_html_table(df_roles)

    df_dicc = pd.DataFrame(diccionarios_list)
    df_renames = df_dicc[df_dicc['column_rename_suggestion'].notnull() & (df_dicc['column_rename_suggestion'] != '')]
    if not df_renames.empty:
        tabla5_html = df_to_html_table(
            df_renames[['file_name','table_name','Atributo','column_rename_suggestion']]
            .rename(columns={'Atributo':'Atributo_original','column_rename_suggestion':'Nuevo_nombre_propuesto'})
        )
    else:
        tabla5_html = '<p>No hay propuestas de renombre.</p>'

    FECHA_GENERACION = date.today().strftime('%d/%m/%Y')
    NUM_TABLAS = metadatos_edit['table_name'].nunique()
    NUM_ATRIBUTOS = df_dicc['Atributo'].shape[0] # .nunique()

    markdown_report = f"""
---
# <b>INFORME DE RESULTADOS</b>

Procesamiento Automático de Metadatos y Descripciones de Tablas

<b>Fecha de generación: {FECHA_GENERACION}</b>

---

### I. Resumen ejecutivo

Durante el proceso se analizaron <b>{NUM_TABLAS}</b> tablas que contienen <b>{NUM_ATRIBUTOS}</b> atributos. Se generaron descripciones automáticas, se verificó la presencia de identificadores de registro, se asignaron/validaron responsables de gobierno de datos y se propusieron nombres para los atributos que carecían de denominación.

---

### II. Resultados detallados

1. <b>Descripciones generadas</b>

{tabla1_html}
    
{tabla2_html}

2. <b>Identificación de IDs de registro</b>

{tabla3_html}

3. <b>Asignación de roles de Gobierno de Datos</b>

{tabla4_html}

4. <b>Propuestas de nomenclatura para atributos sin nombre</b>

{tabla5_html}

---

### III. Recomendaciones inmediatas

1. <b>Validar descripciones</b>: Revisar y aprobar las descripciones generadas para asegurar precisión semántica y alineación con el glosario corporativo.
2. <b>Crear/normalizar IDs</b>: Asignar identificadores únicos a las tablas que carecen de ellos para garantizar trazabilidad.
3. <b>Confirmar responsables</b>: Verificar la asignación de Data Stewards y Data Owners para cada tabla y actualizar en caso de cambios organizacionales.
4. <b>Revisar nombres propuestos</b>: Aceptar o ajustar las sugerencias de nombre de atributos, asegurando consistencia con los estándares de nomenclatura. Verificar si no existen procesos automatizados que impidan el cambio del nombre del atributo.

---

### IV. Próximos pasos

<table class="black-border-table">
<thead>
<tr>
<th>Fase</th>
<th>Acción</th>
<th>Responsable</th>
<th>Fecha objetivo</th>
</tr>
</thead>
<tbody>
<tr>
<td>1</td>
<td>Validación de descripciones y nombres propuestos</td>
<td></td>
<td></td>
</tr>
<tr>
<td>2</td>
<td>Actualización de metadatos en el Catálogo de datos</td>
<td></td>
<td></td>
</tr>
</tbody>
</table>

---

### V. Anexos

<ul>
<li><b>A1. Metadatos y Diccionario de datos</b></li>
<li><b>A2. Datos técnicos de automatización</b>
    <ol>
        <li><b>Fuente de los datos</b>:</li>
        <li><b>Versión del modelo de IA utilizada</b>: ChatGPT-4.1-mini</li>
        <li><b>Versión de la App</b>: v2.0</li>
    </ol>
</li>
</ul>
---
"""
    st.markdown(markdown_report, unsafe_allow_html=True)
