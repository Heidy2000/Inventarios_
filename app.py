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
    a_numero,
    numero_bodega,
    BODEGAS_EXCLUIDAS,
    DIAS_VENTANA_COMPLETA,
)
import acceso
import conciliacion
import ui

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
# PALETA INSTITUCIONAL — ÁREA LIMPIA (definida en ui.py)
# Azul principal, azul oscuro y naranja de acento.
# ============================================================

AZUL = ui.AZUL
AZUL_OSCURO = ui.AZUL_OSCURO
AZUL_MEDIO = ui.AZUL_MEDIO
AZUL_CLARO = ui.AZUL_CLARO
AZUL_SUAVE = ui.AZUL_SUAVE

VERDE = ui.VERDE
VERDE_CLARO = ui.VERDE_CLARO
VERDE_SUAVE = ui.VERDE_SUAVE

NARANJA = ui.NARANJA
NARANJA_CLARO = ui.NARANJA_CLARO
NARANJA_SUAVE = ui.NARANJA_SUAVE

ROJO = ui.ROJO
ROJO_CLARO = ui.ROJO_CLARO
ROJO_SUAVE = ui.ROJO_SUAVE

MORADO = ui.MORADO
MORADO_SUAVE = ui.MORADO_SUAVE

AMARILLO = ui.AMARILLO
AMARILLO_SUAVE = ui.AMARILLO_SUAVE

GRIS_FONDO = ui.GRIS_FONDO
GRIS_PANEL = ui.GRIS_PANEL
GRIS_BORDE = ui.GRIS_BORDE
GRIS_GRID = ui.GRIS_GRID
GRIS_TEXTO = ui.GRIS_TEXTO
GRIS_OSCURO = ui.GRIS_OSCURO
BLANCO = ui.BLANCO

px.defaults.color_discrete_sequence = ui.SECUENCIA_GRAFICOS


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
# ESTILOS DE LA APLICACIÓN (ver ui.py)
# ============================================================

ui.aplicar_estilos(st)


# ============================================================
# FUNCIONES DE FORMATO
# ============================================================

formato_moneda = ui.formato_moneda
formato_numero = ui.formato_numero
formato_entero = ui.formato_entero


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
# LOGO DEL INICIO DE SESIÓN
# ============================================================

def _logo_login():

    base = os.path.dirname(os.path.abspath(__file__))

    for nombre in (
        "logo.png",
        "logo.jpg",
        "logo.jpeg",
        "logo.webp",
        "logo_aldc.png"
    ):
        ruta = os.path.join(base, nombre)

        if os.path.exists(ruta):
            return ruta

    return LOGO_URL


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
            color: #003B7A !important;
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
            color: #003B7A !important;
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
            color: #003B7A !important;
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
            color: #003B7A !important;
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
                    Acceso protegido · Sistema de gestión y análisis de inventarios
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
# USUARIO Y PERMISOS (ver acceso.py)
# El rol se resuelve en cada ejecución a partir de la sesión
# autenticada; las páginas restringidas lo vuelven a comprobar.
# ============================================================

