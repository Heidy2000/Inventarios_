"""Pruebas de la conciliación mensual y del control de acceso."""
import unittest

import numpy as np
import pandas as pd

from datos_prueba import HERRAMIENTAS, REPUESTOS, Escenario, base_minima, g, m, mov

import acceso
import conciliacion as c


def tablero_junio():
    """Stock calculado: 1_111 = 105 (100 + 20 - 15), 1_222 = 10, 7_111 = 5."""
    esc = Escenario(base_minima([
        (REPUESTOS, "111", 100, 1000),
        (REPUESTOS, "222", 10, 100),
        (HERRAMIENTAS, "111", 5, 50),
        (REPUESTOS, "333", 0, 0),
    ]))
    esc.cargar([
        mov("2026-06-10", entrada=20, costo=200),
        mov("2026-06-20", salida=-15, costo=150),
    ])
    return esc.tablero(), esc


def real(filas):
    df = pd.DataFrame(filas, columns=["Bodega", "Codigo", "Descripcion", "Existencia"])
    df["_FILA_ORIGEN"] = np.arange(len(df)) + 2
    return df


def estado(tabla, llave):
    return tabla.loc[tabla["LLAVE"] == llave, "Estado"].iloc[0]


class TestConciliacion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.calc, cls.esc = tablero_junio()

    def conciliar(self, filas, **kw):
        return c.conciliar(self.calc, real(filas), "2026-06", "Bodega", "Codigo", "Existencia", "Descripcion", **kw)

    def test_inventario_real_igual_al_calculado_es_conciliado(self):
        t, r = self.conciliar([
            ["[1] - REPUESTOS", "111", "A", 105],
            ["1", "222", "B", 10],
            ["7", "111", "A7", 5],
        ])
        self.assertEqual(set(t["Estado"]), {c.ESTADO_CONCILIADO})
        fila = t[t["LLAVE"] == "1_111"].iloc[0]
        self.assertEqual(fila["Stock inicial calculado"], 100)
        self.assertEqual(fila["Entradas del mes"], 20)
        self.assertEqual(fila["Salidas del mes"], -15)
        self.assertEqual(fila["Stock final calculado"], 105)
        self.assertEqual(fila["Diferencia"], 0)

    def test_inventario_real_diferente_informa_la_diferencia(self):
        t, r = self.conciliar([["1", "111", "A", 100]])
        fila = t[t["LLAVE"] == "1_111"].iloc[0]
        self.assertEqual(fila["Estado"], c.ESTADO_DIFERENCIA)
        self.assertEqual(fila["Diferencia"], 5)          # calculado - real
        self.assertEqual(r["diferencia_neta"], 5)

    def test_tolerancia(self):
        t, _ = self.conciliar([["1", "111", "A", 104.995]], tolerancia=0.01)
        self.assertEqual(estado(t, "1_111"), c.ESTADO_CONCILIADO)

    def test_cero_reportado_es_dato_y_vacio_es_sin_dato(self):
        t, _ = self.conciliar([["1", "111", "A", 0], ["1", "222", "B", None]])
        # El 0 es un dato: se compara (diferencia 105) pero, por regla, con
        # existencias positivas en el Kardex se conserva el Kardex.
        self.assertEqual(estado(t, "1_111"), c.ESTADO_CONSERVA_KARDEX)
        self.assertEqual(t.loc[t["LLAVE"] == "1_111", "Diferencia"].iloc[0], 105)
        self.assertEqual(estado(t, "1_222"), c.ESTADO_SIN_REAL)

    def test_cantidad_no_numerica_queda_pendiente(self):
        t, _ = self.conciliar([["1", "111", "A", "abc"]])
        self.assertEqual(estado(t, "1_111"), c.ESTADO_PENDIENTE)
        self.assertTrue(pd.isna(t.loc[t["LLAVE"] == "1_111", "Stock final real reportado"].iloc[0]))

    def test_llave_duplicada_queda_pendiente(self):
        t, _ = self.conciliar([["1", "111", "A", 50], ["[1] - REPUESTOS", "111", "A", 55]])
        self.assertEqual(estado(t, "1_111"), c.ESTADO_PENDIENTE)
        self.assertIn("repetida", t.loc[t["LLAVE"] == "1_111", "Observación"].iloc[0])

    def test_presente_solo_en_un_archivo(self):
        t, r = self.conciliar([["1", "999", "Z", 3]])
        self.assertEqual(estado(t, "1_999"), c.ESTADO_SIN_CALCULO)
        self.assertEqual(estado(t, "1_222"), c.ESTADO_SIN_REAL)
        # Stock calculado 0 y ausente del real: se omite por defecto
        self.assertNotIn("1_333", t["LLAVE"].tolist())
        self.assertEqual(r["ceros_ausentes_omitidos"], 1)
        t2, _ = self.conciliar([["1", "999", "Z", 3]], incluir_ceros_ausentes=True)
        self.assertIn("1_333", t2["LLAVE"].tolist())

    def test_bodegas_excluidas_y_filas_sin_codigo(self):
        t, r = self.conciliar([["11", "1", "X", 1], ["1", None, "Y", 2]])
        self.assertEqual(r["filas_bodegas_excluidas"], 1)
        pend = t[(t["Estado"] == c.ESTADO_PENDIENTE) & (t["LLAVE"] == "")]
        self.assertEqual(len(pend), 1)

    def test_no_modifica_el_stock_calculado(self):
        antes = self.calc.copy()
        self.conciliar([["1", "111", "A", 1]])
        pd.testing.assert_frame_equal(antes, self.calc)

    def test_periodo_no_calculado(self):
        with self.assertRaises(ValueError):
            c.conciliar(self.calc, real([["1", "111", "A", 1]]), "2026-08",
                        "Bodega", "Codigo", "Existencia")

    def test_stock_inicial_del_mes_es_el_cierre_anterior(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        esc.cargar([mov("2026-06-10", entrada=20, costo=200), mov("2026-06-20", salida=-15, costo=150)])
        esc.cargar([mov("2026-07-05", salida=-5, costo=50)])
        t, _ = c.conciliar(esc.tablero(), real([["1", "111", "A", 100]]), "2026-07",
                           "Bodega", "Codigo", "Existencia")
        fila = t.iloc[0]
        self.assertEqual(fila["Stock inicial calculado"], 105)
        self.assertEqual(fila["Stock final calculado"], 100)
        self.assertEqual(fila["Estado"], c.ESTADO_CONCILIADO)

    def test_deteccion_de_columnas_y_lectura_con_titulo(self):
        import io
        buf = io.BytesIO()
        df = pd.DataFrame({"Bodega": ["1"], "Cod Articulo": ["111"], "Artículo": ["A"],
                           "Costo Total": [5], "Existencia": [105]})
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            pd.DataFrame([["INVENTARIO FINAL JUNIO"]]).to_excel(w, index=False, header=False)
            df.to_excel(w, index=False, startrow=2)
        leido, _ = c.leer_inventario_real(buf.getvalue(), "real.xlsx")
        cols = c.detectar_columnas(leido)
        self.assertEqual(cols["codigo"], "Cod Articulo")
        self.assertEqual(cols["cantidad"], "Existencia")
        self.assertEqual(cols["descripcion"], "Artículo")

    def test_historial_conserva_la_conciliacion(self):
        t, r = self.conciliar([["1", "111", "A", 100]])
        hist = c.HistorialConciliaciones(self.esc.dir)
        ident = hist.guardar(t, r, "real.xlsx", "admin")
        self.assertEqual(hist.registro()[-1]["id"], ident)
        recuperada = hist.leer(ident)
        self.assertEqual(len(recuperada), len(t))
        self.assertEqual(
            recuperada.loc[recuperada["LLAVE"] == "1_111", "Diferencia"].iloc[0], 5
        )
        self.assertTrue(len(c.a_excel(t, r)) > 0)


class TestAcceso(unittest.TestCase):

    def test_admin_ve_todas_las_paginas(self):
        self.assertEqual(
            acceso.paginas_permitidas("admin"),
            ["Resumen e inventario", "Evolución", "Riesgos y detalle",
             "Órdenes de compra", "Conciliación mensual", "Actualizar Kardex"],
        )

    def test_inventarios_solo_ve_tres_paginas(self):
        self.assertEqual(
            acceso.paginas_permitidas("inventarios"),
            ["Resumen e inventario", "Evolución", "Riesgos y detalle"],
        )

    def test_inventarios_no_es_admin_aunque_figure_en_admins(self):
        self.assertFalse(acceso.es_admin("inventarios", {"admins": ["admin", "inventarios"]}))

    def test_usuario_desconocido_tiene_menor_privilegio(self):
        self.assertEqual(acceso.paginas_permitidas("otro"), acceso.PAGINAS_CONSULTA)
        self.assertEqual(acceso.paginas_permitidas(""), acceso.PAGINAS_CONSULTA)

    def test_roles_configurados_en_secrets(self):
        sec = {"roles": {"jefe": "admin", "admin": "consulta"}}
        self.assertTrue(acceso.es_admin("jefe", sec))
        self.assertFalse(acceso.es_admin("admin", sec))

    def test_lista_admins_existente_se_respeta_para_otros_usuarios(self):
        self.assertTrue(acceso.es_admin("supervisor", {"admins": ["supervisor"]}))

    def test_inventarios_no_puede_cargar_kardex_por_otra_ruta(self):
        esc = Escenario(base_minima([(REPUESTOS, "111", 100, 1000)]))
        plan = esc.plan([mov("2026-06-10", entrada=1, costo=1)])
        with self.assertRaises(acceso.AccesoDenegado):
            g.ejecutar_cargue(plan, esc.base, esc.almacen, "inventarios", esc.ruta_actualizado)
        self.assertEqual(esc.almacen.periodos(), [])
        with self.assertRaises(acceso.AccesoDenegado):
            g.reprocesar_todo(esc.base, esc.almacen, "inventarios", esc.ruta_actualizado)


if __name__ == "__main__":
    unittest.main()
