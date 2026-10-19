# -*- coding: utf-8 -*-
"""
motor_lifo.py
Motor de cálculo Histórico + Kardex del tablero Inventarios ALDC.

* Parte del último mes del histórico base (mayo 2026 en el archivo
  inicial; se detecta por las columnas, no está fijo en el código) y
  reconstruye los meses siguientes con los movimientos del Kardex:
      stock final = stock inicial + entradas + salidas (salidas < 0)
* Respeta el signo de las cantidades según la convención del archivo.
* Conserva las reglas de negocio: bodegas 11, 12, 18, 19, 20 y 21
  excluidas, movimientos ANULADO excluidos, costo con IVA, salidas sin
  existencia registradas y no descontadas.
* La reconstrucción de lotes LIFO se conserva para la trazabilidad y
  las hojas de control.
* La antigüedad se calcula con los indicadores de 12 meses (inventario
  promedio, CMV, días de rotación) en la columna ANTIGUEDAD 12 MESES,
  última columna de la tabla.

La gestión de cargues mensuales (periodos guardados, reemplazos,
continuidad) está en gestion_kardex.py.
"""
import io
import os
import re
import unicodedata
from collections import defaultdict

import numpy as np
import pandas as pd
import openpyxl


EPS = 1e-7
HOJA_SALIDA = "INVENTARIO"

NOMBRES_MES = [
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
    "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
]

# Se excluyen por NÚMERO de bodega
BODEGAS_EXCLUIDAS = {"11", "12", "18", "19", "20", "21"}

MARCA_NUEVO = "NUEVO DESDE KARDEX"
MARCA_NUEVO_CONCILIACION = "NUEVO DESDE CONCILIACION"

TIPO_KARDEX = "KARDEX"
TIPO_AJUSTE_CONCILIACION = "AJUSTE CONCILIACION"

# Fecha que representa el stock inicial cuando el histórico no permite
# deducirla (se usa el último día del mes anterior al primer mes del
# histórico; con el archivo base actual es el 31-may-2025).
FECHA_STOCK_INICIAL = pd.Timestamp("2025-05-31")

# ============================================================
# PARÁMETROS DE LA METODOLOGÍA DE INVENTARIO
# ============================================================

MESES_ANALISIS = 12

# Cada mes se toma como 30 días (días del período = meses usados x 30)
DIAS_POR_MES = 30
DIAS_VENTANA_COMPLETA = DIAS_POR_MES * MESES_ANALISIS  # 360

# Una referencia es "reciente" si lleva menos de 6 meses con stock/registro
MESES_REFERENCIA_RECIENTE = 6

# Si el coste mensual está entre -1 y 1 (incluidos), para el
# inventario promedio se utiliza el COSTO ENTRADA del mismo mes.
# Esta sustitución NO modifica el CMV.
LIMITE_COSTE_REEMPLAZO = 1.0

CLASIFICACION_0_3 = "Entre 0 y 3 meses"
CLASIFICACION_4_6 = "Entre 4 y 6 meses"
CLASIFICACION_7_12 = "Entre 7 y 12 meses"
CLASIFICACION_MAYOR_12 = "Mayor a 12 meses"
CLASIFICACION_SIN = "Sin clasificación"

# Única columna de antigüedad. Queda como la última de la tabla.
COL_ANTIGUEDAD_SALIDA = "ANTIGUEDAD 12 MESES"

# Nombres antiguos de la antigüedad que se retiran para no dejar
# dos columnas de antigüedad con valores distintos.
COLUMNAS_ANTIGUEDAD_ANTERIORES = (
    "ANTIGUEDAD ULTIMO MES DE ACTUALIZACION",
    "MESES",
)


def _fin_mes(anio, mes):
    return pd.Timestamp(anio, mes, 1) + pd.offsets.MonthEnd(0)


# ============================================================
# PERIODOS (año + mes) — SIN AÑOS FIJOS EN EL CÓDIGO
# ============================================================

def periodo_num(anio, mes):
    """Número correlativo del periodo (permite restar meses)."""
    return int(anio) * 12 + int(mes)


def periodo_de_num(numero):
    """Inverso de periodo_num -> (anio, mes)."""
    numero = int(numero)
    anio = (numero - 1) // 12
    return anio, numero - anio * 12


def etiqueta_periodo(anio, mes):
    """'2026-06'"""
    return f"{int(anio)}-{int(mes):02d}"


def periodo_de_etiqueta(etiqueta):
    """'2026-06' -> (2026, 6)"""
    anio, mes = str(etiqueta).strip().split("-")
    return int(anio), int(mes)


def nombre_periodo(anio, mes):
    """'JUNIO 2026' (sufijo usado en los nombres de columna)."""
    return f"{NOMBRES_MES[int(mes) - 1]} {int(anio)}"


def fin_periodo(anio, mes):
    """Último instante del mes."""
    return _fin_mes(anio, mes) + pd.Timedelta(hours=23, minutes=59, seconds=59)


_PATRON_STOCK_MES = re.compile(r"^STOCK\s+([A-Z]+)\s+(\d{4})$")


def meses_con_stock(df):
    """
    Periodos (anio, mes) que tienen columna 'STOCK <MES> <AÑO>',
    en orden cronológico. El último es el corte del archivo.
    """
    encontrados = set()

    for c in df.columns:
        m = _PATRON_STOCK_MES.match(norm(c))
        if m and m.group(1) in NOMBRES_MES:
            encontrados.add((int(m.group(2)), NOMBRES_MES.index(m.group(1)) + 1))

    return sorted(encontrados)


def col_coste_mes(df, nombre, anio):
    """Columna de coste (valor del inventario) de un mes."""
    sfx = f"{nombre} {anio}"
    return col_exacta(df, f"COSTE TOTAL {sfx}") or col_exacta(df, f"COSTE {sfx}")


# ============================================================
# UTILIDADES
# ============================================================

