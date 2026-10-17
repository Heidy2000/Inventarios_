"""Figuras de Plotly simuladas: aceptan las llamadas y guardan el título."""


class Figure:
    def __init__(self, *a, **kw):
        self.trazas = []
        self.titulo = ""

    def add_trace(self, traza, **kw):
        self.trazas.append(traza)
        return self

    def update_layout(self, **kw):
        if "title" in kw:
            self.titulo = kw["title"]
        return self

    def __getattr__(self, nombre):
        if nombre.startswith(("update_", "add_")):
            return lambda *a, **kw: self
        raise AttributeError(nombre)


class _Traza:
    def __init__(self, **kw):
        self.kw = kw


class Bar(_Traza):
    pass


class Scatter(_Traza):
    pass
