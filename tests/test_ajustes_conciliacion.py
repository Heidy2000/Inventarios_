"""
Ajustes de conciliación: el inventario reconstruido con el Kardex se
lleva al inventario real del cierre, con ajustes separados y trazables.

Escenario base (cierre mayo 2026):
    1_111  stock 100  valor 1.000   (10 por unidad)
    1_222  stock  50  valor   500
    7_111  stock  10  valor   100
Kardex junio:
    1_111  +20 ($200)  -15 ($150)  -> 105 und.  $1.050
    1_222  -10 ($100)              ->  40 und.    $400
    7_111  -12 ($120)              ->  -2 und.    -$20  (salida sin existencia)
"""
import unittest

import numpy as np
import pandas as pd

from datos_prueba import HERRAMIENTAS, REPUESTOS, Escenario, base_minima, g, m, mov, valor

import conciliacion as c

KARDEX_JUNIO = [
    mov("2026-06-10", entrada=20, costo=200, cod="111"),
    mov("2026-06-20", salida=-15, costo=150, cod="111"),
    mov("2026-06-12", salida=-10, costo=100, cod="222"),
    mov("2026-06-15", salida=-12, costo=120, bodega=HERRAMIENTAS, cod="111"),
]

# Inventario real de junio: diferencias negativas y positivas
REAL_JUNIO = [
    # bodega, código, descripción, existencia, valor total
    ["1", "111", "A", 100, 1000],     # calc 105 / $1.050 -> -5 und. / -$50
    ["1", "222", "B", 45, 470],       # calc  40 /   $400 -> +5 und. / +$70
    ["7", "111", "A7", 0, 0],         # calc  -2 /   -$20 -> +2 und. / +$20
    ["1", "444", "D", 3, 90],         # no existe en el cálculo -> se crea
]


def escenario():
    esc = Escenario(base_minima([
        (REPUESTOS, "111", 100, 1000),
        (REPUESTOS, "222", 50, 500),
        (HERRAMIENTAS, "111", 10, 100),
    ]))
    esc.cargar(KARDEX_JUNIO, "kardex_junio.xlsx")
    return esc


def real(filas, con_valor=True):
    cols = ["Bodega", "Codigo", "Descripcion", "Existencia", "Valor Total"]
    df = pd.DataFrame(filas, columns=cols)
    if not con_valor:
        df = df.drop(columns=["Valor Total"])
    df["_FILA_ORIGEN"] = np.arange(len(df)) + 2
    return df


def conciliar(esc, filas, periodo="2026-06", con_valor=True, **kw):
    return c.conciliar(
        esc.tablero(), real(filas, con_valor), periodo, "Bodega", "Codigo",
        "Existencia", "Descripcion",
        col_valor="Valor Total" if con_valor else None, **kw,
    )


def aplicar(esc, tabla, periodo="2026-06", usuario="admin", **kw):
    propuesta = c.ajustes_propuestos(tabla, **kw)
    res, _ = g.aplicar_ajustes_conciliacion(
        periodo, propuesta, esc.base, esc.almacen, usuario, esc.ruta_actualizado,
        archivo="real_junio.xlsx",
    )
    return res, propuesta


def fila(tabla, llave):
    return tabla[tabla["LLAVE"] == llave].iloc[0]


