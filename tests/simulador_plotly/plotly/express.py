"""plotly.express simulado: valida que las columnas usadas existan."""
from .graph_objects import Figure


class _Defaults:
    color_discrete_sequence = None


defaults = _Defaults()


def _validar(df, kw):
    columnas = set(df.columns)
    for clave in ("x", "y", "color", "text"):
        valor = kw.get(clave)
        if isinstance(valor, str) and valor not in columnas:
            raise ValueError(f"px: la columna '{valor}' ({clave}) no existe")
    for valor in kw.get("custom_data") or []:
        if valor not in columnas:
            raise ValueError(f"px: la columna '{valor}' (custom_data) no existe")


def bar(data_frame=None, **kw):
    _validar(data_frame, kw)
    return Figure()


def line(data_frame=None, **kw):
    _validar(data_frame, kw)
    return Figure()
