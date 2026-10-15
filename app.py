import os
import re
from datetime import datetime, timedelta
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from motor_lifo import (
    construir_esquema,
    cargar_base,
    firma_archivos,
    tipos_columnas_app,
    col_exacta,
    kpis_corte,
    pagina_actualizar_kardex,
)

# ============================================================
# CONFIGURACIÓN GENERAL
# ============================================================

st.set_page_config(
    page_title="Inventarios ALDC",
    page_icon="AL",
    layout="wide",
    initial_sidebar_state="expanded"
)

EPS = 1e-7

# ============================================================
# PALETA INSTITUCIONAL — REFERENCIA ÁREA LIMPIA
# ============================================================

AZUL = "#254B60"
AZUL_OSCURO = "#193747"
AZUL_MEDIO = "#37647B"
AZUL_CLARO = "#A9C4D0"
AZUL_SUAVE = "#EDF3F6"

VERDE = "#87D33F"
VERDE_CLARO = "#B6E879"
VERDE_SUAVE = "#EDF9E4"

NARANJA = "#F58220"
NARANJA_CLARO = "#F9B56E"
NARANJA_SUAVE = "#FFF1E3"

ROJO = "#E66B6B"
ROJO_CLARO = "#F39A9A"
ROJO_SUAVE = "#FDEEEE"

MORADO = "#7A70D8"
MORADO_SUAVE = "#F1EFFF"

AMARILLO = "#F2B84B"
AMARILLO_SUAVE = "#FFF7E4"

GRIS_FONDO = "#F4F6FA"
GRIS_PANEL = "#FFFFFF"
GRIS_BORDE = "#DFE6EF"
GRIS_GRID = "#E9EEF5"
GRIS_TEXTO = "#667892"
GRIS_OSCURO = "#172D49"
BLANCO = "#FFFFFF"

px.defaults.color_discrete_sequence = [
    AZUL, NARANJA, VERDE, MORADO, AMARILLO, AZUL_CLARO, ROJO,
    "#4D6F91", "#9AA9BA", AZUL_OSCURO, "#2FA4A9",
    NARANJA_CLARO, VERDE_CLARO, "#B7A8FF"
]


# ============================================================
# LOGO
# ============================================================

LOGO_URL = (
    "https://encrypted-tbn0.gstatic.com/images?"
    "q=tbn:ANd9GcT4PEaUuLJVbFJSpTZEJ0g0M20hUiko7iba-wcW1MdcEQ&s"
)


# ============================================================
# AUTENTICACIÓN
# ============================================================

try:
    USUARIOS = {
        str(k).strip(): str(v).strip()
        for k, v in dict(st.secrets["usuarios"]).items()
    }

except Exception:
    USUARIOS = {}

TIEMPO_SESION_MINUTOS = 30


# ============================================================
# CSS — INTERFAZ BASADA EN EL DASHBOARD DE REFERENCIA
# ============================================================

st.markdown(
    f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

    :root {{
        --azul: {AZUL};
        --azul-oscuro: {AZUL_OSCURO};
        --azul-medio: {AZUL_MEDIO};
        --verde: {VERDE};
        --fondo: {GRIS_FONDO};
        --borde: {GRIS_BORDE};
        --texto: {GRIS_OSCURO};
        --texto-suave: {GRIS_TEXTO};
    }}

    html, body, [class*="css"] {{
        font-family: "Inter", "Segoe UI", Arial, sans-serif !important;
    }}

    .stApp,
    [data-testid="stAppViewContainer"] {{
        background: {GRIS_FONDO} !important;
    }}

    [data-testid="stHeader"] {{
        background: transparent !important;
    }}

    .block-container {{
        padding-top: 1.75rem !important;
        padding-bottom: 2rem !important;
        max-width: 1510px !important;
    }}

    h1 {{
        color: {AZUL_OSCURO} !important;
        font-size: 2rem !important;
        font-weight: 800 !important;
        letter-spacing: -0.8px !important;
        line-height: 1.15 !important;
        margin-bottom: 0.15rem !important;
    }}

    h2 {{
        color: {AZUL_OSCURO} !important;
        font-size: 1.3rem !important;
        font-weight: 700 !important;
    }}

    h3 {{
        color: {AZUL_OSCURO} !important;
        font-weight: 700 !important;
    }}

    p, label, .stCaption {{
        color: {GRIS_TEXTO};
    }}

    /* =========================================================
       SIDEBAR
       ========================================================= */
    section[data-testid="stSidebar"] {{
        background: {AZUL_OSCURO} !important;
        border-right: 0 !important;
        min-width: 255px !important;
        max-width: 255px !important;
    }}

    section[data-testid="stSidebar"] > div {{
        background: {AZUL_OSCURO} !important;
        padding: 1.35rem 1rem 1rem 1rem !important;
    }}

    section[data-testid="stSidebar"] * {{
        color: #FFFFFF;
    }}

    .sidebar-brand {{
        display: flex;
        align-items: center;
        gap: 11px;
        padding: 0.15rem 0.15rem 1.25rem 0.15rem;
        border-bottom: 1px solid rgba(255,255,255,0.14);
        margin-bottom: 1.05rem;
    }}

    .brand-mark {{
        width: 45px;
        height: 45px;
        min-width: 45px;
        border-radius: 12px;
        background: {AZUL};
        display: flex;
        align-items: center;
        justify-content: center;
        color: #FFFFFF !important;
        font-size: 18px;
        font-weight: 800;
    }}

    .brand-title {{
        font-size: 1.02rem;
        line-height: 1.15;
        font-weight: 800;
        color: #FFFFFF !important;
    }}

    .brand-subtitle {{
        font-size: 0.72rem;
        margin-top: 4px;
        color: #B9C8DA !important;
    }}

    .sidebar-section-title {{
        color: #AFC1D7 !important;
        font-size: 0.72rem;
        font-weight: 800;
        letter-spacing: 0.55px;
        margin: 1rem 0 0.45rem 0.15rem;
    }}

    .sidebar-menu-item {{
        display: flex;
        align-items: center;
        gap: 10px;
        padding: 0.72rem 0.8rem;
        border-radius: 12px;
        margin-bottom: 0.35rem;
        color: #FFFFFF !important;
        font-weight: 650;
        font-size: 0.92rem;
    }}

    .sidebar-menu-item.active {{
        background: {AZUL_MEDIO};
        border-left: 3px solid {VERDE};
        padding-left: calc(0.8rem - 3px);
        box-shadow: inset 0 0 0 1px rgba(255,255,255,0.025);
    }}

    .sidebar-menu-icon {{
        width: 27px;
        height: 27px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border-radius: 7px;
        background: rgba(255,255,255,0.10);
        font-size: 14px;
    }}

    .sidebar-user {{
        background: rgba(255,255,255,0.055);
        border: 1px solid rgba(255,255,255,0.09);
        border-radius: 12px;
        padding: 0.72rem 0.75rem;
        margin-top: 0.75rem;
        margin-bottom: 0.9rem;
    }}

    .sidebar-user-name {{
        color: #FFFFFF !important;
        font-weight: 700;
        font-size: 0.86rem;
    }}

    .sidebar-user-status {{
        color: #A9D977 !important;
        font-size: 0.72rem;
        margin-top: 3px;
    }}

    section[data-testid="stSidebar"] .stButton > button {{
        background: transparent !important;
        color: #DCE7F2 !important;
        border: 1px solid rgba(255,255,255,0.14) !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        box-shadow: none !important;
        min-height: 40px !important;
    }}

    section[data-testid="stSidebar"] .stButton > button:hover {{
        background: rgba(255,255,255,0.06) !important;
        border-color: rgba(255,255,255,0.25) !important;
        transform: none !important;
    }}

    /* =========================================================
       ENCABEZADO — TÍTULO + PILLS
       ========================================================= */
    .dashboard-header {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 18px;
        margin-bottom: 0.85rem;
    }}

    .dashboard-subtitle {{
        color: #657893;
        font-size: 0.98rem;
        margin-top: 0.35rem;
        line-height: 1.45;
    }}

    .header-pills {{
        display: flex;
        gap: 9px;
        flex-wrap: wrap;
        justify-content: flex-end;
        padding-top: 0.25rem;
    }}

    .header-pill {{
        padding: 0.55rem 0.9rem;
        border-radius: 999px;
        background: #FFFFFF;
        border: 1px solid {GRIS_BORDE};
        color: {AZUL_OSCURO} !important;
        font-size: 0.78rem;
        font-weight: 650;
        white-space: nowrap;
    }}

    .header-pill.primary {{
        background: #EEF4FF;
        border-color: #B9D1F8;
        color: {AZUL} !important;
    }}

    .header-pill.success {{
        background: #F2FAEC;
        border-color: #C8E6A8;
        color: #31A85A !important;
    }}

    /* =========================================================
       TARJETA DE FILTROS
       ========================================================= */
    .filter-card {{
        background: #FFFFFF;
        border: 1px solid {GRIS_BORDE};
        border-radius: 22px;
        padding: 1.35rem 1.45rem 1.05rem 1.45rem;
        box-shadow: 0 4px 15px rgba(0,59,122,0.045);
        margin: 0.9rem 0 0.95rem 0;
    }}

    .filter-title {{
        color: {AZUL_OSCURO};
        font-size: 0.9rem;
        font-weight: 800;
        letter-spacing: 0.35px;
        text-transform: uppercase;
        margin-bottom: 0.12rem;
    }}

    .filter-subtitle {{
        color: #7A8AA0;
        font-size: 0.78rem;
        margin-bottom: 0.95rem;
    }}

    .filter-records {{
        display: inline-flex;
        align-items: center;
        padding: 0.38rem 0.72rem;
        border-radius: 999px;
        background: #F1F5FA;
        color: #61738C !important;
        font-size: 0.72rem;
        font-weight: 650;
        margin-top: 0.75rem;
    }}

    div[data-baseweb="select"] > div {{
        border-radius: 10px !important;
        border: 1px solid #DDE5EF !important;
        background: #EDF2F8 !important;
        min-height: 43px !important;
        box-shadow: none !important;
    }}

    div[data-baseweb="select"] > div:hover,
    div[data-baseweb="select"] > div:focus-within {{
        border-color: {AZUL} !important;
        box-shadow: 0 0 0 2px rgba(6,75,155,0.08) !important;
    }}

    div[data-baseweb="select"] span {{
        color: #243B59 !important;
    }}

    div[data-baseweb="select"] svg {{
        fill: {AZUL_OSCURO} !important;
    }}

    div[data-testid="stSelectbox"] label {{
        color: #62758F !important;
        font-size: 0.75rem !important;
        font-weight: 600 !important;
        margin-bottom: 0.28rem !important;
    }}

    /* =========================================================
       NAVEGACIÓN LATERAL — RECTÁNGULOS SIN PUNTOS
       ========================================================= */
    section[data-testid="stSidebar"] div[data-testid="stRadio"] {{
        margin: 0 !important;
    }}

    section[data-testid="stSidebar"] div[data-testid="stRadio"] > label:first-child {{
        display: none !important;
    }}

    section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] {{
        display: flex !important;
        flex-direction: column !important;
        gap: 7px !important;
        width: 100% !important;
    }}

    section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label {{
        display: flex !important;
        align-items: center !important;
        justify-content: flex-start !important;
        width: 100% !important;
        min-height: 44px !important;
        box-sizing: border-box !important;
        margin: 0 !important;
        padding: 0.62rem 0.8rem !important;
        border-radius: 10px !important;
        border: 1px solid rgba(255,255,255,0.12) !important;
        background: rgba(255,255,255,0.055) !important;
        cursor: pointer !important;
        transition: 0.16s ease !important;
    }}

    section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label:hover {{
        background: rgba(255,255,255,0.10) !important;
        border-color: rgba(255,255,255,0.22) !important;
    }}

    section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label:has(input:checked) {{
        background: {AZUL_MEDIO} !important;
        border-color: rgba(135,211,63,0.55) !important;
        box-shadow: inset 3px 0 0 {VERDE}, 0 2px 7px rgba(0,0,0,0.10) !important;
    }}

    section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label p {{
        color: #DCE7F2 !important;
        font-size: 0.84rem !important;
        font-weight: 600 !important;
        margin: 0 !important;
    }}

    section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label:has(input:checked) p {{
        color: #FFFFFF !important;
        font-weight: 750 !important;
    }}

    section[data-testid="stSidebar"] div[data-testid="stRadio"] input {{
        display: none !important;
    }}

    .sidebar-session-title {{
        margin-top: 1.15rem !important;
    }}

    /* =========================================================
       FILTROS — CONTENEDOR BLANCO REAL DE STREAMLIT
       ========================================================= */
    div[data-testid="stVerticalBlockBorderWrapper"] {{
        background: #FFFFFF !important;
        border: 1px solid {GRIS_BORDE} !important;
        border-radius: 18px !important;
        box-shadow: 0 4px 15px rgba(0,59,122,0.045) !important;
        padding: 0.15rem !important;
    }}

    /* =========================================================
       KPI / CARDS
       ========================================================= */
    div[data-testid="metric-container"] {{
        background: #FFFFFF;
        border: 1px solid {GRIS_BORDE};
        border-radius: 17px;
        padding: 17px 18px 16px 18px;
        box-shadow: 0 4px 14px rgba(0,59,122,0.045);
        min-height: 112px;
    }}

    div[data-testid="stMetricLabel"] {{
        color: #60748E !important;
        font-size: 0.82rem !important;
        font-weight: 650 !important;
    }}

    div[data-testid="stMetricValue"] {{
        color: {AZUL_OSCURO} !important;
        font-size: 1.75rem !important;
        font-weight: 800 !important;
        letter-spacing: -0.55px;
    }}

    div[data-testid="stMetricDelta"] {{
        color: #39A85A !important;
        font-weight: 650 !important;
    }}

    div[data-testid="stVerticalBlockBorderWrapper"] {{
        border-radius: 17px !important;
        border-color: {GRIS_BORDE} !important;
        background: #FFFFFF !important;
        box-shadow: 0 4px 14px rgba(0,59,122,0.04);
    }}

    div[data-testid="stDataFrame"] {{
        border-radius: 13px;
        overflow: hidden;
        border: 1px solid {GRIS_BORDE};
        background: #FFFFFF;
    }}

    .stButton > button {{
        border-radius: 10px !important;
        border: 1px solid {AZUL} !important;
        background: {AZUL} !important;
        color: #FFFFFF !important;
        font-weight: 700 !important;
        min-height: 41px !important;
        box-shadow: 0 4px 10px rgba(6,75,155,0.12);
    }}

    .stButton > button:hover {{
        background: {AZUL_OSCURO} !important;
        border-color: {AZUL_OSCURO} !important;
        transform: translateY(-1px);
    }}

    .stDownloadButton > button {{
        border-radius: 10px !important;
        border: 1px solid {AZUL} !important;
        background: #FFFFFF !important;
        color: {AZUL} !important;
        font-weight: 700 !important;
    }}

    div[data-testid="stAlert"] {{
        border-radius: 12px !important;
    }}

    hr {{
        border-color: {GRIS_BORDE} !important;
    }}

    /* =========================================================
       AJUSTES DE MARCA Y CONSISTENCIA
       ========================================================= */
    .brand-mark {{
        background: {NARANJA} !important;
    }}

    .sidebar-menu-item.active {{
        border-left: 3px solid {NARANJA} !important;
    }}

    section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label:has(input:checked) {{
        border-color: rgba(245,130,32,0.55) !important;
        box-shadow: inset 3px 0 0 {NARANJA}, 0 2px 7px rgba(0,0,0,0.10) !important;
    }}

    .header-pill.accent {{
        background: {NARANJA_SUAVE};
        border-color: {NARANJA_CLARO};
        color: #B85A00 !important;
    }}

    div[data-testid="metric-container"],
    div[data-testid="stMetric"] {{
        border-top: 3px solid {AZUL} !important;
        transition: box-shadow 0.18s ease, transform 0.18s ease;
    }}

    div[data-testid="metric-container"]:hover,
    div[data-testid="stMetric"]:hover {{
        box-shadow: 0 8px 22px rgba(0,59,122,0.10);
        transform: translateY(-1px);
    }}

    /* Métricas dentro de una tarjeta: sin "tarjeta dentro de tarjeta" */
    div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="metric-container"],
    div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stMetric"] {{
        border: 0 !important;
        box-shadow: none !important;
        padding: 0 !important;
        min-height: 0 !important;
        transform: none !important;
    }}

    h3 {{
        font-size: 1.12rem !important;
    }}

    .stDownloadButton > button:hover {{
        background: {AZUL_SUAVE} !important;
        border-color: {AZUL_OSCURO} !important;
        color: {AZUL_OSCURO} !important;
    }}
    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# FUNCIONES DE FORMATO