class TestComparacion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.esc = escenario()
        cls.tabla, cls.resumen = conciliar(cls.esc, REAL_JUNIO)

    def test_diferencia_negativa_en_unidades_y_valor(self):
        f = fila(self.tabla, "1_111")
        self.assertEqual(f["Stock final calculado"], 105)
        self.assertEqual(f["Valor final calculado"], 1050)
        self.assertEqual(f["Diferencia"], 5)            # calculado - real
        self.assertEqual(f["Diferencia valor"], 50)
        self.assertEqual(f["Ajuste unidades propuesto"], -5)   # real - calculado
        self.assertEqual(f["Ajuste valor propuesto"], -50)
        self.assertEqual(f["Estado"], c.ESTADO_DIFERENCIA)

    def test_diferencia_positiva_en_unidades_y_valor(self):
        f = fila(self.tabla, "1_222")
        self.assertEqual(f["Diferencia"], -5)
        self.assertEqual(f["Diferencia valor"], -70)
        self.assertEqual(f["Ajuste unidades propuesto"], 5)
        self.assertEqual(f["Ajuste valor propuesto"], 70)

    def test_stock_negativo_por_salida_sin_existencia_se_compara(self):
        f = fila(self.tabla, "7_111")
        self.assertEqual(f["Stock final calculado"], -2)
        self.assertEqual(f["Salidas del mes"], -12)     # la salida conserva su signo
        self.assertEqual(f["Ajuste unidades propuesto"], 2)
        self.assertEqual(f["Ajuste valor propuesto"], 20)

    def test_referencia_solo_en_el_real(self):
        f = fila(self.tabla, "1_444")
        self.assertEqual(f["Estado"], c.ESTADO_SIN_CALCULO)
        self.assertEqual(f["Ajuste unidades propuesto"], 3)
        self.assertEqual(f["Ajuste valor propuesto"], 90)

    def test_solo_valor_diferente(self):
        t, _ = conciliar(self.esc, [["1", "111", "A", 105, 1100]])
        f = fila(t, "1_111")
        self.assertEqual(f["Diferencia"], 0)
        self.assertEqual(f["Diferencia valor"], -50)
        self.assertEqual(f["Estado"], c.ESTADO_DIFERENCIA)
        self.assertEqual(f["Ajuste unidades propuesto"], 0)
        self.assertEqual(f["Ajuste valor propuesto"], 50)

    def test_tolerancia_de_valor(self):
        t, _ = conciliar(self.esc, [["1", "111", "A", 105, 1050.4]], tolerancia_valor=1)
        self.assertEqual(fila(t, "1_111")["Estado"], c.ESTADO_CONCILIADO)

    def test_valor_no_numerico_queda_pendiente_y_no_se_ajusta(self):
        t, _ = conciliar(self.esc, [["1", "111", "A", 100, "N/A"]])
        self.assertEqual(fila(t, "1_111")["Estado"], c.ESTADO_PENDIENTE)
        self.assertEqual(len(c.ajustes_propuestos(t)), 0)

    def test_resumen_separa_ajustes_positivos_y_negativos(self):
        r = self.resumen
        self.assertEqual(r["ajuste_unidades_positivo"], 10)    # +5 +2 +3
        self.assertEqual(r["ajuste_unidades_negativo"], -5)
        self.assertEqual(r["ajuste_valor_positivo"], 180)      # 70 + 20 + 90
        self.assertEqual(r["ajuste_valor_negativo"], -50)


