"""
Ejecuta app.py completo con un simulador de Streamlit, por usuario y por
página. Detecta errores de ejecución y verifica la navegación y los
permisos. No reemplaza una revisión visual en el navegador.
"""
import importlib
import io
import os
import runpy
import shutil
import sys
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import pandas as pd

from datos_prueba import RAIZ, excel_kardex, mov, m

DIR_TESTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(DIR_TESTS, "simulador_streamlit"))
try:
    import plotly  # noqa: F401
except ImportError:
    sys.path.insert(0, os.path.join(DIR_TESTS, "simulador_plotly"))

import streamlit as st  # noqa: E402  (simulador)

SECRETOS = {"usuarios": {"admin": "clave-prueba-1", "inventarios": "clave-prueba-2"}}


def crear_copia_app():
    """Copia app.py y el histórico a una carpeta temporal (los datos
    generados por la prueba quedan ahí, no en el repositorio)."""
    d = tempfile.mkdtemp(prefix="app_simulada_")
    shutil.copy(os.path.join(RAIZ, "app.py"), d)
    shutil.copy(os.path.join(RAIZ, "HISTORICO_INVENTARIOS.xlsx"), d)
    return d


def ejecutar(dir_app, usuario, pagina=None, sesion=None, archivos=None, botones=None):
    estado = {
        "autenticado": True,
        "usuario": usuario,
        "inicio_sesion": datetime.now(),
    }
    if pagina:
        estado["pagina_navegacion"] = pagina
    estado.update(sesion or {})
    st.configurar(SECRETOS, estado, archivos, botones)

    resultado = "completa"
    try:
        runpy.run_path(os.path.join(dir_app, "app.py"), run_name="__main__")
    except st.Detener:
        resultado = "detenida"
    except st.Reejecutar:
        resultado = "reejecutar"
    return resultado, dict(st.session_state)


def opciones_menu():
    return st.widgets["pagina_navegacion"]["opciones"]