# ============================================================

def formato_moneda(valor):
    if pd.isna(valor):
        return "$0"

    return (
        f"${valor:,.0f}"
        .replace(",", ".")
    )


def formato_numero(valor):
    if pd.isna(valor):
        return "0"

    return (
        f"{valor:,.2f}"
        .replace(",", "X")
        .replace(".", ",")
        .replace("X", ".")
    )


def formato_entero(valor):
    if pd.isna(valor):
        return "0"

    return (
        f"{valor:,.0f}"
        .replace(",", ".")
    )


def suma_columna(dataframe, columna):
    if columna is None or columna not in dataframe.columns:
        return 0

    return dataframe[columna].fillna(0).sum()


def promedio_columna(dataframe, columna):
    if columna is None or columna not in dataframe.columns:
        return 0

    serie = dataframe[columna].dropna()

    if len(serie) == 0:
        return 0

    return serie.mean()


def configurar_figura(fig, altura=430):
    fig.update_layout(
        height=altura,
        plot_bgcolor=BLANCO,
        paper_bgcolor=BLANCO,
        font=dict(
            family="Inter, Segoe UI, Arial",
            color=GRIS_OSCURO
        ),
        margin=dict(
            l=50,
            r=30,
            t=65,
            b=55
        ),
        xaxis=dict(
            showgrid=False,
            linecolor=GRIS_BORDE,
            zeroline=False
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor=GRIS_GRID,
            zeroline=False
        ),
        legend=dict(
            bgcolor="rgba(255,255,255,0.90)",
            bordercolor=GRIS_BORDE,
            borderwidth=1
        ),
        hoverlabel=dict(
            bgcolor="white",
            font_size=13,
            font_family="Inter, Segoe UI, Arial"
        )
    )

    return fig


def porcentaje(parte, total):
    if total == 0:
        return 0

    return parte / total * 100


# ============================================================
# LOGIN
# ============================================================


# ============================================================
# LOGIN — FONDO BLANCO Y LOGO CENTRADO
# ============================================================

