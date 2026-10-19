"""
Pruebas del cálculo de stock y de los cargues mensuales del Kardex.
Ejecutar desde la raíz del proyecto:
    python -m unittest discover -s tests -v
"""
import json
import os
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from datos_prueba import (
    ARCHIVO_HISTORICO_REAL, HERRAMIENTAS, REPUESTOS, Escenario,
    base_minima, excel_kardex, m, g, mov, valor,
)

LL_111 = "1_111"


class TestSignosYStock(unittest.TestCase):

    def test_100_mas_20_menos_15_da_105_con_salida_negativa(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        res = esc.cargar([
            mov("2026-06-10", entrada=20, costo=200),
            mov("2026-06-20", salida=-15, costo=150),
        ])
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", LL_111), 105)
        self.assertEqual(valor(h, "ENTRADA JUNIO 2026", LL_111), 20)
        # La salida conserva su signo negativo en el resultado
        self.assertEqual(valor(h, "SALIDA JUNIO 2026", LL_111), -15)
        self.assertEqual(res["stats"]["convencion_salidas"], m.CONVENCION_NEGATIVA)

    def test_salidas_registradas_en_positivo_tambien_dan_105(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        res = esc.cargar([
            mov("2026-06-10", entrada=20, costo=200),
            mov("2026-06-20", salida=15, costo=150),
        ])
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", LL_111), 105)
        self.assertEqual(valor(h, "SALIDA JUNIO 2026", LL_111), -15)
        self.assertEqual(res["stats"]["convencion_salidas"], m.CONVENCION_POSITIVA)

    def test_salida_negativa_no_se_resta_dos_veces_en_el_tablero(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        esc.cargar([
            mov("2026-06-10", entrada=20, costo=200),
            mov("2026-06-20", salida=-15, costo=150),
        ])
        t = esc.tablero()
        inicial = valor(t, "STOCK MAYO 2026", LL_111)
        ent = valor(t, "ENTRADA JUNIO 2026", LL_111)
        sal = valor(t, "SALIDA JUNIO 2026", LL_111)
        final = valor(t, "STOCK JUNIO 2026", LL_111)
        self.assertEqual(inicial + ent + sal, final)
        self.assertEqual(final, 105)

    def test_salida_con_signo_opuesto_no_se_aplica_y_queda_para_revision(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        res = esc.cargar([
            mov("2026-06-10", salida=-10, costo=100),
            mov("2026-06-11", salida=-5, costo=50),
            mov("2026-06-12", salida=7, costo=70),   # contraria a la convención
        ])
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", LL_111), 85)
        self.assertEqual(res["stats"]["salidas_signo_opuesto"], 1)
        self.assertIn(m.MOTIVO_SIGNO_OPUESTO, res["revision"]["Motivo"].tolist())

    def test_entrada_negativa_se_aplica_como_salida(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        res = esc.cargar([mov("2026-06-10", entrada=-4, costo=40)])
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", LL_111), 96)


class TestIndependencia(unittest.TestCase):

    def test_dos_referencias_en_la_misma_bodega(self):
        esc = Escenario(base_minima([
            (REPUESTOS, "111", 100, 1000),
            (REPUESTOS, "222", 50, 500),
        ]))
        res = esc.cargar([
            mov("2026-06-10", entrada=20, costo=200, cod="111"),
            mov("2026-06-12", salida=-30, costo=300, cod="222"),
        ])
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "1_111"), 120)
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "1_222"), 20)

    def test_misma_referencia_en_dos_bodegas(self):
        esc = Escenario(base_minima([
            (REPUESTOS, "111", 100, 1000),
            (HERRAMIENTAS, "111", 10, 100),
        ]))
        res = esc.cargar([
            mov("2026-06-10", salida=-15, costo=150, bodega=REPUESTOS),
            mov("2026-06-10", entrada=5, costo=50, bodega=HERRAMIENTAS),
        ])
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "1_111"), 85)
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "7_111"), 15)

    def test_referencia_nueva_se_crea_en_su_bodega(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        res = esc.cargar([mov("2026-06-10", entrada=5, costo=50, bodega="[13] - INSUMOS OPERATIVOS", cod="999")])
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "13_999"), 5)
        self.assertEqual(res["stats"]["llaves_nuevas"], 1)