class TestAppSimulada(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.dir = crear_copia_app()

    def sin_errores(self):
        self.assertEqual(st.mensajes("exception"), [])
        self.assertEqual(st.mensajes("error"), [], st.mensajes("error"))

    # ---------------- usuario inventarios ----------------

    def test_inventarios_solo_ve_tres_paginas_y_todas_cargan(self):
        for pagina in ["Resumen e inventario", "Evolución", "Riesgos y detalle"]:
            with self.subTest(pagina=pagina):
                ejecutar(self.dir, "inventarios", pagina)
                self.assertEqual(
                    opciones_menu(),
                    ["Resumen e inventario", "Evolución", "Riesgos y detalle"],
                )
                self.sin_errores()

    def test_inventarios_no_llega_a_una_pagina_restringida(self):
        for pagina in ["Actualizar Kardex", "Conciliación mensual", "Órdenes de compra"]:
            with self.subTest(pagina=pagina):
                _, sesion = ejecutar(self.dir, "inventarios", pagina)
                self.assertEqual(sesion["pagina_navegacion"], "Resumen e inventario")
                self.assertNotIn("up_kardex", st.widgets)
                self.assertNotIn("conc_archivo", st.widgets)
                self.assertNotIn("archivo_ordenes_compra", st.widgets)

    # ---------------- usuario admin ----------------

    def test_admin_ve_todas_las_paginas_y_cargan(self):
        for pagina in [
            "Resumen e inventario", "Evolución", "Riesgos y detalle",
            "Órdenes de compra", "Conciliación mensual", "Actualizar Kardex",
        ]:
            with self.subTest(pagina=pagina):
                ejecutar(self.dir, "admin", pagina)
                self.assertEqual(len(opciones_menu()), 6)
                self.sin_errores()

    def test_evolucion_muestra_las_tablas_que_antes_fallaban(self):
        ejecutar(self.dir, "admin", "Evolución")
        textos = " ".join(st.mensajes("markdown"))
        self.assertIn("Referencias con mayor impacto económico", textos)
        self.assertIn("Lectura analítica de los movimientos", textos)

    def test_riesgos_vistas_del_detalle(self):
        for vista in ["Con stock al corte", "Sin stock o con stock negativo", "Todos"]:
            with self.subTest(vista=vista):
                ejecutar(self.dir, "admin", "Riesgos y detalle",
                         sesion={"riesgos_vista_detalle": vista, "riesgos_buscar": "VALVULA"})
                self.sin_errores()

    def test_filtros_y_restablecer(self):
        ejecutar(self.dir, "inventarios", "Resumen e inventario",
                 sesion={"f_area": "Mantenimiento", "f_bodega": "[1] - REPUESTOS",
                         "f_antiguedad": "Mayor a 12 meses"})
        self.sin_errores()
        _, sesion = ejecutar(self.dir, "inventarios", "Resumen e inventario",
                             sesion={"f_area": "RRHH", "f_bodega": "[1] - REPUESTOS"},
                             botones={"btn_restablecer_filtros"})
        self.assertEqual(sesion.get("f_area"), "Todas")
        # Una selección que ya no existe se descarta sin error
        _, sesion = ejecutar(self.dir, "inventarios", "Resumen e inventario",
                             sesion={"f_area": "RRHH", "f_bodega": "[1] - REPUESTOS"})
        self.assertEqual(sesion.get("f_bodega"), "Todas")

    # ---------------- flujos completos ----------------

    def test_flujo_cargue_kardex_y_tablero_actualizado(self):
        d = crear_copia_app()
        base, _ = m.leer_historico(os.path.join(d, "HISTORICO_INVENTARIOS.xlsx"))
        fila = base.iloc[1]
        kardex = excel_kardex([
            mov("2026-06-15", entrada=2, costo=400000, bodega=fila["Bodega"], cod=fila["Codigo Articulo"]),
            mov("2026-06-20", salida=-1, costo=172550, bodega=fila["Bodega"], cod=fila["Codigo Articulo"]),
        ])
        archivos = {"up_kardex": st.ArchivoSubido("kardex_junio.xlsx", kardex)}

        estado, sesion = ejecutar(d, "admin", "Actualizar Kardex", archivos=archivos)
        self.sin_errores()
        self.assertEqual(list(sesion["plan_kardex"]["por_periodo"]), ["2026-06"])

        estado, sesion = ejecutar(
            d, "admin", "Actualizar Kardex", sesion=sesion, archivos=archivos,
            botones={"Procesar y actualizar el tablero"},
        )
        self.assertEqual(estado, "reejecutar", st.mensajes("error"))
        self.assertTrue(os.path.exists(os.path.join(d, "INVENTARIO_ACTUALIZADO_LIFO.xlsx")))
        self.assertTrue(os.path.exists(os.path.join(d, "datos", "kardex", "2026-06.csv.gz")))

        ejecutar(d, "admin", "Actualizar Kardex", sesion=sesion)
        self.sin_errores()
        self.assertTrue(any("Inventario recalculado hasta Junio 2026" in s for s in st.mensajes("success")))

        ejecutar(d, "inventarios", "Resumen e inventario")
        self.sin_errores()
        self.assertTrue(any("Corte: Junio 2026" in s for s in st.mensajes("markdown")))

        # Conciliación del periodo con el inventario real
        buf = io.BytesIO()
        pd.DataFrame({
            "Bodega": [fila["Bodega"]], "Codigo Articulo": [fila["Codigo Articulo"]],
            "Existencia": [7],
        }).to_excel(buf, index=False)
        archivos = {"conc_archivo": st.ArchivoSubido("real_junio.xlsx", buf.getvalue())}
        _, sesion = ejecutar(d, "admin", "Conciliación mensual", archivos=archivos,
                             botones={"Conciliar"})
        self.sin_errores()
        tabla, resumen, ident = sesion["conc_resultado"]
        self.assertEqual(resumen["periodo"], "2026-06")
        fila_c = tabla[tabla["Codigo Articulo"] == fila["Codigo Articulo"]].iloc[0]
        self.assertEqual(fila_c["Stock final calculado"], 7)
        self.assertEqual(fila_c["Estado"], "Conciliado")
        self.assertIsNotNone(ident)

    def test_flujo_conciliacion_con_ajustes_desde_la_pagina(self):
        d = crear_copia_app()
        base, _ = m.leer_historico(os.path.join(d, "HISTORICO_INVENTARIOS.xlsx"))
        fila = base.iloc[1]
        kardex = excel_kardex([
            mov("2026-06-15", entrada=2, costo=400000, bodega=fila["Bodega"], cod=fila["Codigo Articulo"]),
            mov("2026-06-20", salida=-1, costo=172550, bodega=fila["Bodega"], cod=fila["Codigo Articulo"]),
        ])
        archivos = {"up_kardex": st.ArchivoSubido("kardex_junio.xlsx", kardex)}
        _, sesion = ejecutar(d, "admin", "Actualizar Kardex", archivos=archivos)
        ejecutar(d, "admin", "Actualizar Kardex", sesion=sesion, archivos=archivos,
                 botones={"Procesar y actualizar el tablero"})

        # Real: 5 unidades (el Kardex deja 7) y valor 1.000.000
        buf = io.BytesIO()
        pd.DataFrame({
            "Bodega": [fila["Bodega"]], "Codigo Articulo": [fila["Codigo Articulo"]],
            "Existencia": [5], "Valor Total": [1000000],
        }).to_excel(buf, index=False)
        archivos = {"conc_archivo": st.ArchivoSubido("real_junio.xlsx", buf.getvalue())}
        _, sesion = ejecutar(d, "admin", "Conciliación mensual", archivos=archivos,
                             botones={"Conciliar"})
        self.sin_errores()
        tabla, _, _ = sesion["conc_resultado"]
        f = tabla[tabla["Codigo Articulo"] == fila["Codigo Articulo"]].iloc[0]
        self.assertEqual(f["Estado"], "Con diferencia")
        self.assertEqual(f["Ajuste unidades propuesto"], -2)

        sesion["conc_confirmar_ajustes"] = True
        estado, sesion = ejecutar(d, "admin", "Conciliación mensual", sesion=sesion,
                                  archivos=archivos, botones={"conc_aplicar_ajustes"})
        self.assertEqual(estado, "reejecutar", st.mensajes("error"))

        _, sesion = ejecutar(d, "admin", "Conciliación mensual", sesion=sesion, archivos=archivos)
        self.sin_errores()
        self.assertTrue(any("Se aplicaron 1 ajustes" in s for s in st.mensajes("success")))
        tabla, _, _ = sesion["conc_resultado"]
        f = tabla[tabla["Codigo Articulo"] == fila["Codigo Articulo"]].iloc[0]
        self.assertEqual(f["Estado"], "Conciliado con ajuste")
        self.assertEqual(f["Stock final ajustado"], 5)
        self.assertEqual(f["Valor final ajustado"], 1000000)

        # El tablero (usuario inventarios) ya refleja el inventario ajustado
        ejecutar(d, "inventarios", "Riesgos y detalle")
        self.sin_errores()

    def test_ordenes_de_compra_no_envia_correo_sin_pulsar_el_boton(self):
        buf = io.BytesIO()
        pd.DataFrame({
            "IdOrden": ["OC1", "OC2"],
            "Cod Articulo": ["1011010145", "999999"],
            "Cantidad": [50, 3],
            "Estado": ["[2] - Pendiente", "[2] - Pendiente"],
        }).to_excel(buf, index=False)
        archivos = {"archivo_ordenes_compra": st.ArchivoSubido("ordenes.xlsx", buf.getvalue())}
        secretos = dict(SECRETOS, email={"remitente": "a@b.co", "contrasena": "x",
                                         "destinatarios": "c@d.co"})
        with mock.patch("smtplib.SMTP") as smtp, mock.patch("smtplib.SMTP_SSL") as smtp_ssl:
            st_conf = st.configurar
            try:
                st.configurar = lambda s, *a, **k: st_conf(secretos, *a, **k)
                ejecutar(self.dir, "admin", "Órdenes de compra", archivos=archivos)
            finally:
                st.configurar = st_conf
            self.sin_errores()
            smtp.assert_not_called()
            smtp_ssl.assert_not_called()
        self.assertIn("oc_enviar_correo", st.widgets)


if __name__ == "__main__":
    unittest.main()