def login():

    st.markdown(
        """
        <style>
        /* =====================================================
           FONDO GENERAL BLANCO
           ===================================================== */

        .stApp,
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        section.main {
            background: #FFFFFF !important;
        }

        [data-testid="stHeader"] {
            background: #FFFFFF !important;
        }

        .block-container {
            padding-top: 5vh !important;
            padding-bottom: 2rem !important;
            max-width: 1200px !important;
        }

        /* =====================================================
           TARJETA DE INICIO DE SESIÓN
           ===================================================== */

        div[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) {
            background: #FFFFFF !important;
            border: 1px solid #E1E7ED !important;
            border-top: 5px solid #F58220 !important;
            border-radius: 20px !important;
            box-shadow: 0 12px 35px rgba(23,45,73,0.09) !important;
            padding: 1.6rem 1.7rem 1.2rem 1.7rem !important;
        }

        /* =====================================================
           LOGO CENTRADO
           ===================================================== */

        div[data-testid="stImage"] {
            width: 100% !important;
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
        }

        div[data-testid="stImage"] img {
            display: block !important;
            margin-left: auto !important;
            margin-right: auto !important;
            object-fit: contain !important;
        }

        /* =====================================================
           TÍTULO Y SUBTÍTULO
           ===================================================== */

        .login-head {
            text-align: center;
            margin: 0.5rem 0 1.3rem 0;
        }

        .login-title {
            color: #193747 !important;
            font-size: 1.65rem;
            font-weight: 800;
            letter-spacing: -0.5px;
            line-height: 1.15;
        }

        .login-sub {
            color: #667892 !important;
            font-size: 0.9rem;
            margin: 0.4rem 0 0 0;
        }

        .login-accent {
            width: 44px;
            height: 4px;
            border-radius: 4px;
            background: #F58220;
            margin: 0.95rem auto 0 auto;
        }

        /* =====================================================
           FORMULARIO
           ===================================================== */

        div[data-testid="stForm"] {
            background: #FFFFFF !important;
            border: 0 !important;
            padding: 0 !important;
        }

        div[data-testid="stForm"] label p {
            color: #193747 !important;
            font-weight: 650 !important;
            font-size: 0.82rem !important;
        }

        div[data-baseweb="input"] {
            background: #FFFFFF !important;
            border: 1px solid #D5DFEB !important;
            border-radius: 10px !important;
            min-height: 46px !important;
            box-shadow: none !important;
        }

        div[data-baseweb="base-input"] {
            background: transparent !important;
            border-radius: 10px !important;
        }

        div[data-baseweb="input"]:focus-within {
            border-color: #F58220 !important;
            box-shadow: 0 0 0 3px rgba(245,130,32,0.13) !important;
        }

        div[data-baseweb="input"] input {
            color: #193747 !important;
            font-size: 0.95rem !important;
            background: transparent !important;
        }

        div[data-baseweb="input"] input::placeholder {
            color: #9AA9BA !important;
        }

        /* =====================================================
           BOTÓN INGRESAR
           ===================================================== */

        div[data-testid="stFormSubmitButton"] > button {
            background: #F58220 !important;
            border: 1px solid #F58220 !important;
            color: #FFFFFF !important;
            border-radius: 10px !important;
            min-height: 48px !important;
            font-size: 0.98rem !important;
            font-weight: 700 !important;
            box-shadow: 0 5px 14px rgba(245,130,32,0.18) !important;
            margin-top: 0.35rem;
            transition: all 0.18s ease !important;
        }

        div[data-testid="stFormSubmitButton"] > button:hover {
            background: #D96B10 !important;
            border-color: #D96B10 !important;
            color: #FFFFFF !important;
            transform: translateY(-1px);
        }

        div[data-testid="stFormSubmitButton"] > button:focus-visible {
            outline: none !important;
            box-shadow: 0 0 0 3px rgba(245,130,32,0.30) !important;
        }

        /* =====================================================
           MENSAJES DEL FORMULARIO
           ===================================================== */

        div[data-testid="stAlert"] {
            border-radius: 10px !important;
        }

        /* =====================================================
           PIE DE TARJETA
           ===================================================== */

        .login-footer {
            margin-top: 1.1rem;
            padding-top: 0.9rem;
            border-top: 1px solid #E3EAF3;
            text-align: center;
            color: #7A8AA0 !important;
            font-size: 0.76rem;
            line-height: 1.6;
        }

        .login-footer strong {
            color: #193747 !important;
        }

        /* =====================================================
           AJUSTES PARA PANTALLAS PEQUEÑAS
           ===================================================== */

        @media (max-width: 768px) {
            .block-container {
                padding-top: 2vh !important;
                padding-left: 1rem !important;
                padding-right: 1rem !important;
            }

            div[data-testid="stVerticalBlockBorderWrapper"]:has(.login-marker) {
                padding: 1.2rem 1rem 1rem 1rem !important;
            }

            .login-title {
                font-size: 1.45rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    # --------------------------------------------------------
    # DISTRIBUCIÓN: TARJETA CENTRADA
    # --------------------------------------------------------

    col_izq, col_centro, col_der = st.columns(
        [1, 1.15, 1],
        gap="small"
    )

    with col_centro:

        with st.container(border=True):

            # Marcador para aplicar el CSS exclusivamente
            # a la tarjeta de inicio de sesión.
            st.markdown(
                '<span class="login-marker"></span>',
                unsafe_allow_html=True
            )

            # Logo centrado
            st.image(
                _logo_login(),
                width=190
            )

            # Encabezado
            st.markdown(
                """
                <div class="login-head">
                    <div class="login-title">Inventarios ALDC</div>
                    <p class="login-sub">
                        Plataforma de gestión y analítica de inventarios
                    </p>
                    <div class="login-accent"></div>
                </div>
                """,
                unsafe_allow_html=True
            )

            # ------------------------------------------------
            # FORMULARIO DE AUTENTICACIÓN
            # ------------------------------------------------

            with st.form("form_login", clear_on_submit=False):

                usuario = st.text_input(
                    "Usuario",
                    placeholder="Ingrese su usuario",
                    key="login_usuario"
                )

                contraseña = st.text_input(
                    "Contraseña",
                    type="password",
                    placeholder="Ingrese su contraseña",
                    key="login_contraseña"
                )

                ingresar = st.form_submit_button(
                    "Ingresar",
                    use_container_width=True
                )

            # ------------------------------------------------
            # VALIDACIÓN DE CREDENCIALES
            # ------------------------------------------------

            if ingresar:

                usuario = usuario.strip()

                if (
                    usuario in USUARIOS
                    and USUARIOS[usuario] == contraseña
                ):

                    st.session_state["autenticado"] = True
                    st.session_state["usuario"] = usuario
                    st.session_state["inicio_sesion"] = datetime.now()

                    st.session_state.pop(
                        "login_usuario",
                        None
                    )

                    st.session_state.pop(
                        "login_contraseña",
                        None
                    )

                    st.rerun()

                else:

                    st.error(
                        "Usuario o contraseña incorrectos."
                    )

            # ------------------------------------------------
            # PIE DE TARJETA
            # ------------------------------------------------

            st.markdown(
                """
                <div class="login-footer">
                    <strong>Área Limpia D.C. S.A.S. E.S.P.</strong><br>
                    🔒 Acceso protegido · Sistema de gestión y análisis de inventarios
                </div>
                """,
                unsafe_allow_html=True
            )


# ============================================================
# INICIALIZAR SESIÓN
# ============================================================

if "autenticado" not in st.session_state:
    st.session_state["autenticado"] = False


# ============================================================
# VALIDAR SESIÓN
# ============================================================

if st.session_state["autenticado"]:

    inicio_sesion = st.session_state.get(
        "inicio_sesion"
    )

    if inicio_sesion is None:

        st.session_state["autenticado"] = False

        st.session_state.pop(
            "usuario",
            None
        )

    else:

        tiempo_transcurrido = (
            datetime.now() - inicio_sesion
        )

        if tiempo_transcurrido >= timedelta(
            minutes=TIEMPO_SESION_MINUTOS
        ):

            st.session_state["autenticado"] = False

            st.session_state.pop(
                "usuario",
                None
            )

            st.session_state.pop(
                "inicio_sesion",
                None
            )

            st.warning(
                "La sesión ha expirado. "
                "Por favor, inicia sesión nuevamente."
            )

            st.stop()

# ============================================================
# MOSTRAR LOGIN
# ============================================================

if not st.session_state["autenticado"]:

    login()
    st.stop()


# ============================================================
# CARGA DE DATOS
#
#   HISTORICO_INVENTARIOS.xlsx            -> base (mayo 2026)
#   INVENTARIO_ACTUALIZADO_LIFO.xlsx      -> resultado de cargar el Kardex
#
# Si existe el archivo actualizado se usa ese; si no, el histórico base.
# ============================================================

BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)

ARCHIVO_HISTORICO = os.path.join(
    BASE_DIR,
    "HISTORICO_INVENTARIOS.xlsx"
)

ARCHIVO_ACTUALIZADO = os.path.join(
    BASE_DIR,
    "INVENTARIO_ACTUALIZADO_LIFO.xlsx"
)


@st.cache_data
def cargar_datos(firma):

    datos, _ = cargar_base(
        ARCHIVO_ACTUALIZADO,
        ARCHIVO_HISTORICO
    )

    return datos


if "df_actualizado" in st.session_state:

    df = st.session_state["df_actualizado"].copy()

else:

    try:

        df = cargar_datos(
            firma_archivos(
                ARCHIVO_ACTUALIZADO,
                ARCHIVO_HISTORICO
            )
        )

    except Exception as e:

        st.error(
            f"No fue posible cargar el archivo Excel.\n\n"
            f"Archivo esperado:\n{ARCHIVO_HISTORICO}\n\n"
            f"Error: {e}"
        )

        st.stop()

    if df is None:

        st.warning(
            "No hay un histórico base en el servidor. "
            "Cárgalo junto con el Kardex para comenzar."
        )

        pagina_actualizar_kardex(
            st,
            st.session_state.get("usuario", ""),
            ARCHIVO_ACTUALIZADO,
            ARCHIVO_HISTORICO
        )

        st.stop()

    df = df.copy()


# ============================================================
# ESQUEMA DE COLUMNAS (meses y columnas del último corte)
# ============================================================

try:

    ESQ = construir_esquema(df)

except Exception as e:

    st.error(
        f"El archivo de datos no tiene la estructura esperada.\n\n{e}"
    )

    st.stop()


# ============================================================
# CORRECCIÓN 1 — COLUMNA DE COSTE DEL ÚLTIMO CORTE
#
# construir_esquema() tiene fijada "COSTE TOTAL AGOSTO 2026".
# Eso hace que el stock sea del último mes (septiembre) pero el
# valor del inventario sea el de agosto, y el valor por
# antigüedad queda descuadrado. Aquí se fuerza la columna de
# coste del MISMO mes que el stock del corte.
#
# Como kpis_corte() lee esq["col_coste"], también se actualiza
# el diccionario ESQ.
# ============================================================

_ultimo_mes = ESQ["meses"][-1]

if _ultimo_mes.get("coste"):
    ESQ["col_coste"] = _ultimo_mes["coste"]


# ============================================================
# MAPEO DE BODEGAS
# ============================================================

MAPA_BODEGAS = {

    "[1] - REPUESTOS": "Mantenimiento",
    "[2] - LUBRICANTES": "Mantenimiento",
    "[3] - COMBUSTIBLES": "Operaciones",
    "[4] - DOTACIONES": "RRHH",
    "[5] - INSUMOS DE MANTENIMIENTO": "Mantenimiento",
    "[7] - HERRAMIENTAS": "Operaciones",
    "[8] - LLANTAS": "Mantenimiento",
    "[9] - IMPORTACIONES": "Mantenimiento",
    "[13] - INSUMOS OPERATIVOS": "Operaciones",
    "[14] - INSUMOS REP. CONTENEDORES": "Mantenimiento",
    "[15] - INSUMOS REP LOCATIVAS": "Mantenimiento",
    "[16] - INSUMOS RRHH Y SST": "RRHH",
    "[44] - OBSOLETOS": "Sin asignar",
    "[46] - GESTIÓN DE CALIDAD": "RRHH"
}


# ============================================================
# COLORES POR ÁREA
# ============================================================

COLORES_AREA = {
    "Mantenimiento": AZUL,
    "Operaciones": "#4D6F91",
    "RRHH": VERDE,
    "Sin asignar": "#9AA9BA"
}


# ============================================================
# CREAR ÁREA (por número de bodega, sin depender del nombre)
# ============================================================

def numero_de_bodega(texto):

    coincidencia = re.search(
        r"\[\s*(\d+)\s*\]",
        str(texto)
    )

    return coincidencia.group(1) if coincidencia else None


MAPA_AREA_NUMERO = {
    numero_de_bodega(nombre): area
    for nombre, area in MAPA_BODEGAS.items()
}

if "Bodega" in df.columns:

    df["AREA"] = (
        df["Bodega"]
        .apply(numero_de_bodega)
        .map(MAPA_AREA_NUMERO)
        .fillna("Sin asignar")
    )

else:

    df["AREA"] = "Sin asignar"


# ============================================================
# CONVERSIÓN NUMÉRICA
# ============================================================

COLUMNAS_TEXTO = set(
    tipos_columnas_app(df)
) | {"AREA"}

for columna in df.columns:

    if columna not in COLUMNAS_TEXTO:

        df[columna] = pd.to_numeric(
            df[columna],
            errors="coerce"
        )


# ============================================================
# COLUMNAS PRINCIPALES (último corte disponible en los datos)
# ============================================================

COL_STOCK = ESQ["col_stock"]
COL_COSTE = ESQ["col_coste"]
COL_ROTACION = ESQ["columnas_rotacion"]

# ------------------------------------------------------------
# CORRECCIÓN 7 — La columna de antigüedad en el Excel se llama
# "ANTIGUEDAD 12 MESES", pero construir_esquema() solo reconoce
# "ANTIGUEDAD ULTIMO MES DE ACTUALIZACIÓN" (o "ANTIGUEDAD <MES AÑO>").
# Al no encontrarla, COL_ANTIGUEDAD quedaba en None y el tablero
# decía que faltaban columnas. Se buscan ambos nombres
# (sin importar tildes ni mayúsculas) y, solo si no aparece
# ninguno, se usa lo que devuelva el esquema.
# ------------------------------------------------------------

COL_ANTIGUEDAD = None

for _nombre in (
    "ANTIGUEDAD 12 MESES",
    "ANTIGUEDAD ULTIMO MES DE ACTUALIZACION",
    "ANTIGUEDAD ULTIMO MES DE ACTUALIZACIÓN",
):

    _c = col_exacta(df, _nombre)

    if _c is not None:
        COL_ANTIGUEDAD = _c
        break

if COL_ANTIGUEDAD is None:
    COL_ANTIGUEDAD = ESQ["col_antiguedad"]

ESQ["col_antiguedad"] = COL_ANTIGUEDAD

# ------------------------------------------------------------
# CORRECCIÓN 2 — Indicadores de la nueva metodología
# (antes COL_DIAS = None y el detalle nunca mostraba los días)
# ------------------------------------------------------------
COL_DIAS = ESQ.get("col_dias_rotacion_12_meses")
COL_INV_PROMEDIO = ESQ.get("col_inventario_promedio")
COL_CMV_12 = ESQ.get("col_cmv_12_meses")
COL_ROT_12 = ESQ.get("col_rotacion_12_meses")
COL_PERIODO = ESQ.get("col_periodo_inventario")

# Período de análisis (texto) para mostrarlo en el tablero
PERIODO_ANALISIS = ""

if COL_PERIODO and COL_PERIODO in df.columns:

    _periodos = (
        df[COL_PERIODO]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    if _periodos:
        PERIODO_ANALISIS = _periodos[0]


# ============================================================
# ORDEN
#
# CORRECCIÓN 3 — La nueva metodología solo genera 4 categorías.
# "Sin stock" y "Sin trazabilidad" ya no existen: dejarlas aquí
# creaba columnas/filas vacías en la matriz y en los filtros.
# Si se carga un archivo viejo que todavía las trae, se agregan
# al final automáticamente (ver ordenar_antiguedades).
# ============================================================

ORDEN_ANTIGUEDAD = [
    "Entre 0 y 3 meses",
    "Entre 4 y 6 meses",
    "Entre 7 y 12 meses",
    "Mayor a 12 meses"
]

ORDEN_AREAS = [
    "Mantenimiento",
    "Operaciones",
    "RRHH",
    "Sin asignar"
]


def ordenar_antiguedades(valores):
    """Categorías oficiales primero; cualquier otra al final."""

    valores = list(valores)

    oficiales = [
        e for e in ORDEN_ANTIGUEDAD
        if e in valores
    ]

    extras = sorted(
        v for v in valores
        if v not in ORDEN_ANTIGUEDAD
    )

    return oficiales + extras


# ============================================================
# COLORES ANTIGÜEDAD
# ============================================================

COLORES_EDAD = {
    "Entre 0 y 3 meses": "#D9E9FB",
    "Entre 4 y 6 meses": "#A9C8EC",
    "Entre 7 y 12 meses": AZUL_CLARO,
    "Mayor a 12 meses": AZUL,
    "Sin trazabilidad": "#9AA9BA",
    "Sin stock": "#DFE6EF"
}


# ============================================================
# CONSTRUIR SERIE MENSUAL
#
# Usa las columnas reales de cada mes (ENTRADA / SALIDA / STOCK ...)
# que trae el histórico y las que calcula el Kardex.
# Las salidas se toman en valor absoluto.
# ============================================================

def construir_serie_mensual(dataframe):

    def suma(columna):

        if columna and columna in dataframe.columns:
            return dataframe[columna].fillna(0).sum()

        return 0

    datos = []

    for mes in ESQ["meses"]:

        entradas = suma(mes["entrada"])
        salidas = abs(suma(mes["salida"]))

        rotacion_mes = (
            dataframe[mes["rotacion"]].mean()
            if mes["rotacion"]
            and mes["rotacion"] in dataframe.columns
            else 0
        )

        datos.append({
            "Mes": mes["label"],
            "Entradas": entradas,
            "Salidas": salidas,
            "Costo entradas": suma(mes["costo_entrada"]),
            "Costo salidas": abs(suma(mes["costo_salida"])),
            "Neto": entradas - salidas,
            "Rotacion": rotacion_mes,
            "Stock de cierre": suma(mes["stock"])
        })

    resultado = pd.DataFrame(datos)

    resultado["Mes_num"] = range(
        1,
        len(resultado) + 1
    )

    return resultado


# ============================================================
# SIDEBAR — NAVEGACIÓN LATERAL ESTILO ÁREA LIMPIA
# ============================================================

with st.sidebar:

    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="brand-mark">AL</div>
            <div>
                <div class="brand-title">Área Limpia</div>
                <div class="brand-subtitle">D.C. S.A.S. E.S.P.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="sidebar-section-title">OPERACIÓN</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="sidebar-menu-item active">
            <span class="sidebar-menu-icon">▣</span>
            <span>Inventarios</span>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="sidebar-section-title">NAVEGACIÓN</div>',
        unsafe_allow_html=True
    )

    pagina = st.radio(
        "Navegación",
        [
            "Resumen e inventario",
            "Evolución",
            "Riesgos y detalle",
            "Órdenes de compra",
            "Actualizar Kardex"
        ],
        label_visibility="collapsed",
        key="pagina_navegacion"
    )

    st.markdown(
        '<div class="sidebar-section-title sidebar-session-title">SESIÓN</div>',
        unsafe_allow_html=True
    )

    usuario_actual = st.session_state.get(
        "usuario",
        ""
    )

    st.markdown(
        f"""
        <div class="sidebar-user">
            <div class="sidebar-user-name">◉ &nbsp;{usuario_actual}</div>
            <div class="sidebar-user-status">● &nbsp;Sesión activa</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if st.button(
        "↪  Cerrar sesión",
        use_container_width=True
    ):

        st.session_state["autenticado"] = False

        st.session_state.pop(
            "usuario",
            None
        )

        st.session_state.pop(
            "inicio_sesion",
            None
        )

        st.rerun()

    st.markdown(
        """
        <div style="margin-top:2.2rem; padding-top:0.9rem; border-top:1px solid rgba(255,255,255,0.13);">
            <div style="color:#AFC1D7;font-size:0.73rem;line-height:1.55;">
                Área Limpia D.C.<br>
                Sistema de análisis de inventarios
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


# ============================================================
# PÁGINA: ACTUALIZAR KARDEX
# (se muestra sola, sin encabezado ni filtros del tablero)
# ============================================================

if pagina == "Actualizar Kardex":

    pagina_actualizar_kardex(
        st,
        st.session_state.get("usuario", ""),
        ARCHIVO_ACTUALIZADO,
        ARCHIVO_HISTORICO
    )

    st.stop()


# ============================================================
# ENCABEZADO PRINCIPAL
# ============================================================

_pill_periodo = (
    f'<div class="header-pill">Antigüedad: {PERIODO_ANALISIS}</div>'
    if PERIODO_ANALISIS
    else ""
)

st.markdown(
    f"""
    <div class="dashboard-header">
        <div>
            <h1 style="margin:0 !important;">Inventarios 2026</h1>
            <div class="dashboard-subtitle">
                Análisis de inventario, rotación y movimientos acumulados — cifras del sistema de inventarios
            </div>
        </div>
        <div class="header-pills">
            <div class="header-pill primary">Inventario actual</div>
            <div class="header-pill accent">Corte: {ESQ["corte"]}</div>
            {_pill_periodo}
            <div class="header-pill success">Datos actualizados</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True
)

# Aviso si el archivo cargado no trae la nueva metodología
_requeridas = {
    "ANTIGUEDAD 12 MESES": COL_ANTIGUEDAD,
    "INVENTARIO PROMEDIO 12 MESES": COL_INV_PROMEDIO,
    "CMV 12 MESES": COL_CMV_12,
    "ROTACION 12 MESES": COL_ROT_12,
    "DIAS ROTACION 12 MESES": COL_DIAS,
    "COSTE TOTAL (último mes)": COL_COSTE,
}

_faltantes = [
    nombre
    for nombre, col in _requeridas.items()
    if not col or col not in df.columns
]

if _faltantes:

    st.warning(
        "No se encontraron estas columnas en el archivo cargado: "
        + ", ".join(_faltantes)
        + ". Columnas detectadas que empiezan por "
        "ANTIGUEDAD: "
        + (
            ", ".join(
                str(c)
                for c in df.columns
                if str(c).upper().startswith("ANTIG")
            )
            or "ninguna"
        )
        + "."
    )


# ============================================================
# FILTROS EN CASCADA
# ============================================================

with st.container(border=True):

    st.markdown(
        """
        <div class="filter-title">Filtros del informe</div>
        <div class="filter-subtitle">Los indicadores y análisis se actualizan según la selección.</div>
        """,
        unsafe_allow_html=True
    )

    col1, col2, col3, col4 = st.columns(4)

    # --------------------------------------------------------
    # ÁREA
    # --------------------------------------------------------

    areas_existentes = (
        df["AREA"]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
    )

    areas = [
        area
        for area in ORDEN_AREAS
        if area in areas_existentes
    ]

    with col1:

        area_seleccionada = st.selectbox(
            "Área",
            ["Todas"] + areas
        )

    df_area = df.copy()

    if area_seleccionada != "Todas":

        df_area = df_area[
            df_area["AREA"] == area_seleccionada
        ]

    # --------------------------------------------------------
    # BODEGA
    # --------------------------------------------------------

    bodegas_existentes = (
        df_area["Bodega"]
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
        if "Bodega" in df_area.columns
        else []
    )

    bodegas_ordenadas = [
        bodega
        for bodega in MAPA_BODEGAS.keys()
        if bodega in bodegas_existentes
    ]

    bodegas_no_mapeadas = [
        bodega
        for bodega in bodegas_existentes
        if bodega not in MAPA_BODEGAS
    ]

    bodegas = (
        bodegas_ordenadas
        + sorted(bodegas_no_mapeadas)
    )

    with col2:

        bodega_seleccionada = st.selectbox(
            "Bodega",
            ["Todas"] + bodegas
        )

    df_bodega = df_area.copy()

    if bodega_seleccionada != "Todas":

        df_bodega = df_bodega[
            df_bodega["Bodega"]
            .astype(str)
            .str.strip()
            == bodega_seleccionada
        ]

    # --------------------------------------------------------
    # ARTÍCULO
    # --------------------------------------------------------

    articulos = (
        sorted(
            df_bodega["Articulo"]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )
        if "Articulo" in df_bodega.columns
        else []
    )

    with col3:

        articulo_seleccionado = st.selectbox(
            "Artículo",
            ["Todos"] + articulos
        )

    df_articulo = df_bodega.copy()

    if articulo_seleccionado != "Todos":

        df_articulo = df_articulo[
            df_articulo["Articulo"]
            .astype(str)
            == articulo_seleccionado
        ]

    # --------------------------------------------------------
    # ANTIGÜEDAD
    # --------------------------------------------------------

    antiguedades_existentes = (
        df_articulo[COL_ANTIGUEDAD]
        .dropna()
        .astype(str)
        .unique()
        .tolist()
        if COL_ANTIGUEDAD and COL_ANTIGUEDAD in df_articulo.columns
        else []
    )

    antiguedades = ordenar_antiguedades(
        antiguedades_existentes
    )

    with col4:

        antiguedad_seleccionada = st.selectbox(
            "Antigüedad",
            ["Todas"] + antiguedades
        )

    df_filtrado = df_articulo.copy()

    if antiguedad_seleccionada != "Todas":

        df_filtrado = df_filtrado[
            df_filtrado[COL_ANTIGUEDAD]
            .astype(str)
            == antiguedad_seleccionada
        ]

    st.markdown(
        f'<div class="filter-records">Registros analizados: {len(df_filtrado):,}'.replace(",", ".") + '</div>',
        unsafe_allow_html=True
    )


# ============================================================
# CORRECCIÓN 4 — SOLO REGISTROS CON INVENTARIO EN EL CORTE
#
# La nueva clasificación ya no genera "Sin stock": un artículo
# con stock 0 en el último mes igual recibe una categoría de
# antigüedad (por defecto "Entre 0 y 3 meses", o "Mayor a 12
# meses" si tuvo inventario promedio y CMV cero). Para contar
# registros, artículos o alertas hay que considerar únicamente
# los que realmente tienen inventario al corte.
# ============================================================

if COL_STOCK in df_filtrado.columns:

    df_con_stock = df_filtrado[
        df_filtrado[COL_STOCK].fillna(0) > EPS
    ].copy()

else:

    df_con_stock = df_filtrado.copy()


# ============================================================
# SERIE MENSUAL
# ============================================================

df_mensual = construir_serie_mensual(
    df_filtrado
)


# ============================================================
# INDICADORES GENERALES DEL FILTRO
# ============================================================

stock_total, valor_total, rotacion, dias_promedio = kpis_corte(
    df_filtrado,
    ESQ
)

# Suma de la columna de costo: base de todos los porcentajes mostrados
valor_total_col = suma_columna(df_filtrado, COL_COSTE)


# ============================================================
# PÁGINA 1
# RESUMEN EJECUTIVO
# ============================================================

if pagina in ("Resumen", "Resumen e inventario"):

    st.title(
        "Resumen ejecutivo"
    )

    st.caption(
        "Lectura estratégica del estado actual del inventario."
    )

    if PERIODO_ANALISIS:

        st.caption(
            f"Antigüedad según días de rotación "
            f"(inventario promedio ÷ CMV × 365) del período "
            f"{PERIODO_ANALISIS}."
        )

    # --------------------------------------------------------
    # KPIs
    # --------------------------------------------------------

    valor_mayor_12 = 0

    if COL_ANTIGUEDAD and COL_ANTIGUEDAD in df_con_stock.columns:

        valor_mayor_12 = suma_columna(
            df_con_stock[
                df_con_stock[COL_ANTIGUEDAD]
                .astype(str)
                .str.contains(
                    "Mayor a 12 meses",
                    case=False,
                    na=False
                )
            ],
            COL_COSTE
        )

    porcentaje_envejecido = porcentaje(
        valor_mayor_12,
        valor_total_col
    )

    k1, k2, k3, k4 = st.columns(4)

    with k1:
        st.metric(
            "📦 Stock actual",
            formato_numero(stock_total)
        )

    with k2:
        st.metric(
            "💰 Valor inventario",
            formato_moneda(valor_total)
        )

    with k3:
        st.metric(
            "⏱️ Días de inventario",
            formato_numero(dias_promedio)
        )

    with k4:
        st.metric(
            "⚠️ Valor > 12 meses",
            formato_moneda(valor_mayor_12),
            f"{porcentaje_envejecido:.1f}% del valor"
        )

    st.write("")

    # --------------------------------------------------------
    # LECTURA AUTOMÁTICA
    # --------------------------------------------------------

    if abs(valor_total - valor_total_col) > 1:
        st.caption(
            "⚠️ El valor del KPI difiere de la suma de la columna de costo del corte; "
            "los porcentajes usan la suma de la columna."
        )

    mes_mayor_entrada = (
        df_mensual.loc[
            df_mensual["Entradas"].idxmax(),
            "Mes"
        ]
        if len(df_mensual) > 0
        else "-"
    )

    mayor_entrada = (
        df_mensual["Entradas"].max()
        if len(df_mensual) > 0
        else 0
    )

    mes_mayor_neto = (
        df_mensual.loc[
            df_mensual["Neto"].idxmax(),
            "Mes"
        ]
        if len(df_mensual) > 0
        else "-"
    )

    mayor_neto = (
        df_mensual["Neto"].max()
        if len(df_mensual) > 0
        else 0
    )

    # --------------------------------------------------------
    # TRES HALLAZGOS
    # --------------------------------------------------------

    st.subheader("🔍 ¿Qué está ocurriendo?")

    h1, h2, h3 = st.columns(3)

    with h1:

        with st.container(border=True):

            st.markdown("### 📥 Mayor entrada")

            st.metric(
                mes_mayor_entrada,
                formato_numero(mayor_entrada)
            )

            st.caption(
                "Mes con el mayor volumen de unidades ingresadas."
            )

    with h2:

        with st.container(border=True):

            st.markdown("### 📊 Mayor acumulación")

            st.metric(
                mes_mayor_neto,
                formato_numero(mayor_neto)
            )

            st.caption(
                "Mayor incremento neto de inventario del periodo."
            )

    with h3:

        with st.container(border=True):

            st.markdown("### ⚠️ Inventario envejecido")

            st.metric(
                "Mayor a 12 meses",
                f"{porcentaje_envejecido:.1f}%"
            )

            st.caption(
                "Participación del inventario envejecido sobre el valor total."
            )

    # --------------------------------------------------------
    # DISTRIBUCIÓN ESTRATÉGICA
    # --------------------------------------------------------

    st.subheader(
        "📌 ¿Dónde está concentrado el inventario?"
    )

    col_a, col_b = st.columns([1.1, 1])

    with col_a:

        resumen_area = (
            df_filtrado
            .groupby("AREA", as_index=False)
            .agg(
                Valor=(COL_COSTE, "sum"),
                Stock=(COL_STOCK, "sum")
            )
            .sort_values(
                "Valor",
                ascending=False
            )
        )

        fig_area = px.bar(
            resumen_area,
            x="Valor",
            y="AREA",
            orientation="h",
            color="AREA",
            color_discrete_map=COLORES_AREA,
            text="Valor"
        )

        fig_area.update_traces(
            texttemplate="$%{text:,.0f}",
            textposition="outside",
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Valor: $%{x:,.0f}<br>"
                "<extra></extra>"
            )
        )

        fig_area.update_layout(
            title="Concentración del valor por área",
            xaxis_title="Valor del inventario",
            yaxis_title="",
            showlegend=False
        )

        configurar_figura(
            fig_area,
            390
        )

        fig_area.update_yaxes(categoryorder="total ascending")

        st.plotly_chart(
            fig_area,
            use_container_width=True
        )

    with col_b:

        if (
            COL_ANTIGUEDAD
            and COL_ANTIGUEDAD in df_con_stock.columns
            and len(df_con_stock) > 0
        ):

            resumen_edad = (
                df_con_stock
                .groupby(
                    COL_ANTIGUEDAD,
                    as_index=False
                )[COL_COSTE]
                .sum()
            )

            orden_edad = ordenar_antiguedades(
                resumen_edad[COL_ANTIGUEDAD]
                .astype(str)
                .tolist()
            )

            resumen_edad["Orden"] = (
                resumen_edad[COL_ANTIGUEDAD]
                .map({
                    edad: i
                    for i, edad
                    in enumerate(orden_edad)
                })
                .fillna(99)
            )

            resumen_edad = resumen_edad.sort_values(
                "Orden"
            )

            fig_edad = px.bar(
                resumen_edad,
                x=COL_COSTE,
                y=COL_ANTIGUEDAD,
                orientation="h",
                color=COL_ANTIGUEDAD,
                color_discrete_map=COLORES_EDAD,
                category_orders={
                    COL_ANTIGUEDAD: orden_edad
                }
            )

            fig_edad.update_traces(
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Valor: $%{x:,.0f}"
                    "<extra></extra>"
                )
            )

            fig_edad.update_layout(
                title="Valor del inventario por antigüedad (LIFO)",
                xaxis_title="Valor del inventario",
                yaxis_title="",
                showlegend=False
            )

            fig_edad.update_yaxes(
                autorange="reversed"
            )

            configurar_figura(
                fig_edad,
                390
            )

            st.plotly_chart(
                fig_edad,
                use_container_width=True
            )

        else:

            st.info(
                "No hay inventario con antigüedad calculada "
                "para los filtros seleccionados."
            )