class TestAplicarAjustes(unittest.TestCase):

    def setUp(self):
        self.esc = escenario()
        tabla, _ = conciliar(self.esc, REAL_JUNIO)
        self.res, self.propuesta = aplicar(self.esc, tabla)
        self.h = self.res["historico"]

    def test_el_inventario_queda_igual_al_real(self):
        for llave, und, val in [("1_111", 100, 1000), ("1_222", 45, 470), ("7_111", 0, 0), ("1_444", 3, 90)]:
            with self.subTest(llave=llave):
                self.assertEqual(valor(self.h, "STOCK JUNIO 2026", llave), und)
                self.assertEqual(valor(self.h, "COSTE TOTAL JUNIO 2026", llave), val)

    def test_ajustes_identificados_en_columnas_propias(self):
        self.assertEqual(valor(self.h, "AJUSTE CONCILIACION UNIDADES JUNIO 2026", "1_111"), -5)
        self.assertEqual(valor(self.h, "AJUSTE CONCILIACION VALOR JUNIO 2026", "1_111"), -50)
        self.assertEqual(valor(self.h, "AJUSTE CONCILIACION UNIDADES JUNIO 2026", "1_222"), 5)
        self.assertEqual(valor(self.h, "AJUSTE CONCILIACION VALOR JUNIO 2026", "1_222"), 70)

    def test_movimientos_originales_y_signos_sin_cambios(self):
        self.assertEqual(valor(self.h, "ENTRADA JUNIO 2026", "1_111"), 20)
        self.assertEqual(valor(self.h, "SALIDA JUNIO 2026", "1_111"), -15)
        self.assertEqual(valor(self.h, "SALIDA JUNIO 2026", "7_111"), -12)
        self.assertEqual(valor(self.h, "COSTO SALIDA JUNIO 2026", "1_111"), -150)
        mov_k = self.res["movimientos"]
        kardex = mov_k[mov_k["Tipo movimiento"] == m.TIPO_KARDEX]
        ajustes = mov_k[mov_k["Tipo movimiento"] == m.TIPO_AJUSTE_CONCILIACION]
        self.assertEqual(len(kardex), 4)
        self.assertEqual(len(ajustes), 4)
        self.assertTrue((kardex["Ajuste conciliación unidades"] == 0).all())
        self.assertTrue((ajustes["Entrada aplicada"] == 0).all())
        self.assertTrue((ajustes["Salida aplicada"] == 0).all())

    def test_el_ajuste_no_cambia_el_costo_de_ventas(self):
        self.assertEqual(valor(self.h, "CMV 12 MESES", "1_111"), 150)

    def test_hoja_de_control_trazable(self):
        aj = self.res["ajustes_conciliacion"].set_index("LLAVE")
        self.assertEqual(aj.loc["1_111", "Stock calculado antes del ajuste"], 105)
        self.assertEqual(aj.loc["1_111", "Stock real"], 100)
        self.assertEqual(aj.loc["1_111", "Ajuste unidades"], -5)
        self.assertEqual(aj.loc["1_111", "Valor calculado antes del ajuste"], 1050)
        self.assertEqual(aj.loc["1_111", "Ajuste valor"], -50)
        self.assertEqual(aj.loc["1_111", "Origen del valor"], m.ORIGEN_VALOR_ARCHIVO)
        self.assertEqual(aj.loc["1_111", "Usuario"], "admin")
        self.assertEqual(aj.loc["1_111", "Archivo"], "real_junio.xlsx")
        self.assertFalse(aj["Cambió desde la aprobación"].any())
        nueva = self.h[self.h["LLAVE"] == "1_444"].iloc[0]
        self.assertEqual(nueva["OBSERVACION"], m.MARCA_NUEVO_CONCILIACION)
        self.assertEqual(nueva["Bodega"], REPUESTOS)   # nombre completo de la bodega
        self.assertEqual([v for v in self.res["verificaciones"] if not v[1]], [])

    def test_volver_a_conciliar_muestra_conciliado_con_ajuste(self):
        tabla, resumen = conciliar(self.esc, REAL_JUNIO)
        self.assertEqual(set(tabla["Estado"]), {c.ESTADO_AJUSTADO})
        f = fila(tabla, "1_111")
        self.assertEqual(f["Stock final calculado"], 105)   # lo que deja el Kardex
        self.assertEqual(f["Ajuste vigente unidades"], -5)
        self.assertEqual(f["Stock final ajustado"], 100)

    def test_aplicar_dos_veces_no_duplica(self):
        tabla, _ = conciliar(self.esc, REAL_JUNIO)
        res2, _ = aplicar(self.esc, tabla)
        h2 = res2["historico"]
        self.assertEqual(valor(h2, "STOCK JUNIO 2026", "1_111"), 100)
        self.assertEqual(valor(h2, "AJUSTE CONCILIACION UNIDADES JUNIO 2026", "1_111"), -5)
        self.assertEqual(len(res2["ajustes_conciliacion"]), 4)
        vigentes = [r for r in self.esc.almacen.registro_ajustes() if r["vigente"]]
        self.assertEqual(len(vigentes), 1)

    def test_el_mes_siguiente_parte_del_inventario_ajustado(self):
        res = self.esc.cargar([mov("2026-07-05", salida=-10, costo=100, cod="111")], "kardex_julio.xlsx")
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JULIO 2026", "1_111"), 90)
        self.assertEqual(valor(h, "COSTE TOTAL JULIO 2026", "1_111"), 900)
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "1_111"), 100)   # el ajuste se conserva

    def test_corregir_el_kardex_del_mes_recalcula_el_ajuste(self):
        corregido = [mov("2026-06-10", entrada=25, costo=250, cod="111")] + KARDEX_JUNIO[1:]
        plan = self.esc.plan(corregido, "kardex_junio_v2.xlsx")
        self.assertEqual(plan["con_ajustes"], ["2026-06"])
        res, _ = g.ejecutar_cargue(plan, self.esc.base, self.esc.almacen, "admin",
                                   self.esc.ruta_actualizado, confirmar_reemplazo=True)
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "1_111"), 100)      # sigue igual al real
        self.assertEqual(valor(h, "AJUSTE CONCILIACION UNIDADES JUNIO 2026", "1_111"), -10)
        aj = res["ajustes_conciliacion"].set_index("LLAVE")
        self.assertTrue(aj.loc["1_111", "Cambió desde la aprobación"])
        self.assertEqual(aj.loc["1_111", "Ajuste unidades aprobado"], -5)

    def test_retirar_ajustes_vuelve_al_kardex(self):
        res, _ = g.retirar_ajustes_conciliacion("2026-06", self.esc.base, self.esc.almacen,
                                               "admin", self.esc.ruta_actualizado)
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "1_111"), 105)
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "7_111"), -2)
        self.assertEqual(len(res["ajustes_conciliacion"]), 0)
        self.assertEqual(self.esc.almacen.periodos_ajustados(), [])

    def test_inventarios_no_puede_aplicar_ajustes(self):
        import acceso
        tabla, _ = conciliar(self.esc, REAL_JUNIO)
        with self.assertRaises(acceso.AccesoDenegado):
            aplicar(self.esc, tabla, usuario="inventarios")