SECRETOS = acceso.secretos_de(st)
USUARIO = acceso.usuario_sesion(st)
ES_ADMIN = acceso.es_admin(USUARIO, SECRETOS)
PAGINAS_PERMITIDAS = acceso.paginas_permitidas(USUARIO, SECRETOS)


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
            "No fue posible cargar los datos del inventario "
            f"({os.path.basename(ARCHIVO_ACTUALIZADO)} o "
            f"{os.path.basename(ARCHIVO_HISTORICO)}).\n\n"
            f"Detalle: {e}"
        )

        st.stop()

    if df is None:

        if ES_ADMIN:

            pagina_actualizar_kardex(
                st,
                USUARIO,
                ARCHIVO_ACTUALIZADO,
                ARCHIVO_HISTORICO
            )

        else:

            st.warning(
                "Todavía no hay información de inventario cargada. "
                "Un administrador debe cargar el histórico base."
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
# Las salidas se muestran en valor absoluto.
#
# Inventario inicial de cada mes = stock de cierre del mes anterior;
# el del primer mes es el STOCK INICIAL del histórico (antes se
# mostraba 0, corrección H-10).
#
# Rotación mensual = salidas del mes ÷ inventario inicial del mes,
# calculada igual para todos los meses (antes solo los meses del
# Kardex tenían rotación y los del histórico aparecían en 0, H-11).
# ============================================================

def construir_serie_mensual(dataframe):

    def suma(columna):

        if columna and columna in dataframe.columns:
            return dataframe[columna].fillna(0).sum()

        return 0

    col_stock_inicial = col_exacta(dataframe, "STOCK INICIAL")
    stock_anterior = (
        suma(col_stock_inicial) if col_stock_inicial is not None else None
    )

    datos = []

    for mes in ESQ["meses"]:

        entradas = suma(mes["entrada"])
        salidas = abs(suma(mes["salida"]))
        cierre = suma(mes["stock"])

        if stock_anterior is not None and stock_anterior > EPS:
            rotacion_mes = salidas / stock_anterior
        else:
            rotacion_mes = None

        datos.append({
            "Mes": mes["label"],
            "Inventario inicial": stock_anterior,
            "Entradas": entradas,
            "Salidas": salidas,
            "Costo entradas": suma(mes["costo_entrada"]),
            "Costo salidas": abs(suma(mes["costo_salida"])),
            "Neto": entradas - salidas,
            "Rotacion": rotacion_mes,
            "Stock de cierre": cierre
        })

        stock_anterior = cierre

    resultado = pd.DataFrame(datos)

    resultado["Mes_num"] = range(
        1,
        len(resultado) + 1
    )

    return resultado


# ============================================================
# SIDEBAR — NAVEGACIÓN SEGÚN EL USUARIO
# admin: todas las páginas. inventarios: solo las de análisis.
# ============================================================

ICONOS_PAGINA = {
    "Resumen e inventario": "▣",
    "Evolución": "↗",
    "Riesgos y detalle": "⚠",
    "Órdenes de compra": "▤",
    "Conciliación mensual": "⇄",
    "Actualizar Kardex": "⟳",
}

SUBTITULOS_PAGINA = {
    "Resumen e inventario": "Estado actual del inventario: valor, antigüedad y concentración por área, bodega y artículo.",
    "Evolución": "Entradas, salidas y stock de cierre mes a mes.",
    "Riesgos y detalle": "Inventario con antigüedad mayor a 12 meses y detalle por registro.",
    "Órdenes de compra": "Cantidades solicitadas frente al inventario consolidado, el consumo reciente y la cobertura.",
}

# Si la sesión trae una página que el usuario no puede ver (p. ej. tras
# cambiar de usuario), se vuelve a la primera permitida.
if st.session_state.get("pagina_navegacion") not in PAGINAS_PERMITIDAS:
    st.session_state["pagina_navegacion"] = PAGINAS_PERMITIDAS[0]

with st.sidebar:

    st.markdown(
        """
        <div class="sidebar-brand">
            <div class="brand-mark">AL</div>
            <div>
                <div class="brand-title">Inventarios ALDC</div>
                <div class="brand-subtitle">Área Limpia D.C. S.A.S. E.S.P.</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="sidebar-section-title">ANÁLISIS</div>',
        unsafe_allow_html=True
    )

    pagina = st.radio(
        "Navegación",
        PAGINAS_PERMITIDAS,
        format_func=lambda p: f"{ICONOS_PAGINA.get(p, '•')}   {p}",
        label_visibility="collapsed",
        key="pagina_navegacion"
    )

    st.markdown(
        '<div class="sidebar-section-title">SESIÓN</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        f"""
        <div class="sidebar-user">
            <div class="sidebar-user-name">{ui._e(USUARIO)}</div>
            <div class="sidebar-user-role">{"Administrador" if ES_ADMIN else "Consulta"}</div>
            <div class="sidebar-user-status">● Sesión activa</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if st.button(
        "Cerrar sesión",
        use_container_width=True
    ):

        for _clave in list(st.session_state.keys()):
            st.session_state.pop(_clave, None)

        st.session_state["autenticado"] = False

        st.rerun()

    st.markdown(
        f"""
        <div style="margin-top:2rem; padding-top:0.9rem; border-top:1px solid rgba(255,255,255,0.13);">
            <div style="color:#AFC1D7;font-size:0.72rem;line-height:1.55;">
                Corte de datos: {ui._e(ESQ["corte"])}<br>
                Sistema de análisis de inventarios
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

# Segunda barrera: la página elegida debe estar permitida.
if pagina not in PAGINAS_PERMITIDAS:
    st.error("No tienes acceso a esta página.")
    st.stop()


# ============================================================
# PÁGINAS DE ADMINISTRACIÓN
# (se muestran solas, sin filtros del tablero; cada una vuelve a
#  verificar el permiso del usuario de la sesión)
# ============================================================

if pagina == "Actualizar Kardex":

    pagina_actualizar_kardex(
        st,
        USUARIO,
        ARCHIVO_ACTUALIZADO,
        ARCHIVO_HISTORICO
    )

    st.stop()

if pagina == "Conciliación mensual":

    conciliacion.pagina_conciliacion(st, df, BASE_DIR)

    st.stop()


# ============================================================
# ENCABEZADO DE LA PÁGINA
# ============================================================

ui.encabezado_pagina(
    st,
    pagina,
    SUBTITULOS_PAGINA.get(pagina, ""),
    eyebrow="Inventarios ALDC",
    pills=[
        (f"Corte: {ESQ['corte']}", "accent"),
        (f"Indicadores: {PERIODO_ANALISIS}" if PERIODO_ANALISIS else "", "primary"),
    ],
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

CLAVES_FILTROS = ("f_area", "f_bodega", "f_articulo", "f_antiguedad")


def restablecer_filtros():
    for clave in CLAVES_FILTROS:
        st.session_state.pop(clave, None)


def opciones_filtro(clave, opciones):
    """Descarta una selección guardada que ya no está entre las opciones."""
    if clave in st.session_state and st.session_state[clave] not in opciones:
        st.session_state.pop(clave, None)
    return opciones


# Las páginas de análisis usan filtros; Órdenes de compra trabaja con
# la base completa y no los muestra.
MOSTRAR_FILTROS = pagina in acceso.PAGINAS_CONSULTA

contenedor_filtros = (
    st.container(border=True)
    if MOSTRAR_FILTROS
    else st.empty().container()
)

with contenedor_filtros:

    if MOSTRAR_FILTROS:

        cab1, cab2 = st.columns([4, 1])

        with cab1:
            st.markdown(
                """
                <div class="filter-title">Filtros del informe</div>
                <div class="filter-subtitle">Los indicadores y análisis se actualizan según la selección.</div>
                """,
                unsafe_allow_html=True
            )

        with cab2:
            st.button(
                "Restablecer filtros",
                on_click=restablecer_filtros,
                use_container_width=True,
                key="btn_restablecer_filtros"
            )

    col1, col2, col3, col4 = (
        st.columns(4) if MOSTRAR_FILTROS else (st.empty(),) * 4
    )

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

        area_seleccionada = (
            st.selectbox("Área", opciones_filtro("f_area", ["Todas"] + areas), key="f_area")
            if MOSTRAR_FILTROS else "Todas"
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

        bodega_seleccionada = (
            st.selectbox("Bodega", opciones_filtro("f_bodega", ["Todas"] + bodegas), key="f_bodega")
            if MOSTRAR_FILTROS else "Todas"
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

        articulo_seleccionado = (
            st.selectbox("Artículo", opciones_filtro("f_articulo", ["Todos"] + articulos), key="f_articulo")
            if MOSTRAR_FILTROS else "Todos"
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

        antiguedad_seleccionada = (
            st.selectbox("Antigüedad", opciones_filtro("f_antiguedad", ["Todas"] + antiguedades), key="f_antiguedad")
            if MOSTRAR_FILTROS else "Todas"
        )

    df_filtrado = df_articulo.copy()

    if antiguedad_seleccionada != "Todas":

        df_filtrado = df_filtrado[
            df_filtrado[COL_ANTIGUEDAD]
            .astype(str)
            == antiguedad_seleccionada
        ]

    if MOSTRAR_FILTROS:
        st.markdown(
            f'<div class="filter-records">Registros analizados: {formato_entero(len(df_filtrado))}</div>',
            unsafe_allow_html=True
        )


# ============================================================
# BASE DE LOS INDICADORES DE VALOR
#
# Todo artículo recibe una categoría de antigüedad, aunque tenga
# stock 0 al corte (por ejemplo "Entre 0 y 3 meses" si su inventario
# promedio y su CMV son cero). Por eso el stock, el valor, los
# porcentajes, los conteos y las alertas se calculan SOLO con los
# registros que tienen inventario al corte (stock > 0). Así el
# numerador y el denominador de cada porcentaje usan la misma base
# (corrección H-09). Rotación y días usan todos los registros del
# filtro, porque también miden lo que ya salió.
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

_, _, rotacion, dias_promedio = kpis_corte(
    df_filtrado,
    ESQ
)

stock_total = suma_columna(df_con_stock, COL_STOCK)
valor_total = suma_columna(df_con_stock, COL_COSTE)

# Base única de todos los porcentajes de valor mostrados
valor_total_col = valor_total

# Registros fuera de la base: sin stock al corte pero con valor
# (costos residuales heredados o stocks negativos).
if COL_STOCK in df_filtrado.columns and COL_COSTE in df_filtrado.columns:
    _fuera = df_filtrado[
        (df_filtrado[COL_STOCK].fillna(0) <= EPS)
        & (df_filtrado[COL_COSTE].fillna(0).abs() > 0.5)
    ]
else:
    _fuera = df_filtrado.iloc[0:0]

NOTA_BASE_VALOR = (
    f"Valores calculados sobre {formato_entero(len(df_con_stock))} registros con "
    f"stock al corte {ESQ['corte']}."
    + (
        f" Se excluyen {formato_entero(len(_fuera))} registros sin stock que "
        f"conservan valor ({formato_moneda(suma_columna(_fuera, COL_COSTE))}); "
        "revísalos en Riesgos y detalle."
        if len(_fuera)
        else ""
    )
)


# ============================================================
# PÁGINA 1
# RESUMEN E INVENTARIO
# ============================================================

if pagina in ("Resumen", "Resumen e inventario"):

    ui.seccion(
        st,
        "Resumen ejecutivo",
        "Lectura estratégica del estado actual del inventario."
        + (
            f" Antigüedad según días de rotación (inventario promedio ÷ CMV "
            f"× 360, meses de 30 días) del período {PERIODO_ANALISIS}."
            if PERIODO_ANALISIS else ""
        ),
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

    ui.fila_kpis(st, [
        ("Stock actual", formato_numero(stock_total),
         f"unidades al corte {ESQ['corte']}", "azul"),
        ("Valor del inventario", formato_moneda(valor_total),
         f"{formato_entero(len(df_con_stock))} registros con stock", "oscuro"),
        ("Días de inventario", formato_numero(dias_promedio, 1),
         f"rotación {formato_numero(rotacion)} veces en 12 meses", "azul"),
        ("Valor mayor a 12 meses", formato_moneda(valor_mayor_12),
         f"{porcentaje_envejecido:.1f}% del valor del inventario", "naranja"),
    ])

    st.caption(NOTA_BASE_VALOR)

    # --------------------------------------------------------
    # LECTURA AUTOMÁTICA
    # --------------------------------------------------------

    hay_meses = len(df_mensual) > 0

    mes_mayor_entrada = (
        df_mensual.loc[df_mensual["Entradas"].idxmax(), "Mes"] if hay_meses else "-"
    )
    mayor_entrada = df_mensual["Entradas"].max() if hay_meses else 0

    mes_mayor_neto = (
        df_mensual.loc[df_mensual["Neto"].idxmax(), "Mes"] if hay_meses else "-"
    )
    mayor_neto = df_mensual["Neto"].max() if hay_meses else 0

    ui.seccion(st, "¿Qué está ocurriendo?")

    ui.fila_kpis(st, [
        (f"Mayor entrada · {mes_mayor_entrada}", formato_numero(mayor_entrada),
         "mes con más unidades ingresadas", "azul"),
        (f"Mayor acumulación · {mes_mayor_neto}", formato_numero(mayor_neto),
         "mayor incremento neto del stock", "azul"),
        ("Inventario envejecido", f"{porcentaje_envejecido:.1f}%",
         "del valor tiene más de 12 meses", "naranja"),
    ])

    # --------------------------------------------------------
    # DISTRIBUCIÓN ESTRATÉGICA
    # --------------------------------------------------------

    ui.seccion(st, "¿Dónde está concentrado el inventario?")

    col_a, col_b = st.columns([1.1, 1])

    with col_a:

        resumen_area = (
            df_con_stock
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
                title="Valor del inventario por antigüedad",
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

    ui.seccion(
        st,
        "Inventario",
        "Concentración del inventario y principales componentes del valor.",
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

    ui.fila_kpis(st, [
        ("Artículos con stock", formato_entero(numero_articulos),
         "referencias distintas al corte", "azul"),
        ("Bodegas", formato_entero(numero_bodegas), "con inventario al corte", "azul"),
        ("Valor promedio por artículo", formato_moneda(valor_promedio_articulo),
         "valor del inventario ÷ artículos", "oscuro"),
    ])

    # --------------------------------------------------------
    # TOP ARTÍCULOS
    # --------------------------------------------------------

    ui.seccion(st, "¿Qué artículos explican el valor?")

    if (
        "Articulo" in df_con_stock.columns
        and COL_COSTE in df_con_stock.columns
        and len(df_con_stock) > 0
    ):

        top_articulos = (
            df_con_stock
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

    ui.seccion(
        st,
        "¿Dónde se concentra el inventario envejecido?",
        "Valor del inventario con stock al corte, por área y rango de antigüedad.",
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

    ui.seccion(st, "Concentración por bodega")

    resumen_bodega = (
        df_con_stock
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

    ui.seccion(
        st,
        "Comportamiento del periodo",
        "Relación entre entradas, salidas, acumulación y trayectoria del inventario.",
    )

    # --------------------------------------------------------
    # KPIs DEL PERIODO
    # --------------------------------------------------------

    if antiguedad_seleccionada != "Todas":
        st.info(
            "La antigüedad se calcula con el corte actual: la serie mensual "
            "muestra el histórico de los registros que hoy pertenecen a ese rango."
        )

    hay_meses = len(df_mensual) > 0

    total_entradas = df_mensual["Entradas"].sum()
    total_salidas = df_mensual["Salidas"].sum()
    neto_periodo = total_entradas - total_salidas

    mes_mayor_stock = (
        df_mensual.loc[df_mensual["Stock de cierre"].idxmax(), "Mes"]
        if hay_meses else "-"
    )
    stock_mayor = df_mensual["Stock de cierre"].max() if hay_meses else 0

    ui.fila_kpis(st, [
        ("Entradas acumuladas", formato_numero(total_entradas),
         f"{len(df_mensual)} meses", "verde"),
        ("Salidas acumuladas", formato_numero(total_salidas),
         "unidades despachadas", "rojo"),
        ("Neto del periodo", formato_numero(neto_periodo),
         "entradas − salidas", "azul"),
        ("Mayor stock de cierre", formato_numero(stock_mayor),
         mes_mayor_stock, "oscuro"),
    ])

    # --------------------------------------------------------
    # GRÁFICO PRINCIPAL
    # --------------------------------------------------------

    ui.seccion(
        st,
        "Entradas y salidas mensuales vs. stock de cierre",
        "Barras: entradas (arriba) y salidas (abajo). Línea: stock de cierre de cada mes.",
    )

    fig_evolucion = go.Figure()

    # --------------------------------------------------------
    # UMBRALES ANALÍTICOS
    # Meses "críticos": entradas y stock de cierre en el cuartil
    # superior del periodo (percentil 75).
    # CORRECCIÓN H-01: la definición de df_marcados se había comentado
    # junto con las marcas del gráfico, pero las tablas de abajo la
    # usan y la página fallaba (NameError). Se restituye la definición;
    # las marcas sobre el gráfico siguen desactivadas.
    # --------------------------------------------------------

    umbral_entrada = df_mensual["Entradas"].quantile(0.75)
    umbral_stock = df_mensual["Stock de cierre"].quantile(0.75)

    df_marcados = df_mensual[
        (df_mensual["Entradas"] >= umbral_entrada)
        & (df_mensual["Stock de cierre"] >= umbral_stock)
        & (df_mensual["Entradas"] > 0)
    ].copy()

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
                "Inventario inicial: %{customdata[0]:,.2f}<br>"
                "Entradas: %{customdata[1]:,.2f}<br>"
                "Salidas: %{customdata[2]:,.2f}<br>"
                "Inventario final: %{customdata[3]:,.2f}"
                "<extra></extra>"
            )
        )
    )

    # --------------------------------------------------------
    # IDENTIFICAR COINCIDENCIAS
    # ENTRADA ALTA + STOCK ALTO
    # --------------------------------------------------------

    # df_marcados = df_mensual[
    #     (df_mensual["Entradas"] >= umbral_entrada)
    #     & (df_mensual["Stock de cierre"] >= umbral_stock)
    # ].copy()

    # if len(df_marcados) > 0:

    #     fig_evolucion.add_trace(
    #         go.Scatter(
    #             x=df_marcados["Mes"],
    #             y=df_marcados["Stock de cierre"],
    #             name="Entrada alta + stock alto",
    #             mode="markers",
    #             yaxis="y2",
    #             marker=dict(
    #                 size=17,
    #                 symbol="diamond",
    #                 color=AZUL,
    #                 line=dict(
    #                     width=2,
    #                     color="white"
    #                 )
    #             ),
    #             customdata=df_marcados[
    #                 [
    #                     "Entradas",
    #                     "Salidas",
    #                     "Neto"
    #                 ]
    #             ],
    #             hovertemplate=(
    #                 "<b>%{x}</b><br>"
    #                 "⚠️ <b>Entrada alta + stock alto</b><br>"
    #                 "📦 Stock: %{y:,.2f}<br>"
    #                 "📥 Entradas: %{customdata[0]:,.2f}<br>"
    #                 "📤 Salidas: %{customdata[1]:,.2f}<br>"
    #                 "📊 Neto: %{customdata[2]:,.2f}"
    #                 "<extra></extra>"
    #             )
    #         )
    #     )

    # --------------------------------------------------------
    # ZONA DE STOCK ALTO
    # --------------------------------------------------------

    # fig_evolucion.add_hrect(
    #     y0=umbral_stock,
    #     y1=stock_max * 1.05,
    #     yref="y2",
    #     fillcolor=AZUL,
    #     opacity=0.08,
    #     line_width=0,
    #     layer="below"
    # )

    # --------------------------------------------------------
    # LÍNEA DE UMBRAL DE STOCK ALTO
    # --------------------------------------------------------

    # fig_evolucion.add_shape(
    #     type="line",
    #     x0=0,
    #     x1=1,
    #     xref="paper",
    #     y0=umbral_stock,
    #     y1=umbral_stock,
    #     yref="y2",
    #     line=dict(
    #         color=AZUL,
    #         width=1.5,
    #         dash="dash"
    #     )
    # )

    # --------------------------------------------------------
    # CONFIGURACIÓN
    # --------------------------------------------------------

    fig_evolucion.update_layout(
        height=610,
        barmode="relative",


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

    ui.seccion(st, "Referencias con mayor impacto económico")

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
                            "Valor entradas críticas",
                            format="$%,.0f"
                        ),

                    "Valor inventario actual":
                        st.column_config.NumberColumn(
                            "Valor inventario actual",
                            format="$%,.0f"
                        ),

                    "Participación":
                        st.column_config.NumberColumn(
                            "Participación",
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

    ui.seccion(st, "Lectura analítica de los movimientos")

    if len(df_mensual) > 0:

        coincidencias = df_marcados

        if len(coincidencias) > 0:

            st.warning(
                "Se identificaron meses en los que "
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
            title="Rotación mensual (salidas ÷ inventario inicial del mes)",
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

    ui.seccion(
        st,
        "Inventario con más de 12 meses",
        "Priorización de inventarios que requieren revisión (solo registros con stock al corte).",
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

    ui.fila_kpis(st, [
        ("Registros mayores a 12 meses", formato_entero(cantidad_alertas),
         "bodega + referencia con stock", "naranja"),
        ("Stock involucrado", formato_numero(stock_alerta), "unidades", "azul"),
        ("Valor comprometido", formato_moneda(valor_alerta),
         "valor al corte", "oscuro"),
        ("Participación", f"{participacion_alerta:.1f}%",
         "del valor total del inventario", "naranja"),
    ])

    st.caption(NOTA_BASE_VALOR)

    # --------------------------------------------------------
    # TOP RIESGOS
    # --------------------------------------------------------

    ui.seccion(st, "Principales inventarios a revisar")

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

    ui.seccion(
        st,
        "Detalle de registros",
        "Indicadores que explican la antigüedad: inventario promedio, CMV, rotación y días.",
    )

    d1, d2 = st.columns([1.3, 1])

    with d1:
        vista_detalle = st.radio(
            "Registros",
            ["Con stock al corte", "Sin stock que conservan valor", "Todos"],
            horizontal=True,
            key="riesgos_vista_detalle"
        )

    with d2:
        buscar_detalle = st.text_input(
            "Buscar código o artículo",
            key="riesgos_buscar"
        )

    if vista_detalle == "Con stock al corte":
        base_detalle = df_con_stock
    elif vista_detalle == "Sin stock que conservan valor":
        base_detalle = _fuera
    else:
        base_detalle = df_filtrado

    if buscar_detalle.strip():
        _b = buscar_detalle.strip().upper()
        _mascara = pd.Series(False, index=base_detalle.index)
        for _c in ("Codigo Articulo", "Articulo"):
            if _c in base_detalle.columns:
                _mascara |= base_detalle[_c].astype(str).str.upper().str.contains(_b, regex=False)
        base_detalle = base_detalle[_mascara]

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
            and columna in base_detalle.columns
            and columna not in columnas_disponibles
        ):
            columnas_disponibles.append(columna)

    df_detalle = base_detalle[
        columnas_disponibles
    ].copy()

    st.caption(f"{formato_entero(len(df_detalle))} registros")

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
        label="Descargar detalle en CSV",
        data=csv,
        file_name="detalle_inventarios_aldc.csv",
        mime="text/csv"
    )





# ============================================================
# PÁGINA: ÓRDENES DE COMPRA
#
# Reemplaza COMPLETO el bloque anterior, desde
#     elif pagina == "Órdenes de compra":
# hasta justo antes del "# PIE" (st.divider final).
#
# Dependencias que ya existen en app.py (no se tocan):
#   - df               -> base completa de inventario (sin filtros)
#   - COL_STOCK        -> columna de stock del último corte
#   - COL_ANTIGUEDAD   -> columna de antigüedad
#   - pd, st, re, datetime (importados arriba en app.py)
# ============================================================

elif pagina == "Órdenes de compra":

    # Verificación en el momento de ejecutar (no basta con ocultar la página)
    if not acceso.es_admin(acceso.usuario_sesion(st), SECRETOS):
        st.error("Tu usuario no tiene permiso para esta página.")
        st.stop()

    import io
    import html
    import hashlib
    import smtplib
    import ssl
    import unicodedata
    from email.message import EmailMessage

    # ============================================================
    # 0. PARÁMETROS CONFIGURABLES
    # ============================================================

    OC_META_COBERTURA = 4          # meses máximos de cobertura objetivo
    OC_UMBRAL_STOCK_MEDIO = 2      # meses para considerar stock medio/alto
    OC_VENTANA = 6                 # meses de la ventana de consumo
    OC_HISTORICO_MAX = 15          # meses máximos del histórico complementario
    OC_EPS = 1e-9

    # Fragmentos (sin tildes, minúscula) de estados NO activos.
    # Es solo el valor por defecto: el usuario puede cambiarlo en pantalla.
    OC_ESTADOS_NO_ACTIVOS = (
        "anulad", "cancelad", "cerrad",
        "recibid", "finaliz", "completad"
    )

    OC_MESES_ES = {
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
        "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
        "septiembre": 9, "setiembre": 9, "octubre": 10,
        "noviembre": 11, "diciembre": 12
    }

    OC_NOMBRES_MES = [
        "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre",
        "Noviembre", "Diciembre"
    ]

    OC_EDADES_MAYOR_3M = {
        "entre 4 y 6 meses",
        "entre 7 y 12 meses",
        "mayor a 12 meses",
        "mayor de 12 meses",
    }

    # ============================================================
    # 1. FUNCIONES AUXILIARES
    # ============================================================

    def oc_normalizar(texto):
        """Minúscula, sin tildes y solo letras/números."""
        texto = str(texto).strip().lower()
        texto = unicodedata.normalize("NFKD", texto)
        texto = "".join(
            c for c in texto if not unicodedata.combining(c)
        )
        return re.sub(r"[^a-z0-9]", "", texto)

    def oc_buscar_columna(dataframe, candidatos):
        """Busca una columna sin importar tildes, espacios o mayúsculas."""
        mapa = {}
        for columna in dataframe.columns:
            mapa.setdefault(oc_normalizar(columna), columna)

        for candidato in candidatos:
            encontrada = mapa.get(oc_normalizar(candidato))
            if encontrada is not None:
                return encontrada

        return None

    def oc_numero(valor):
        """Convierte un valor (número o texto) a float con las mismas
        reglas que el motor del Kardex (motor_lifo._a_float)."""
        resultado = a_numero(pd.Series([valor], dtype=object)).iloc[0]
        return float(resultado)

    def oc_serie_numerica(serie):
        """Serie -> float. Rápido si ya es numérica."""
        return a_numero(serie)

    def oc_normalizar_referencia(valor):
        """Normaliza códigos sin convertirlos a número."""

        if not isinstance(valor, str) and pd.isna(valor):
            return ""

        if isinstance(valor, float) and valor.is_integer():
            valor = int(valor)

        texto = str(valor).strip()
        texto = re.sub(r"\.0+$", "", texto)

        if texto.lower() in {"", "nan", "none", "null"}:
            return ""

        return texto.upper()

    def oc_identificar_mes(columna):
        """
        Reconoce 'SALIDA JUNIO 2025', 'SALIDA AGOSTO 2026', etc.
        Un encabezado duplicado que pandas renombró
        ('SALIDA JUNIO 2025.1') se marca como duplicado.
        Las columnas 'COSTO SALIDA ...' NO coinciden.
        """

        texto = oc_normalizar(columna)

        coincidencia = re.fullmatch(
            r"salida([a-z]+)(20\d{2})(\d*)",
            texto
        )

        if not coincidencia:
            return None

        mes = OC_MESES_ES.get(coincidencia.group(1))

        if mes is None:
            return None

        anio = int(coincidencia.group(2))

        return {
            "columna": columna,
            "anio": anio,
            "mes": mes,
            "periodo": anio * 12 + mes,
            "etiqueta": f"{OC_NOMBRES_MES[mes - 1]} {anio}",
            "duplicado": coincidencia.group(3) != ""
        }

    def oc_son_consecutivos(meses):
        """True si los periodos de la lista son consecutivos."""
        periodos = sorted(m["periodo"] for m in meses)
        return all(
            periodos[i] - periodos[i - 1] == 1
            for i in range(1, len(periodos))
        )

    def oc_es_critico(valor):
        return oc_normalizar(valor) in {
            "si", "s", "true", "1",
            "critico", "alta", "alto", "prioritario"
        }

    def oc_estado_no_activo(estado):
        n = oc_normalizar(estado)
        return any(p in n for p in OC_ESTADOS_NO_ACTIVOS)

    # ============================================================
    # 2. ENCABEZADO Y CARGA DEL ARCHIVO
    # ============================================================

    st.info(
        "La evaluación usa los seis meses calendario más recientes "
        "disponibles en el histórico. El stock se consolida por "
        "referencia sumando todas las bodegas. Las alertas son "
        "preventivas: no bloquean ni autorizan una compra."
    )

    archivo_ordenes = st.file_uploader(
        "Cargar archivo de órdenes de compra",
        type=["xlsx", "xls", "csv"],
        key="archivo_ordenes_compra"
    )

    if archivo_ordenes is None:

        st.warning(
            "Carga el archivo de órdenes para ejecutar el análisis."
        )
        st.stop()

    # ------------------------------------------------------------
    # Leer el archivo
    # ------------------------------------------------------------

    try:

        contenido_archivo = archivo_ordenes.getvalue()

        if archivo_ordenes.name.lower().endswith(".csv"):

            try:
                df_ordenes_original = pd.read_csv(
                    io.BytesIO(contenido_archivo),
                    sep=None,
                    engine="python",
                    encoding="utf-8-sig"
                )
            except UnicodeDecodeError:
                df_ordenes_original = pd.read_csv(
                    io.BytesIO(contenido_archivo),
                    sep=None,
                    engine="python",
                    encoding="latin-1"
                )

        else:
            df_ordenes_original = pd.read_excel(
                io.BytesIO(contenido_archivo)
            )

    except Exception as error:

        st.error(f"No fue posible leer el archivo: {error}")
        st.stop()

    if df_ordenes_original.empty:

        st.error("El archivo de órdenes no contiene registros.")
        st.stop()

    df_ordenes_original = df_ordenes_original.reset_index(drop=True)

    # ============================================================
    # 3. IDENTIFICAR COLUMNAS DE LAS ÓRDENES
    # ============================================================

    col_orden = oc_buscar_columna(
        df_ordenes_original,
        [
            "IdOrden", "ID Orden", "Id Orden", "Orden",
            "Número de orden", "Numero de orden"
        ]
    )

    # Se prefiere el código de artículo; "Id Articulo" solo si no hay otro.
    col_referencia_oc = oc_buscar_columna(
        df_ordenes_original,
        [
            "Cod Articulo", "Código Artículo", "Codigo Articulo",
            "Código de artículo", "Codigo de articulo",
            "Id Articulo", "Referencia", "Código"
        ]
    )

    col_cantidad_oc = oc_buscar_columna(
        df_ordenes_original,
        ["Cantidad", "Cantidad solicitada", "Cantidad ordenada"]
    )

    col_estado_oc = oc_buscar_columna(
        df_ordenes_original,
        ["Estado", "Estado Orden", "Estado de la orden"]
    )

    col_grupo_oc = oc_buscar_columna(
        df_ordenes_original, ["Grupo"]
    )

    col_req_oc = oc_buscar_columna(
        df_ordenes_original,
        ["Req", "Requisición", "Requisicion"]
    )

    col_fecha_oc = oc_buscar_columna(
        df_ordenes_original,
        ["Fecha", "Fecha Orden", "Fecha de orden"]
    )

    columnas_faltantes = []

    if col_orden is None:
        columnas_faltantes.append("IdOrden")

    if col_referencia_oc is None:
        columnas_faltantes.append("Cod Articulo o Id Articulo")

    if col_cantidad_oc is None:
        columnas_faltantes.append("Cantidad")

    if columnas_faltantes:

        st.error(
            "Faltan columnas obligatorias: "
            + ", ".join(columnas_faltantes)
        )
        st.write(
            "Columnas encontradas en el archivo:",
            list(df_ordenes_original.columns)
        )
        st.stop()

    # ============================================================
    # 4. PREPARAR LAS ÓRDENES
    # ============================================================

    oc_base = pd.DataFrame({
        "_orden_oc": (
            df_ordenes_original[col_orden]
            .fillna("").astype(str).str.strip()
        ),
        "_ref_oc": (
            df_ordenes_original[col_referencia_oc]
            .apply(oc_normalizar_referencia)
        ),
        "_cantidad_oc": (
            df_ordenes_original[col_cantidad_oc]
            .apply(oc_numero)
        ),
    })

    if col_estado_oc is not None:

        oc_base["_estado_oc"] = (
            df_ordenes_original[col_estado_oc]
            .fillna("").astype(str).str.strip()
            .replace("", "Sin estado informado")
        )

    else:

        oc_base["_estado_oc"] = "Sin estado informado"

    if col_grupo_oc is not None:
        oc_base["Grupo"] = df_ordenes_original[col_grupo_oc]

    if col_req_oc is not None:
        oc_base["Req"] = df_ordenes_original[col_req_oc]

    if col_fecha_oc is not None:

        _fechas = pd.to_datetime(
            df_ordenes_original[col_fecha_oc],
            errors="coerce",
            dayfirst=True
        )

        if _fechas.notna().mean() >= 0.5:
            oc_base["Fecha"] = _fechas.dt.date
        else:
            oc_base["Fecha"] = (
                df_ordenes_original[col_fecha_oc].astype(str)
            )

    # ------------------------------------------------------------
    # Estados: configurables. Los desconocidos se tratan como ACTIVOS.
    # ------------------------------------------------------------
    estados_detectados = sorted(
    oc_base["_estado_oc"].unique().tolist()
)

    estados_por_defecto = [
        "[4] - Cerrada",
        "[5] - Aprobada",
        "[8] - Anulada",
        "[1] - Creada",
        "[6] - EnTransito",
        "[7] - EnTransito_EntradaParcial"
    ]
    
    estados_excluidos = st.multiselect(
        "Estados que NO se consideran pendientes de compra",
        options=estados_detectados,
        default=[
            estado for estado in estados_por_defecto
            if estado in estados_detectados
        ],
        key="oc_estados_excluidos"
    )
    
    # CORRECCIÓN H-07: el texto listaba como activos estados que la
    # lista por defecto excluye. Ahora se calcula a partir de la
    # selección real del usuario.
    estados_activos = [
        e for e in estados_detectados if e not in estados_excluidos
    ]

    st.caption(
        "Se analizan: "
        + (", ".join(estados_activos) or "ningún estado")
        + ". Cualquier estado que no excluyas aquí se analiza."
    )
    
    oc = oc_base[
        ~oc_base["_estado_oc"].isin(estados_excluidos)
    ].copy()
    
    oc = oc[
        (oc["_orden_oc"] != "")
        & (oc["_ref_oc"] != "")
        & (oc["_cantidad_oc"] > 0)
    ].copy()
    if oc.empty:

        st.warning(
            "No hay órdenes activas con referencias y cantidades "
            "válidas para analizar."
        )
        st.stop()

    # Consolidar renglones repetidos de la misma orden y referencia.
    agregaciones = {
        "_cantidad_oc": "sum",
        "_estado_oc": "first"
    }

    for columna in ["Grupo", "Req", "Fecha"]:
        if columna in oc.columns:
            agregaciones[columna] = "first"

    oc = (
        oc.groupby(
            ["_orden_oc", "_ref_oc"],
            as_index=False,
            dropna=False
        )
        .agg(agregaciones)
    )

    # Pendiente total por referencia (todas las órdenes activas)
    pendientes_por_referencia = (
        oc.groupby("_ref_oc", as_index=False)
        .agg(**{
            "Cantidad total pendiente referencia":
                ("_cantidad_oc", "sum")
        })
    )

    # ============================================================
    # 5. PREPARAR EL INVENTARIO (BASE COMPLETA, SIN FILTROS)
    # ============================================================
    # 'df' es la base completa. Los filtros de la interfaz trabajan
    # sobre copias (df_area, df_bodega, df_filtrado), nunca sobre df.

    if "df" not in globals() or not isinstance(df, pd.DataFrame) or df.empty:

        st.error("No se encontró la base de inventario o está vacía.")
        st.stop()

    df_inv = df.reset_index(drop=True)

    col_referencia_inv = oc_buscar_columna(
        df_inv,
        [
            "Codigo Articulo", "Código de artículo",
            "Código Artículo", "Cod Articulo",
            "Id Articulo", "Referencia", "Código"
        ]
    )

    col_stock_inv = (
        COL_STOCK
        if isinstance(COL_STOCK, str) and COL_STOCK in df_inv.columns
        else oc_buscar_columna(
            df_inv,
            ["Stock total", "Stock", "Existencias", "Stock actual"]
        )
    )

    col_articulo_inv = oc_buscar_columna(
        df_inv,
        [
            "Articulo", "Artículo", "Descripción", "Descripcion",
            "Nombre artículo", "Nombre articulo"
        ]
    )

    col_bodega_inv = oc_buscar_columna(
        df_inv, ["Bodega", "Nombre bodega"]
    )

    col_edad_inv = (
        COL_ANTIGUEDAD
        if isinstance(COL_ANTIGUEDAD, str)
        and COL_ANTIGUEDAD in df_inv.columns
        else oc_buscar_columna(
            df_inv,
            [
                "ANTIGUEDAD 12 MESES",
                "ANTIGUEDAD ULTIMO MES DE ACTUALIZACION",
                "Antigüedad", "Antiguedad"
            ]
        )
    )

    col_criticidad_inv = oc_buscar_columna(
        df_inv,
        [
            "Criticidad", "Crítico", "Critico",
            "Artículo crítico", "Articulo critico",
            "Es crítico", "Es critico"
        ]
    )

    if col_referencia_inv is None:

        st.error(
            "No se encontró la columna de referencia "
            "('Codigo Articulo') en el inventario."
        )
        st.stop()

    if col_stock_inv is None:

        st.error(
            "No se encontró la columna de stock del último corte."
        )
        st.stop()

    hist = pd.DataFrame(index=df_inv.index)

    hist["_ref_oc"] = (
        df_inv[col_referencia_inv].apply(oc_normalizar_referencia)
    )

    hist["_stock_oc"] = (
        oc_serie_numerica(df_inv[col_stock_inv]).clip(lower=0)
    )

    hist["_articulo_oc"] = (
        df_inv[col_articulo_inv].fillna("").astype(str)
        if col_articulo_inv is not None else ""
    )

    hist["_bodega_oc"] = (
        df_inv[col_bodega_inv].fillna("").astype(str).str.strip()
        if col_bodega_inv is not None else ""
    )

    hist["_edad_oc"] = (
        df_inv[col_edad_inv].fillna("").astype(str)
        if col_edad_inv is not None else ""
    )

    # Criticidad: solo si existe la columna. Si no, "Sin dato".
    hist["_critico_oc"] = (
        df_inv[col_criticidad_inv].apply(oc_es_critico)
        if col_criticidad_inv is not None else False
    )

    hist = hist[hist["_ref_oc"] != ""].copy()

    # R-07: decisión explícita sobre el stock de la bodega de obsoletos.
    # Por defecto se conserva el comportamiento anterior (se incluye).
    incluir_obsoletos = st.checkbox(
        "Incluir la bodega 44 (OBSOLETOS) en el stock que cubre las órdenes",
        value=True,
        key="oc_incluir_obsoletos",
        help=(
            "Si lo desmarcas, el stock de OBSOLETOS no cuenta como cobertura "
            "y no genera alertas de posible exceso."
        ),
    )

    if not incluir_obsoletos:
        _es_obsoleto = hist["_bodega_oc"].apply(numero_bodega) == "44"
        hist.loc[_es_obsoleto, "_stock_oc"] = 0.0

    if "LLAVE" in df_inv.columns:

        _llaves_rep = int(df_inv["LLAVE"].duplicated().sum())

        if _llaves_rep:
            st.caption(
                f"El inventario tiene {_llaves_rep} filas con LLAVE "
                "repetida. El motor asigna los movimientos a la "
                "primera fila de cada llave, por lo que la suma de "
                "stock y salidas no se duplica."
            )

    # ============================================================
    # 6. IDENTIFICAR DINÁMICAMENTE LOS MESES DISPONIBLES
    # ============================================================

    meses_detectados = [
        m for m in (
            oc_identificar_mes(c) for c in df_inv.columns
        )
        if m is not None
    ]

    columnas_duplicadas = [
        m["columna"] for m in meses_detectados if m["duplicado"]
    ]

    # Un solo registro por periodo (se ignoran duplicados)
    meses_unicos = {}

    for m in meses_detectados:
        if not m["duplicado"]:
            meses_unicos.setdefault(m["periodo"], m)

    meses_disponibles = sorted(
        meses_unicos.values(),
        key=lambda x: x["periodo"]
    )

    if not meses_disponibles:

        st.error(
            "No se encontraron columnas con el formato "
            "'SALIDA MES AÑO' (por ejemplo, 'SALIDA JUNIO 2025')."
        )
        st.stop()

    meses_6 = meses_disponibles[-OC_VENTANA:]
    meses_15 = meses_disponibles[-OC_HISTORICO_MAX:]

    # ============================================================
    # 7. SALIDAS DE LOS ÚLTIMOS 6 MESES Y DEL HISTÓRICO
    # ============================================================
    # Valor absoluto por registro, antes de sumar.

    salidas_mes = {}

    for m in meses_15:

        salidas_mes[m["columna"]] = (
            oc_serie_numerica(df_inv[m["columna"]])
            .abs()
            .loc[hist.index]
        )

    # Un mes con salidas en cero para TODA la base indica
    # una columna vacía o un mes sin cargar.
    meses_sin_datos = [
        m["etiqueta"]
        for m in meses_6
        if salidas_mes[m["columna"]].sum() <= OC_EPS
    ]

    seis_meses_validos = (
        len(meses_6) == OC_VENTANA
        and oc_son_consecutivos(meses_6)
        and not meses_sin_datos
    )

    # ------------------------------------------------------------
    # Periodo de análisis y advertencias
    # ------------------------------------------------------------

    st.subheader("Periodo de análisis")

    if len(meses_6) == OC_VENTANA:

        st.caption(
            "Meses utilizados para el consumo: "
            + " · ".join(m["etiqueta"] for m in meses_6)
        )

    if len(meses_6) < OC_VENTANA:

        st.warning(
            f"El histórico solo tiene {len(meses_6)} meses de salidas. "
            "No se calculará una cobertura definitiva."
        )

    elif not oc_son_consecutivos(meses_6):

        st.warning(
            "Los seis meses más recientes no son consecutivos "
            "(falta algún mes intermedio). Las referencias quedarán "
            "marcadas para validar el histórico."
        )

    if meses_sin_datos:

        st.warning(
            "Estos meses no tienen salidas en ninguna referencia y "
            "podrían estar incompletos: "
            + ", ".join(meses_sin_datos)
            + ". No se presentará la cobertura como definitiva."
        )

    if columnas_duplicadas:

        st.warning(
            "Hay encabezados de salidas duplicados en el histórico "
            "(se ignoraron): " + ", ".join(columnas_duplicadas)
        )

    if len(meses_disponibles) > OC_VENTANA:

        st.caption(
            f"Histórico complementario: {len(meses_15)} meses "
            f"({meses_15[0]['etiqueta']} a {meses_15[-1]['etiqueta']}) "
            "para revisar la ausencia de consumo."
        )

    hist["_salidas_6_oc"] = (
        sum(salidas_mes[m["columna"]] for m in meses_6)
        if meses_6 else 0.0
    )

    hist["_salidas_15_oc"] = (
        sum(salidas_mes[m["columna"]] for m in meses_15)
        if meses_15 else 0.0
    )

    # ============================================================
    # 8. CONSOLIDAR STOCK Y CONSUMO POR REFERENCIA
    # ============================================================

    hist["_stock_mas_3m_oc"] = 0.0

    if col_edad_inv is not None:

        mascara_edad = (
            hist["_edad_oc"]
            .apply(oc_normalizar)
            .isin({oc_normalizar(x) for x in OC_EDADES_MAYOR_3M})
        )

        hist.loc[mascara_edad, "_stock_mas_3m_oc"] = (
            hist.loc[mascara_edad, "_stock_oc"]
        )

    # Solo se listan las bodegas que realmente tienen stock
    hist["_bodega_con_stock"] = hist["_bodega_oc"].where(
        hist["_stock_oc"] > OC_EPS, ""
    )

    stock_por_referencia = (
        hist.groupby("_ref_oc", as_index=False)
        .agg(**{
            "Stock consolidado": ("_stock_oc", "sum"),
            "Stock con antigüedad mayor a 3 meses":
                ("_stock_mas_3m_oc", "sum"),
            "Salidas últimos 6 meses": ("_salidas_6_oc", "sum"),
            "Salidas histórico disponible": ("_salidas_15_oc", "sum"),
            "Artículo": ("_articulo_oc", "first"),
            "Bodegas": (
                "_bodega_con_stock",
                lambda v: ", ".join(
                    sorted({str(x).strip() for x in v if str(x).strip()})
                )
            ),
            "Artículo crítico": ("_critico_oc", "max"),
        })
    )

    # El promedio solo existe con 6 meses válidos y consecutivos
    if seis_meses_validos:

        stock_por_referencia["Promedio salidas mensual"] = (
            stock_por_referencia["Salidas últimos 6 meses"] / OC_VENTANA
        )

    else:

        stock_por_referencia["Promedio salidas mensual"] = 0.0

    # ============================================================
    # 9. CRUZAR ÓRDENES CON INVENTARIO
    # ============================================================

    analisis = (
        oc.merge(stock_por_referencia, on="_ref_oc", how="left")
        .merge(pendientes_por_referencia, on="_ref_oc", how="left")
    )

    analisis["Existe en inventario"] = (
        analisis["Stock consolidado"].notna()
    )

    for columna in [
        "Stock consolidado",
        "Stock con antigüedad mayor a 3 meses",
        "Salidas últimos 6 meses",
        "Salidas histórico disponible",
        "Promedio salidas mensual",
        "Cantidad total pendiente referencia"
    ]:

        analisis[columna] = (
            pd.to_numeric(analisis[columna], errors="coerce")
            .fillna(0)
        )

    analisis["Artículo"] = analisis["Artículo"].fillna("")
    analisis["Bodegas"] = analisis["Bodegas"].fillna("")

    analisis["Artículo crítico"] = (
        analisis["Artículo crítico"].fillna(False).astype(bool)
    )

    # ============================================================
    # 10. COBERTURA Y ESTADO DE LA COMPRA
    # ============================================================

    def oc_evaluar_fila(fila):

        stock = fila["Stock consolidado"]
        promedio = fila["Promedio salidas mensual"]
        cantidad_orden = fila["_cantidad_oc"]
        pendientes = fila["Cantidad total pendiente referencia"]
        salidas_6 = fila["Salidas últimos 6 meses"]
        salidas_hist = fila["Salidas histórico disponible"]
        critico = fila["Artículo crítico"]
        existe = fila["Existe en inventario"]

        resultado = {
            "Stock proyectado": stock + pendientes,
            "Cobertura actual (meses)": None,
            "Cobertura proyectada (meses)": None,
            "Porcentaje orden sobre stock": None,
            "Estado análisis": "",
            "Motivo de revisión": ""
        }

        # Caso E: datos insuficientes


        if not seis_meses_validos:

            resultado["Estado análisis"] = "VALIDAR HISTÓRICO"
            resultado["Motivo de revisión"] = (
                "No hay seis meses completos y consecutivos en el "
                "histórico; la cobertura no puede ser definitiva."
            )
            return pd.Series(resultado)

        # Caso D: sin salidas en los últimos seis meses
        if promedio <= 0 or salidas_6 <= 0:

            if critico:

                resultado["Estado análisis"] = (
                    "VALIDACIÓN MANUAL: ARTÍCULO CRÍTICO"
                )
                resultado["Motivo de revisión"] = (
                    "Artículo crítico sin salidas en los últimos seis "
                    "meses. Validar necesidad y programación de la compra."
                )

            elif salidas_hist <= 0:

                resultado["Estado análisis"] = (
                    "VALIDAR COMPRA: SIN SALIDAS HISTÓRICAS"
                )
                resultado["Motivo de revisión"] = (
                    "No registra salidas en el histórico disponible. "
                    "Confirmar si la compra es necesaria o si responde "
                    "a una necesidad operativa programada."
                )

            else:

                resultado["Estado análisis"] = (
                    "VALIDAR: SIN SALIDAS RECIENTES"
                )
                resultado["Motivo de revisión"] = (
                    "Sin salidas en los últimos seis meses, pero sí en "
                    "meses anteriores. Revisar si es consumo ocasional, "
                    "estacional o programado."
                )

            return pd.Series(resultado)

        # Casos A, B y C
        cobertura_actual = stock / promedio
        cobertura_proyectada = (stock + pendientes) / promedio

        resultado["Cobertura actual (meses)"] = cobertura_actual
        resultado["Cobertura proyectada (meses)"] = cobertura_proyectada
        resultado["Porcentaje orden sobre stock"] = (
            cantidad_orden / stock * 100 if stock > 0 else None
        )

        if cobertura_proyectada > OC_META_COBERTURA:

            if cobertura_actual >= OC_UMBRAL_STOCK_MEDIO:

                resultado["Estado análisis"] = "REVISAR POSIBLE EXCESO"
                resultado["Motivo de revisión"] = (
                    "La existencia actual ya cubre al menos "
                    f"{OC_UMBRAL_STOCK_MEDIO} meses de consumo y la "
                    "compra llevaría la cobertura por encima del "
                    f"objetivo de {OC_META_COBERTURA} meses."
                )

            else:

                resultado["Estado análisis"] = (
                    "REVISAR CANTIDAD SOLICITADA"
                )
                resultado["Motivo de revisión"] = (
                    "La compra proyectaría una cobertura superior a "
                    f"{OC_META_COBERTURA} meses. Revisar la cantidad "
                    "solicitada frente al consumo esperado."
                )

        else:

            resultado["Estado análisis"] = "SIN ALERTA POR COBERTURA"
            resultado["Motivo de revisión"] = (
                "La cobertura proyectada no supera "
                f"{OC_META_COBERTURA} meses (no implica aprobación "
                "automática de la compra)."
            )

        return pd.Series(resultado)

    resultados_evaluacion = analisis.apply(oc_evaluar_fila, axis=1)

    analisis = pd.concat(
        [
            analisis.reset_index(drop=True),
            resultados_evaluacion.reset_index(drop=True)
        ],
        axis=1
    )

    # ============================================================
    # 11. TABLA DE RESULTADOS
    # ============================================================

    analisis["_critico_txt"] = (
        analisis["Artículo crítico"].map({True: "Sí", False: "No"})
        if col_criticidad_inv is not None
        else "Sin dato"
    )

    mapa_columnas = [
        ("Orden", "_orden_oc"),
        ("Grupo", "Grupo"),
        ("Req", "Req"),
        ("Fecha", "Fecha"),
        ("Referencia", "_ref_oc"),
        ("Artículo", "Artículo"),
        ("Estado de la orden", "_estado_oc"),
        ("Cantidad de esta orden", "_cantidad_oc"),
        ("Cantidad total pendiente referencia",
         "Cantidad total pendiente referencia"),
        ("Stock consolidado", "Stock consolidado"),
        ("Stock con antigüedad mayor a 3 meses",
         "Stock con antigüedad mayor a 3 meses"),
        ("Salidas últimos 6 meses", "Salidas últimos 6 meses"),
        ("Salidas histórico disponible", "Salidas histórico disponible"),
        ("Promedio salidas mensual", "Promedio salidas mensual"),
        ("Stock proyectado", "Stock proyectado"),
        ("Cobertura actual (meses)", "Cobertura actual (meses)"),
        ("Cobertura proyectada (meses)", "Cobertura proyectada (meses)"),
        ("Porcentaje orden sobre stock", "Porcentaje orden sobre stock"),
        ("Artículo crítico", "_critico_txt"),
        ("Bodegas con stock", "Bodegas"),
        ("Estado análisis", "Estado análisis"),
        ("Motivo de revisión", "Motivo de revisión"),
    ]

    analisis_final = pd.DataFrame({
        nombre: analisis[origen]
        for nombre, origen in mapa_columnas
        if origen in analisis.columns
    })

    for columna in [
        "Cobertura actual (meses)",
        "Cobertura proyectada (meses)",
        "Porcentaje orden sobre stock"
    ]:
        analisis_final[columna] = pd.to_numeric(
            analisis_final[columna], errors="coerce"
        )

    prioridad_estados = {
        "VALIDAR HISTÓRICO": 2,
        "VALIDACIÓN MANUAL: ARTÍCULO CRÍTICO": 3,
        "VALIDAR COMPRA: SIN SALIDAS HISTÓRICAS": 4,
        "VALIDAR: SIN SALIDAS RECIENTES": 5,
        "REVISAR POSIBLE EXCESO": 6,
        "REVISAR CANTIDAD SOLICITADA": 7,
        "SIN ALERTA POR COBERTURA": 8
    }

    analisis_final["_prioridad"] = (
        analisis_final["Estado análisis"]
        .map(prioridad_estados)
        .fillna(99)
    )

    analisis_final = (
        analisis_final
        .sort_values(
            by=["_prioridad", "Cobertura proyectada (meses)"],
            ascending=[True, False],
            na_position="last"
        )
        .drop(columns=["_prioridad"])
        .reset_index(drop=True)
    )

    alertas_oc = analisis_final[
        analisis_final["Estado análisis"] != "SIN ALERTA POR COBERTURA"
    ].copy()

    config_columnas_oc = {
        "Cobertura actual (meses)":
            st.column_config.NumberColumn(format="%.1f"),
        "Cobertura proyectada (meses)":
            st.column_config.NumberColumn(format="%.1f"),
        "Porcentaje orden sobre stock":
            st.column_config.NumberColumn(format="%.0f%%"),
        "Promedio salidas mensual":
            st.column_config.NumberColumn(format="%.1f"),
    }

    # ============================================================
    # 12. INDICADORES
    # ============================================================

    total_exceso = int(
        (analisis_final["Estado análisis"] == "REVISAR POSIBLE EXCESO")
        .sum()
    )

    ui.fila_kpis(st, [
        ("Órdenes analizadas", formato_entero(analisis["_orden_oc"].nunique()),
         f"cantidad total {formato_numero(analisis['_cantidad_oc'].sum())}", "azul"),
        ("Referencias analizadas", formato_entero(analisis["_ref_oc"].nunique()),
         "stock consolidado de todas las bodegas", "azul"),
        ("Casos para revisión", formato_entero(len(alertas_oc)),
         "alertas preventivas", "naranja"),
        ("Posible exceso", formato_entero(total_exceso),
         f"cobertura proyectada > {OC_META_COBERTURA} meses", "rojo"),
    ])

    # ============================================================
    # 13. TABLA DE ALERTAS
    # ============================================================

    st.subheader("Referencias que requieren revisión")

    if alertas_oc.empty:

        st.success(
            "No se identificaron alertas con las reglas de cobertura "
            "configuradas."
        )

    else:

        estados_alerta = [
            e for e in prioridad_estados
            if e in alertas_oc["Estado análisis"].unique()
        ]

        filtro_estados = st.multiselect(
            "Filtrar por tipo de alerta",
            options=estados_alerta,
            default=estados_alerta,
            key="oc_filtro_estados_alerta"
        )

        st.dataframe(
            alertas_oc[
                alertas_oc["Estado análisis"].isin(filtro_estados)
            ],
            use_container_width=True,
            hide_index=True,
            column_config=config_columnas_oc
        )

    # ============================================================
    # 14. ANÁLISIS COMPLETO
    # ============================================================

    with st.expander("Ver análisis completo de las órdenes", expanded=False):

        st.dataframe(
            analisis_final,
            use_container_width=True,
            hide_index=True,
            column_config=config_columnas_oc
        )

    # ============================================================
    # 15. DESCARGA EXCEL (.xlsx REAL, DOS HOJAS)
    # ============================================================

    st.subheader("Descargar resultados")

    buffer_excel = io.BytesIO()

    with pd.ExcelWriter(buffer_excel, engine="openpyxl") as writer:

        alertas_oc.to_excel(writer, index=False, sheet_name="Alertas")
        analisis_final.to_excel(
            writer, index=False, sheet_name="Analisis completo"
        )

        for nombre_hoja in ["Alertas", "Analisis completo"]:

            hoja = writer.sheets[nombre_hoja]
            hoja.freeze_panes = "A2"
            hoja.auto_filter.ref = hoja.dimensions

            for columna in hoja.columns:

                letra = columna[0].column_letter

                longitud = max(
                    len("" if c.value is None else str(c.value))
                    for c in columna
                )

                hoja.column_dimensions[letra].width = min(
                    max(longitud + 2, 12), 45
                )

    st.download_button(
        label="Descargar análisis en Excel (.xlsx)",
        data=buffer_excel.getvalue(),
        file_name=(
            "Analisis_Ordenes_Compra_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".xlsx"
        ),
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
        key="descargar_analisis_ordenes_excel"
    )

    # ============================================================
    # 16. CORREO CON ALERTAS
    # ============================================================

    if not alertas_oc.empty:

        st.subheader("Notificación por correo")

        try:

            cfg = st.secrets["email"]

            remitente = cfg["remitente"]
            contrasena = cfg["contrasena"]
            servidor = cfg.get("servidor", "smtp.office365.com")
            puerto = int(cfg.get("puerto", 587))

            dest_cfg = cfg.get("destinatarios", "")

            if isinstance(dest_cfg, str):
                destinatarios = [
                    c.strip()
                    for c in re.split(r"[,;]", dest_cfg)
                    if c.strip()
                ]
            else:
                destinatarios = list(dest_cfg)

            if not destinatarios:

                st.warning(
                    "No hay destinatarios configurados en "
                    "st.secrets['email']['destinatarios']."
                )

            else:

                # La firma incluye archivo, estados excluidos y
                # ventana de meses: si cambia algo, es otro análisis.
                firma_archivo = hashlib.sha256(
                    contenido_archivo
                    + "|".join(sorted(estados_excluidos)).encode("utf-8")
                    + "|".join(
                        m["etiqueta"] for m in meses_6
                    ).encode("utf-8")
                ).hexdigest()

                if st.session_state.get(
                    "firma_ordenes_correo_enviada"
                ) == firma_archivo:

                    st.info(
                        "Las alertas de este mismo análisis ya se "
                        "enviaron durante esta sesión. No se repitió "
                        "el envío."
                    )

                elif not st.button(
                    f"Enviar correo con {len(alertas_oc)} alertas "
                    f"a {len(destinatarios)} destinatario(s)",
                    key="oc_enviar_correo",
                ):

                    # CORRECCIÓN H-08: antes el correo se enviaba solo al
                    # cargar el archivo. Ahora requiere la acción del usuario.
                    st.caption(
                        "El correo solo se envía cuando presionas el botón. "
                        "Destinatarios: " + ", ".join(destinatarios)
                    )

                else:

                    acceso.exigir_admin(
                        acceso.usuario_sesion(st), SECRETOS,
                        "enviar correos de alertas",
                    )

                    columnas_correo = [
                        c for c in [
                            "Orden", "Referencia", "Artículo",
                            "Cantidad de esta orden",
                            "Stock consolidado",
                            "Cantidad total pendiente referencia",
                            "Cobertura proyectada (meses)",
                            "Estado análisis", "Motivo de revisión"
                        ]
                        if c in alertas_oc.columns
                    ]

                    tabla_html = (
                        alertas_oc[columnas_correo]
                        .round(2)
                        .to_html(
                            index=False,
                            border=1,
                            justify="center",
                            escape=True
                        )
                    )

                    periodo_txt = (
                        f"{meses_6[0]['etiqueta']} a "
                        f"{meses_6[-1]['etiqueta']}"
                        if meses_6 else "sin periodo"
                    )

                    cuerpo_html = f"""
                    <html>
                    <body style="font-family: Arial, sans-serif; color: #333333;">
                        <div style="background-color: #064B9B; padding: 12px;
                                    color: white; font-size: 20px;
                                    font-weight: bold;">
                            Revisión de órdenes de compra
                        </div>
                        <p>Se identificaron <b>{len(alertas_oc)}</b>
                           registros que requieren revisión.</p>
                        <p>Periodo de consumo analizado:
                           <b>{html.escape(periodo_txt)}</b>. El stock se
                           consolida por referencia sumando todas las
                           bodegas.</p>
                        <p>La alerta es preventiva y no bloquea ni autoriza
                           automáticamente la compra.</p>
                        <div style="overflow-x: auto;">{tabla_html}</div>
                        <p><b>Archivo analizado:</b>
                           {html.escape(archivo_ordenes.name)}</p>
                        <p>Correo generado automáticamente por la
                           aplicación de inventarios.</p>
                    </body>
                    </html>
                    """

                    mensaje = EmailMessage()
                    mensaje["Subject"] = (
                        "Alerta de revisión de órdenes de compra"
                    )
                    mensaje["From"] = remitente
                    mensaje["To"] = ", ".join(destinatarios)
                    mensaje.set_content(
                        "Se identificaron registros que requieren "
                        "revisión en las órdenes de compra. Consulte "
                        "el reporte generado en la aplicación."
                    )
                    mensaje.add_alternative(cuerpo_html, subtype="html")

                    if puerto == 465:

                        with smtplib.SMTP_SSL(
                            servidor,
                            puerto,
                            context=ssl.create_default_context(),
                            timeout=30
                        ) as smtp:
                            smtp.login(remitente, contrasena)
                            rechazados = smtp.send_message(mensaje)

                    else:

                        with smtplib.SMTP(
                            servidor, puerto, timeout=30
                        ) as smtp:
                            smtp.ehlo()
                            smtp.starttls(
                                context=ssl.create_default_context()
                            )
                            smtp.ehlo()
                            smtp.login(remitente, contrasena)
                            rechazados = smtp.send_message(mensaje)

                    # send_message devuelve un dict con los destinatarios
                    # que el servidor rechazó. Si hay alguno, NO se marca
                    # como enviado.
                    if rechazados:

                        raise RuntimeError(
                            "El servidor rechazó a: "
                            + ", ".join(rechazados.keys())
                        )

                    st.session_state[
                        "firma_ordenes_correo_enviada"
                    ] = firma_archivo

                    st.success("Correo de alertas enviado correctamente.")

        except Exception as error:

            st.error(f"No fue posible enviar el correo. Detalle: {error}")
            st.caption(
                "La consulta y la descarga del Excel siguen "
                "disponibles aunque falle el envío del correo."
            )

# ============================================================
# PIE
# ============================================================

st.divider()

st.caption(
    "Inventarios ALDC  |  "
    "Herramienta de análisis y seguimiento de inventarios  |  "
    "Área Limpia D.C."
)