# ============================================================
# PÁGINA 2
# INVENTARIO
# ============================================================

if pagina in ("Inventario", "Resumen e inventario"):

    st.title(
        "Inventario"
    )

    st.caption(
        "Concentración del inventario y principales componentes del valor."
    )

    # --------------------------------------------------------
    # KPIs DE INVENTARIO
    # (solo artículos con stock al corte)
    # --------------------------------------------------------

    numero_articulos = (
        df_con_stock["Articulo"]
        .nunique()
        if "Articulo" in df_con_stock.columns
        else 0
    )

    numero_bodegas = (
        df_con_stock["Bodega"]
        .nunique()
        if "Bodega" in df_con_stock.columns
        else 0
    )

    valor_promedio_articulo = (
        valor_total / numero_articulos
        if numero_articulos > 0
        else 0
    )

    k1, k2, k3 = st.columns(3)

    with k1:
        st.metric(
            "🧾 Artículos",
            formato_entero(numero_articulos)
        )

    with k2:
        st.metric(
            "🏭 Bodegas",
            formato_entero(numero_bodegas)
        )

    with k3:
        st.metric(
            "💰 Valor promedio / artículo",
            formato_moneda(valor_promedio_articulo)
        )

    st.write("")

    # --------------------------------------------------------
    # TOP ARTÍCULOS
    # --------------------------------------------------------

    st.subheader(
        "🏆 ¿Qué artículos explican el valor?"
    )

    if (
        "Articulo" in df_filtrado.columns
        and COL_COSTE in df_filtrado.columns
    ):

        top_articulos = (
            df_filtrado
            .groupby(
                ["Articulo", "Bodega"],
                as_index=False
            )
            .agg(
                Valor=(COL_COSTE, "sum"),
                Stock=(COL_STOCK, "sum")
            )
            .sort_values(
                "Valor",
                ascending=False
            )
            .head(12)
        )

        top_articulos["Participacion"] = (
            top_articulos["Valor"]
            / valor_total_col
            * 100
            if valor_total_col != 0
            else 0
        )

        fig_top = px.bar(
            top_articulos.sort_values(
                "Valor",
                ascending=True
            ),
            x="Valor",
            y="Articulo",
            orientation="h",
            color="Bodega",
            custom_data=[
                "Bodega",
                "Stock",
                "Participacion"
            ]
        )

        fig_top.update_traces(
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Bodega: %{customdata[0]}<br>"
                "Valor: $%{x:,.0f}<br>"
                "Stock: %{customdata[1]:,.2f}<br>"
                "Participación: %{customdata[2]:.1f}%"
                "<extra></extra>"
            )
        )

        fig_top.update_layout(
            title=f"Top 12 artículos por valor de inventario — corte {ESQ['corte']}",
            xaxis_title="Valor",
            yaxis_title="",
            legend_title="Bodega"
        )

        configurar_figura(
            fig_top,
            500
        )

        st.plotly_chart(
            fig_top,
            use_container_width=True
        )

    # --------------------------------------------------------
    # MATRIZ ÁREA / ANTIGÜEDAD
    # --------------------------------------------------------

    st.subheader(
        "🧭 ¿Dónde se concentra el inventario envejecido?"
    )

    if (
        COL_ANTIGUEDAD
        and COL_ANTIGUEDAD in df_con_stock.columns
        and len(df_con_stock) > 0
    ):

        columnas_edad = ordenar_antiguedades(
            df_con_stock[COL_ANTIGUEDAD]
            .dropna()
            .astype(str)
            .unique()
            .tolist()
        )

        matriz = (
            df_con_stock
            .pivot_table(
                index="AREA",
                columns=COL_ANTIGUEDAD,
                values=COL_COSTE,
                aggfunc="sum",
                fill_value=0
            )
            .reindex(
                index=ORDEN_AREAS,
                columns=columnas_edad,
                fill_value=0
            )
        )

        matriz_mostrar = matriz.copy()

        for columna in matriz_mostrar.columns:
            matriz_mostrar[columna] = (
                matriz_mostrar[columna]
                .apply(formato_moneda)
            )

        st.dataframe(
            matriz_mostrar,
            use_container_width=True
        )

    else:

        st.info(
            "No hay inventario con antigüedad calculada "
            "para los filtros seleccionados."
        )

    # --------------------------------------------------------
    # BODEGAS
    # --------------------------------------------------------

    st.subheader(
        "🏭 Concentración por bodega"
    )

    resumen_bodega = (
        df_filtrado
        .groupby(
            "Bodega",
            as_index=False
        )
        .agg(
            Stock=(COL_STOCK, "sum"),
            Valor=(COL_COSTE, "sum"),
            Articulos=("Articulo", "nunique")
        )
        .sort_values(
            "Valor",
            ascending=False
        )
    )

    resumen_bodega["Participacion"] = (
        resumen_bodega["Valor"]
        / valor_total_col
        * 100
        if valor_total_col != 0
        else 0
    )

    st.dataframe(
        resumen_bodega,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Valor": st.column_config.NumberColumn(
                "Valor",
                format="$ %,.0f"
            ),
            "Stock": st.column_config.NumberColumn(
                "Stock",
                format="%.2f"
            ),
            "Participacion": st.column_config.NumberColumn(
                "Participación",
                format="%.1f%%"
            )
        }
    )


