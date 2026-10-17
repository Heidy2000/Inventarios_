"""
ui.py
Identidad visual de Inventarios ALDC (Área Limpia D.C.):
paleta, hoja de estilos y componentes de interfaz reutilizables
(encabezados de página, secciones, tarjetas KPI, insignias de estado).
"""
import html

# ============================================================
# PALETA CORPORATIVA — ÁREA LIMPIA
# Azul principal, azul oscuro y naranja de acento sobre fondos claros.
# ============================================================

AZUL = "#064B9B"
AZUL_OSCURO = "#003B7A"
AZUL_MEDIO = "#0B5AAE"
AZUL_CLARO = "#5B93D3"
AZUL_SUAVE = "#E8F1FB"

NARANJA = "#F58220"
NARANJA_OSCURO = "#C9650F"
NARANJA_CLARO = "#F9B56E"
NARANJA_SUAVE = "#FFF1E3"

VERDE = "#2E9D5B"
VERDE_CLARO = "#8FD3A8"
VERDE_SUAVE = "#E8F6EE"

ROJO = "#D64545"
ROJO_CLARO = "#F0A0A0"
ROJO_SUAVE = "#FDEDED"

MORADO = "#6F63D0"
MORADO_SUAVE = "#F1EFFF"

AMARILLO = "#E9A92C"
AMARILLO_SUAVE = "#FFF7E4"

GRIS_FONDO = "#F5F7FA"
GRIS_PANEL = "#FFFFFF"
GRIS_BORDE = "#DCE3EC"
GRIS_GRID = "#EAEFF5"
GRIS_TEXTO = "#5F7189"
GRIS_OSCURO = "#14294A"
BLANCO = "#FFFFFF"

# Secuencia de colores de los gráficos: azules y naranja primero.
SECUENCIA_GRAFICOS = [
    AZUL, NARANJA, AZUL_CLARO, AZUL_OSCURO, NARANJA_CLARO,
    "#4D6F91", VERDE, "#9AA9BA", MORADO, AMARILLO,
]

TONOS = {
    "azul": AZUL,
    "oscuro": AZUL_OSCURO,
    "naranja": NARANJA,
    "verde": VERDE,
    "rojo": ROJO,
    "gris": "#8A9AB0",
}


def _e(valor):
    return html.escape(str(valor))


# ============================================================
# HOJA DE ESTILOS
# ============================================================

def css_aplicacion():
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {{
    font-family: "Inter", "Segoe UI", Arial, sans-serif !important;
}}

.stApp, [data-testid="stAppViewContainer"] {{
    background: {GRIS_FONDO} !important;
}}

[data-testid="stHeader"] {{ background: transparent !important; }}

.block-container {{
    padding-top: 1.6rem !important;
    padding-bottom: 2.5rem !important;
    max-width: 1480px !important;
}}

h1 {{
    color: {AZUL_OSCURO} !important;
    font-size: 1.85rem !important;
    font-weight: 800 !important;
    letter-spacing: -0.6px !important;
    line-height: 1.15 !important;
}}

h2, h3 {{
    color: {AZUL_OSCURO} !important;
    font-weight: 700 !important;
}}

h3 {{ font-size: 1.08rem !important; }}

p, label, .stCaption {{ color: {GRIS_TEXTO}; }}

/* ---------------- BARRA LATERAL ---------------- */
section[data-testid="stSidebar"] {{
    background: {AZUL_OSCURO} !important;
    border-right: 0 !important;
    min-width: 260px !important;
    max-width: 260px !important;
}}

section[data-testid="stSidebar"] > div {{
    background: {AZUL_OSCURO} !important;
    padding: 1.3rem 1rem 1rem 1rem !important;
}}

