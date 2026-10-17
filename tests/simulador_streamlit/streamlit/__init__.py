"""
Simulador mínimo de Streamlit para pruebas automáticas.

NO reemplaza a Streamlit: no dibuja nada. Ejecuta app.py de principio a
fin registrando cada elemento y mensaje, con widgets que devuelven
valores controlados por la prueba. Sirve para detectar errores de
ejecución (NameError, columnas inexistentes, etc.) y para verificar la
navegación por usuario sin un navegador.
"""


class Detener(BaseException):
    """st.stop() (en Streamlit también hereda de BaseException)"""


class Reejecutar(BaseException):
    """st.rerun() (en Streamlit también hereda de BaseException)"""


class EstadoSesion(dict):
    def __getattr__(self, nombre):
        try:
            return self[nombre]
        except KeyError as e:
            raise AttributeError(nombre) from e

    def __setattr__(self, nombre, valor):
        self[nombre] = valor


session_state = EstadoSesion()
secrets = {}
_archivos = {}
_botones = set()
registro = []
widgets = {}


def configurar(secretos=None, sesion=None, archivos=None, botones=None):
    global secrets
    secrets = dict(secretos or {})
    session_state.clear()
    session_state.update(sesion or {})
    _archivos.clear()
    _archivos.update(archivos or {})
    _botones.clear()
    _botones.update(botones or ())
    registro.clear()
    widgets.clear()


def mensajes(tipo):
    return [texto for t, texto in registro if t == tipo]


class ArchivoSubido:
    def __init__(self, nombre, contenido):
        self.name = nombre
        self._contenido = contenido

    def getvalue(self):
        return self._contenido

    def read(self):
        return self._contenido


class _Contexto:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, nombre):
        import streamlit as st
        return getattr(st, nombre)

    def container(self, **kw):
        return _Contexto()


def _anotar(tipo, texto=""):
    registro.append((tipo, str(texto)))


# ---------------- configuración y salida ----------------

def set_page_config(**kw):
    pass


def markdown(texto="", **kw):
    _anotar("markdown", texto)


def caption(texto="", **kw):
    _anotar("caption", texto)


def write(*a, **kw):
    _anotar("write", " ".join(map(str, a)))


def title(texto="", **kw):
    _anotar("title", texto)


def subheader(texto="", **kw):
    _anotar("subheader", texto)


header = subheader


def text(texto="", **kw):
    _anotar("text", texto)


def divider(**kw):
    pass


def image(*a, **kw):
    pass


def info(texto="", **kw):
    _anotar("info", texto)


def warning(texto="", **kw):
    _anotar("warning", texto)


def error(texto="", **kw):
    _anotar("error", texto)


def success(texto="", **kw):
    _anotar("success", texto)


def exception(e):
    _anotar("exception", e)


def metric(etiqueta, valor, delta=None, **kw):
    _anotar("metric", f"{etiqueta}: {valor}")


def dataframe(datos=None, **kw):
    import pandas as pd
    if datos is not None and not isinstance(datos, pd.DataFrame):
        datos = getattr(datos, "data", datos)  # Styler
    _anotar("dataframe", "" if datos is None else f"{len(datos)} filas")


table = dataframe


def plotly_chart(fig, **kw):
    _anotar("plotly_chart", getattr(fig, "titulo", ""))


def download_button(label=None, data=None, **kw):
    etiqueta = label
    if not isinstance(data, (bytes, str)):
        raise TypeError(f"download_button '{etiqueta}': data debe ser bytes o str")
    _anotar("download_button", etiqueta)
    return False


# ---------------- contenedores ----------------

sidebar = _Contexto()


def columns(spec, **kw):
    n = spec if isinstance(spec, int) else len(spec)
    return [_Contexto() for _ in range(n)]


def container(**kw):
    return _Contexto()


def empty():
    return _Contexto()


def expander(etiqueta="", expanded=False, **kw):
    _anotar("expander", etiqueta)
    return _Contexto()


def spinner(texto="", **kw):
    return _Contexto()


def form(clave, **kw):
    return _Contexto()


# ---------------- widgets ----------------

def _registrar_widget(clave, etiqueta, opciones=None):
    widgets[clave or etiqueta] = {"etiqueta": etiqueta, "opciones": opciones}


def _elegir(etiqueta, opciones, indice, clave, format_func):
    opciones = list(opciones)
    if format_func is not None:
        for o in opciones:
            format_func(o)
    _registrar_widget(clave, etiqueta, opciones)
    if clave and clave in session_state and session_state[clave] in opciones:
        return session_state[clave]
    valor = opciones[indice] if opciones and indice is not None else None
    if clave:
        session_state[clave] = valor
    return valor


def radio(etiqueta, options, index=0, format_func=None, key=None, **kw):
    return _elegir(etiqueta, options, index, key, format_func)


def selectbox(etiqueta, options, index=0, format_func=None, key=None, **kw):
    return _elegir(etiqueta, options, index, key, format_func)


def multiselect(etiqueta, options, default=None, key=None, **kw):
    _registrar_widget(key, etiqueta, list(options))
    if key and key in session_state:
        return session_state[key]
    valor = list(default or [])
    if key:
        session_state[key] = valor
    return valor


def text_input(etiqueta, value="", key=None, **kw):
    _registrar_widget(key, etiqueta)
    if key and key in session_state:
        return session_state[key]
    if key:
        session_state[key] = value
    return value


def number_input(etiqueta, min_value=None, max_value=None, value=0.0, key=None, **kw):
    _registrar_widget(key, etiqueta)
    return session_state.get(key, value) if key else value


def checkbox(etiqueta, value=False, key=None, **kw):
    _registrar_widget(key, etiqueta)
    if key and key in session_state:
        return session_state[key]
    return value


toggle = checkbox


def button(label=None, key=None, on_click=None, disabled=False, **kw):
    etiqueta = label
    _registrar_widget(key, etiqueta)
    pulsado = (key in _botones or etiqueta in _botones) and not disabled
    if pulsado and on_click is not None:
        on_click()
    return pulsado


form_submit_button = button


def file_uploader(etiqueta, type=None, key=None, **kw):
    _registrar_widget(key, etiqueta)
    return _archivos.get(key)


def stop():
    raise Detener()


def rerun():
    raise Reejecutar()


# ---------------- caché ----------------

class _CacheData:
    def __call__(self, funcion=None, **kw):
        if funcion is None:
            return lambda f: f
        return funcion

    def clear(self):
        pass


cache_data = _CacheData()


class _ConfigColumnas:
    def __getattr__(self, nombre):
        return lambda *a, **kw: {"tipo": nombre, "args": a, **kw}


column_config = _ConfigColumnas()