# ============================================================
# PÁGINA 3
# EVOLUCIÓN
#
# CORRECCIÓN 5 — En el código original esta página tenía los
# bloques "Referencias con mayor impacto económico", "Lectura
# analítica" y "Costos y rotación" repetidos (uno de ellos mal
# indentado dentro de un else). Streamlit rechaza gráficos
# idénticos duplicados (DuplicateElementId) y la tabla aparecía
# dos veces. Aquí cada bloque aparece una sola vez.
# ============================================================

elif pagina == "Evolución":

    st.title(
        "Evolución del inventario"
    )

    st.caption(
        "Análisis mensual para relacionar entradas, salidas, "
        "acumulación y trayectoria del inventario."
    )

    # --------------------------------------------------------
    # KPIs DEL PERIODO
    # --------------------------------------------------------

    if antiguedad_seleccionada != "Todas":
        st.info(
            "La antigüedad se calcula con el corte actual: la serie mensual "
            "muestra el histórico de los registros que hoy pertenecen a ese rango."
        )

    total_entradas = df_mensual["Entradas"].sum()
    total_salidas = df_mensual["Salidas"].sum()

    neto_periodo = (
        total_entradas
        - total_salidas
    )

    indice_mayor_stock = (
        df_mensual["Stock de cierre"].idxmax()
        if len(df_mensual) > 0
        else 0
    )

    mes_mayor_stock = (
        df_mensual.loc[
            indice_mayor_stock,
            "Mes"
        ]
        if len(df_mensual) > 0
        else "-"
    )

    stock_mayor = (
        df_mensual["Stock de cierre"].max()
        if len(df_mensual) > 0
        else 0
    )

    k1, k2, k3, k4 = st.columns(4)

    with k1:
        st.metric(
            "📥 Entradas acumuladas",
            formato_numero(total_entradas)
        )

    with k2:
        st.metric(
            "📤 Salidas acumuladas",
            formato_numero(total_salidas)
        )

    with k3:
        st.metric(
            "📊 Neto del periodo",
            formato_numero(neto_periodo)
        )

    with k4:
        st.metric(
            "📈 Mayor stock del periodo",
            formato_numero(stock_mayor),
            mes_mayor_stock
        )

    st.write("")

    # --------------------------------------------------------
    # GRÁFICO PRINCIPAL
    # --------------------------------------------------------

    st.subheader(
        "🔎 Entradas vs. nivel de inventario"
    )

    st.caption(
        "La línea representa el stock de cierre de cada mes. "
        "La franja azul identifica niveles altos de inventario. "
        "Los marcadores destacados muestran meses donde coincidieron "
        "entradas altas y stock elevado."
    )

    fig_evolucion = go.Figure()

    # --------------------------------------------------------
    # UMBRALES ANALÍTICOS
    # --------------------------------------------------------

    umbral_entrada = df_mensual["Entradas"].quantile(0.75)
    umbral_stock = df_mensual["Stock de cierre"].quantile(0.75)

    stock_max = df_mensual["Stock de cierre"].max()

    # --------------------------------------------------------
    # INVENTARIO INICIAL DE CADA MES
    # --------------------------------------------------------

    df_mensual["Inventario inicial"] = (
        df_mensual["Stock de cierre"]
        .shift(1)
        .fillna(0)
    )

    # --------------------------------------------------------
    # ENTRADAS
    # --------------------------------------------------------

    fig_evolucion.add_trace(
        go.Bar(
            x=df_mensual["Mes"],
            y=df_mensual["Entradas"],
            name="Entradas",
            marker_color=VERDE,
            opacity=0.72,
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Entradas: %{y:,.2f}<br>"
                "<extra></extra>"
            )
        )
    )

    # --------------------------------------------------------
    # SALIDAS
    # --------------------------------------------------------

    fig_evolucion.add_trace(
        go.Bar(
            x=df_mensual["Mes"],
            y=-df_mensual["Salidas"],
            name="Salidas",
            marker_color=ROJO,
            opacity=0.65,
            customdata=df_mensual["Salidas"],
            hovertemplate=(
                "<b>%{x}</b><br>"
                "Salidas: %{customdata:,.2f}<br>"
                "<extra></extra>"
            )
        )
    )

    # --------------------------------------------------------
    # STOCK DE CIERRE
    # --------------------------------------------------------

    fig_evolucion.add_trace(
        go.Scatter(
            x=df_mensual["Mes"],
            y=df_mensual["Stock de cierre"],
            name="Stock de cierre",
            mode="lines+markers",
            line=dict(
                color=AZUL,
                width=4
            ),
            marker=dict(
                size=9,
                color=AZUL
            ),
            yaxis="y2",
            customdata=df_mensual[
                [
                    "Inventario inicial",
                    "Entradas",
                    "Salidas",
                    "Stock de cierre"
                ]
            ],
            hovertemplate=(
                "<b>%{x}</b><br>"
                "📦 Inventario inicial: %{customdata[0]:,.2f}<br>"
                "📥 Entradas: %{customdata[1]:,.2f}<br>"
                "📤 Salidas: %{customdata[2]:,.2f}<br>"
                "📦 Inventario final: %{customdata[3]:,.2f}"
                "<extra></extra>"
            )
        )
    )

    # --------------------------------------------------------
    # IDENTIFICAR COINCIDENCIAS
    # ENTRADA ALTA + STOCK ALTO
    # --------------------------------------------------------

    df_marcados = df_mensual[
        (df_mensual["Entradas"] >= umbral_entrada)
        & (df_mensual["Stock de cierre"] >= umbral_stock)
    ].copy()

    if len(df_marcados) > 0:

        fig_evolucion.add_trace(
            go.Scatter(
                x=df_marcados["Mes"],
                y=df_marcados["Stock de cierre"],
                name="Entrada alta + stock alto",
                mode="markers",
                yaxis="y2",
                marker=dict(
                    size=17,
                    symbol="diamond",
                    color=AZUL,
                    line=dict(
                        width=2,
                        color="white"
                    )
                ),
                customdata=df_marcados[
                    [
                        "Entradas",
                        "Salidas",
                        "Neto"
                    ]
                ],
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "⚠️ <b>Entrada alta + stock alto</b><br>"
                    "📦 Stock: %{y:,.2f}<br>"
                    "📥 Entradas: %{customdata[0]:,.2f}<br>"
                    "📤 Salidas: %{customdata[1]:,.2f}<br>"
                    "📊 Neto: %{customdata[2]:,.2f}"
                    "<extra></extra>"
                )
            )
        )

    # --------------------------------------------------------
    # ZONA DE STOCK ALTO
    # --------------------------------------------------------

    fig_evolucion.add_hrect(
        y0=umbral_stock,
        y1=stock_max * 1.05,
        yref="y2",
        fillcolor=AZUL,
        opacity=0.08,
        line_width=0,
        layer="below"
    )

    # --------------------------------------------------------
    # LÍNEA DE UMBRAL DE STOCK ALTO
    # --------------------------------------------------------

    fig_evolucion.add_shape(
        type="line",
        x0=0,
        x1=1,
        xref="paper",
        y0=umbral_stock,
        y1=umbral_stock,
        yref="y2",
        line=dict(
            color=AZUL,
            width=1.5,
            dash="dash"
        )
    )

    # --------------------------------------------------------
    # CONFIGURACIÓN
    # --------------------------------------------------------

    fig_evolucion.update_layout(
        height=610,
        barmode="relative",

        title=(
            "Entradas y salidas mensuales vs. stock de cierre"
        ),

        xaxis=dict(
            title="Periodo",
            categoryorder="array",
            categoryarray=df_mensual["Mes"].tolist(),
            showgrid=False
        ),

        yaxis=dict(
            title="Entradas / Salidas (unidades)",
            showgrid=True,
            gridcolor=GRIS_GRID,
            zeroline=True,
            zerolinecolor=GRIS_BORDE
        ),

        yaxis2=dict(
            title="Stock de cierre (unidades)",
            overlaying="y",
            side="right",
            showgrid=False,
            rangemode="tozero",
            zeroline=False
        ),

        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0
        ),

        plot_bgcolor=BLANCO,
        paper_bgcolor=BLANCO,

        font=dict(
            family="Inter, Segoe UI, Arial",
            color=GRIS_OSCURO
        ),

        margin=dict(
            l=60,
            r=85,
            t=85,
            b=55
        )
    )

    st.plotly_chart(
        fig_evolucion,
        use_container_width=True
    )

    # --------------------------------------------------------
    # REFERENCIAS CON MAYOR IMPACTO ECONÓMICO
    # ENTRADA ALTA + STOCK ALTO
    # --------------------------------------------------------

    st.subheader(
        "💰 Referencias con mayor impacto económico"
    )

    st.caption(
        "Muestra las referencias que concentran el mayor valor "
        "económico de las entradas durante los meses identificados "
        "como entrada alta + stock alto."
    )

    if len(df_marcados) > 0:

        filas_referencias = []

        for mes_critico in df_marcados["Mes"]:

            mes_info = next(
                (
                    m
                    for m in ESQ["meses"]
                    if m["label"] == mes_critico
                ),
                None
            )

            if mes_info is None:
                continue

            col_entrada = mes_info["entrada"]
            col_stock = mes_info["stock"]
            col_costo_entrada = mes_info["costo_entrada"]

            if (
                col_entrada is None
                or col_entrada not in df_filtrado.columns
                or col_stock is None
                or col_stock not in df_filtrado.columns
                or col_costo_entrada is None
                or col_costo_entrada not in df_filtrado.columns
            ):
                continue

            columnas_base = [
                "Codigo Articulo",
                "Articulo",
                "Bodega",
                "AREA"
            ]

            columnas_disponibles = [
                c
                for c in columnas_base
                if c in df_filtrado.columns
            ]

            datos_mes = df_filtrado[
                columnas_disponibles
                + [
                    col_entrada,
                    col_stock,
                    col_costo_entrada
                ]
            ].copy()

            datos_mes = datos_mes.rename(
                columns={
                    col_entrada: "Entradas mes",
                    col_stock: "Stock mes",
                    col_costo_entrada: "Valor entradas mes"
                }
            )

            datos_mes["Mes crítico"] = mes_critico

            datos_mes["Entradas mes"] = pd.to_numeric(
                datos_mes["Entradas mes"],
                errors="coerce"
            ).fillna(0)

            datos_mes["Stock mes"] = pd.to_numeric(
                datos_mes["Stock mes"],
                errors="coerce"
            ).fillna(0)

            datos_mes["Valor entradas mes"] = pd.to_numeric(
                datos_mes["Valor entradas mes"],
                errors="coerce"
            ).fillna(0)

            # Solo referencias que realmente tuvieron
            # entradas en el mes crítico
            datos_mes = datos_mes[
                datos_mes["Entradas mes"] > 0
            ].copy()

            filas_referencias.append(
                datos_mes
            )

        if len(filas_referencias) > 0:

            detalle_criticos = pd.concat(
                filas_referencias,
                ignore_index=True
            )

            columnas_grupo = [
                c
                for c in [
                    "Codigo Articulo",
                    "Articulo",
                    "Bodega",
                    "AREA"
                ]
                if c in detalle_criticos.columns
            ]

            tabla_referencias = (
                detalle_criticos
                .groupby(
                    columnas_grupo,
                    as_index=False
                )
                .agg(
                    Valor_entradas_criticas=(
                        "Valor entradas mes",
                        "sum"
                    ),
                    Stock_maximo=(
                        "Stock mes",
                        "max"
                    ),
                    Meses_criticos=(
                        "Mes crítico",
                        "nunique"
                    )
                )
                .sort_values(
                    "Valor_entradas_criticas",
                    ascending=False
                )
            )

            # ------------------------------------------------
            # VALOR ACTUAL DEL INVENTARIO
            # ------------------------------------------------

            if (
                COL_COSTE is not None
                and COL_COSTE in df_filtrado.columns
            ):

                valor_actual = (
                    df_filtrado
                    .groupby(
                        columnas_grupo,
                        as_index=False
                    )
                    .agg(
                        Valor_inventario_actual=(
                            COL_COSTE,
                            "sum"
                        )
                    )
                )

                tabla_referencias = tabla_referencias.merge(
                    valor_actual,
                    on=columnas_grupo,
                    how="left"
                )

            else:

                tabla_referencias[
                    "Valor_inventario_actual"
                ] = 0

            # ------------------------------------------------
            # PARTICIPACIÓN ECONÓMICA
            # ------------------------------------------------

            total_valor_critico = (
                tabla_referencias[
                    "Valor_entradas_criticas"
                ].sum()
            )

            tabla_referencias[
                "Participacion"
            ] = (
                tabla_referencias[
                    "Valor_entradas_criticas"
                ]
                / total_valor_critico
                * 100
                if total_valor_critico > 0
                else 0
            )

            # ------------------------------------------------
            # RENOMBRAR
            # ------------------------------------------------

            tabla_referencias = tabla_referencias.rename(
                columns={
                    "Codigo Articulo": "Referencia",
                    "Valor_entradas_criticas":
                        "Valor entradas críticas",
                    "Valor_inventario_actual":
                        "Valor inventario actual",
                    "Stock_maximo":
                        "Stock máximo",
                    "Meses_criticos":
                        "Meses críticos",
                    "Participacion":
                        "Participación"
                }
            )

            # ------------------------------------------------
            # REDONDEAR
            # ------------------------------------------------

            tabla_referencias[
                "Valor entradas críticas"
            ] = tabla_referencias[
                "Valor entradas críticas"
            ].round(0)

            tabla_referencias[
                "Valor inventario actual"
            ] = tabla_referencias[
                "Valor inventario actual"
            ].round(0)

            tabla_referencias[
                "Stock máximo"
            ] = tabla_referencias[
                "Stock máximo"
            ].round(0)

            tabla_referencias[
                "Participación"
            ] = tabla_referencias[
                "Participación"
            ].round(1)

            # ------------------------------------------------
            # TOP 20
            # ------------------------------------------------

            tabla_referencias = (
                tabla_referencias
                .head(20)
            )

            st.dataframe(
                tabla_referencias,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Valor entradas críticas":
                        st.column_config.NumberColumn(
                            "💰 Valor entradas críticas",
                            format="$%,.0f"
                        ),

                    "Valor inventario actual":
                        st.column_config.NumberColumn(
                            "📦 Valor inventario actual",
                            format="$%,.0f"
                        ),

                    "Participación":
                        st.column_config.NumberColumn(
                            "📊 Participación",
                            format="%.1f%%"
                        ),

                    "Stock máximo":
                        st.column_config.NumberColumn(
                            "Stock máximo",
                            format="%,.0f"
                        )
                }
            )

        else:

            st.info(
                "No fue posible identificar referencias con "
                "valor económico en los meses críticos."
            )

    else:

        st.success(
            "No se identificaron meses críticos de "
            "entrada alta + stock alto."
        )

    # --------------------------------------------------------
    # DETECCIÓN DE MESES DE POSIBLE SOBREABASTECIMIENTO
    # --------------------------------------------------------

    st.subheader(
        "🧠 Lectura analítica de los movimientos"
    )

    if len(df_mensual) > 0:

        coincidencias = df_marcados

        if len(coincidencias) > 0:

            st.warning(
                "⚠️ Se identificaron meses en los que "
                "las entradas estuvieron entre las más altas "
                "del periodo mientras el stock "
                "también estaba en niveles altos."
            )

            tabla_coincidencias = coincidencias[
                [
                    "Mes",
                    "Entradas",
                    "Salidas",
                    "Neto",
                    "Stock de cierre"
                ]
            ].copy()

            st.dataframe(
                tabla_coincidencias,
                use_container_width=True,
                hide_index=True
            )

        else:

            st.success(
                "No se identificaron coincidencias entre "
                "entradas excepcionalmente altas y niveles "
                "altos de stock bajo el criterio estadístico "
                "utilizado."
            )

    # --------------------------------------------------------
    # COSTOS Y ROTACIÓN
    # --------------------------------------------------------

    col1, col2 = st.columns(2)

    with col1:

        fig_costos = go.Figure()

        fig_costos.add_trace(
            go.Scatter(
                x=df_mensual["Mes"],
                y=df_mensual["Costo entradas"],
                mode="lines+markers",
                name="Costo entradas",
                line=dict(
                    color=AZUL,
                    width=3
                ),
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Costo entradas: $%{y:,.0f}"
                    "<extra></extra>"
                )
            )
        )

        fig_costos.add_trace(
            go.Scatter(
                x=df_mensual["Mes"],
                y=df_mensual["Costo salidas"],
                mode="lines+markers",
                name="Costo salidas",
                line=dict(
                    color=NARANJA,
                    width=3
                ),
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Costo salidas: $%{y:,.0f}"
                    "<extra></extra>"
                )
            )
        )

        fig_costos.update_layout(
            title="Valor de entradas y salidas por mes",
            xaxis_title="",
            yaxis_title="Valor"
        )

        configurar_figura(
            fig_costos,
            400
        )

        st.plotly_chart(
            fig_costos,
            use_container_width=True
        )

    with col2:

        fig_rotacion = go.Figure()

        fig_rotacion.add_trace(
            go.Scatter(
                x=df_mensual["Mes"],
                y=df_mensual["Rotacion"],
                mode="lines+markers",
                name="Rotación",
                line=dict(
                    color=MORADO,
                    width=3
                ),
                marker=dict(
                    size=8
                ),
                hovertemplate=(
                    "<b>%{x}</b><br>"
                    "Rotación: %{y:.2f}"
                    "<extra></extra>"
                )
            )
        )

        fig_rotacion.update_layout(
            title="Rotación promedio por registro",
            xaxis_title="",
            yaxis_title="Rotación"
        )

        configurar_figura(
            fig_rotacion,
            400
        )

        st.plotly_chart(
            fig_rotacion,
            use_container_width=True
        )