class TestCarguesMensuales(unittest.TestCase):

    def setUp(self):
        self.esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        self.junio = [mov("2026-06-10", entrada=20, costo=200), mov("2026-06-20", salida=-15, costo=150)]
        self.julio = [mov("2026-07-05", salida=-5, costo=50)]

    def test_mes_consecutivo_parte_del_cierre_anterior(self):
        self.esc.cargar(self.junio, "junio.xlsx")
        res = self.esc.cargar(self.julio, "julio.xlsx")
        h = res["historico"]
        # Antes del arreglo, cargar julio solo dejaba junio en 100 y julio en 95.
        self.assertEqual(valor(h, "STOCK JUNIO 2026", LL_111), 105)
        self.assertEqual(valor(h, "STOCK JULIO 2026", LL_111), 100)
        self.assertEqual(self.esc.almacen.periodos(), ["2026-06", "2026-07"])

    def test_recargar_un_periodo_no_duplica_movimientos(self):
        contenido = excel_kardex(self.junio)
        self.esc.cargar(self.junio, "junio.xlsx", contenido=contenido)
        plan = self.esc.plan(self.junio, "junio.xlsx", contenido=contenido)
        self.assertEqual(plan["reemplazos"], ["2026-06"])
        self.assertTrue(plan["mismo_archivo"])
        with self.assertRaises(ValueError):
            g.ejecutar_cargue(plan, self.esc.base, self.esc.almacen, "admin", self.esc.ruta_actualizado)
        res, _ = g.ejecutar_cargue(
            plan, self.esc.base, self.esc.almacen, "admin",
            self.esc.ruta_actualizado, confirmar_reemplazo=True,
        )
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", LL_111), 105)
        self.assertEqual(res["stats"]["movimientos_procesados"], 2)
        vigentes = self.esc.almacen.registro_vigente()
        self.assertEqual(len(vigentes), 1)
        self.assertEqual(vigentes[0]["accion"], "reemplazo")

    def test_corregir_un_mes_anterior_recalcula_los_siguientes(self):
        self.esc.cargar(self.junio, "junio.xlsx")
        self.esc.cargar(self.julio, "julio.xlsx")
        corregido = [mov("2026-06-10", entrada=30, costo=300), mov("2026-06-20", salida=-15, costo=150)]
        plan = self.esc.plan(corregido, "junio_corregido.xlsx")
        self.assertEqual(plan["anteriores_al_ultimo"], ["2026-06"])
        res, _ = g.ejecutar_cargue(
            plan, self.esc.base, self.esc.almacen, "admin",
            self.esc.ruta_actualizado, confirmar_reemplazo=True,
        )
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", LL_111), 115)
        self.assertEqual(valor(res["historico"], "STOCK JULIO 2026", LL_111), 110)

    def test_un_mes_faltante_bloquea_el_cargue(self):
        self.esc.cargar(self.junio, "junio.xlsx")
        plan = self.esc.plan([mov("2026-08-05", salida=-1, costo=10)], "agosto.xlsx")
        self.assertEqual(plan["faltantes"], ["2026-07"])
        self.assertTrue(plan["bloqueos"])
        with self.assertRaises(ValueError):
            g.ejecutar_cargue(plan, self.esc.base, self.esc.almacen, "admin", self.esc.ruta_actualizado)
        self.assertEqual(self.esc.almacen.periodos(), ["2026-06"])

    def test_archivo_con_varios_meses_se_divide_por_periodo(self):
        res = self.esc.cargar(self.junio + self.julio, "jun_jul.xlsx")
        self.assertEqual(self.esc.almacen.periodos(), ["2026-06", "2026-07"])
        self.assertEqual(valor(res["historico"], "STOCK JULIO 2026", LL_111), 100)

    def test_movimientos_anteriores_a_la_base_se_ignoran_e_informan(self):
        plan = self.esc.plan(self.junio + [mov("2026-05-15", entrada=50, costo=500)])
        self.assertEqual(plan["anteriores_a_base"], 1)
        self.assertEqual(list(plan["por_periodo"]), ["2026-06"])

    def test_fallo_al_escribir_no_deja_cambios_parciales(self):
        self.esc.cargar(self.junio, "junio.xlsx")
        registro_antes = self.esc.almacen.registro()
        with open(self.esc.ruta_actualizado, "rb") as f:
            actualizado_antes = f.read()

        original = g.escribir_atomico

        def falla_en_registro(ruta, contenido):
            if ruta.endswith("registro_cargues.json"):
                raise OSError("disco lleno (simulado)")
            return original(ruta, contenido)

        plan = self.esc.plan(self.julio, "julio.xlsx")
        with mock.patch.object(g, "escribir_atomico", side_effect=falla_en_registro):
            with self.assertRaises(OSError):
                g.ejecutar_cargue(plan, self.esc.base, self.esc.almacen, "admin", self.esc.ruta_actualizado)

        self.assertEqual(self.esc.almacen.periodos(), ["2026-06"])
        self.assertEqual(self.esc.almacen.registro(), registro_antes)
        with open(self.esc.ruta_actualizado, "rb") as f:
            self.assertEqual(f.read(), actualizado_antes)
        self.assertFalse(os.path.exists(self.esc.almacen.ruta_bloqueo))