section[data-testid="stSidebar"] * {{ color: #FFFFFF; }}

.sidebar-brand {{
    display: flex; align-items: center; gap: 11px;
    padding: 0.15rem 0.15rem 1.2rem 0.15rem;
    border-bottom: 1px solid rgba(255,255,255,0.14);
    margin-bottom: 1rem;
}}

.brand-mark {{
    width: 44px; height: 44px; min-width: 44px;
    border-radius: 12px; background: {NARANJA};
    display: flex; align-items: center; justify-content: center;
    color: #FFFFFF !important; font-size: 17px; font-weight: 800;
}}

.brand-title {{ font-size: 1rem; font-weight: 800; color: #FFFFFF !important; line-height: 1.15; }}
.brand-subtitle {{ font-size: 0.72rem; margin-top: 4px; color: #B9C8DA !important; }}

.sidebar-section-title {{
    color: #9FB5D1 !important; font-size: 0.7rem; font-weight: 800;
    letter-spacing: 0.7px; margin: 1rem 0 0.45rem 0.15rem;
}}

.sidebar-user {{
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 12px; padding: 0.7rem 0.75rem; margin: 0.7rem 0 0.9rem 0;
}}

.sidebar-user-name {{ color: #FFFFFF !important; font-weight: 700; font-size: 0.86rem; }}
.sidebar-user-role {{ color: #B9C8DA !important; font-size: 0.72rem; margin-top: 2px; }}
.sidebar-user-status {{ color: {NARANJA_CLARO} !important; font-size: 0.72rem; margin-top: 3px; }}

section[data-testid="stSidebar"] div[data-testid="stRadio"] > label:first-child {{ display: none !important; }}

section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] {{
    display: flex !important; flex-direction: column !important; gap: 6px !important; width: 100% !important;
}}

section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label {{
    display: flex !important; align-items: center !important; width: 100% !important;
    min-height: 42px !important; box-sizing: border-box !important; margin: 0 !important;
    padding: 0.6rem 0.8rem !important; border-radius: 10px !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    background: rgba(255,255,255,0.05) !important;
    cursor: pointer !important; transition: 0.15s ease !important;
}}

section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label:hover {{
    background: rgba(255,255,255,0.10) !important;
}}

section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label:has(input:checked) {{
    background: {AZUL} !important;
    border-color: rgba(245,130,32,0.60) !important;
    box-shadow: inset 3px 0 0 {NARANJA} !important;
}}

section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label p {{
    color: #DCE7F2 !important; font-size: 0.86rem !important; font-weight: 600 !important; margin: 0 !important;
}}

section[data-testid="stSidebar"] div[data-testid="stRadio"] div[role="radiogroup"] > label:has(input:checked) p {{
    color: #FFFFFF !important; font-weight: 750 !important;
}}

section[data-testid="stSidebar"] div[data-testid="stRadio"] input {{ display: none !important; }}

section[data-testid="stSidebar"] .stButton > button {{
    background: transparent !important; color: #DCE7F2 !important;
    border: 1px solid rgba(255,255,255,0.16) !important; border-radius: 10px !important;
    font-weight: 600 !important; box-shadow: none !important;
}}

section[data-testid="stSidebar"] .stButton > button:hover {{
    background: rgba(255,255,255,0.08) !important; transform: none !important;
}}

/* ---------------- ENCABEZADO DE PÁGINA ---------------- */
.page-header {{
    display: flex; justify-content: space-between; align-items: flex-end;
    gap: 18px; flex-wrap: wrap;
    padding: 0 0 0.9rem 0; margin-bottom: 1rem;
    border-bottom: 1px solid {GRIS_BORDE};
}}

.page-eyebrow {{
    color: {NARANJA_OSCURO}; font-size: 0.72rem; font-weight: 800;
    letter-spacing: 0.9px; text-transform: uppercase; margin-bottom: 0.25rem;
}}

.page-title {{
    color: {AZUL_OSCURO}; font-size: 1.85rem; font-weight: 800;
    letter-spacing: -0.6px; line-height: 1.15; margin: 0;
}}

.page-subtitle {{ color: {GRIS_TEXTO}; font-size: 0.95rem; margin-top: 0.35rem; line-height: 1.45; }}

.header-pills {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}

.header-pill {{
    padding: 0.45rem 0.85rem; border-radius: 999px; background: #FFFFFF;
    border: 1px solid {GRIS_BORDE}; color: {AZUL_OSCURO} !important;
    font-size: 0.76rem; font-weight: 650; white-space: nowrap;
}}

.header-pill.primary {{ background: {AZUL_SUAVE}; border-color: #BFD5F1; color: {AZUL} !important; }}
.header-pill.accent {{ background: {NARANJA_SUAVE}; border-color: {NARANJA_CLARO}; color: {NARANJA_OSCURO} !important; }}

/* ---------------- SECCIONES ---------------- */
.section-head {{ margin: 1.5rem 0 0.7rem 0; }}
.section-title {{
    color: {AZUL_OSCURO}; font-size: 1.08rem; font-weight: 750;
    display: flex; align-items: center; gap: 9px;
}}
.section-title::before {{
    content: ""; width: 4px; height: 18px; border-radius: 4px; background: {NARANJA}; display: inline-block;
}}
.section-desc {{ color: {GRIS_TEXTO}; font-size: 0.84rem; margin: 0.2rem 0 0 13px; }}

/* ---------------- TARJETAS KPI ---------------- */
.kpi-card {{
    background: #FFFFFF; border: 1px solid {GRIS_BORDE}; border-radius: 14px;
    padding: 14px 16px 13px 16px; min-height: 108px;
    box-shadow: 0 3px 12px rgba(0,59,122,0.05);
    border-top: 3px solid var(--kpi-tono, {AZUL});
    margin-bottom: 0.6rem;
}}
.kpi-label {{
    color: {GRIS_TEXTO}; font-size: 0.74rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.45px;
}}
.kpi-value {{
    color: {AZUL_OSCURO}; font-size: 1.6rem; font-weight: 800;
    letter-spacing: -0.5px; margin-top: 6px; line-height: 1.15;
    overflow-wrap: anywhere;
}}
.kpi-detail {{ color: {GRIS_TEXTO}; font-size: 0.76rem; margin-top: 5px; line-height: 1.35; }}

/* st.metric (se conserva en algunos lugares) */
div[data-testid="stMetric"], div[data-testid="metric-container"] {{
    background: #FFFFFF; border: 1px solid {GRIS_BORDE}; border-radius: 14px;
    padding: 14px 16px; box-shadow: 0 3px 12px rgba(0,59,122,0.05);
    border-top: 3px solid {AZUL};
}}
div[data-testid="stMetricValue"] {{ color: {AZUL_OSCURO} !important; font-weight: 800 !important; }}
div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stMetric"] {{
    border: 0 !important; box-shadow: none !important; padding: 0 !important;
}}

/* ---------------- CONTENEDORES, FILTROS Y TABLAS ---------------- */
div[data-testid="stVerticalBlockBorderWrapper"] {{
    background: #FFFFFF !important; border: 1px solid {GRIS_BORDE} !important;
    border-radius: 14px !important; box-shadow: 0 3px 12px rgba(0,59,122,0.04) !important;
}}

.filter-title {{
    color: {AZUL_OSCURO}; font-size: 0.82rem; font-weight: 800;
    letter-spacing: 0.5px; text-transform: uppercase;
}}
.filter-subtitle {{ color: #7A8AA0; font-size: 0.78rem; margin-bottom: 0.6rem; }}
.filter-records {{
    display: inline-flex; padding: 0.35rem 0.7rem; border-radius: 999px;
    background: {AZUL_SUAVE}; color: {AZUL} !important; font-size: 0.74rem; font-weight: 700;
}}

div[data-baseweb="select"] > div {{
    border-radius: 10px !important; border: 1px solid #D6DFEA !important;
    background: #F4F7FB !important; min-height: 42px !important;
}}
div[data-baseweb="select"] > div:focus-within {{
    border-color: {AZUL} !important; box-shadow: 0 0 0 2px rgba(6,75,155,0.12) !important;
}}

div[data-testid="stSelectbox"] label, div[data-testid="stMultiSelect"] label {{
    color: #5B6F89 !important; font-size: 0.76rem !important; font-weight: 650 !important;
}}

span[data-baseweb="tag"] {{ background: {AZUL_SUAVE} !important; }}
span[data-baseweb="tag"] span {{ color: {AZUL_OSCURO} !important; }}

div[data-testid="stDataFrame"] {{
    border-radius: 12px; overflow: hidden; border: 1px solid {GRIS_BORDE}; background: #FFFFFF;
}}

div[data-testid="stFileUploader"] section {{
    border: 1.5px dashed #9DB8DA !important; border-radius: 12px !important;
    background: {AZUL_SUAVE} !important;
}}

div[data-testid="stExpander"] details {{
    border-radius: 12px !important; border: 1px solid {GRIS_BORDE} !important; background: #FFFFFF !important;
}}

/* ---------------- BOTONES ---------------- */
.stButton > button {{
    border-radius: 10px !important; border: 1px solid {AZUL} !important;
    background: {AZUL} !important; color: #FFFFFF !important;
    font-weight: 700 !important; min-height: 41px !important;
}}
.stButton > button:hover {{ background: {AZUL_OSCURO} !important; border-color: {AZUL_OSCURO} !important; }}
.stButton > button:disabled {{ background: #B9C6D6 !important; border-color: #B9C6D6 !important; }}

.stDownloadButton > button {{
    border-radius: 10px !important; border: 1px solid {AZUL} !important;
    background: #FFFFFF !important; color: {AZUL} !important; font-weight: 700 !important;
}}
.stDownloadButton > button:hover {{ background: {AZUL_SUAVE} !important; }}

div[data-testid="stAlert"] {{ border-radius: 12px !important; }}

/* ---------------- INSIGNIAS DE ESTADO ---------------- */
.badge {{
    display: inline-block; padding: 0.2rem 0.6rem; border-radius: 999px;
    font-size: 0.74rem; font-weight: 700; margin: 0 0.25rem 0.25rem 0;
}}
.badge-ok {{ background: {VERDE_SUAVE}; color: {VERDE}; }}
.badge-warn {{ background: {NARANJA_SUAVE}; color: {NARANJA_OSCURO}; }}
.badge-err {{ background: {ROJO_SUAVE}; color: {ROJO}; }}
.badge-info {{ background: {AZUL_SUAVE}; color: {AZUL}; }}

.step {{
    display: flex; gap: 10px; align-items: flex-start; margin-bottom: 0.4rem;
    color: {GRIS_OSCURO}; font-size: 0.86rem;
}}
.step-num {{
    min-width: 22px; height: 22px; border-radius: 50%; background: {AZUL};
    color: #FFFFFF; font-size: 0.72rem; font-weight: 800;
    display: inline-flex; align-items: center; justify-content: center;
}}

hr {{ border-color: {GRIS_BORDE} !important; }}
</style>
"""


def aplicar_estilos(st):
    st.markdown(css_aplicacion(), unsafe_allow_html=True)


# ============================================================
# COMPONENTES
# ============================================================

def encabezado_pagina(st, titulo, subtitulo="", eyebrow="", pills=()):
    """Título de la página con subtítulo y etiquetas de contexto."""
    pills_html = "".join(
        f'<div class="header-pill {_e(clase)}">{_e(texto)}</div>'
        for texto, clase in pills
        if texto
    )
    st.markdown(
        f"""
<div class="page-header">
  <div>
    {f'<div class="page-eyebrow">{_e(eyebrow)}</div>' if eyebrow else ''}
    <div class="page-title">{_e(titulo)}</div>
    {f'<div class="page-subtitle">{_e(subtitulo)}</div>' if subtitulo else ''}
  </div>
  <div class="header-pills">{pills_html}</div>
</div>
""",
        unsafe_allow_html=True,
    )


def seccion(st, titulo, descripcion=""):
    st.markdown(
        f"""
<div class="section-head">
  <div class="section-title">{_e(titulo)}</div>
  {f'<div class="section-desc">{_e(descripcion)}</div>' if descripcion else ''}
</div>
""",
        unsafe_allow_html=True,
    )


def tarjeta_kpi(titulo, valor, detalle="", tono="azul"):
    color = TONOS.get(tono, AZUL)
    return (
        f'<div class="kpi-card" style="--kpi-tono:{color}">'
        f'<div class="kpi-label">{_e(titulo)}</div>'
        f'<div class="kpi-value">{_e(valor)}</div>'
        f'<div class="kpi-detail">{_e(detalle)}</div>'
        f"</div>"
    )


def fila_kpis(st, tarjetas):
    """tarjetas: lista de tuplas (titulo, valor, detalle, tono)."""
    columnas = st.columns(len(tarjetas))
    for col, t in zip(columnas, tarjetas):
        titulo, valor = t[0], t[1]
        detalle = t[2] if len(t) > 2 else ""
        tono = t[3] if len(t) > 3 else "azul"
        with col:
            st.markdown(tarjeta_kpi(titulo, valor, detalle, tono), unsafe_allow_html=True)


def insignia(texto, tipo="info"):
    return f'<span class="badge badge-{_e(tipo)}">{_e(texto)}</span>'


def pasos(st, lista):
    st.markdown(
        "".join(
            f'<div class="step"><span class="step-num">{i}</span><span>{_e(p)}</span></div>'
            for i, p in enumerate(lista, start=1)
        ),
        unsafe_allow_html=True,
    )


# ============================================================
# FORMATO NUMÉRICO (formato colombiano: punto de miles, coma decimal)
# ============================================================

def formato_moneda(valor):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return "$0"
    if v != v:
        return "$0"
    signo = "-" if v < 0 else ""
    return f"{signo}${abs(v):,.0f}".replace(",", ".")


def formato_numero(valor, decimales=2):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return "0"
    if v != v:
        return "0"
    return (
        f"{v:,.{decimales}f}"
        .replace(",", "X").replace(".", ",").replace("X", ".")
    )


def formato_entero(valor):
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return "0"
    if v != v:
        return "0"
    return f"{v:,.0f}".replace(",", ".")