# ============================================================
# PÁGINA 4
# RIESGOS Y DETALLE
# ============================================================

elif pagina == "Riesgos y detalle":

    st.title(
        "Riesgos y detalle"
    )

    st.caption(
        "Priorización de inventarios que requieren revisión."
    )

    # --------------------------------------------------------
    # FILTRO DE ANTIGÜEDAD
    #
    # CORRECCIÓN 6 — Antes se contaban como "riesgo" todos los
    # registros clasificados > 12 meses, incluso los que tenían
    # stock 0 en el corte. Ahora solo cuentan los que tienen
    # inventario al corte.
    # --------------------------------------------------------

    df_alertas = df_con_stock.copy()

    if COL_ANTIGUEDAD and COL_ANTIGUEDAD in df_alertas.columns:

        df_alertas = df_alertas[
            df_alertas[
                COL_ANTIGUEDAD
            ]
            .astype(str)
            .str.contains(
                "Mayor a 12 meses",
                case=False,
                na=False
            )
        ].copy()

    valor_alerta = suma_columna(
        df_alertas,
        COL_COSTE
    )

    stock_alerta = suma_columna(
        df_alertas,
        COL_STOCK
    )

    cantidad_alertas = len(df_alertas)

    participacion_alerta = porcentaje(
        valor_alerta,
        valor_total_col
    )

    k1, k2, k3, k4 = st.columns(4)

    with k1:
        st.metric(
            "⚠️ Registros > 12 meses",
            formato_entero(cantidad_alertas)
        )

    with k2:
        st.metric(
            "📦 Stock involucrado",
            formato_numero(stock_alerta)
        )

    with k3:
        st.metric(
            "💰 Valor comprometido",
            formato_moneda(valor_alerta)
        )

    with k4:
        st.metric(
            "📊 Participación",
            f"{participacion_alerta:.1f}%"
        )

    st.write("")

    # --------------------------------------------------------
    # TOP RIESGOS
    # --------------------------------------------------------

    st.subheader(
        "🚨 Principales inventarios a revisar"
    )

    if len(df_alertas) > 0:

        top_riesgos = (
            df_alertas
            .groupby(
                [
                    "Articulo",
                    "Bodega"
                ],
                as_index=False
            )
            .agg(
                Valor=(COL_COSTE, "sum"),
                Stock=(COL_STOCK, "sum")
            )
            .sort_values(
                "Valor",
                ascending=False
            )
            .head(15)
        )

        fig_riesgos = px.bar(
            top_riesgos.sort_values(
                "Valor",
                ascending=True
            ),
            x="Valor",
            y="Articulo",
            orientation="h",
            color="Bodega",
            custom_data=[
                "Bodega",
                "Stock"
            ]
        )

        fig_riesgos.update_traces(
            hovertemplate=(
                "<b>%{y}</b><br>"
                "Bodega: %{customdata[0]}<br>"
                "Valor: $%{x:,.0f}<br>"
                "Stock: %{customdata[1]:,.2f}"
                "<extra></extra>"
            )
        )

        fig_riesgos.update_layout(
            title=f"Mayor valor concentrado en inventario > 12 meses — corte {ESQ['corte']}",
            xaxis_title="Valor",
            yaxis_title="",
            legend_title="Bodega"
        )

        configurar_figura(
            fig_riesgos,
            540
        )

        st.plotly_chart(
            fig_riesgos,
            use_container_width=True
        )

    else:

        st.success(
            "No se encontraron registros con antigüedad "
            "superior a 12 meses para los filtros seleccionados."
        )

    # --------------------------------------------------------
    # TABLA DE DETALLE
    #
    # Ahora incluye los indicadores que explican la antigüedad:
    # inventario promedio, CMV, rotación y días de rotación.
    # --------------------------------------------------------

    st.subheader(
        "📋 Detalle de registros"
    )

    columnas_detalle = [
        "AREA",
        "Bodega",
        "Codigo Articulo",
        "Articulo",
        COL_STOCK,
        COL_COSTE,
        COL_INV_PROMEDIO,
        COL_CMV_12,
        COL_ROT_12,
        COL_DIAS,
        COL_ANTIGUEDAD
    ]

    columnas_disponibles = []

    for columna in columnas_detalle:

        if (
            columna is not None
            and columna in df_filtrado.columns
            and columna not in columnas_disponibles
        ):
            columnas_disponibles.append(columna)

    df_detalle = df_filtrado[
        columnas_disponibles
    ].copy()

    if COL_COSTE in df_detalle.columns:
        df_detalle = df_detalle.sort_values(
            COL_COSTE,
            ascending=False
        )

    config_detalle = {}

    for columna, formato in [
        (COL_COSTE, "$ %,.0f"),
        (COL_INV_PROMEDIO, "$ %,.0f"),
        (COL_CMV_12, "$ %,.0f"),
        (COL_ROT_12, "%.2f"),
        (COL_DIAS, "%.0f"),
    ]:

        if columna and columna in df_detalle.columns:

            config_detalle[columna] = (
                st.column_config.NumberColumn(
                    columna,
                    format=formato
                )
            )

    st.dataframe(
        df_detalle,
        use_container_width=True,
        hide_index=True,
        height=470,
        column_config=config_detalle
    )

    # --------------------------------------------------------
    # DESCARGA
    # --------------------------------------------------------

    csv = df_detalle.to_csv(
        index=False,
        encoding="utf-8-sig"
    )

    st.download_button(
        label="⬇️ Descargar detalle en CSV",
        data=csv,
        file_name="detalle_inventarios_aldc.csv",
        mime="text/csv"
    )