class TestValidaciones(unittest.TestCase):

    def setUp(self):
        self.esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))

    def test_cantidad_invalida_se_rechaza_e_informa(self):
        res = self.esc.cargar([
            mov("2026-06-10", entrada=20, costo=200),
            mov("2026-06-11", entrada="veinte", costo=200),
        ])
        self.assertEqual(res["stats"]["rechazados"], 1)
        self.assertIn("Cantidad de entrada no numérica", res["rechazados"]["Motivo"].iloc[0])
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", LL_111), 120)

    def test_fecha_invalida_se_rechaza_e_informa(self):
        plan = self.esc.plan([
            mov("2026-06-10", entrada=20, costo=200),
            mov("no es fecha", entrada=5, costo=50),
        ])
        self.assertEqual(len(plan["rechazados"]), 1)
        self.assertIn("Fecha inválida", plan["rechazados"]["Motivo"].iloc[0])
        self.assertEqual(int(plan["rechazados"]["Fila en el archivo"].iloc[0]), 3)

    def test_fechas_en_texto_dia_primero_e_iso(self):
        res = self.esc.cargar([
            mov("15/06/2026", entrada=1, costo=10),
            mov("2026-06-03", entrada=1, costo=10),
        ])
        self.assertEqual(res["stats"]["rechazados"], 0)
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", LL_111), 102)

    def test_archivo_vacio_o_sin_columnas(self):
        with self.assertRaises(ValueError):
            m.leer_kardex(excel_kardex([{"Bodega": "x", "Otra": 1}]))

    def test_salida_sin_existencia_se_contabiliza_completa(self):
        # Stock 100, salida de 130: se descuentan las 130 (stock -30),
        # la salida conserva su signo y su costo cuenta completo.
        res = self.esc.cargar([mov("2026-06-10", salida=-130, costo=1300)])
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", LL_111), -30)
        self.assertEqual(valor(h, "SALIDA JUNIO 2026", LL_111), -130)
        self.assertEqual(valor(h, "COSTO SALIDA JUNIO 2026", LL_111), -1300)
        self.assertEqual(len(res["sin_existencia"]), 1)
        self.assertEqual(float(res["sin_existencia"]["Salida sin existencia"].iloc[0]), 30)
        self.assertEqual(float(res["sin_existencia"]["Salida aplicada"].iloc[0]), 130)
        self.assertEqual([v for v in res["verificaciones"] if not v[1]], [])

    def test_salida_con_stock_inicial_cero(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 0, 0)]))
        res = esc.cargar([mov("2026-06-10", salida=-8, costo=800)])
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", LL_111), -8)
        self.assertEqual(valor(h, "SALIDA JUNIO 2026", LL_111), -8)
        self.assertEqual(valor(h, "COSTO SALIDA JUNIO 2026", LL_111), -800)
        self.assertEqual(valor(h, "CMV 12 MESES", LL_111), 800)

    def test_salida_de_referencia_nueva_sin_existencias(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 10, 100)]))
        res = esc.cargar([mov("2026-06-10", salida=-3, costo=30, cod="777")])
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", "1_777"), -3)

    def test_entrada_posterior_cubre_la_salida_sin_existencia(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 0, 0)]))
        res = esc.cargar([
            mov("2026-06-10", salida=-5, costo=500),
            mov("2026-06-20", entrada=8, costo=800),
            mov("2026-07-02", salida=-2, costo=200),
        ])
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", LL_111), 3)
        self.assertEqual(valor(h, "STOCK JULIO 2026", LL_111), 1)
        self.assertEqual([v for v in res["verificaciones"] if not v[1]], [])

    def test_stock_negativo_heredado_sigue_descontando_y_cuadra(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", -2, -200)]))
        res = esc.cargar([mov("2026-06-10", salida=-1, costo=100)])
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", LL_111), -3)
        self.assertEqual(len(res["sin_existencia"]), 1)
        self.assertEqual([v for v in res["verificaciones"] if not v[1]], [])

    def test_stock_negativo_heredado_se_recupera_con_entradas(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", -2, -200)]))
        res = esc.cargar([mov("2026-06-10", entrada=5, costo=500), mov("2026-06-11", salida=-4, costo=400)])
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", LL_111), -1)
        self.assertEqual(float(res["sin_existencia"]["Salida sin existencia"].iloc[0]), 1)
        self.assertEqual([v for v in res["verificaciones"] if not v[1]], [])

    def test_anulados_y_bodegas_excluidas(self):
        res = self.esc.cargar([
            mov("2026-06-10", entrada=20, costo=200),
            mov("2026-06-11", entrada=500, costo=1, estado="5-ANULADO"),
            mov("2026-06-12", entrada=500, costo=1, bodega="[11] - OTRA"),
        ])
        self.assertEqual(res["stats"]["anulados"], 1)
        self.assertEqual(res["stats"]["excluidos_bodega"], 1)
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", LL_111), 120)

    def test_filas_identicas_se_informan_y_solo_se_excluyen_si_se_pide(self):
        fila = mov("2026-06-10", entrada=5, costo=50)
        res = self.esc.cargar([fila, fila])
        self.assertEqual(valor(res["historico"], "STOCK JUNIO 2026", LL_111), 110)
        self.assertEqual(res["stats"]["posibles_duplicados"], 2)

        esc2 = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        res2 = esc2.cargar([fila, fila], excluir_filas_identicas=True)
        self.assertEqual(valor(res2["historico"], "STOCK JUNIO 2026", LL_111), 105)


class TestCostos(unittest.TestCase):

    def test_fila_mixta_reparte_el_costo(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 10, 1000)]))
        res = esc.cargar([mov("2026-06-10", entrada=3, salida=-1, costo=400)])
        h = res["historico"]
        self.assertEqual(valor(h, "COSTO ENTRADA JUNIO 2026", LL_111), 300)
        self.assertEqual(valor(h, "COSTO SALIDA JUNIO 2026", LL_111), -100)
        self.assertEqual(valor(h, "STOCK JUNIO 2026", LL_111), 12)

    def test_stock_en_cero_deja_valor_en_cero_con_ajuste_trazable(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 6, 1035300)]))
        res = esc.cargar([mov("2026-06-10", salida=-6, costo=900000)])
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", LL_111), 0)
        self.assertEqual(valor(h, "COSTE TOTAL JUNIO 2026", LL_111), 0)
        self.assertEqual(valor(h, "AJUSTE COSTO JUNIO 2026", LL_111), -135300)
        # El costo de ventas (CMV) no se altera con el ajuste
        self.assertEqual(valor(h, "COSTO SALIDA JUNIO 2026", LL_111), -900000)
        self.assertEqual(len(res["ajustes_costo"]), 1)

    def test_coste_entre_menos_1_y_1_usa_costo_de_entrada_regla_conservada(self):
        hist = pd.DataFrame({
            "Bodega": [REPUESTOS], "Codigo Articulo": ["111"],
            "STOCK JUNIO 2025": [0], "COSTE JUNIO 2025": [0.5], "COSTO ENTRADA JUNIO 2025": [120],
            "COSTO SALIDA JUNIO 2025": [-120], "ENTRADA JUNIO 2025": [1], "SALIDA JUNIO 2025": [-1],
        })
        hist = m.preparar_historico(hist)
        h, _, _ = m.calcular_indicadores_12_meses(hist, m.obtener_meses_disponibles(hist))
        self.assertEqual(float(h["INVENTARIO PROMEDIO 12 MESES"].iloc[0]), 120)

    def test_verificaciones_en_verde(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        res = esc.cargar([mov("2026-06-10", entrada=20, costo=200), mov("2026-06-20", salida=-120, costo=1200)])
        fallidas = [v for v in res["verificaciones"] if not v[1]]
        self.assertEqual(fallidas, [])


class TestHistoricoReal(unittest.TestCase):
    """Pruebas con el HISTORICO_INVENTARIOS.xlsx del repositorio."""

    @classmethod
    def setUpClass(cls):
        cls.base, _ = m.leer_historico(ARCHIVO_HISTORICO_REAL)

    def test_mes_base_se_detecta_desde_las_columnas(self):
        self.assertEqual(m.meses_con_stock(self.base)[-1], (2026, 5))
        self.assertIn("COSTE MAYO 2026", self.base.columns)

    def test_antiguedad_stock_inicial_sin_consumo_es_mayor_a_12(self):
        h, _, _ = m.calcular_indicadores_12_meses(
            self.base.copy(), m.obtener_meses_disponibles(self.base)
        )
        grupo = h[
            (m.a_numero(h["STOCK INICIAL"]) > 0)
            & (h["CMV 12 MESES"].abs() <= 1e-7)
            & (h["STOCK MAYO 2026"] > 1e-7)
        ]
        self.assertEqual(len(grupo), 536)
        self.assertEqual(set(grupo[m.COL_ANTIGUEDAD_SALIDA]), {m.CLASIFICACION_MAYOR_12})

    def test_esquema_usa_coste_del_mismo_mes_que_el_stock(self):
        esc = Escenario(self.base)
        fila = self.base.iloc[1]
        res = esc.cargar([
            mov(f"2026-{mm:02d}-10", entrada=1, costo=10, bodega=fila["Bodega"], cod=fila["Codigo Articulo"])
            for mm in (6, 7, 8, 9)
        ])
        esq = m.construir_esquema(res["historico"])
        self.assertEqual(esq["col_stock"], "STOCK SEPTIEMBRE 2026")
        self.assertEqual(esq["col_coste"], "COSTE TOTAL SEPTIEMBRE 2026")

    def test_periodos_de_2027_funcionan(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        meses = [mov(f"2026-{mm:02d}-15", entrada=1, costo=10) for mm in range(6, 13)]
        meses.append(mov("2027-01-15", entrada=1, costo=10))
        res = esc.cargar(meses)
        self.assertEqual(valor(res["historico"], "STOCK ENERO 2027", LL_111), 108)
        self.assertEqual(res["stats"]["periodo_final"], "2027-01")


if __name__ == "__main__":
    unittest.main()