class TestCasosEspeciales(unittest.TestCase):

    def test_sin_columna_de_valor_usa_el_costo_unitario(self):
        esc = escenario()
        filas = [r[:4] + [None] for r in REAL_JUNIO[:2]]
        tabla, _ = conciliar(esc, filas, con_valor=False)
        res, _ = aplicar(esc, tabla)
        h = res["historico"]
        # 1_111: 100 und. x ($1.050 / 105) = $1.000 ; 1_222: 45 x 10 = $450
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "1_111"), 100)
        self.assertEqual(valor(h, "COSTE TOTAL JUNIO 2026", "1_111"), 1000)
        self.assertEqual(valor(h, "COSTE TOTAL JUNIO 2026", "1_222"), 450)
        aj = res["ajustes_conciliacion"].set_index("LLAVE")
        self.assertEqual(aj.loc["1_111", "Origen del valor"], m.ORIGEN_VALOR_UNITARIO)

    def test_ausentes_se_llevan_a_cero_solo_si_se_pide(self):
        esc = escenario()
        tabla, _ = conciliar(esc, REAL_JUNIO[:1])
        sin = c.ajustes_propuestos(tabla)
        self.assertNotIn("222", sin["Codigo Articulo"].tolist())
        res, _ = aplicar(esc, tabla, ausentes_como_cero=True)
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "1_222"), 0)
        self.assertEqual(valor(h, "COSTE TOTAL JUNIO 2026", "1_222"), 0)
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "7_111"), 0)

    def test_solo_se_ajustan_periodos_con_kardex(self):
        esc = escenario()
        tabla, _ = conciliar(esc, [["1", "111", "A", 90, 900]], periodo="2026-05")
        with self.assertRaises(ValueError):
            aplicar(esc, tabla, periodo="2026-05")

    def test_nuevo_inventario_real_reemplaza_y_retira_lo_que_ya_no_aplica(self):
        esc = escenario()
        tabla, _ = conciliar(esc, REAL_JUNIO)
        aplicar(esc, tabla)
        # Nuevo conteo: 1_111 coincide con el Kardex; 1_222 con otra cantidad
        nuevo = [["1", "111", "A", 105, 1050], ["1", "222", "B", 41, 410]]
        tabla2, _ = conciliar(esc, nuevo)
        self.assertEqual(fila(tabla2, "1_111")["Estado"], c.ESTADO_DIFERENCIA)
        propuesta = c.ajustes_propuestos(tabla2)
        retirados = c.ajustes_que_se_retiran(tabla2, propuesta)
        self.assertIn("1_111", retirados["LLAVE"].tolist())
        res, _ = aplicar(esc, tabla2)
        h = res["historico"]
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "1_111"), 105)
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "1_222"), 41)
        self.assertEqual(valor(h, "STOCK JUNIO 2026", "7_111"), -2)


if __name__ == "__main__":
    unittest.main()