# ============================================================
# PÁGINA: ÓRDENES DE COMPRA
# Alertas por referencias con inventario > 3 meses y OC > 30%
# del stock total existente en el histórico.
# ============================================================

elif pagina == "Órdenes de compra":

    import hashlib
    import io
    import smtplib
    import unicodedata
    from email.message import EmailMessage

    st.title("Órdenes de compra")
    st.caption(
        "Identifica órdenes que incluyen referencias con inventario "
        "de más de 3 meses y cuya cantidad solicitada supera el 30% "
        "del stock total registrado en el histórico."
    )

    def _normalizar_nombre_columna(valor):
        texto = str(valor).strip().lower()
        texto = unicodedata.normalize("NFKD", texto)
        texto = "".join(c for c in texto if not unicodedata.combining(c))
        return re.sub(r"[^a-z0-9]", "", texto)

    def _buscar_columna(df_busqueda, candidatos):
        mapa = {
            _normalizar_nombre_columna(c): c
            for c in df_busqueda.columns
        }
        for candidato in candidatos:
            encontrada = mapa.get(_normalizar_nombre_columna(candidato))
            if encontrada is not None:
                return encontrada
        return None

    def _normalizar_referencia(serie):
        return (
            serie.astype(str)
            .str.strip()
            .str.replace(r"\.0$", "", regex=True)
            .replace({"nan": "", "None": "", "NaT": ""})
        )

    def _numero_seguro(serie):
        if pd.api.types.is_numeric_dtype(serie):
            return pd.to_numeric(serie, errors="coerce").fillna(0)
        texto = serie.astype(str).str.strip()
        # Admite números con separadores de miles y coma decimal.
        texto = texto.str.replace("$", "", regex=False).str.replace(" ", "", regex=False)
        ambos = texto.str.contains(",", na=False) & texto.str.contains(r"\.", na=False)
        texto.loc[ambos] = (
            texto.loc[ambos].str.replace(".", "", regex=False)
            .str.replace(",", ".", regex=False)
        )
        solo_coma = texto.str.contains(",", na=False) & ~texto.str.contains(r"\.", na=False)
        texto.loc[solo_coma] = texto.loc[solo_coma].str.replace(",", ".", regex=False)
        return pd.to_numeric(texto, errors="coerce").fillna(0)

    st.markdown("### 1. Cargar archivo de órdenes")
    archivo_ordenes = st.file_uploader(
        "Carga el Excel o CSV con las órdenes de compra",
        type=["xlsx", "xls", "csv"],
        key="archivo_ordenes_compra"
    )

    st.info(
        "El archivo debe incluir el identificador de la orden, la referencia "
        "del artículo y la cantidad solicitada. Se aceptan encabezados como "
        "IdOrden, Cod Articulo / Id Articulo y Cantidad. Si existe una columna "
        "Estado, se excluyen registros anulados, cancelados, cerrados o recibidos."
    )

    if archivo_ordenes is not None:
        try:
            bytes_ordenes = archivo_ordenes.getvalue()
            firma_ordenes = hashlib.sha256(bytes_ordenes).hexdigest()

            if archivo_ordenes.name.lower().endswith(".csv"):
                try:
                    df_ordenes_original = pd.read_csv(
                        io.BytesIO(bytes_ordenes), sep=None, engine="python"
                    )
                except UnicodeDecodeError:
                    df_ordenes_original = pd.read_csv(
                        io.BytesIO(bytes_ordenes), sep=None, engine="python",
                        encoding="latin-1"
                    )
            else:
                df_ordenes_original = pd.read_excel(io.BytesIO(bytes_ordenes))

            col_orden = _buscar_columna(
                df_ordenes_original,
                ["IdOrden", "Id Orden", "Orden de compra", "Codigo de orden",
                 "Código de orden", "Numero de orden", "Número de orden", "OC"]
            )
            col_referencia_oc = _buscar_columna(
                df_ordenes_original,
                ["Cod Articulo", "Código Articulo", "Codigo Articulo",
                 "Id Articulo", "IdArtículo", "Referencia", "Código de artículo",
                 "Codigo de articulo", "Material"]
            )
            col_cantidad_oc = _buscar_columna(
                df_ordenes_original,
                ["Cantidad", "Cantidad solicitada", "Cantidad ordenada",
                 "Cantidad OC", "Qty", "Cantidad requerida"]
            )
            col_estado_oc = _buscar_columna(
                df_ordenes_original,
                ["Estado", "Status", "Estado de la orden"]
            )

            faltantes_oc = []
            if col_orden is None:
                faltantes_oc.append("IdOrden / Orden de compra")
            if col_referencia_oc is None:
                faltantes_oc.append("Cod Articulo / Id Articulo / Referencia")
            if col_cantidad_oc is None:
                faltantes_oc.append("Cantidad")

            if faltantes_oc:
                st.error(
                    "No pude identificar estas columnas en el archivo: "
                    + ", ".join(faltantes_oc)
                    + ". Revisa los encabezados y vuelve a cargarlo."
                )
                st.write("Encabezados encontrados:", list(df_ordenes_original.columns))
            elif not COL_ANTIGUEDAD or COL_ANTIGUEDAD not in df.columns:
                st.error(
                    "El histórico no contiene una columna de antigüedad reconocida. "
                    "No es posible validar la regla de más de 3 meses."
                )
            elif not COL_STOCK or COL_STOCK not in df.columns:
                st.error(
                    "No se encontró la columna de stock en el histórico. "
                    "No es posible comparar las cantidades de las órdenes."
                )
            elif _buscar_columna(df, ["Codigo Articulo", "Código Articulo",
                                      "Cod Articulo", "Id Articulo",
                                      "Referencia", "Material"]) is None:
                st.error(
                    "No se encontró una columna de referencia de artículo "
                    "en el histórico de inventarios."
                )
            else:
                col_referencia_hist = _buscar_columna(
                    df, ["Codigo Articulo", "Código Articulo", "Cod Articulo",
                         "Id Articulo", "Referencia", "Material"]
                )
                col_articulo_hist = _buscar_columna(
                    df, ["Articulo", "Artículo", "Descripcion", "Descripción"]
                )
                col_bodega_hist = _buscar_columna(
                    df, ["Bodega", "Almacen", "Almacén"]
                )

                # El histórico se consolida por referencia: stock total y
                # stock ubicado en categorías con antigüedad superior a 3 meses.
                hist = df.copy()
                hist["_ref_oc"] = _normalizar_referencia(hist[col_referencia_hist])
                hist["_stock_oc"] = _numero_seguro(hist[COL_STOCK]).clip(lower=0)
                hist["_edad_oc"] = hist[COL_ANTIGUEDAD].astype(str).str.strip()
                hist["_edad_mayor_3m"] = hist["_edad_oc"].str.contains(
                    r"Entre 4 y 6 meses|Entre 7 y 12 meses|Mayor a 12 meses|"
                    r"Mayor de 3 meses|Mas de 3 meses|Más de 3 meses",
                    case=False, na=False, regex=True
                )
                hist = hist[hist["_ref_oc"].ne("")].copy()

                agregaciones_hist = {
                    "Stock histórico": ("_stock_oc", "sum"),
                    "Stock con antigüedad > 3 meses": (
                        "_stock_oc",
                        lambda x: float(x[hist.loc[x.index, "_edad_mayor_3m"]].sum())
                    ),
                    "Categorías de antigüedad": (
                        "_edad_oc",
                        lambda x: ", ".join(sorted(set(
                            str(v) for v in x
                            if pd.notna(v) and str(v).strip()
                        )))
                    )
                }
                if col_articulo_hist:
                    agregaciones_hist["Artículo"] = (col_articulo_hist, "first")
                if col_bodega_hist:
                    agregaciones_hist["Bodegas"] = (
                        col_bodega_hist,
                        lambda x: ", ".join(sorted(set(
                            str(v) for v in x if pd.notna(v) and str(v).strip()
                        )))
                    )

                hist_ref = hist.groupby("_ref_oc", as_index=False).agg(**agregaciones_hist)

                oc = df_ordenes_original.copy()
                oc["_orden_oc"] = _normalizar_referencia(oc[col_orden])
                oc["_ref_oc"] = _normalizar_referencia(oc[col_referencia_oc])
                oc["_cantidad_oc"] = _numero_seguro(oc[col_cantidad_oc])
                oc = oc[
                    oc["_orden_oc"].ne("")
                    & oc["_ref_oc"].ne("")
                    & (oc["_cantidad_oc"] > 0)
                ].copy()

                if col_estado_oc:
                    estados = oc[col_estado_oc].astype(str).str.lower()
                    estados_no_vigentes = (
                        estados.str.contains(
                            r"anulad|cancelad|cerrad|recibid|finaliz|completad",
                            na=False
                        )
                    )
                    oc = oc[~estados_no_vigentes].copy()

                # Consolidar renglones repetidos de una misma orden y referencia.
                claves_oc = ["_orden_oc", "_ref_oc"]
                extras_oc = {}
                for posible in ["Grupo", "Req", "Fecha", "Estado"]:
                    col_extra = _buscar_columna(oc, [posible])
                    if col_extra and col_extra not in [col_orden, col_referencia_oc,
                                                       col_cantidad_oc]:
                        extras_oc[posible] = (col_extra, "first")

                agg_oc = {"Cantidad ordenada": ("_cantidad_oc", "sum")}
                for nombre_extra, (col_extra, metodo) in extras_oc.items():
                    agg_oc[nombre_extra] = (col_extra, metodo)
                oc_agrupada = oc.groupby(claves_oc, as_index=False).agg(**agg_oc)

                alertas_oc = oc_agrupada.merge(
                    hist_ref, on="_ref_oc", how="left"
                )
                alertas_oc["Stock histórico"] = alertas_oc["Stock histórico"].fillna(0)
                alertas_oc["Stock con antigüedad > 3 meses"] = (
                    alertas_oc["Stock con antigüedad > 3 meses"].fillna(0)
                )
                alertas_oc["% de la orden sobre el stock"] = (
                    alertas_oc["Cantidad ordenada"]
                    .div(alertas_oc["Stock histórico"].replace(0, pd.NA))
                    .mul(100)
                )

                alertas_oc = alertas_oc[
                    (alertas_oc["Stock con antigüedad > 3 meses"] > 0)
                    & (alertas_oc["Stock histórico"] > 0)
                    & (
                        alertas_oc["Cantidad ordenada"]
                        > alertas_oc["Stock histórico"] * 0.30
                    )
                ].copy()

                alertas_oc = alertas_oc.rename(
                    columns={"_orden_oc": "Orden de compra", "_ref_oc": "Referencia"}
                )
                columnas_salida = [
                    "Orden de compra", "Referencia", "Artículo",
                    "Cantidad ordenada", "Stock histórico",
                    "Stock con antigüedad > 3 meses",
                    "% de la orden sobre el stock",
                    "Categorías de antigüedad", "Bodegas",
                    "Grupo", "Req", "Fecha", "Estado"
                ]
                columnas_salida = [
                    c for c in columnas_salida if c in alertas_oc.columns
                ]
                alertas_oc = alertas_oc[columnas_salida].sort_values(
                    "% de la orden sobre el stock", ascending=False
                )

                st.markdown("### 2. Resultados de la validación")
                m1, m2, m3 = st.columns(3)
                m1.metric("Órdenes/referencias alertadas", f"{len(alertas_oc):,}")
                m2.metric(
                    "Referencias diferentes",
                    f"{alertas_oc['Referencia'].nunique() if not alertas_oc.empty else 0:,}"
                )
                m3.metric(
                    "Umbral de compra",
                    "Más del 30% del stock"
                )

                if alertas_oc.empty:
                    st.success(
                        "No se encontraron órdenes que cumplan simultáneamente "
                        "las dos condiciones: stock con antigüedad superior a 3 meses "
                        "y cantidad ordenada mayor al 30% del stock histórico."
                    )
                else:
                    st.warning(
                        "Se encontraron órdenes que cumplen las condiciones de alerta."
                    )
                    st.dataframe(
                        alertas_oc,
                        use_container_width=True,
                        hide_index=True
                    )
                    st.download_button(
                        "Descargar alertas de órdenes (Excel/CSV)",
                        data=alertas_oc.to_csv(index=False, encoding="utf-8-sig"),
                        file_name="alertas_ordenes_compra.csv",
                        mime="text/csv"
                    )

                # Correo automático una sola vez por archivo en la sesión.
                # La configuración se toma de st.secrets["email"].
                if not alertas_oc.empty and st.session_state.get(
                    "firma_ordenes_correo_enviada"
                ) != firma_ordenes:
                    try:
                        config_email = dict(st.secrets["email"])
                        remitente = str(config_email.get("remitente", "")).strip()
                        contrasena = str(config_email.get("contrasena", "")).strip()
                        servidor = str(
                            config_email.get("servidor", "smtp.office365.com")
                        ).strip()
                        puerto = int(config_email.get("puerto", 587))

                        destinatarios_config = (
                            config_email.get("destinatarios")
                            or config_email.get("destinatario")
                            or config_email.get("correo_destino")
                            or config_email.get("para")
                            or ""
                        )
                        destinatarios = [
                            x.strip()
                            for x in re.split(r"[,;]", str(destinatarios_config))
                            if x.strip()
                        ]

                        if not remitente or not contrasena or not destinatarios:
                            raise ValueError(
                                "Falta configurar remitente, contraseña o destinatarios "
                                "en st.secrets['email']."
                            )

                        cuerpo_html = alertas_oc.to_html(
                            index=False, border=0, justify="left"
                        )
                        mensaje = EmailMessage()
                        mensaje["Subject"] = (
                            f"Alerta de órdenes de compra: {len(alertas_oc)} "
                            "referencias con inventario antiguo"
                        )
                        mensaje["From"] = remitente
                        mensaje["To"] = ", ".join(destinatarios)
                        mensaje.set_content(
                            "Se detectaron órdenes de compra que cumplen los criterios "
                            "de antigüedad superior a 3 meses y cantidad mayor al 30% "
                            "del stock histórico. Consulte la tabla en la versión HTML "
                            "de este correo."
                        )
                        mensaje.add_alternative(
                            f"""
                            <html><body style="font-family:Arial,sans-serif;color:#172D49">
                            <div style="background:#102D50;color:#fff;padding:18px">
                                <h2 style="margin:0;color:#fff">Alerta de órdenes de compra</h2>
                                <p style="margin:6px 0 0">Inventarios ALDC</p>
                            </div>
                            <p>Se identificaron <b>{len(alertas_oc)}</b> combinaciones
                            de orden y referencia para revisar.</p>
                            <p><b>Regla:</b> la referencia tiene stock con antigüedad
                            superior a 3 meses y la cantidad de la orden supera el 30%
                            del stock total existente en el histórico.</p>
                            <div style="overflow-x:auto">{cuerpo_html}</div>
                            <p style="font-size:12px;color:#667892">
                            Mensaje automático generado por Inventarios ALDC.
                            </p></body></html>
                            """,
                            subtype="html"
                        )

                        with smtplib.SMTP(servidor, puerto, timeout=30) as smtp:
                            smtp.starttls()
                            smtp.login(remitente, contrasena)
                            smtp.send_message(mensaje)

                        st.session_state["firma_ordenes_correo_enviada"] = firma_ordenes
                        st.success(
                            "Correo de alerta enviado automáticamente a: "
                            + ", ".join(destinatarios)
                        )
                    except Exception as exc:
                        st.error(
                            "Las alertas se calcularon, pero no fue posible enviar "
                            f"el correo automático. Detalle: {exc}"
                        )
                        st.caption(
                            "Configura los datos SMTP en los Secrets de Streamlit Cloud. "
                            "Después de corregirlos, vuelve a cargar el archivo de órdenes."
                        )
                elif not alertas_oc.empty:
                    st.info(
                        "El correo de este archivo ya se envió en esta sesión; "
                        "no se volverá a enviar automáticamente en cada actualización."
                    )

        except Exception as exc:
            st.error(f"No fue posible procesar el archivo de órdenes: {exc}")


# ============================================================
# PIE
# ============================================================

st.divider()

st.caption(
    "Inventarios ALDC  |  "
    "Herramienta de análisis y seguimiento de inventarios  |  "
    "Área Limpia D.C."
)