def norm(nombre):
    t = str(nombre).strip().upper()
    t = "".join(
        c for c in unicodedata.normalize("NFD", t)
        if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", t)


def col_exacta(df, nombre):
    objetivo = norm(nombre)
    for c in df.columns:
        if norm(c) == objetivo:
            return c
    return None


def col_buscar(df, candidatos, obligatoria=True):
    # Primero búsqueda exacta
    for cand in candidatos:
        c = col_exacta(df, cand)
        if c is not None:
            return c

    # Luego búsqueda parcial
    cands = [norm(x) for x in candidatos]
    for cand in cands:
        for c in df.columns:
            if cand in norm(c):
                return c

    if obligatoria:
        raise ValueError(
            "No se encontró ninguna de estas columnas: "
            + ", ".join(candidatos)
            + ". Columnas disponibles: "
            + ", ".join(str(c) for c in df.columns[:40])
        )
    return None


def detectar_fila_encabezado(origen, hoja, columnas, minimo=2, max_filas=40):
    tmp = pd.read_excel(origen, sheet_name=hoja, header=None, nrows=max_filas)
    buscadas = [norm(x) for x in columnas]

    for i in range(len(tmp)):
        vals = [norm(v) for v in tmp.iloc[i].tolist() if not pd.isna(v)]
        if sum(1 for b in buscadas if any(b in v for v in vals)) >= minimo:
            return i
    return None


def _a_float(valor):
    if pd.isna(valor):
        return 0.0

    v = str(valor).strip()
    if v == "" or v.lower() in ("nan", "none", "nat"):
        return 0.0

    v = v.replace("$", "").replace(" ", "")

    if "." in v and "," in v:
        if v.rfind(",") > v.rfind("."):
            v = v.replace(".", "").replace(",", ".")
        else:
            v = v.replace(",", "")
    elif "," in v:
        p = v.split(",")
        if len(p) == 2 and len(p[1]) <= 4:
            v = p[0] + "." + p[1]
        else:
            v = "".join(p)
    elif "." in v:
        p = v.split(".")
        if len(p) > 2:
            v = "".join(p)

    try:
        return float(v)
    except Exception:
        # Texto que no es un número: se marca como NaN para que
        # a_numero_validado pueda informarlo. a_numero lo deja en 0
        # (comportamiento histórico para las columnas del histórico).
        return np.nan


def a_numero(serie):
    """Convierte a número; vacíos y textos no numéricos quedan en 0."""
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce").fillna(0.0).astype(float)
    return serie.apply(_a_float).astype(float).fillna(0.0)


def a_numero_validado(serie):
    """
    Igual que a_numero, pero además devuelve la máscara de celdas con
    texto que NO es un número (p. ej. 'N/A', '12a'). Una celda vacía
    se considera 0 y es válida: en el Kardex una fila de entrada trae
    la salida vacía y viceversa.
    """
    if pd.api.types.is_numeric_dtype(serie):
        valores = pd.to_numeric(serie, errors="coerce").astype(float)
        return valores.fillna(0.0), pd.Series(False, index=serie.index)

    convertidos = serie.apply(_a_float).astype(float)
    vacios = serie.apply(lambda v: texto(v) == "")
    invalidos = convertidos.isna() & ~vacios
    return convertidos.fillna(0.0), invalidos


def texto(valor):
    if pd.isna(valor):
        return ""
    v = str(valor).strip()
    if v.lower() in ("nan", "none", "nat"):
        return ""
    return v


def codigo(valor):
    t = texto(valor)
    if t == "":
        return ""
    try:
        n = float(t)
        if n.is_integer():
            return str(int(n))
    except Exception:
        pass
    return t


def bodega_txt(valor):
    return re.sub(r"\s+", " ", texto(valor)).strip()


def numero_bodega(valor):
    t = texto(valor)
    m = re.search(r"\[\s*(\d+)\s*\]", t) or re.match(r"^\s*(\d+)\b", t)
    if m:
        return m.group(1).lstrip("0") or "0"
    return t.upper()


def crear_llave(bodega, cod):
    return f"{numero_bodega(bodega)}_{codigo(cod)}"


# ============================================================
# ANTIGÜEDAD LIFO (SOLO COMPATIBILIDAD)
# ============================================================
# Se conservan estas funciones por compatibilidad con el motor
# y las hojas de control. YA NO SE UTILIZAN PARA CLASIFICAR
# LA ANTIGÜEDAD DEL INVENTARIO.
# ============================================================

def bucket_antiguedad(fecha_lote, fecha_corte):
    if fecha_lote is None or pd.isna(fecha_lote):
        return "Sin trazabilidad"

    fecha_lote = pd.Timestamp(fecha_lote)
    fecha_corte = pd.Timestamp(fecha_corte)
    meses = max((fecha_corte - fecha_lote).days, 0) / 30.4375

    if meses <= 3:
        return CLASIFICACION_0_3
    if meses <= 6:
        return CLASIFICACION_4_6
    if meses <= 12:
        return CLASIFICACION_7_12
    return CLASIFICACION_MAYOR_12


def antiguedad_lifo(lotes, stock, fecha_corte):
    if stock <= EPS:
        return "Sin stock"

    vivos = [l for l in lotes if float(l.get("cantidad", 0.0)) > EPS]
    if not vivos:
        return "Sin trazabilidad"

    fechas = []
    for lote in vivos:
        fecha = lote.get("fecha")
        if fecha is None or pd.isna(fecha):
            return "Sin trazabilidad"
        fechas.append(pd.Timestamp(fecha))

    if not fechas:
        return "Sin trazabilidad"

    return bucket_antiguedad(min(fechas), fecha_corte)


def consumir_lifo(lotes, cantidad):
    consumos = []
    pendiente = cantidad

    while pendiente > EPS and lotes:
        lote = lotes[-1]

        if lote["cantidad"] <= EPS:
            lotes.pop()
            continue

        c = min(lote["cantidad"], pendiente)
        lote["cantidad"] -= c
        pendiente -= c
        consumos.append((lote, c))

        if lote["cantidad"] <= EPS:
            lotes.pop()

    return consumos, max(pendiente, 0.0)


def _leer_bytes(origen):
    """Acepta ruta, bytes o archivo subido de Streamlit."""
    if isinstance(origen, (bytes, bytearray)):
        return bytes(origen)

    if isinstance(origen, str):
        with open(origen, "rb") as f:
            return f.read()

    return origen.getvalue() if hasattr(origen, "getvalue") else origen.read()


# ============================================================
# LECTURA DEL HISTÓRICO
# ============================================================

def preparar_historico(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(axis=0, how="all").reset_index(drop=True)

    c_bod = col_buscar(df, ["Bodega"])
    c_cod = col_buscar(df, ["Codigo Articulo"])

    df[c_bod] = df[c_bod].apply(bodega_txt)
    df[c_cod] = df[c_cod].apply(codigo)

    # --------------------------------------------------------
    # MES DE CORTE DEL ARCHIVO: el último 'STOCK <MES> <AÑO>'.
    # (Antes estaba fijo en 'STOCK MAYO 2026'.)
    # --------------------------------------------------------
    meses = meses_con_stock(df)
    if not meses:
        raise ValueError(
            "El histórico no tiene columnas 'STOCK <MES> <AÑO>' "
            "(por ejemplo 'STOCK MAYO 2026')."
        )

    anio_c, mes_c = meses[-1]
    nombre_c = NOMBRES_MES[mes_c - 1]
    sfx_c = f"{nombre_c} {anio_c}"
    c_stock = col_exacta(df, f"STOCK {sfx_c}")

    # Coste del mes de corte. Si viene sin año (p. ej. 'COSTE TOTAL
    # MAYO', como en el archivo base) se renombra a 'COSTE MAYO 2026'.
    if col_coste_mes(df, nombre_c, anio_c) is None:
        c_coste = None
        for cand in [
            f"COSTE TOTAL {nombre_c}",
            f"COSTO TOTAL {nombre_c}",
            f"COSTE {nombre_c}",
            f"COSTO {sfx_c}",
            f"COSTO TOTAL {sfx_c}",
        ]:
            c_coste = col_exacta(df, cand)
            if c_coste:
                break

        if c_coste is not None:
            df = df.rename(columns={c_coste: f"COSTE {sfx_c}"})
        else:
            # Reconstrucción: coste del mes anterior + costo de
            # entradas + costo de salidas (las salidas restan).
            anio_p, mes_p = periodo_de_num(periodo_num(anio_c, mes_c) - 1)
            c_prev = col_coste_mes(df, NOMBRES_MES[mes_p - 1], anio_p)
            c_ent = col_exacta(df, f"COSTO ENTRADA {sfx_c}")
            c_sal = col_exacta(df, f"COSTO SALIDA {sfx_c}")

            if c_prev is None or c_ent is None:
                raise ValueError(
                    f"El histórico no trae el coste de {sfx_c.lower()} "
                    "y no se puede reconstruir (falta el coste del mes "
                    "anterior y/o el costo de entrada del mes)."
                )

            coste = a_numero(df[c_prev]) + a_numero(df[c_ent])
            if c_sal is not None:
                coste = coste - a_numero(df[c_sal]).abs()
            df[f"COSTE {sfx_c}"] = coste

    c_coste_final = col_coste_mes(df, nombre_c, anio_c)
    df[c_coste_final] = a_numero(df[c_coste_final])
    df[c_stock] = a_numero(df[c_stock])

    df["LLAVE"] = df.apply(lambda f: crear_llave(f[c_bod], f[c_cod]), axis=1)

    if col_exacta(df, "OBSERVACION") is None:
        df["OBSERVACION"] = ""

    return df


def leer_historico(origen):
    contenido = _leer_bytes(origen)
    xl = pd.ExcelFile(io.BytesIO(contenido))

    for hoja in xl.sheet_names:
        fila = detectar_fila_encabezado(
            io.BytesIO(contenido),
            hoja,
            ["Bodega", "Codigo Articulo"],
            minimo=2,
        )

        if fila is not None:
            df = pd.read_excel(io.BytesIO(contenido), sheet_name=hoja, header=fila)
            return preparar_historico(df), hoja

    raise ValueError(
        "No se encontró una hoja con 'Bodega' y 'Codigo Articulo' "
        "en el histórico."
    )


# ============================================================
# LECTURA DEL KARDEX
# ============================================================

REQ_KARDEX = [
    "Bodega",
    "Codigo Articulo",
    "Fecha Movimiento",
    "Cantidad Entrada",
    "Cantidad Salida",
]


def leer_kardex(origen):
    contenido = _leer_bytes(origen)
    xl = pd.ExcelFile(io.BytesIO(contenido))

    hojas = sorted(
        xl.sheet_names,
        key=lambda h: 0 if "LISTAEXPORTADA" in norm(h) else 1,
    )

    hoja_k = None
    fila_k = None

    for hoja in hojas:
        fila = detectar_fila_encabezado(
            io.BytesIO(contenido),
            hoja,
            REQ_KARDEX,
            minimo=len(REQ_KARDEX),
        )

        if fila is not None:
            hoja_k = hoja
            fila_k = fila
            break

    if hoja_k is None:
        raise ValueError(
            "El archivo no contiene un Kardex detallado "
            "(se necesitan: " + ", ".join(REQ_KARDEX) + "). "
            "Una tabla dinámica no sirve."
        )

    wb = openpyxl.load_workbook(
        io.BytesIO(contenido), read_only=True, data_only=True
    )
    filas = list(wb[hoja_k].iter_rows(values_only=True))
    wb.close()

    encabezados = []
    vistos = defaultdict(int)

    for i, h in enumerate(filas[fila_k]):
        nombre = str(h).strip() if h is not None else f"COL_VACIA_{i}"
        vistos[nombre] += 1
        if vistos[nombre] > 1:
            nombre = f"{nombre}_{vistos[nombre]}"
        encabezados.append(nombre)

    ancho = len(encabezados)
    datos = [
        (tuple(f) + (None,) * ancho)[:ancho] for f in filas[fila_k + 1:]
    ]
    k = pd.DataFrame(datos, columns=encabezados)

    # Fila de Excel de cada movimiento (para reportar rechazos).
    k["_FILA_ORIGEN"] = np.arange(len(k)) + fila_k + 2

    columnas_datos = [c for c in k.columns if c != "_FILA_ORIGEN"]
    k = (
        k.dropna(axis=0, how="all", subset=columnas_datos)
        .reset_index(drop=True)
    )
    vacias = [c for c in columnas_datos if k[c].isna().all()]
    k = k.drop(columns=vacias)

    if k.empty:
        raise ValueError(
            "El Kardex tiene encabezados pero no contiene movimientos."
        )

    return k, hoja_k


# ============================================================
# MESES DISPONIBLES EN LA BASE
# ============================================================

def obtener_meses_disponibles(df):
    """
    Detecta automáticamente todos los meses que existen en la base
    utilizando las columnas mensuales (STOCK, COSTE, ENTRADA, SALIDA,
    COSTO ENTRADA, COSTO SALIDA). Devuelve la lista ordenada
    cronológicamente, sin meses repetidos.
    """
    encontrados = []

    patron = re.compile(
        r"^(STOCK|COSTE TOTAL|COSTE|ENTRADA|SALIDA|"
        r"COSTO ENTRADA|COSTO SALIDA)\s+"
        r"(.+)\s+(\d{4})$"
    )

    for c in df.columns:
        m = patron.match(norm(c))
        if not m:
            continue

        nombre_mes = m.group(2)
        anio = int(m.group(3))

        if nombre_mes not in NOMBRES_MES:
            continue

        mes_num = NOMBRES_MES.index(nombre_mes) + 1

        encontrados.append(
            {
                "nombre": nombre_mes,
                "anio": anio,
                "mes": mes_num,
                "fecha": _fin_mes(anio, mes_num),
            }
        )

    unicos = {(x["anio"], x["mes"]): x for x in encontrados}
    return sorted(unicos.values(), key=lambda x: x["fecha"])


def obtener_ultimos_12_meses(df, avisos=None):
    """
    Obtiene los 12 meses cronológicamente más recientes disponibles.
    Si existen menos de 12, utiliza todos los disponibles.
    """
    if avisos is None:
        avisos = []

    disponibles = obtener_meses_disponibles(df)

    if not disponibles:
        raise ValueError(
            "No se encontraron meses disponibles en la base de datos."
        )

    ultimos = disponibles[-MESES_ANALISIS:]

    if len(ultimos) < MESES_ANALISIS:
        avisos.append(
            f"La base contiene únicamente {len(ultimos)} meses "
            f"disponibles para el cálculo. Se utilizarán todos los "
            f"meses disponibles en lugar de los {MESES_ANALISIS} "
            f"meses requeridos."
        )

    return ultimos


def columnas_mes(df, nombre, anio):
    """Detecta las columnas correspondientes a un mes."""
    sfx = f"{nombre} {anio}"

    return {
        "stock": col_exacta(df, f"STOCK {sfx}"),
        "coste": (
            col_exacta(df, f"COSTE TOTAL {sfx}")
            or col_exacta(df, f"COSTE {sfx}")
        ),
        "entrada": col_exacta(df, f"ENTRADA {sfx}"),
        "salida": col_exacta(df, f"SALIDA {sfx}"),
        "costo_entrada": col_exacta(df, f"COSTO ENTRADA {sfx}"),
        "costo_salida": col_exacta(df, f"COSTO SALIDA {sfx}"),
    }


# ============================================================
# CLASIFICACIÓN DE ANTIGÜEDAD (NUEVA LÓGICA)
# ============================================================

def clasificar_meses(meses):
    """Antigüedad según los meses transcurridos desde el primer stock."""
    if meses <= 3:
        return CLASIFICACION_0_3
    if meses <= 6:
        return CLASIFICACION_4_6
    if meses <= 12:
        return CLASIFICACION_7_12
    return CLASIFICACION_MAYOR_12


def clasificar_dias(dias):
    """Antigüedad según los días de rotación (meses de 30 días)."""
    if pd.isna(dias) or not np.isfinite(dias):
        return CLASIFICACION_SIN
    if dias <= 90:
        return CLASIFICACION_0_3
    if dias <= 180:
        return CLASIFICACION_4_6
    if dias <= 360:
        return CLASIFICACION_7_12
    return CLASIFICACION_MAYOR_12


def _clasificar_por_cortes(valores, corte_1, corte_2, corte_3):
    """Versión vectorizada de clasificar_meses / clasificar_dias."""
    return np.select(
        [valores <= corte_1, valores <= corte_2, valores <= corte_3],
        [CLASIFICACION_0_3, CLASIFICACION_4_6, CLASIFICACION_7_12],
        default=CLASIFICACION_MAYOR_12,
    )


def _matriz_mes(hist, meses_info, clave):
    """Matriz (filas x meses) con la columna `clave` de cada mes."""
    columnas = []

    for m in meses_info:
        c = m.get(clave)

        if c is None:
            columnas.append(np.zeros(len(hist)))
        else:
            columnas.append(a_numero(hist[c]).to_numpy(dtype=float))

    return np.column_stack(columnas)


def calcular_indicadores_12_meses(hist, meses_analisis, avisos=None):
    """
    Calcula para cada fila (bodega + referencia):

        Inventario Promedio, CMV, Rotación, Días de rotación,
        Meses utilizados, Primer mes con stock, Antigüedad.

    `meses_analisis` debe ser la lista de TODOS los meses disponibles
    (la de obtener_meses_disponibles). Las ventanas se arman así:

      * Con stock inicial > 0                 -> últimos 12 meses.
      * Primer stock hace MENOS de 6 meses    -> desde ese mes al último.
      * Primer stock hace 6 meses o más       -> últimos 12 meses.
      * Nunca tuvo stock: se usa el primer mes con cualquier registro
        con la misma regla de 6 meses.
      * Sin actividad                         -> últimos 12 meses.

    Inventario promedio = suma del coste mensual / meses de la ventana
    (si el coste está entre -1 y 1 se usa el COSTO ENTRADA del mes).
    CMV = |suma de COSTO SALIDA| de la ventana.
    Rotación = CMV / inventario promedio.
    Días de rotación = (meses de la ventana x 30) / rotación.

    Antigüedad (se evalúa en este orden, solo con los últimos 12 meses):
      1. Sin stock positivo en 12 meses pero con costo de ventas
         -> Entre 0 y 3 meses.
      2. Inventario promedio y CMV en cero -> Entre 0 y 3 meses.
      3. CMV > 0 y días calculados -> según días (90/180/360).
      4. Sin CMV pero con primer stock -> según meses desde el primer stock.
      5. Sin stock ni CMV, con actividad previa -> según meses desde el
         primer registro.
      6. En otro caso -> Entre 0 y 3 meses.
    """
    if avisos is None:
        avisos = []

    todos = list(meses_analisis)
    n_m = len(todos)

    if n_m == 0:
        raise ValueError(
            "No se encontraron meses disponibles en la base de datos."
        )

    k = min(MESES_ANALISIS, n_m)

    if k < MESES_ANALISIS:
        avisos.append(
            f"La base contiene únicamente {n_m} meses disponibles "
            f"para el cálculo. Se utilizarán todos los meses "
            f"disponibles en lugar de los {MESES_ANALISIS} meses "
            f"requeridos."
        )

    n = len(hist)

    meses_info = [
        {**p, **columnas_mes(hist, p["nombre"], p["anio"])} for p in todos
    ]

    # --------------------------------------------------------
    # MATRICES (filas x meses)
    # --------------------------------------------------------
    stock = _matriz_mes(hist, meses_info, "stock")
    coste = _matriz_mes(hist, meses_info, "coste")
    entrada = _matriz_mes(hist, meses_info, "entrada")
    salida = _matriz_mes(hist, meses_info, "salida")
    costo_entrada = _matriz_mes(hist, meses_info, "costo_entrada")
    costo_salida = _matriz_mes(hist, meses_info, "costo_salida")

    c_stock_ini = col_exacta(hist, "STOCK INICIAL")
    stock_ini = (
        a_numero(hist[c_stock_ini]).to_numpy(dtype=float)
        if c_stock_ini is not None
        else np.zeros(n)
    )

    periodos_num = np.array([p["anio"] * 12 + p["mes"] for p in todos])
    ultimo_num = periodos_num[-1]
    idx_meses = np.arange(n_m)
    inicio_12 = n_m - k
    en_12 = idx_meses >= inicio_12

    # --------------------------------------------------------
    # PRIMER MES CON STOCK / PRIMER REGISTRO
    # --------------------------------------------------------
    stock_positivo = stock > EPS
    hay_stock = stock_positivo.any(axis=1)
    primer_stock_idx = stock_positivo.argmax(axis=1)
    stock_existia = stock_ini > EPS

    hubo_registro = (
        (np.abs(entrada) > EPS)
        | (np.abs(salida) > EPS)
        | (np.abs(stock) > EPS)
        | (np.abs(costo_entrada) > EPS)
        | (np.abs(costo_salida) > EPS)
        | (np.abs(coste) > EPS)
    )
    hay_registro = hubo_registro.any(axis=1)
    primer_registro_idx = hubo_registro.argmax(axis=1)

    tiene_primer_stock = stock_existia | hay_stock

    # -1 = sin actividad identificable
    primer_idx = np.where(
        stock_existia,
        0,
        np.where(
            hay_stock,
            primer_stock_idx,
            np.where(hay_registro, primer_registro_idx, -1),
        ),
    )

    # Periodo desde el que se cuenta la permanencia.
    # CORRECCIÓN H-03: el STOCK INICIAL es la existencia ANTERIOR al
    # primer mes del histórico (31-may-2025 con el archivo base), así
    # que se cuenta desde el mes previo a la primera columna. Antes se
    # contaba desde la primera columna y una referencia sin consumo en
    # 12 meses quedaba en "Entre 7 y 12 meses".
    periodo_stock_inicial = periodos_num[0] - 1

    periodo_primero = np.where(
        stock_existia,
        periodo_stock_inicial,
        periodos_num[np.clip(primer_idx, 0, None)],
    )

    meses_desde = np.where(
        primer_idx >= 0,
        ultimo_num - periodo_primero + 1,
        0,
    )

    # --------------------------------------------------------
    # VENTANA DE CÁLCULO DE CADA FILA (siempre termina en el último mes)
    # --------------------------------------------------------
    reciente = (
        (primer_idx >= 0)
        & (meses_desde < MESES_REFERENCIA_RECIENTE)
        & ~stock_existia
    )

    inicio = np.where(reciente, primer_idx, inicio_12)
    ventana = idx_meses[None, :] >= inicio[:, None]

    divisor = np.maximum(ventana.sum(axis=1), 1)
    dias_periodo = divisor * DIAS_POR_MES

    # --------------------------------------------------------
    # INVENTARIO PROMEDIO
    # --------------------------------------------------------
    coste_usado = np.where(
        (coste >= -LIMITE_COSTE_REEMPLAZO) & (coste <= LIMITE_COSTE_REEMPLAZO),
        costo_entrada,
        coste,
    )
    inventario_promedio = (coste_usado * ventana).sum(axis=1) / divisor

    # --------------------------------------------------------
    # CMV
    # --------------------------------------------------------
    cmv = np.abs((costo_salida * ventana).sum(axis=1))

    # --------------------------------------------------------
    # ROTACIÓN Y DÍAS DE ROTACIÓN
    # --------------------------------------------------------
    rotacion = np.full(n, np.nan)
    m_rot = inventario_promedio > EPS
    rotacion[m_rot] = cmv[m_rot] / inventario_promedio[m_rot]

    dias_rotacion = np.full(n, np.nan)
    m_dias = ~np.isnan(rotacion) & (rotacion > EPS)
    dias_rotacion[m_dias] = dias_periodo[m_dias] / rotacion[m_dias]

    # --------------------------------------------------------
    # ANTIGÜEDAD
    # --------------------------------------------------------
    tuvo_stock_12m = stock_positivo[:, en_12].any(axis=1)
    tuvo_costo_ventas_12m = (np.abs(costo_salida[:, en_12]) > EPS).any(axis=1)

    regla_1 = ~tuvo_stock_12m & tuvo_costo_ventas_12m
    regla_2 = (np.abs(inventario_promedio) <= EPS) & (np.abs(cmv) <= EPS)
    regla_3 = (cmv > EPS) & ~np.isnan(dias_rotacion)
    regla_4 = tiene_primer_stock
    regla_5 = meses_desde > 0

    cat_dias = _clasificar_por_cortes(np.nan_to_num(dias_rotacion), 90, 180, 360)
    cat_meses = _clasificar_por_cortes(meses_desde, 3, 6, 12)

    antiguedad = np.select(
        [regla_1, regla_2, regla_3, regla_4, regla_5],
        [CLASIFICACION_0_3, CLASIFICACION_0_3, cat_dias, cat_meses, cat_meses],
        default=CLASIFICACION_0_3,
    ).astype(object)

    # --------------------------------------------------------
    # COLUMNAS DE RESULTADO
    # --------------------------------------------------------
    nombres_ventana = [
        f"{m['nombre']} {m['anio']}" for m in meses_info[inicio_12:]
    ]
    texto_periodo = f"{nombres_ventana[0]} a {nombres_ventana[-1]}"

    etiqueta_primer_stock = np.array(
        [
            etiqueta_periodo(*periodo_de_num(p)) if p > 0 else None
            for p in periodo_primero
        ],
        dtype=object,
    )

    # Se agregan todas las columnas juntas (evita la fragmentación
    # del DataFrame que pandas advertía columna por columna).
    nuevas = {
        "INVENTARIO PROMEDIO 12 MESES": inventario_promedio,
        "CMV 12 MESES": cmv,
        "ROTACION 12 MESES": rotacion,
        "DIAS ROTACION 12 MESES": dias_rotacion,
        "MESES VALIDOS INVENTARIO": divisor,
        "DIAS DEL PERIODO": dias_periodo,
        "PRIMER MES CON STOCK": np.where(
            tiene_primer_stock, etiqueta_primer_stock, None
        ),
        "MESES DESDE PRIMER STOCK": np.where(tiene_primer_stock, meses_desde, 0),
        "PERIODO ANALISIS INVENTARIO": texto_periodo,
        COL_ANTIGUEDAD_SALIDA: antiguedad,
    }

    hist = pd.concat(
        [
            hist.drop(columns=[c for c in nuevas if c in hist.columns]),
            pd.DataFrame(nuevas, index=hist.index),
        ],
        axis=1,
    )

    # --------------------------------------------------------
    # CONTROL
    # --------------------------------------------------------
    control = pd.DataFrame(
        [
            {
                "mes": f"{m['nombre']} {m['anio']}",
                "en_ventana_12_meses": i >= inicio_12,
                "columna_coste": m["coste"],
                "columna_stock": m["stock"],
                "columna_entrada": m["entrada"],
                "columna_salida": m["salida"],
                "columna_costo_entrada": m["costo_entrada"],
                "columna_costo_salida": m["costo_salida"],
            }
            for i, m in enumerate(meses_info)
        ]
    )

    info_periodo = {
        "periodo": texto_periodo,
        "cantidad_meses": len(nombres_ventana),
        "meses": nombres_ventana,
        "mes_inicial": nombres_ventana[0],
        "mes_final": nombres_ventana[-1],
    }

    return hist, info_periodo, control


# ============================================================
# NORMALIZACIÓN Y VALIDACIÓN DEL KARDEX
# ============================================================

# Columnas estándar con las que el motor trabaja internamente y con
# las que se guardan los movimientos de cada periodo cargado.
COLUMNAS_MOVIMIENTO = [
    "Fecha Movimiento",
    "Bodega",
    "Codigo Articulo",
    "Articulo",
    "EstadoMovimiento",
    "Cantidad Entrada",
    "Cantidad Salida",
    "Costo Total Con Iva",
]

# Convención de signo de la columna de salidas en el archivo fuente.
CONVENCION_NEGATIVA = "negativa"   # salidas registradas como -15
CONVENCION_POSITIVA = "positiva"   # salidas registradas como 15

MOTIVO_SIGNO_OPUESTO = (
    "Salida con signo opuesto a la convención del archivo "
    "(posible reversión). No se aplicó: revisar."
)
MOTIVO_ENTRADA_NEGATIVA = (
    "Entrada con signo negativo: se aplicó como salida, "
    "respetando su signo."
)
MOTIVO_FILA_MIXTA = (
    "Fila con entrada y salida a la vez: el costo se repartió "
    "en proporción a las cantidades."
)
MOTIVO_DUPLICADO = "Posible duplicado: fila idéntica a otra del Kardex."
MOTIVO_SIN_COSTO = "Entrada sin costo: el inventario no aumenta de valor."


_PATRON_FECHA_ISO = re.compile(r"^\s*\d{4}-\d{1,2}-\d{1,2}")


def _a_fecha(valor):
    """
    Convierte una celda de fecha. Las fechas de Excel llegan como
    datetime; los textos 'AAAA-MM-DD' se leen como ISO y el resto con
    día primero (formato colombiano 15/06/2026).
    """
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return pd.NaT

    if isinstance(valor, (pd.Timestamp, np.datetime64)) or hasattr(valor, "year"):
        return pd.to_datetime(valor, errors="coerce")

    t = str(valor).strip()
    if t == "":
        return pd.NaT

    if _PATRON_FECHA_ISO.match(t):
        return pd.to_datetime(t, errors="coerce", dayfirst=False)

    return pd.to_datetime(t, errors="coerce", dayfirst=True)


def convertir_fechas(serie):
    if pd.api.types.is_datetime64_any_dtype(serie):
        return pd.to_datetime(serie, errors="coerce")
    return serie.apply(_a_fecha).astype("datetime64[ns]")


def detectar_convencion_salidas(salidas):
    """
    Determina cómo registra el archivo las salidas: mayoritariamente
    negativas (-15) o positivas (15). Sin salidas -> negativa.
    """
    no_cero = salidas[salidas.abs() > EPS]
    if len(no_cero) == 0:
        return CONVENCION_NEGATIVA
    negativas = int((no_cero < 0).sum())
    positivas = int((no_cero > 0).sum())
    return CONVENCION_NEGATIVA if negativas >= positivas else CONVENCION_POSITIVA


def _col_articulo(df, col_codigo):
    """'Articulo' exacto; si no, una columna que lo contenga y no sea el código."""
    c = col_exacta(df, "Articulo")
    if c is not None:
        return c
    for c in df.columns:
        if c != col_codigo and "ARTICULO" in norm(c) and "COD" not in norm(c):
            return c
    return None


def normalizar_kardex(kardex):
    """
    Lleva el Kardex (crudo o ya guardado) a las columnas estándar y
    valida cada fila SIN alterar los valores originales:

      * Las cantidades conservan su signo tal como vienen.
      * '_CONVENCION' indica si el archivo registra las salidas en
        negativo o en positivo (se detecta por archivo).
      * '_MOTIVO_RECHAZO' no vacío = la fila no se puede procesar
        (fecha inválida, cantidad o costo no numérico, sin código...).
    """
    k = kardex.copy()

    k_bod = col_buscar(k, ["Bodega"])
    k_cod = col_buscar(k, ["Codigo Articulo"])
    k_est = col_buscar(k, ["EstadoMovimiento", "Estado Movimiento"], obligatoria=False)
    k_art = _col_articulo(k, k_cod)
    k_fec = col_buscar(k, ["Fecha Movimiento"])
    k_ent = col_buscar(k, ["Cantidad Entrada"])
    k_sal = col_buscar(k, ["Cantidad Salida"])
    k_cos = col_buscar(k, ["Costo Total Con Iva"])

    out = pd.DataFrame(index=k.index)
    out["Fecha Movimiento"] = convertir_fechas(k[k_fec])
    out["Bodega"] = k[k_bod].apply(bodega_txt)
    out["Codigo Articulo"] = k[k_cod].apply(codigo)
    out["Articulo"] = k[k_art].apply(texto) if k_art is not None else ""
    out["EstadoMovimiento"] = k[k_est].apply(texto) if k_est is not None else ""

    ent, ent_inv = a_numero_validado(k[k_ent])
    sal, sal_inv = a_numero_validado(k[k_sal])
    cos, cos_inv = a_numero_validado(k[k_cos])

    out["Cantidad Entrada"] = ent
    out["Cantidad Salida"] = sal
    out["Costo Total Con Iva"] = cos

    out["_FILA_ORIGEN"] = (
        k["_FILA_ORIGEN"].values if "_FILA_ORIGEN" in k.columns
        else np.arange(len(k)) + 2
    )

    motivos = [
        (out["Fecha Movimiento"].isna(), "Fecha inválida o vacía"),
        (out["Bodega"] == "", "Sin bodega"),
        (out["Codigo Articulo"] == "", "Sin código de artículo"),
        (ent_inv, "Cantidad de entrada no numérica"),
        (sal_inv, "Cantidad de salida no numérica"),
        (cos_inv, "Costo no numérico"),
    ]

    motivo = pd.Series("", index=out.index, dtype=object)
    for mascara, texto_motivo in motivos:
        mascara = mascara.fillna(False).astype(bool)
        motivo = np.where(
            mascara,
            np.where(motivo == "", texto_motivo, motivo + "; " + texto_motivo),
            motivo,
        )
        motivo = pd.Series(motivo, index=out.index, dtype=object)
    out["_MOTIVO_RECHAZO"] = motivo

    # Convención de signo: la del archivo guardado (si existe) o la
    # detectada con las salidas válidas de este archivo.
    c_conv = col_exacta(k, "_CONVENCION")
    if c_conv is not None:
        out["_CONVENCION"] = k[c_conv].astype(str).str.strip().str.lower().values
    else:
        validas = out["_MOTIVO_RECHAZO"] == ""
        out["_CONVENCION"] = detectar_convencion_salidas(sal[validas])

    return out


def _tabla_motivo(df, motivo, columnas_extra=()):
    """Filas de control con el motivo indicado."""
    cols = ["_FILA_ORIGEN"] + COLUMNAS_MOVIMIENTO + [
        c for c in columnas_extra if c in df.columns
    ]
    t = df[[c for c in cols if c in df.columns]].copy()
    t = t.rename(columns={"_FILA_ORIGEN": "Fila en el archivo"})
    t["Motivo"] = motivo if isinstance(motivo, str) else motivo.values
    return t


# ============================================================
# AJUSTES DE CONCILIACIÓN
# ============================================================

# Columnas con que se guardan los ajustes aprobados de cada periodo.
COLUMNAS_AJUSTE = [
    "Periodo",
    "Bodega",
    "Codigo Articulo",
    "Articulo",
    "LLAVE",
    "Stock real",
    "Valor real",
    "Ajuste unidades aprobado",
    "Ajuste valor aprobado",
    "Id conciliacion",
    "Archivo",
    "Usuario",
    "Fecha aprobacion",
]

ORIGEN_VALOR_ARCHIVO = "Valor del inventario real"
ORIGEN_VALOR_UNITARIO = "Costo unitario calculado"
ORIGEN_VALOR_CERO = "Stock real en 0"
ORIGEN_VALOR_SIN_REFERENCIA = "Sin costo de referencia (valor sin cambio)"


def normalizar_ajustes(ajustes):
    """
    Ajustes de conciliación aprobados -> DataFrame estándar.

    Cada fila fija el inventario de una LLAVE al CIERRE de un periodo:
    'Stock real' (unidades del conteo) y 'Valor real' (valor total; vacío
    si el inventario real no traía valor). El motor calcula el ajuste
    como (real - reconstruido con el Kardex) en el momento de aplicarlo,
    de modo que el stock siempre queda igual al conteo aunque luego se
    corrija un mes anterior.
    """
    if ajustes is None or len(ajustes) == 0:
        return pd.DataFrame(columns=COLUMNAS_AJUSTE + ["_NUM_PERIODO"])

    a = ajustes.copy()
    for c in COLUMNAS_AJUSTE:
        if c not in a.columns:
            a[c] = np.nan

    a["Bodega"] = a["Bodega"].apply(bodega_txt)
    a["Codigo Articulo"] = a["Codigo Articulo"].apply(codigo)
    a["Articulo"] = a["Articulo"].apply(texto)
    a["LLAVE"] = [
        crear_llave(b, c) for b, c in zip(a["Bodega"], a["Codigo Articulo"])
    ]
    for c in ("Stock real", "Valor real", "Ajuste unidades aprobado", "Ajuste valor aprobado"):
        a[c] = pd.to_numeric(a[c], errors="coerce")

    a = a[a["Stock real"].notna() & (a["Codigo Articulo"] != "")].copy()
    a["_NUM_PERIODO"] = [
        periodo_num(*periodo_de_etiqueta(p)) for p in a["Periodo"].astype(str)
    ]

    # Una sola fila por LLAVE y periodo (la última aprobada).
    a = a.drop_duplicates(subset=["_NUM_PERIODO", "LLAVE"], keep="last")
    return a.reset_index(drop=True)


# ============================================================
# MOTOR PRINCIPAL
# ============================================================

def _resolver_periodo_final(periodo_final, num_base, fechas_validas):
    """
    periodo_final admite:
      * None      -> último mes con movimientos posteriores a la base.
      * 'AAAA-MM' o (anio, mes).
      * int (compatibilidad): número de mes; se toma la primera
        ocurrencia de ese mes posterior a la base.
    """
    if periodo_final is None:
        posteriores = fechas_validas[
            fechas_validas >= pd.Timestamp(*periodo_de_num(num_base + 1), 1)
        ]
        if len(posteriores) == 0:
            return None
        f = posteriores.max()
        return periodo_num(f.year, f.month)

    if isinstance(periodo_final, str):
        return periodo_num(*periodo_de_etiqueta(periodo_final))

    if isinstance(periodo_final, (tuple, list)):
        return periodo_num(*periodo_final)

    mes = int(periodo_final)
    anio_base, mes_base = periodo_de_num(num_base)
    anio = anio_base if mes > mes_base else anio_base + 1
    return periodo_num(anio, mes)


def procesar_inventario(
    historico,
    kardex,
    periodo_final=None,
    excluir_filas_identicas=False,
    ajustes_conciliacion=None,
):
    """
    historico : DataFrame preparado (leer_historico). Su último mes con
                'STOCK <MES> <AÑO>' es la BASE (mayo 2026 en el archivo
                inicial).
    kardex    : movimientos de TODOS los meses posteriores a la base que
                se quieren calcular (crudo o ya normalizado). La gestión
                de cargues mensuales (gestion_kardex.py) une aquí los
                periodos guardados, de modo que cada mes parte del
                cierre del mes anterior.
    periodo_final : último periodo a calcular (ver _resolver_periodo_final).

    La unidad de consolidación es LLAVE = número de bodega + código de
    artículo: cada bodega conserva sus propios movimientos, existencias,
    costos e indicadores.

    Siempre se parte del histórico base y se recalculan todos los meses
    posteriores con los movimientos recibidos: procesar dos veces los
    mismos movimientos da el mismo resultado (no acumula).

    Signos: las cantidades se respetan como vienen. Con la convención
    negativa (-15) la salida se suma tal cual: stock = inicial +
    entradas + salidas. Con la convención positiva (15) la salida se
    resta. Una salida con el signo contrario a la convención del
    archivo NO se aplica y queda para revisión.

    Salidas sin existencia: se aplican completas aunque no haya stock
    (el stock puede quedar negativo) y su costo cuenta completo. Quedan
    listadas en 'sin_existencia' para revisión.

    ajustes_conciliacion: inventario real aprobado al cierre de cada
    periodo (ver normalizar_ajustes). Se aplica al final del mes, después
    de todos los movimientos del Kardex, como un movimiento separado de
    tipo AJUSTE CONCILIACION.
    """

    avisos = []

    hist = historico.copy()

    # ========================================================
    # BASE: último mes del histórico
    # ========================================================

    meses_archivo = meses_con_stock(hist)
    if not meses_archivo:
        raise ValueError(
            "El histórico no tiene columnas 'STOCK <MES> <AÑO>'."
        )

    anio_base, mes_base = meses_archivo[-1]
    num_base = periodo_num(anio_base, mes_base)
    nombre_base = nombre_periodo(anio_base, mes_base)

    c_bod = col_buscar(hist, ["Bodega"])
    c_cod = col_buscar(hist, ["Codigo Articulo"])
    c_art = col_exacta(hist, "Articulo")

    c_stock_base = col_exacta(hist, f"STOCK {nombre_base}")
    c_coste_base = col_coste_mes(hist, NOMBRES_MES[mes_base - 1], anio_base)

    if c_coste_base is None:
        raise ValueError(
            f"El histórico no trae el coste de {nombre_base.lower()}."
        )

    c_stock_ini = col_exacta(hist, "STOCK INICIAL")
    c_coste_ini = col_exacta(hist, "COSTE INICIAL")

    if "LLAVE" not in hist.columns:
        hist["LLAVE"] = [
            crear_llave(b, c) for b, c in zip(hist[c_bod], hist[c_cod])
        ]

    if col_exacta(hist, "OBSERVACION") is None:
        hist["OBSERVACION"] = ""

    # ========================================================
    # COLUMNAS MENSUALES DEL HISTÓRICO (hasta la base)
    # ========================================================

    meses_hist = [
        p for p in obtener_meses_disponibles(hist)
        if periodo_num(p["anio"], p["mes"]) <= num_base
    ]

    if meses_hist:
        anio_ini, mes_ini = periodo_de_num(
            periodo_num(meses_hist[0]["anio"], meses_hist[0]["mes"]) - 1
        )
        fecha_stock_inicial = _fin_mes(anio_ini, mes_ini)
    else:
        fecha_stock_inicial = FECHA_STOCK_INICIAL

    cols_h = []
    faltan = 0

    for p in meses_hist:
        nombre = f"{p['nombre']} {p['anio']}"
        cols = {
            "entrada": col_exacta(hist, f"ENTRADA {nombre}"),
            "salida": col_exacta(hist, f"SALIDA {nombre}"),
            "stock": col_exacta(hist, f"STOCK {nombre}"),
            "costo_entrada": col_exacta(hist, f"COSTO ENTRADA {nombre}"),
        }
        faltan += sum(1 for v in cols.values() if v is None)
        cols_h.append((nombre, p["fecha"], cols))

    if faltan:
        avisos.append(
            f"{faltan} columnas mensuales del histórico "
            "no existen (se toman como 0)."
        )

    num_cols = {c_stock_base, c_coste_base, c_stock_ini, c_coste_ini}
    for _, _, cols in cols_h:
        num_cols.update(cols.values())

    for c in [x for x in num_cols if x is not None]:
        hist[c] = a_numero(hist[c])

    # ========================================================
    # DUPLICADOS DEL HISTÓRICO
    # ========================================================

    duplicados = hist[hist["LLAVE"].duplicated(keep=False)]

    df_duplicados = duplicados[
        ["LLAVE", c_bod, c_cod, c_stock_base, c_coste_base]
    ].copy()

    if len(duplicados):
        avisos.append(
            f"{duplicados['LLAVE'].nunique()} llaves repetidas en el "
            "histórico; los movimientos se asignan a la primera fila "
            "de cada llave."
        )

    # ========================================================
    # KARDEX: NORMALIZACIÓN Y VALIDACIÓN
    # ========================================================

    kn = normalizar_kardex(kardex)

    stats = {"filas_kardex": len(kn)}
    revision = []

    if len(kn) == 15000:
        avisos.append(
            "El Kardex trae exactamente 15.000 filas: "
            "la exportación podría estar truncada en origen."
        )

    rechazo = kn["_MOTIVO_RECHAZO"] != ""
    df_rechazados = _tabla_motivo(kn[rechazo], kn.loc[rechazo, "_MOTIVO_RECHAZO"])
    df_fechas_invalidas = kn[kn["Fecha Movimiento"].isna()].copy()

    stats["rechazados"] = int(rechazo.sum())
    stats["fechas_invalidas"] = len(df_fechas_invalidas)

    if stats["rechazados"]:
        avisos.append(
            f"{stats['rechazados']} movimientos rechazados por datos "
            "inválidos (fecha, cantidad, costo, código o bodega). "
            "No se procesan; ver 'Movimientos rechazados'."
        )

    k = kn[~rechazo].copy()

    # Posibles duplicados: filas idénticas en todas las columnas.
    # No se eliminan salvo decisión explícita del usuario.
    dup = k.duplicated(subset=COLUMNAS_MOVIMIENTO, keep=False)
    stats["posibles_duplicados"] = int(dup.sum())

    if stats["posibles_duplicados"]:
        revision.append(
            _tabla_motivo(
                k[dup],
                MOTIVO_DUPLICADO
                + (
                    " Se conservó solo la primera."
                    if excluir_filas_identicas
                    else " Se procesaron todas."
                ),
            )
        )

    if excluir_filas_identicas:
        n0 = len(k)
        k = k[~k.duplicated(subset=COLUMNAS_MOVIMIENTO, keep="first")].copy()
        stats["duplicados_excluidos"] = n0 - len(k)
    else:
        stats["duplicados_excluidos"] = 0

    k["_NUM_BODEGA"] = k["Bodega"].apply(numero_bodega)

    n0 = len(k)
    k = k[~k["_NUM_BODEGA"].isin(BODEGAS_EXCLUIDAS)].copy()
    stats["excluidos_bodega"] = n0 - len(k)

    anulado = k["EstadoMovimiento"].astype(str).str.upper().str.contains(
        "ANULADO", na=False
    )
    stats["anulados"] = int(anulado.sum())
    k = k[~anulado].copy()

    k["LLAVE"] = k["_NUM_BODEGA"] + "_" + k["Codigo Articulo"]

    # --------------------------------------------------------
    # SIGNOS
    # --------------------------------------------------------
    ent = k["Cantidad Entrada"]
    sal = k["Cantidad Salida"]
    conv = k["_CONVENCION"]

    opuesto = (
        ((conv == CONVENCION_NEGATIVA) & (sal > EPS))
        | ((conv == CONVENCION_POSITIVA) & (sal < -EPS))
    )

    stats["salidas_signo_opuesto"] = int(opuesto.sum())
    stats["salidas_positivas"] = stats["salidas_signo_opuesto"]

    if stats["salidas_signo_opuesto"]:
        revision.append(_tabla_motivo(k[opuesto], MOTIVO_SIGNO_OPUESTO))
        avisos.append(
            f"{stats['salidas_signo_opuesto']} salidas tienen el signo "
            "contrario al resto del archivo y no se aplicaron "
            "(ver 'Movimientos para revisión')."
        )

    k = k[~opuesto].copy()

    stats["entradas_negativas"] = int((k["Cantidad Entrada"] < 0).sum())
    if stats["entradas_negativas"]:
        revision.append(
            _tabla_motivo(k[k["Cantidad Entrada"] < 0], MOTIVO_ENTRADA_NEGATIVA)
        )

    conv_valores = k["_CONVENCION"].value_counts()
    stats["convencion_salidas"] = (
        conv_valores.index[0] if len(conv_valores) else CONVENCION_NEGATIVA
    )

    # --------------------------------------------------------
    # PERIODO A CALCULAR
    # --------------------------------------------------------
    num_fin = _resolver_periodo_final(
        periodo_final, num_base, k["Fecha Movimiento"]
    )

    anio_ini_k, mes_ini_k = periodo_de_num(num_base + 1)
    fecha_inicio = pd.Timestamp(anio_ini_k, mes_ini_k, 1)

    if num_fin is None:
        raise ValueError(
            f"El Kardex no tiene movimientos válidos posteriores a "
            f"{nombre_base.lower()} (base del histórico)."
        )

    if num_fin <= num_base:
        raise ValueError(
            f"El periodo a calcular debe ser posterior a "
            f"{nombre_base.lower()} (base del histórico)."
        )

    anio_fin, mes_fin = periodo_de_num(num_fin)
    fecha_fin = fin_periodo(anio_fin, mes_fin)

    meses = [
        (NOMBRES_MES[m - 1], a, m)
        for a, m in (periodo_de_num(n) for n in range(num_base + 1, num_fin + 1))
    ]

    stats["anteriores_a_base"] = int((k["Fecha Movimiento"] < fecha_inicio).sum())
    stats["posteriores_al_periodo"] = int((k["Fecha Movimiento"] > fecha_fin).sum())

    if stats["anteriores_a_base"]:
        avisos.append(
            f"{stats['anteriores_a_base']} movimientos son anteriores a "
            f"{fecha_inicio:%d/%m/%Y} (ya incluidos en el histórico base) "
            "y no se procesan."
        )

    if stats["posteriores_al_periodo"]:
        avisos.append(
            f"{stats['posteriores_al_periodo']} movimientos son "
            f"posteriores a {fecha_fin:%d/%m/%Y} y no se procesan."
        )

    kp = k[
        (k["Fecha Movimiento"] >= fecha_inicio)
        & (k["Fecha Movimiento"] <= fecha_fin)
    ].copy()
    stats["movimientos_periodo"] = len(kp)

    # Ajustes de conciliación aplicables a los periodos calculados
    aj = normalizar_ajustes(ajustes_conciliacion)
    fuera = (aj["_NUM_PERIODO"] <= num_base) | (aj["_NUM_PERIODO"] > num_fin)
    if fuera.any():
        avisos.append(
            f"{int(fuera.sum())} ajustes de conciliación son de periodos "
            "fuera del cálculo y no se aplicaron."
        )
    aj = aj[~fuera].copy()
    stats["ajustes_conciliacion"] = len(aj)

    if len(kp) == 0:
        raise ValueError(
            f"El Kardex no tiene movimientos entre "
            f"{fecha_inicio:%d/%m/%Y} y {fecha_fin:%d/%m/%Y}."
        )

    stats["fecha_min"] = kp["Fecha Movimiento"].min()
    stats["fecha_max"] = kp["Fecha Movimiento"].max()

    ent = kp["Cantidad Entrada"]
    sal = kp["Cantidad Salida"]

    # Entradas positivas suman. La salida se expresa SIEMPRE en
    # negativo para el cálculo, respetando el signo original:
    #   convención negativa: -15 se usa tal cual (nunca se resta dos veces)
    #   convención positiva:  15 se convierte en -15
    # Una entrada negativa se aplica como salida con su propio signo.
    salida_signo = np.where(
        kp["_CONVENCION"] == CONVENCION_POSITIVA, -sal, sal
    )
    kp["ENT"] = ent.clip(lower=0.0)
    kp["SAL"] = salida_signo + ent.where(ent < 0, 0.0)

    mixtas = (kp["ENT"] > 0) & (kp["SAL"] < 0)
    stats["filas_mixtas"] = int(mixtas.sum())
    if stats["filas_mixtas"]:
        revision.append(_tabla_motivo(kp[mixtas], MOTIVO_FILA_MIXTA))

    sin_costo = (kp["ENT"] > 0) & (kp["Costo Total Con Iva"].abs() <= EPS)
    stats["entradas_sin_costo"] = int(sin_costo.sum())
    if stats["entradas_sin_costo"]:
        revision.append(_tabla_motivo(kp[sin_costo], MOTIVO_SIN_COSTO))

    # ========================================================
    # LLAVES NUEVAS (referencia o bodega que aparecen por 1ª vez)
    # ========================================================

    nuevas = (set(kp["LLAVE"]) | set(aj["LLAVE"])) - set(hist["LLAVE"])
    stats["llaves_nuevas"] = len(nuevas)

    if nuevas:
        primeras = (
            kp.sort_values("Fecha Movimiento")
            .drop_duplicates("LLAVE")
            .set_index("LLAVE")
        )
        primeras_aj = aj.drop_duplicates("LLAVE").set_index("LLAVE")

        # Nombre completo de la bodega ('[1] - REPUESTOS') a partir de
        # su número, por si el archivo de origen trae solo '1'.
        nombre_bodega = {}
        for b in hist[c_bod]:
            if "[" in str(b):
                nombre_bodega.setdefault(numero_bodega(b), b)

        filas = []

        for llave in sorted(nuevas):
            if llave in primeras.index:
                p = primeras.loc[llave]
                marca = MARCA_NUEVO
            else:
                p = primeras_aj.loc[llave]
                marca = MARCA_NUEVO_CONCILIACION

            nueva = {c: np.nan for c in hist.columns}
            nueva["LLAVE"] = llave
            nueva[c_bod] = nombre_bodega.get(numero_bodega(p["Bodega"]), p["Bodega"])
            nueva[c_cod] = p["Codigo Articulo"]

            if c_art is not None:
                nueva[c_art] = p["Articulo"]

            nueva["OBSERVACION"] = marca
            filas.append(nueva)

        hist = pd.concat(
            [hist, pd.DataFrame(filas, columns=hist.columns)],
            ignore_index=True,
        )

        for c in [x for x in num_cols if x is not None]:
            hist[c] = a_numero(hist[c])

    # ========================================================
    # BASE (cierre del mes base)
    # ========================================================

    base = defaultdict(lambda: {"stock": 0.0, "costo": 0.0})

    for ll, s, c in zip(hist["LLAVE"], hist[c_stock_base], hist[c_coste_base]):
        base[ll]["stock"] += float(s)
        base[ll]["costo"] += float(c)

    # ========================================================
    # LOTES HISTÓRICOS LIFO
    # ========================================================

    lotes_lifo = defaultdict(list)
    ctrl_hist = []

    def val(fila, col):
        if col is None:
            return 0.0
        return float(fila[col])

    for _, fila in hist.iterrows():
        ll = fila["LLAVE"]
        lotes = lotes_lifo[ll]

        s_ini = val(fila, c_stock_ini)
        c_ini = val(fila, c_coste_ini)

        if s_ini > 0:
            lotes.append(
                {
                    "fecha": fecha_stock_inicial,
                    "cantidad": s_ini,
                    "costo_unitario": c_ini / s_ini,
                    "origen": "STOCK INICIAL",
                }
            )

        for nombre, fecha_mes, cols in cols_h:
            e = val(fila, cols["entrada"])
            s = abs(val(fila, cols["salida"]))
            ce = val(fila, cols["costo_entrada"])

            if e > 0:
                lotes.append(
                    {
                        "fecha": fecha_mes,
                        "cantidad": e,
                        "costo_unitario": ce / e,
                        "origen": f"ENTRADA {nombre}",
                    }
                )

            if s > 0:
                _, no = consumir_lifo(lotes, s)

                if no > EPS:
                    ctrl_hist.append(
                        {
                            "LLAVE": ll,
                            "MES": nombre,
                            "TIPO": "SALIDA NO RESPALDADA POR LOTES",
                            "CANTIDAD": no,
                        }
                    )

    # ========================================================
    # CUADRAR LOTES CONTRA EL STOCK BASE
    # ========================================================

    etiqueta_ajuste = f"AJUSTE A {nombre_base}"

    # Unidades salidas sin existencia que todavía no tienen lote que las
    # respalde (stock negativo). La próxima entrada las cubre primero.
    # Invariante: suma de lotes - deficit = stock.
    deficit = defaultdict(float)

    for ll, b in base.items():
        lotes = lotes_lifo[ll]
        if b["stock"] < 0:
            deficit[ll] = -b["stock"]
        dif = sum(l["cantidad"] for l in lotes) - max(b["stock"], 0.0)

        if dif > 0.0001:
            consumir_lifo(lotes, dif)
            ctrl_hist.append(
                {
                    "LLAVE": ll,
                    "MES": etiqueta_ajuste,
                    "TIPO": "LOTES EN EXCESO (consumidos LIFO)",
                    "CANTIDAD": dif,
                }
            )

        elif dif < -0.0001:
            lotes.insert(
                0,
                {
                    "fecha": None,
                    "cantidad": -dif,
                    "costo_unitario": (
                        b["costo"] / b["stock"] if b["stock"] > 0 else 0.0
                    ),
                    "origen": f"SIN TRAZABILIDAD ({etiqueta_ajuste})",
                },
            )
            ctrl_hist.append(
                {
                    "LLAVE": ll,
                    "MES": etiqueta_ajuste,
                    "TIPO": "STOCK SIN LOTES (sin trazabilidad)",
                    "CANTIDAD": -dif,
                }
            )

    # ========================================================
    # STOCK Y COSTO ACTUAL
    # ========================================================

    stock_actual = {ll: b["stock"] for ll, b in base.items()}
    costo_actual = {ll: b["costo"] for ll, b in base.items()}

    # ========================================================
    # PROCESAR MOVIMIENTOS (orden cronológico; el mismo día las
    # entradas puras van antes que las salidas)
    # ========================================================

    kp["_ORD"] = np.where((kp["ENT"] > 0) & (kp["SAL"] == 0), 0, 1)
    kp["_SEQ"] = np.arange(len(kp))

    kp = kp.sort_values(["Fecha Movimiento", "_ORD", "_SEQ"]).reset_index(drop=True)

    movs = []
    sin_ex = []
    lifo = []
    ajustes = []
    ajustes_conc = []

    def agregar_lote(ll, fecha, cantidad, costo_unitario, origen):
        """Nuevo lote; primero cubre las salidas sin existencia pendientes."""
        cubre = min(deficit[ll], cantidad)
        deficit[ll] -= cubre
        resto = cantidad - cubre
        if resto > EPS:
            lotes_lifo[ll].append(
                {
                    "fecha": fecha,
                    "cantidad": resto,
                    "costo_unitario": costo_unitario,
                    "origen": origen,
                }
            )

    def costo_unitario_referencia(ll, s_antes, c_antes):
        if s_antes > EPS and c_antes > 0:
            return c_antes / s_antes
        for lote in reversed(lotes_lifo[ll]):
            if lote["cantidad"] > EPS and lote["costo_unitario"] > 0:
                return lote["costo_unitario"]
        return None

    def aplicar_ajustes_periodo(num, filas):
        """Lleva cada LLAVE al inventario real aprobado al cierre del mes."""
        anio_a, mes_a = periodo_de_num(num)
        fecha = fin_periodo(anio_a, mes_a)
        etiqueta = etiqueta_periodo(anio_a, mes_a)

        for r in filas.to_dict("records"):
            ll = r["LLAVE"]
            stock_actual.setdefault(ll, 0.0)
            costo_actual.setdefault(ll, 0.0)
            s_antes = stock_actual[ll]
            c_antes = costo_actual[ll]

            real_u = float(r["Stock_real"])
            real_v = r["Valor_real"]

            if real_v is not None and not pd.isna(real_v):
                real_v = float(real_v)
                origen_valor = ORIGEN_VALOR_ARCHIVO
            elif abs(real_u) <= EPS:
                real_v = 0.0
                origen_valor = ORIGEN_VALOR_CERO
            else:
                cu = costo_unitario_referencia(ll, s_antes, c_antes)
                if cu is not None:
                    real_v = real_u * cu
                    origen_valor = ORIGEN_VALOR_UNITARIO
                else:
                    real_v = c_antes
                    origen_valor = ORIGEN_VALOR_SIN_REFERENCIA

            aj_u = real_u - s_antes
            aj_v = real_v - c_antes

            if aj_u > EPS:
                agregar_lote(
                    ll, fecha, aj_u,
                    real_v / real_u if real_u > EPS else 0.0,
                    TIPO_AJUSTE_CONCILIACION,
                )
            elif aj_u < -EPS:
                _, faltante = consumir_lifo(lotes_lifo[ll], -aj_u)
                deficit[ll] += faltante
            # Invariante de lotes: suma de lotes - deficit = stock.
            deficit[ll] = max(
                sum(l["cantidad"] for l in lotes_lifo[ll]) - real_u, 0.0
            )

            stock_actual[ll] = real_u
            costo_actual[ll] = real_v

            aprobado_u = r["Ajuste_unidades_aprobado"]
            aprobado_v = r["Ajuste_valor_aprobado"]
            cambio = (
                (not pd.isna(aprobado_u) and abs(aprobado_u - aj_u) > 0.001)
                or (not pd.isna(aprobado_v) and abs(aprobado_v - aj_v) > 0.5)
            )

            ajustes_conc.append(
                {
                    "Periodo": etiqueta,
                    "Fecha": fecha,
                    "Bodega": r["Bodega"],
                    "Codigo Articulo": r["Codigo_Articulo"],
                    "Articulo": r["Articulo"],
                    "LLAVE": ll,
                    "Stock calculado antes del ajuste": s_antes,
                    "Stock real": real_u,
                    "Ajuste unidades": aj_u,
                    "Valor calculado antes del ajuste": c_antes,
                    "Valor real": real_v,
                    "Ajuste valor": aj_v,
                    "Origen del valor": origen_valor,
                    "Ajuste unidades aprobado": aprobado_u,
                    "Ajuste valor aprobado": aprobado_v,
                    "Cambió desde la aprobación": bool(cambio),
                    "Id conciliacion": r["Id_conciliacion"],
                    "Archivo": r["Archivo"],
                    "Usuario": r["Usuario"],
                    "Fecha aprobacion": r["Fecha_aprobacion"],
                }
            )

            movs.append(
                {
                    "Fecha": fecha,
                    "Tipo movimiento": TIPO_AJUSTE_CONCILIACION,
                    "Bodega": r["Bodega"],
                    "Codigo Articulo": r["Codigo_Articulo"],
                    "Articulo": r["Articulo"],
                    "LLAVE": ll,
                    "Stock antes": s_antes,
                    "Entrada Kardex": 0.0,
                    "Salida Kardex": 0.0,
                    "Entrada aplicada": 0.0,
                    "Salida aplicada": 0.0,
                    "Salida sin existencia": 0.0,
                    "Ajuste conciliación unidades": aj_u,
                    "Stock después": real_u,
                    "Costo Kardex Con Iva": 0.0,
                    "Costo entrada aplicado": 0.0,
                    "Costo salida aplicado": 0.0,
                    "Ajuste costo residual": 0.0,
                    "Ajuste conciliación valor": aj_v,
                    "Costo después": real_v,
                }
            )

    # Ajustes pendientes por periodo, en orden cronológico
    aj_util = aj.rename(columns=lambda c: c.replace(" ", "_"))
    pendientes_aj = [
        (num, aj_util[aj_util["_NUM_PERIODO"] == num])
        for num in sorted(aj_util["_NUM_PERIODO"].unique())
    ]

    i_fec = kp.columns.get_loc("Fecha Movimiento")
    i_bod = kp.columns.get_loc("Bodega")
    i_cod = kp.columns.get_loc("Codigo Articulo")
    i_art = kp.columns.get_loc("Articulo")
    i_ent_k = kp.columns.get_loc("Cantidad Entrada")
    i_sal_k = kp.columns.get_loc("Cantidad Salida")
    i_cos = kp.columns.get_loc("Costo Total Con Iva")
    i_ll = kp.columns.get_loc("LLAVE")
    i_ent = kp.columns.get_loc("ENT")
    i_sal = kp.columns.get_loc("SAL")

    for f in kp.itertuples(index=False, name=None):
        ll = f[i_ll]
        fecha = f[i_fec]

        # Antes del primer movimiento de un mes posterior se aplican
        # los ajustes de conciliación de los meses ya cerrados.
        while pendientes_aj and fecha > fin_periodo(*periodo_de_num(pendientes_aj[0][0])):
            aplicar_ajustes_periodo(*pendientes_aj.pop(0))

        ent_ = float(f[i_ent])
        sal_ = float(f[i_sal])
        costo_k = float(f[i_cos])
        bodega_ = f[i_bod]
        cod_ = f[i_cod]
        art = f[i_art]

        stock_actual.setdefault(ll, 0.0)
        costo_actual.setdefault(ll, 0.0)

        lotes = lotes_lifo[ll]

        s_antes = stock_actual[ll]
        c_antes = costo_actual[ll]

        e_apl = 0.0
        s_apl = 0.0
        s_sin = 0.0
        c_ent = 0.0
        c_sal = 0.0

        # Fila mixta (entrada y salida en la misma fila): el costo de
        # la fila se reparte en proporción a las cantidades para no
        # aplicarlo dos veces (corrección H-05).
        if ent_ > 0 and sal_ < 0:
            total = ent_ + abs(sal_)
            costo_ent_fila = abs(costo_k) * ent_ / total
            costo_sal_fila = abs(costo_k) * abs(sal_) / total
        else:
            costo_ent_fila = abs(costo_k)
            costo_sal_fila = abs(costo_k)

        # ENTRADA
        if ent_ > 0:
            e_apl = ent_
            c_ent = costo_ent_fila
            agregar_lote(ll, fecha, ent_, costo_ent_fila / ent_, TIPO_KARDEX)

        # SALIDA
        # Se aplica COMPLETA aunque no haya existencias: la salida se
        # conserva con su signo negativo, descuenta el stock (que puede
        # quedar negativo) y su costo cuenta completo. La parte que
        # supera lo disponible se informa como 'salida sin existencia'.
        if sal_ < 0:
            sol = abs(sal_)
            disp = max(s_antes + e_apl, 0.0)
            s_apl = sol
            s_sin = max(sol - disp, 0.0)

            c_sal = -costo_sal_fila

            consumos, faltante = consumir_lifo(lotes, sol)
            deficit[ll] += faltante

            if s_sin > EPS:
                sin_ex.append(
                    {
                        "Fecha": fecha,
                        "Bodega": bodega_,
                        "Codigo Articulo": cod_,
                        "Articulo": art,
                        "LLAVE": ll,
                        "Stock antes": s_antes,
                        "Entrada del movimiento": e_apl,
                        "Stock disponible": disp,
                        "Salida solicitada": sol,
                        "Salida aplicada": sol,
                        "Salida sin existencia": s_sin,
                        "Stock después": s_antes + e_apl - sol,
                        "Costo Total Con Iva": costo_k,
                    }
                )

            for lote, cant in consumos:
                lifo.append(
                    {
                        "Fecha": fecha,
                        "LLAVE": ll,
                        "Bodega": bodega_,
                        "Codigo Articulo": cod_,
                        "Cantidad salida aplicada": cant,
                        "Fecha lote consumido": lote["fecha"],
                        "Origen lote": lote["origen"],
                        "Costo unitario lote": lote["costo_unitario"],
                        "Costo salida LIFO": cant * lote["costo_unitario"],
                    }
                )

        # STOCK / COSTO DESPUÉS
        s_des = s_antes + e_apl - s_apl
        if abs(s_des) < EPS:
            s_des = 0.0
        c_des = c_antes + c_ent + c_sal

        # Corrección H-04: cuando el stock queda exactamente en 0 puede
        # quedar un valor sin unidades (el costo de salida viene del
        # Kardex). Se lleva a 0 y la diferencia queda registrada como
        # AJUSTE COSTO (hoja CONTROL_AJUSTES_COSTO), sin alterar el CMV.
        ajuste = 0.0
        if abs(s_des) <= EPS and abs(c_des) > 0:
            ajuste = -c_des
            if abs(ajuste) >= 0.01:
                ajustes.append(
                    {
                        "Fecha": fecha,
                        "Bodega": bodega_,
                        "Codigo Articulo": cod_,
                        "Articulo": art,
                        "LLAVE": ll,
                        "Costo antes del ajuste": c_des,
                        "Ajuste costo residual": ajuste,
                    }
                )
            c_des = 0.0

        stock_actual[ll] = s_des
        costo_actual[ll] = c_des

        movs.append(
            {
                "Fecha": fecha,
                "Tipo movimiento": TIPO_KARDEX,
                "Bodega": bodega_,
                "Codigo Articulo": cod_,
                "Articulo": art,
                "LLAVE": ll,
                "Stock antes": s_antes,
                "Entrada Kardex": float(f[i_ent_k]),
                "Salida Kardex": float(f[i_sal_k]),
                "Entrada aplicada": e_apl,
                "Salida aplicada": -s_apl,
                "Salida sin existencia": -s_sin,
                "Ajuste conciliación unidades": 0.0,
                "Stock después": s_des,
                "Costo Kardex Con Iva": costo_k,
                "Costo entrada aplicado": c_ent,
                "Costo salida aplicado": c_sal,
                "Ajuste costo residual": ajuste,
                "Ajuste conciliación valor": 0.0,
                "Costo después": c_des,
            }
        )

    # Ajustes de los meses sin movimientos posteriores
    while pendientes_aj:
        aplicar_ajustes_periodo(*pendientes_aj.pop(0))

    # ========================================================
    # DATAFRAMES DE CONTROL
    # ========================================================

    cols_mov = [
        "Fecha", "Tipo movimiento", "Bodega", "Codigo Articulo", "Articulo",
        "LLAVE", "Stock antes", "Entrada Kardex", "Salida Kardex",
        "Entrada aplicada", "Salida aplicada", "Salida sin existencia",
        "Ajuste conciliación unidades", "Stock después",
        "Costo Kardex Con Iva", "Costo entrada aplicado",
        "Costo salida aplicado", "Ajuste costo residual",
        "Ajuste conciliación valor", "Costo después",
    ]

    cols_sin = [
        "Fecha", "Bodega", "Codigo Articulo", "Articulo", "LLAVE",
        "Stock antes", "Entrada del movimiento", "Stock disponible",
        "Salida solicitada", "Salida aplicada", "Salida sin existencia",
        "Stock después", "Costo Total Con Iva",
    ]

    cols_aj_conc = [
        "Periodo", "Fecha", "Bodega", "Codigo Articulo", "Articulo", "LLAVE",
        "Stock calculado antes del ajuste", "Stock real", "Ajuste unidades",
        "Valor calculado antes del ajuste", "Valor real", "Ajuste valor",
        "Origen del valor", "Ajuste unidades aprobado", "Ajuste valor aprobado",
        "Cambió desde la aprobación", "Id conciliacion", "Archivo", "Usuario",
        "Fecha aprobacion",
    ]

    cols_lifo = [
        "Fecha", "LLAVE", "Bodega", "Codigo Articulo",
        "Cantidad salida aplicada", "Fecha lote consumido",
        "Origen lote", "Costo unitario lote", "Costo salida LIFO",
    ]

    cols_aj = [
        "Fecha", "Bodega", "Codigo Articulo", "Articulo", "LLAVE",
        "Costo antes del ajuste", "Ajuste costo residual",
    ]

    df_mov = pd.DataFrame(movs, columns=cols_mov)
    df_sin = pd.DataFrame(sin_ex, columns=cols_sin)
    df_lifo = pd.DataFrame(lifo, columns=cols_lifo)
    df_aj = pd.DataFrame(ajustes, columns=cols_aj)
    df_aj_conc = pd.DataFrame(ajustes_conc, columns=cols_aj_conc)
    df_ch = pd.DataFrame(
        ctrl_hist, columns=["LLAVE", "MES", "TIPO", "CANTIDAD"]
    )

    if revision:
        df_revision = pd.concat(revision, ignore_index=True)
    else:
        df_revision = pd.DataFrame(
            columns=["Fila en el archivo"] + COLUMNAS_MOVIMIENTO + ["Motivo"]
        )

    # ========================================================
    # RESUMEN MENSUAL
    # (crea las columnas de los meses nuevos o sobrescribe las
    #  existentes; nunca duplica una columna de un mismo mes)
    # Stock final = stock inicial + entradas + salidas (salidas < 0)
    # ========================================================

    primera = ~hist["LLAVE"].duplicated(keep="first")

    stock_prev = hist[c_stock_base].copy()
    coste_prev = hist[c_coste_base].copy()

    nuevas_cols = {}

    for nombre, anio, num in meses:
        ini = pd.Timestamp(anio, num, 1)
        fin = fin_periodo(anio, num)

        datos = df_mov[(df_mov["Fecha"] >= ini) & (df_mov["Fecha"] <= fin)]

        res = datos.groupby("LLAVE")[
            [
                "Entrada aplicada",
                "Salida aplicada",
                "Costo entrada aplicado",
                "Costo salida aplicado",
                "Ajuste costo residual",
                "Ajuste conciliación unidades",
                "Ajuste conciliación valor",
            ]
        ].sum()

        def mapear(col):
            return (
                hist["LLAVE"].map(res[col]).fillna(0.0).where(primera, 0.0)
            )

        sfx = f"{nombre} {anio}"

        entrada_m = mapear("Entrada aplicada")
        salida_m = mapear("Salida aplicada")
        neto_m = entrada_m + salida_m
        ce_m = mapear("Costo entrada aplicado")
        cs_m = mapear("Costo salida aplicado")
        aj_m = mapear("Ajuste costo residual")
        ajc_u = mapear("Ajuste conciliación unidades")
        ajc_v = mapear("Ajuste conciliación valor")
        # Stock = inicial + entradas + salidas (negativas) + ajuste de
        # conciliación. NETO conserva solo los movimientos del Kardex.
        stock_m = stock_prev + neto_m + ajc_u
        coste_m = coste_prev + ce_m + cs_m + aj_m + ajc_v

        nuevas_cols[f"ENTRADA {sfx}"] = entrada_m
        nuevas_cols[f"SALIDA {sfx}"] = salida_m
        nuevas_cols[f"NETO {sfx}"] = neto_m
        nuevas_cols[f"COSTO ENTRADA {sfx}"] = ce_m
        nuevas_cols[f"COSTO SALIDA {sfx}"] = cs_m
        nuevas_cols[f"AJUSTE COSTO {sfx}"] = aj_m
        nuevas_cols[f"AJUSTE CONCILIACION UNIDADES {sfx}"] = ajc_u
        nuevas_cols[f"AJUSTE CONCILIACION VALOR {sfx}"] = ajc_v
        nuevas_cols[f"STOCK {sfx}"] = stock_m
        nuevas_cols[f"COSTE TOTAL {sfx}"] = coste_m

        # ROTACIÓN MENSUAL (compatibilidad con el tablero)
        nuevas_cols[f"ROTACION {sfx}"] = pd.Series(
            np.where(
                stock_prev > 0,
                salida_m.abs() / stock_prev.replace(0, np.nan),
                np.nan,
            ),
            index=hist.index,
        )

        stock_prev = stock_m
        coste_prev = coste_m

    hist = pd.concat(
        [
            hist.drop(columns=[c for c in nuevas_cols if c in hist.columns]),
            pd.DataFrame(nuevas_cols, index=hist.index),
        ],
        axis=1,
    )

    # ========================================================
    # INDICADORES Y ANTIGÜEDAD
    # Usa TODOS los meses disponibles para ubicar el primer stock
    # y los últimos 12 para la antigüedad.
    # ========================================================

    hist, info_periodo, control_periodo = calcular_indicadores_12_meses(
        hist,
        obtener_meses_disponibles(hist),
        avisos,
    )

    norm_antiguos = {norm(x) for x in COLUMNAS_ANTIGUEDAD_ANTERIORES}
    hist = hist.drop(
        columns=[c for c in hist.columns if norm(c) in norm_antiguos]
    )

    # ========================================================
    # ORDEN Y REDONDEO
    # LLAVE penúltima y ANTIGUEDAD 12 MESES última.
    # ========================================================

    hist = hist[
        [
            c for c in hist.columns
            if c not in ("LLAVE", COL_ANTIGUEDAD_SALIDA)
        ]
        + ["LLAVE", COL_ANTIGUEDAD_SALIDA]
    ]

    for c in hist.columns:
        n = norm(c)

        if n.startswith("MESES"):
            continue

        if any(
            x in n
            for x in (
                "STOCK", "COST", "ENTRADA", "SALIDA", "NETO",
                "ROTACION", "CMV", "DIAS", "AJUSTE",
            )
        ):
            if pd.api.types.is_numeric_dtype(hist[c]):
                hist[c] = hist[c].astype(float).round(4)

    # ========================================================
    # VERIFICACIONES
    # Se separan los problemas heredados del histórico base de los
    # causados por los movimientos procesados.
    # ========================================================

    nombre_fin = nombre_periodo(anio_fin, mes_fin)

    verif = []

    d_stock = hist[f"STOCK {nombre_fin}"].sum() - sum(stock_actual.values())
    d_coste = hist[f"COSTE TOTAL {nombre_fin}"].sum() - sum(costo_actual.values())

    verif.append(
        (
            "Stock de la hoja cuadra con el motor",
            abs(d_stock) < 0.01,
            f"dif. {d_stock:,.4f}",
        )
    )

    verif.append(
        (
            "Costo de la hoja cuadra con el motor",
            abs(d_coste) < 0.01,
            f"dif. {d_coste:,.4f}",
        )
    )

    negativos_base = {ll for ll, b in base.items() if b["stock"] < -0.000001}
    con_movimiento = set(kp["LLAVE"]) | set(aj["LLAVE"])

    neg = {ll for ll, v in stock_actual.items() if v < -0.000001}
    neg_nuevos = neg - negativos_base

    verif.append(
        (
            "Llaves con stock negativo al cierre por salidas sin existencia (informativo)",
            True,
            f"{len(neg_nuevos)} llaves",
        )
    )

    if neg_nuevos:
        avisos.append(
            f"{len(neg_nuevos)} referencias quedaron con stock negativo al "
            "cierre porque registraron salidas sin existencias. Las salidas "
            "se contabilizaron completas; ver 'Salidas sin existencia'."
        )

    desc = {
        ll
        for ll in stock_actual
        if abs(
            sum(l["cantidad"] for l in lotes_lifo.get(ll, []))
            - deficit.get(ll, 0.0)
            - stock_actual[ll]
        )
        > 0.001
    }
    desc_nuevos = desc

    verif.append(
        (
            "Lotes LIFO cuadran con el stock",
            len(desc_nuevos) == 0,
            f"{len(desc_nuevos)} llaves",
        )
    )

    resid = {
        ll
        for ll in stock_actual
        if abs(stock_actual[ll]) <= EPS and abs(costo_actual[ll]) > 0.01
    }
    resid_nuevos = (resid & con_movimiento) - negativos_base

    verif.append(
        (
            "Sin costo residual con stock en 0 en llaves con movimientos",
            len(resid_nuevos) == 0,
            f"{len(resid_nuevos)} llaves",
        )
    )

    heredados = (neg & negativos_base) | (resid - con_movimiento)
    verif.append(
        (
            "Novedades heredadas del histórico base (informativo)",
            True,
            f"{len(neg & negativos_base)} stocks negativos y "
            f"{len(resid - con_movimiento)} costos residuales sin "
            "movimientos posteriores",
        )
    )

    if len(df_aj_conc):
        cambiaron = int(df_aj_conc["Cambió desde la aprobación"].sum())
        verif.append(
            (
                "Ajustes de conciliación aplicados (el stock queda igual al conteo real)",
                True,
                f"{len(df_aj_conc)} ajustes; {cambiaron} recalculados porque cambió un periodo anterior",
            )
        )
        if cambiaron:
            avisos.append(
                f"{cambiaron} ajustes de conciliación se recalcularon porque "
                "cambiaron los movimientos desde su aprobación (el stock "
                "sigue igual al conteo real). Ver 'Ajustes de conciliación'."
            )

    cols_antig = [c for c in hist.columns if norm(c).startswith("ANTIGUEDAD")]
    verif.append(
        (
            "Antigüedad en una sola columna, al final de la tabla",
            cols_antig == [COL_ANTIGUEDAD_SALIDA]
            and hist.columns[-1] == COL_ANTIGUEDAD_SALIDA,
            COL_ANTIGUEDAD_SALIDA,
        )
    )

    verif.append(
        (
            "Período de análisis de inventario",
            True,
            info_periodo["periodo"],
        )
    )

    verif.append(
        (
            "Meses utilizados para inventario",
            info_periodo["cantidad_meses"] > 0,
            f"{info_periodo['cantidad_meses']} meses",
        )
    )

    # ========================================================
    # ESTADÍSTICAS
    # ========================================================

    inv_prom_total = float(hist["INVENTARIO PROMEDIO 12 MESES"].fillna(0).sum())
    cmv_total = float(hist["CMV 12 MESES"].fillna(0).sum())

    stats.update(
        {
            "periodo_base": etiqueta_periodo(anio_base, mes_base),
            "periodo_final": etiqueta_periodo(anio_fin, mes_fin),
            "periodos": [
                etiqueta_periodo(a, m) for _, a, m in meses
            ],
            "mes_final": nombre_fin,
            "movimientos_procesados": len(df_mov),
            "con_salida_sin_existencia": len(df_sin),
            "unidades_sin_existencia": float(df_sin["Salida sin existencia"].sum()),
            "para_revision": len(df_revision),
            "ajustes_costo": len(df_aj),
            "ajustes_conciliacion": len(df_aj_conc),
            "ajuste_conciliacion_unidades": float(df_aj_conc["Ajuste unidades"].sum()),
            "ajuste_conciliacion_valor": float(df_aj_conc["Ajuste valor"].sum()),
            "llaves_stock_negativo": len(neg),
            "valor_ajustes_costo": float(df_aj["Ajuste costo residual"].sum()),
            "novedades_heredadas": len(heredados),
            "stock_base": float(hist[c_stock_base].sum()),
            "stock_mayo": float(hist[c_stock_base].sum()),
            "stock_final": float(hist[f"STOCK {nombre_fin}"].sum()),
            "coste_base": float(hist[c_coste_base].sum()),
            "coste_mayo": float(hist[c_coste_base].sum()),
            "coste_final": float(hist[f"COSTE TOTAL {nombre_fin}"].sum()),
            "sin_trazabilidad": 0,
            "periodo_inventario": info_periodo["periodo"],
            "meses_inventario": info_periodo["cantidad_meses"],
            "inventario_promedio_total": inv_prom_total,
            "cmv_12_meses_total": cmv_total,
            "rotacion_12_meses": (
                cmv_total / inv_prom_total if inv_prom_total > EPS else 0.0
            ),
        }
    )

    # ========================================================
    # RESULTADO
    # ========================================================

    return {
        "historico": hist,
        "movimientos": df_mov,
        "sin_existencia": df_sin,
        "lifo": df_lifo,
        "ajustes_costo": df_aj,
        "ajustes_conciliacion": df_aj_conc,
        "rechazados": df_rechazados,
        "revision": df_revision,
        "resumen": pd.DataFrame(
            [
                {
                    "LLAVE": ll,
                    "STOCK BASE": base[ll]["stock"] if ll in base else 0.0,
                    "COSTO BASE": base[ll]["costo"] if ll in base else 0.0,
                    "STOCK FINAL": stock_actual[ll],
                    "COSTO FINAL": costo_actual[ll],
                }
                for ll in sorted(stock_actual)
            ]
        ),
        "control_historico": df_ch,
        "control_periodo_12_meses": control_periodo,
        "duplicados": df_duplicados,
        "fechas_invalidas": df_fechas_invalidas,
        "avisos": avisos,
        "verificaciones": verif,
        "stats": stats,
    }


# ============================================================
# EXPORTACIÓN
# ============================================================

def resultado_a_excel(res):
    """Devuelve los bytes del Excel de salida."""

    buf = io.BytesIO()

    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        res["historico"].to_excel(w, sheet_name=HOJA_SALIDA, index=False)
        res["movimientos"].to_excel(w, sheet_name="CONTROL_MOVIMIENTOS", index=False)
        res["sin_existencia"].to_excel(w, sheet_name="CONTROL_SIN_EXISTENCIA", index=False)
        res["lifo"].to_excel(w, sheet_name="CONTROL_LIFO", index=False)
        res["resumen"].to_excel(w, sheet_name="RESUMEN_CONTROL", index=False)
        res["control_historico"].to_excel(w, sheet_name="CONTROL_HISTORICO", index=False)

        if "control_periodo_12_meses" in res:
            res["control_periodo_12_meses"].to_excel(
                w, sheet_name="CONTROL_12_MESES", index=False
            )

        if len(res["duplicados"]):
            res["duplicados"].to_excel(w, sheet_name="CONTROL_DUPLICADOS", index=False)

        if len(res["fechas_invalidas"]):
            res["fechas_invalidas"].to_excel(
                w, sheet_name="CONTROL_FECHAS_INVALIDAS", index=False
            )

        for clave, hoja in (
            ("rechazados", "CONTROL_RECHAZADOS"),
            ("revision", "CONTROL_REVISION"),
            ("ajustes_costo", "CONTROL_AJUSTES_COSTO"),
            ("ajustes_conciliacion", "CONTROL_AJUSTES_CONCILIACION"),
        ):
            if clave in res and len(res[clave]):
                res[clave].to_excel(w, sheet_name=hoja, index=False)

    return buf.getvalue()


# ============================================================
# CARGA PARA EL TABLERO
# ============================================================

def cargar_base(archivo_actualizado, archivo_historico):
    """
    Prioridad:
    archivo actualizado -> histórico base.
    """

    if archivo_actualizado and os.path.exists(archivo_actualizado):
        df, _ = leer_historico(archivo_actualizado)
        return df, "actualizado"

    if archivo_historico and os.path.exists(archivo_historico):
        df, _ = leer_historico(archivo_historico)
        return df, "base"

    return None, None


def firma_archivos(*rutas):
    return tuple(
        os.path.getmtime(r) if r and os.path.exists(r) else 0 for r in rutas
    )


def _secuencia_meses(df):
    """Meses (nombre, año) presentes en los datos, sin años fijos."""
    return [(NOMBRES_MES[m - 1], a) for a, m in meses_con_stock(df)]


# ============================================================
# ESQUEMA
# ============================================================

def construir_esquema(df):
    """Detecta meses y columnas del tablero."""

    meses = []

    for nombre, anio in _secuencia_meses(df):
        sfx = f"{nombre} {anio}"

        stock = col_exacta(df, f"STOCK {sfx}")
        if stock is None:
            continue

        coste_total = col_exacta(df, f"COSTE TOTAL {sfx}")
        coste_simple = col_exacta(df, f"COSTE {sfx}")
        coste = coste_total if coste_total is not None else coste_simple

        meses.append(
            {
                "label": f"{nombre[:3]} {str(anio)[2:]}",
                "sfx": sfx,
                "stock": stock,
                "coste": coste,
                "entrada": col_exacta(df, f"ENTRADA {sfx}"),
                "salida": col_exacta(df, f"SALIDA {sfx}"),
                "costo_entrada": col_exacta(df, f"COSTO ENTRADA {sfx}"),
                "costo_salida": col_exacta(df, f"COSTO SALIDA {sfx}"),
                "rotacion": col_exacta(df, f"ROTACION {sfx}"),
                "antiguedad": col_exacta(df, f"ANTIGUEDAD {sfx}"),
            }
        )

    if not meses:
        raise ValueError(
            "No se encontraron columnas 'STOCK <MES> <AÑO>' en los datos."
        )

    ultimo = meses[-1]

    con_coste = [m for m in meses if m["coste"]]
    con_antig = [m for m in meses if m["antiguedad"]]

    columnas_rotacion = [
        m["rotacion"] for m in meses if m["rotacion"] is not None
    ]

    # ========================================================
    # ANTIGÜEDAD: ANTIGUEDAD 12 MESES (la vigente) y, si no
    # existe, los nombres anteriores.
    # ========================================================

    col_antig_actual = (
        col_exacta(df, COL_ANTIGUEDAD_SALIDA)
        or col_exacta(df, "ANTIGUEDAD ULTIMO MES DE ACTUALIZACIÓN")
    )

    if col_antig_actual is not None:
        col_antiguedad_tablero = col_antig_actual
    elif con_antig:
        col_antiguedad_tablero = con_antig[-1]["antiguedad"]
    else:
        col_antiguedad_tablero = col_exacta(df, "MESES")

    return {
        "meses": meses,
        "etiquetas": [m["label"] for m in meses],
        "corte": ultimo["sfx"].title(),
        "col_stock": ultimo["stock"],
        # Corrección H-06: valor del MISMO mes que el stock del corte
        # (antes estaba fijo en 'COSTE TOTAL AGOSTO 2026').
        "col_coste": (
            ultimo["coste"]
            if ultimo["coste"]
            else (con_coste[-1]["coste"] if con_coste else None)
        ),
        "col_antiguedad": col_antiguedad_tablero,
        "columnas_rotacion": columnas_rotacion,
        "mes_rotacion": ultimo,
        "col_inventario_promedio": col_exacta(df, "INVENTARIO PROMEDIO 12 MESES"),
        "col_cmv_12_meses": col_exacta(df, "CMV 12 MESES"),
        "col_rotacion_12_meses": col_exacta(df, "ROTACION 12 MESES"),
        "col_dias_rotacion_12_meses": col_exacta(df, "DIAS ROTACION 12 MESES"),
        "col_meses_validos": col_exacta(df, "MESES VALIDOS INVENTARIO"),
        "col_periodo_inventario": col_exacta(df, "PERIODO ANALISIS INVENTARIO"),
    }


# ============================================================
# TIPOS DE COLUMNAS
# ============================================================

def tipos_columnas_app(df):
    texto_ = {
        "Bodega",
        "Codigo Articulo",
        "Articulo",
        "MESES",
        "AREA",
        "LLAVE",
        "OBSERVACION",
        "PERIODO ANALISIS INVENTARIO",
        "PRIMER MES CON STOCK",
    }

    return [
        c
        for c in df.columns
        if c in texto_ or norm(c).startswith("ANTIGUEDAD")
    ]


# ============================================================
# KPIs
# ============================================================

def kpis_corte(df_f, esq):

    # STOCK
    stock = float(df_f[esq["col_stock"]].fillna(0).sum())

    # VALOR INVENTARIO
    valor = (
        float(df_f[esq["col_coste"]].fillna(0).sum())
        if esq["col_coste"]
        else 0.0
    )

    # ROTACIÓN 12 MESES
    rot = 0.0
    col_rot_12 = esq.get("col_rotacion_12_meses")

    if col_rot_12 and col_rot_12 in df_f.columns:
        inventario_promedio = float(
            pd.to_numeric(df_f[esq["col_inventario_promedio"]], errors="coerce")
            .fillna(0)
            .sum()
        )
        cmv = float(
            pd.to_numeric(df_f[esq["col_cmv_12_meses"]], errors="coerce")
            .fillna(0)
            .sum()
        )

        if inventario_promedio > EPS:
            rot = cmv / inventario_promedio

    # DÍAS DE ROTACIÓN 12 MESES
    # Global: inventario promedio total x días de la ventana completa
    # (12 meses x 30 días = 360) / CMV total.
    dias = 0.0
    col_dias = esq.get("col_dias_rotacion_12_meses")

    if col_dias and col_dias in df_f.columns:
        valores_dias = pd.to_numeric(df_f[col_dias], errors="coerce")

        if (
            col_rot_12
            and esq.get("col_inventario_promedio")
            and esq.get("col_cmv_12_meses")
        ):
            inv_prom = float(
                pd.to_numeric(df_f[esq["col_inventario_promedio"]], errors="coerce")
                .fillna(0)
                .sum()
            )
            cmv_total = float(
                pd.to_numeric(df_f[esq["col_cmv_12_meses"]], errors="coerce")
                .fillna(0)
                .sum()
            )

            if cmv_total > EPS:
                dias = DIAS_VENTANA_COMPLETA * inv_prom / cmv_total

        elif len(valores_dias.dropna()):
            dias = float(valores_dias.mean())

    return stock, valor, rot, dias


# ============================================================
# PESTAÑA STREAMLIT
# La página vive ahora en gestion_kardex.py (cargues mensuales con
# registro de periodos). Se conserva este nombre por compatibilidad.
# ============================================================

def pagina_actualizar_kardex(st, usuario, archivo_actualizado, archivo_historico):
    """Renderiza la página Actualizar Kardex (ver gestion_kardex.py)."""
    import gestion_kardex

    return gestion_kardex.pagina_actualizar_kardex(
        st, usuario, archivo_actualizado, archivo_historico
    )
