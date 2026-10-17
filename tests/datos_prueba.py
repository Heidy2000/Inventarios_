"""Datos y utilidades compartidas por las pruebas."""
import io
import os
import sys
import tempfile
import warnings

import pandas as pd

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

import motor_lifo as m  # noqa: E402
import gestion_kardex as g  # noqa: E402

ARCHIVO_HISTORICO_REAL = os.path.join(RAIZ, "HISTORICO_INVENTARIOS.xlsx")

REPUESTOS = "[1] - REPUESTOS"
HERRAMIENTAS = "[7] - HERRAMIENTAS"


def base_minima(filas):
    """
    Histórico base con cierre en mayo 2026.
    filas: lista de (bodega, codigo, stock_mayo, coste_mayo).
    """
    df = pd.DataFrame(
        [
            {
                "Bodega": b,
                "Codigo Articulo": c,
                "Articulo": f"ART {c}",
                "STOCK INICIAL": s,
                "COSTE INICIAL": v,
                "STOCK MAYO 2026": s,
                "COSTE MAYO 2026": v,
            }
            for b, c, s, v in filas
        ]
    )
    return m.preparar_historico(df)


def mov(fecha, entrada=0, salida=0, costo=0, bodega=REPUESTOS, cod="111", estado="3-APROBADO"):
    return {
        "Bodega": bodega,
        "Codigo Articulo": cod,
        "Articulo": f"ART {cod}",
        "EstadoMovimiento": estado,
        "Fecha Movimiento": pd.Timestamp(fecha) if not isinstance(fecha, str) or "-" in fecha else fecha,
        "Cantidad Entrada": entrada,
        "Cantidad Salida": salida,
        "Costo Total Con Iva": costo,
    }


def excel_kardex(filas, encabezado_extra=0):
    """Excel de Kardex como lo exporta el sistema (bytes)."""
    buf = io.BytesIO()
    df = pd.DataFrame(filas)
    df.to_excel(buf, index=False, startrow=encabezado_extra, sheet_name="ListaExportada")
    return buf.getvalue()


class Escenario:
    """Almacén temporal + histórico base para probar cargues."""

    def __init__(self, base):
        self.dir = tempfile.mkdtemp(prefix="inv_prueba_")
        self.base = base
        self.almacen = g.Almacen(self.dir)
        self.ruta_actualizado = os.path.join(self.dir, "INVENTARIO_ACTUALIZADO_LIFO.xlsx")

    def plan(self, filas, nombre="kardex.xlsx", contenido=None):
        contenido = contenido if contenido is not None else excel_kardex(filas)
        kardex, _ = m.leer_kardex(contenido)
        return g.analizar_kardex(kardex, self.base, self.almacen, nombre, contenido)

    def cargar(self, filas, nombre="kardex.xlsx", usuario="admin", contenido=None, **kw):
        plan = self.plan(filas, nombre, contenido)
        res, _ = g.ejecutar_cargue(
            plan, self.base, self.almacen, usuario, self.ruta_actualizado, **kw
        )
        return res

    def tablero(self):
        """Lo que lee el tablero tras el cargue (archivo actualizado)."""
        df, _ = m.leer_historico(self.ruta_actualizado)
        return df


def valor(df, columna, llave):
    fila = df[df["LLAVE"] == llave]
    assert len(fila) == 1, f"{llave}: {len(fila)} filas"
    return float(fila[columna].iloc[0])
