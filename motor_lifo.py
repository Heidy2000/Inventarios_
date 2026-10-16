# -*- coding: utf-8 -*-
"""
motor_lifo.py
Motor de actualización Histórico + Kardex y pestaña de Streamlit
"Actualizar Kardex" para el tablero Inventarios ALDC.

La reconstrucción de stock y costos continúa utilizando el motor
LIFO para conservar la trazabilidad y las hojas de control.

La antigüedad ya NO se calcula con los lotes LIFO: se calcula con los
indicadores de rotación (inventario promedio, CMV, días de rotación) y
se escribe en la columna ANTIGUEDAD 12 MESES, que queda como la ÚLTIMA
columna de la tabla.
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
ANIO = 2026
HOJA_SALIDA = "INVENTARIO"

NOMBRES_MES = [
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO",
    "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
]

# Se excluyen por NÚMERO de bodega
BODEGAS_EXCLUIDAS = {"11", "12", "18", "19", "20", "21"}

MARCA_NUEVO = "NUEVO DESDE KARDEX"

# Fecha que representa el stock inicial
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
# MESES HISTÓRICOS
# ============================================================

# Jun-2025 ... May-2026
MESES_HISTORICO = [
    (f"{NOMBRES_MES[m - 1]} {a}", _fin_mes(a, m))
    for a, m in (
        [(2025, x) for x in range(6, 13)]
        + [(2026, x) for x in range(1, 6)]
    )
]


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
        return 0.0


def a_numero(serie):
    if pd.api.types.is_numeric_dtype(serie):
        return pd.to_numeric(serie, errors="coerce").fillna(0.0).astype(float)
    return serie.apply(_a_float).astype(float)


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

    c_stock = col_exacta(df, "STOCK MAYO 2026")
    if c_stock is None:
        raise ValueError(
            "El histórico no tiene la columna 'STOCK MAYO 2026'."
        )

    c_coste = None
    for cand in [
        "COSTE MAYO 2026",
        "COSTE TOTAL MAYO 2026",
        "COSTE TOTAL MAYO",
        "COSTO TOTAL MAYO",
        "COSTE MAYO",
        "COSTO MAYO 2026",
    ]:
        c_coste = col_exacta(df, cand)
        if c_coste:
            break

    if c_coste is not None:
        if c_coste != "COSTE MAYO 2026":
            df = df.rename(columns={c_coste: "COSTE MAYO 2026"})
        df["COSTE MAYO 2026"] = a_numero(df["COSTE MAYO 2026"])
    else:
        c_abr = col_exacta(df, "COSTE ABRIL 2026")
        c_ent = col_exacta(df, "COSTO ENTRADA MAYO 2026")
        c_sal = col_exacta(df, "COSTO SALIDA MAYO 2026")

        if c_abr is None or c_ent is None:
            raise ValueError(
                "El histórico no trae el coste de mayo 2026 "
                "y no se puede reconstruir "
                "(faltan 'COSTE ABRIL 2026' y/o "
                "'COSTO ENTRADA MAYO 2026')."
            )

        coste = a_numero(df[c_abr]) + a_numero(df[c_ent])
        if c_sal is not None:
            coste = coste - a_numero(df[c_sal]).abs()
        df["COSTE MAYO 2026"] = coste

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
        io.BytesIO(contenido), read_only=False, data_only=True
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

    k = pd.DataFrame(filas[fila_k + 1:], columns=encabezados)
    k = (
        k.dropna(axis=0, how="all")
        .reset_index(drop=True)
        .dropna(axis=1, how="all")
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

    meses_desde = np.where(
        primer_idx >= 0,
        ultimo_num - periodos_num[np.clip(primer_idx, 0, None)] + 1,
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
    etiqueta_periodo = f"{nombres_ventana[0]} a {nombres_ventana[-1]}"

    etiquetas_mes = np.array(
        [f"{p['anio']}-{p['mes']:02d}" for p in todos], dtype=object
    )

    hist["INVENTARIO PROMEDIO 12 MESES"] = inventario_promedio
    hist["CMV 12 MESES"] = cmv
    hist["ROTACION 12 MESES"] = rotacion
    hist["DIAS ROTACION 12 MESES"] = dias_rotacion
    hist["MESES VALIDOS INVENTARIO"] = divisor
    hist["DIAS DEL PERIODO"] = dias_periodo
    hist["PRIMER MES CON STOCK"] = np.where(
        tiene_primer_stock,
        etiquetas_mes[np.clip(primer_idx, 0, None)],
        None,
    )
    hist["MESES DESDE PRIMER STOCK"] = np.where(tiene_primer_stock, meses_desde, 0)
    hist["PERIODO ANALISIS INVENTARIO"] = etiqueta_periodo
    hist[COL_ANTIGUEDAD_SALIDA] = antiguedad

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
        "periodo": etiqueta_periodo,
        "cantidad_meses": len(nombres_ventana),
        "meses": nombres_ventana,
        "mes_inicial": nombres_ventana[0],
        "mes_final": nombres_ventana[-1],
    }

    return hist, info_periodo, control


# ============================================================
# MOTOR PRINCIPAL
# ============================================================

def procesar_inventario(historico, kardex, mes_final=9):
    """
    historico: DataFrame ya preparado.
    kardex   : DataFrame crudo del Kardex detallado.
    mes_final: último mes de 2026 a calcular.

    La unidad de consolidación es LLAVE = número de bodega + código
    de artículo, por lo que cada bodega conserva sus propios
    movimientos, existencias, costos e indicadores.

    Siempre se parte del histórico base (stock y coste de mayo 2026) y
    se recalculan los meses jun-2026 ... mes_final: cargar dos veces el
    mismo Kardex da el mismo resultado (no acumula).
    """

    avisos = []

    meses = [(NOMBRES_MES[m - 1], m) for m in range(6, mes_final + 1)]

    fecha_inicio = pd.Timestamp(ANIO, 6, 1)
    fecha_fin = _fin_mes(ANIO, mes_final) + pd.Timedelta(
        hours=23, minutes=59, seconds=59
    )

    hist = historico.copy()

    c_bod = col_buscar(hist, ["Bodega"])
    c_cod = col_buscar(hist, ["Codigo Articulo"])
    c_art = col_buscar(hist, ["Articulo"], obligatoria=False)

    c_stock_mayo = col_exacta(hist, "STOCK MAYO 2026")
    c_coste_mayo = "COSTE MAYO 2026"
    c_stock_ini = col_exacta(hist, "STOCK INICIAL")
    c_coste_ini = col_exacta(hist, "COSTE INICIAL")

    # ========================================================
    # COLUMNAS MENSUALES DEL HISTÓRICO
    # ========================================================

    cols_h = {}
    faltan = 0

    for nombre, _ in MESES_HISTORICO:
        cols = {
            "entrada": col_exacta(hist, f"ENTRADA {nombre}"),
            "salida": col_exacta(hist, f"SALIDA {nombre}"),
            "stock": col_exacta(hist, f"STOCK {nombre}"),
            "costo_entrada": col_exacta(hist, f"COSTO ENTRADA {nombre}"),
        }
        faltan += sum(1 for v in cols.values() if v is None)
        cols_h[nombre] = cols

    if faltan:
        avisos.append(
            f"{faltan} columnas mensuales del histórico "
            "no existen (se toman como 0)."
        )

    num_cols = {c_stock_mayo, c_coste_mayo, c_stock_ini, c_coste_ini}
    for cols in cols_h.values():
        num_cols.update(cols.values())

    for c in [x for x in num_cols if x is not None]:
        hist[c] = a_numero(hist[c])

    # ========================================================
    # DUPLICADOS
    # ========================================================

    duplicados = hist[hist["LLAVE"].duplicated(keep=False)]

    df_duplicados = duplicados[
        ["LLAVE", c_bod, c_cod, c_stock_mayo, c_coste_mayo]
    ].copy()

    if len(duplicados):
        avisos.append(
            f"{duplicados['LLAVE'].nunique()} llaves repetidas en el "
            "histórico; los movimientos se asignan a la primera fila "
            "de cada llave."
        )

    # ========================================================
    # KARDEX
    # ========================================================

    k = kardex.copy()

    k_bod = col_buscar(k, ["Bodega"])
    k_cod = col_buscar(k, ["Codigo Articulo"])
    k_est = col_buscar(k, ["EstadoMovimiento", "Estado Movimiento"])
    k_art = col_buscar(k, ["Articulo"], obligatoria=False)
    k_fec = col_buscar(k, ["Fecha Movimiento"])
    k_ent = col_buscar(k, ["Cantidad Entrada"])
    k_sal = col_buscar(k, ["Cantidad Salida"])
    k_cos = col_buscar(k, ["Costo Total Con Iva"])

    k[k_bod] = k[k_bod].apply(bodega_txt)
    k[k_cod] = k[k_cod].apply(codigo)

    if pd.api.types.is_datetime64_any_dtype(k[k_fec]):
        k[k_fec] = pd.to_datetime(k[k_fec], errors="coerce")
    else:
        k[k_fec] = pd.to_datetime(k[k_fec], errors="coerce", dayfirst=True)

    for c in (k_ent, k_sal, k_cos):
        k[c] = a_numero(k[c])

    stats = {"filas_kardex": len(k)}

    if len(k) == 15000:
        avisos.append(
            "El Kardex trae exactamente 15.000 filas: "
            "la exportación podría estar truncada en origen."
        )

    df_fechas_invalidas = k[k[k_fec].isna()].copy()
    stats["fechas_invalidas"] = len(df_fechas_invalidas)

    if stats["fechas_invalidas"]:
        avisos.append(
            f"{stats['fechas_invalidas']} movimientos "
            "sin fecha válida (no se procesan)."
        )

    k["_NUM_BODEGA"] = k[k_bod].apply(numero_bodega)

    n0 = len(k)
    k = k[~k["_NUM_BODEGA"].isin(BODEGAS_EXCLUIDAS)].copy()
    stats["excluidos_bodega"] = n0 - len(k)

    anulado = k[k_est].astype(str).str.upper().str.contains("ANULADO", na=False)
    stats["anulados"] = int(anulado.sum())
    k = k[~anulado].copy()

    k["LLAVE"] = k.apply(lambda f: crear_llave(f[k_bod], f[k_cod]), axis=1)

    kp = k[(k[k_fec] >= fecha_inicio) & (k[k_fec] <= fecha_fin)].copy()
    stats["movimientos_periodo"] = len(kp)

    if len(kp) == 0:
        raise ValueError(
            f"El Kardex no tiene movimientos entre "
            f"{fecha_inicio:%d/%m/%Y} y {fecha_fin:%d/%m/%Y}."
        )

    stats["fecha_min"] = kp[k_fec].min()
    stats["fecha_max"] = kp[k_fec].max()

    ent = kp[k_ent]
    sal = kp[k_sal]

    stats["entradas_negativas"] = int((ent < 0).sum())
    stats["salidas_positivas"] = int((sal > 0).sum())

    kp["ENT"] = ent.clip(lower=0.0)
    kp["SAL"] = -sal.abs() + ent.where(ent < 0, 0.0)

    # ========================================================
    # LLAVES NUEVAS (referencia o bodega que aparecen por 1ª vez)
    # ========================================================

    nuevas = set(kp["LLAVE"]) - set(hist["LLAVE"])
    stats["llaves_nuevas"] = len(nuevas)

    if nuevas:
        primeras = (
            kp.sort_values(k_fec).drop_duplicates("LLAVE").set_index("LLAVE")
        )

        filas = []

        for llave in sorted(nuevas):
            p = primeras.loc[llave]

            nueva = {c: np.nan for c in hist.columns}
            nueva["LLAVE"] = llave
            nueva[c_bod] = p[k_bod]
            nueva[c_cod] = p[k_cod]

            if c_art is not None and k_art is not None:
                nueva[c_art] = p[k_art]

            nueva["OBSERVACION"] = MARCA_NUEVO
            filas.append(nueva)

        hist = pd.concat(
            [hist, pd.DataFrame(filas, columns=hist.columns)],
            ignore_index=True,
        )

        for c in [x for x in num_cols if x is not None]:
            hist[c] = a_numero(hist[c])

    # ========================================================
    # BASE MAYO 2026
    # ========================================================

    base = defaultdict(lambda: {"stock": 0.0, "costo": 0.0})

    for ll, s, c in zip(hist["LLAVE"], hist[c_stock_mayo], hist[c_coste_mayo]):
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

        # STOCK INICIAL
        s_ini = val(fila, c_stock_ini)
        c_ini = val(fila, c_coste_ini)

        if s_ini > 0:
            lotes.append(
                {
                    "fecha": FECHA_STOCK_INICIAL,
                    "cantidad": s_ini,
                    "costo_unitario": c_ini / s_ini,
                    "origen": "STOCK INICIAL",
                }
            )

        # ENTRADAS Y SALIDAS HISTÓRICAS (JUNIO 2025 - MAYO 2026)
        for nombre, fecha_mes in MESES_HISTORICO:
            cols = cols_h[nombre]

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
    # CUADRAR LOTES CONTRA STOCK MAYO
    # ========================================================

    for ll, b in base.items():
        lotes = lotes_lifo[ll]
        dif = sum(l["cantidad"] for l in lotes) - b["stock"]

        if dif > 0.0001:
            consumir_lifo(lotes, dif)
            ctrl_hist.append(
                {
                    "LLAVE": ll,
                    "MES": "AJUSTE A MAYO 2026",
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
                    "origen": "SIN TRAZABILIDAD (AJUSTE A MAYO 2026)",
                },
            )
            ctrl_hist.append(
                {
                    "LLAVE": ll,
                    "MES": "AJUSTE A MAYO 2026",
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
    # CIERRES MENSUALES
    # ========================================================

    pendientes = [
        (
            n,
            _fin_mes(ANIO, m) + pd.Timedelta(hours=23, minutes=59, seconds=59),
        )
        for n, m in meses
    ]

    # ========================================================
    # PROCESAR MOVIMIENTOS
    # ========================================================

    kp["_ORD"] = np.where((kp["ENT"] > 0) & (kp["SAL"] == 0), 0, 1)
    kp["_SEQ"] = np.arange(len(kp))

    kp = kp.sort_values([k_fec, "_ORD", "_SEQ"]).reset_index(drop=True)

    movs = []
    sin_ex = []
    lifo = []

    for _, f in kp.iterrows():
        ll = f["LLAVE"]
        fecha = f[k_fec]

        ent_ = float(f["ENT"])
        sal_ = float(f["SAL"])
        costo_k = float(f[k_cos])

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

        art = f[k_art] if k_art is not None else ""

        # ENTRADA
        if ent_ > 0:
            e_apl = ent_
            c_ent = abs(costo_k)

            lotes.append(
                {
                    "fecha": fecha,
                    "cantidad": ent_,
                    "costo_unitario": abs(costo_k) / ent_,
                    "origen": "KARDEX",
                }
            )

        # SALIDA
        if sal_ < 0:
            sol = abs(sal_)
            disp = max(s_antes + e_apl, 0.0)
            s_apl = min(sol, disp)
            s_sin = sol - s_apl

            if s_sin > EPS:
                sin_ex.append(
                    {
                        "Fecha": fecha,
                        "Bodega": f[k_bod],
                        "Codigo Articulo": f[k_cod],
                        "Articulo": art,
                        "LLAVE": ll,
                        "Stock antes": s_antes,
                        "Entrada del movimiento": e_apl,
                        "Stock disponible": disp,
                        "Salida solicitada": sol,
                        "Salida aplicada": s_apl,
                        "Salida sin existencia": s_sin,
                        "Costo Total Con Iva": costo_k,
                    }
                )

            c_sal = -abs(costo_k) * (s_apl / sol if sol else 0.0)

            consumos, _ = consumir_lifo(lotes, s_apl)

            for lote, cant in consumos:
                lifo.append(
                    {
                        "Fecha": fecha,
                        "LLAVE": ll,
                        "Bodega": f[k_bod],
                        "Codigo Articulo": f[k_cod],
                        "Cantidad salida aplicada": cant,
                        "Fecha lote consumido": lote["fecha"],
                        "Origen lote": lote["origen"],
                        "Costo unitario lote": lote["costo_unitario"],
                        "Costo salida LIFO": cant * lote["costo_unitario"],
                    }
                )

        # STOCK / COSTO DESPUÉS
        s_des = max(s_antes + e_apl - s_apl, 0.0)
        c_des = c_antes + c_ent + c_sal

        if c_des < 0 and abs(c_des) < 0.01:
            c_des = 0.0

        stock_actual[ll] = s_des
        costo_actual[ll] = c_des

        movs.append(
            {
                "Fecha": fecha,
                "Bodega": f[k_bod],
                "Codigo Articulo": f[k_cod],
                "Articulo": art,
                "LLAVE": ll,
                "Stock antes": s_antes,
                "Entrada Kardex": ent_,
                "Salida Kardex": sal_,
                "Entrada aplicada": e_apl,
                "Salida aplicada": -s_apl,
                "Salida sin existencia": -s_sin,
                "Stock después": s_des,
                "Costo Kardex Con Iva": costo_k,
                "Costo entrada aplicado": c_ent,
                "Costo salida aplicado": c_sal,
                "Costo después": c_des,
            }
        )

        # FOTOS MENSUALES (se conserva por compatibilidad;
        # ya NO determina la antigüedad)
        while pendientes and fecha > pendientes[0][1]:
            pendientes.pop(0)

    # ========================================================
    # DATAFRAMES DE CONTROL
    # ========================================================

    cols_mov = [
        "Fecha", "Bodega", "Codigo Articulo", "Articulo", "LLAVE",
        "Stock antes", "Entrada Kardex", "Salida Kardex",
        "Entrada aplicada", "Salida aplicada", "Salida sin existencia",
        "Stock después", "Costo Kardex Con Iva",
        "Costo entrada aplicado", "Costo salida aplicado",
        "Costo después",
    ]

    cols_sin = [
        "Fecha", "Bodega", "Codigo Articulo", "Articulo", "LLAVE",
        "Stock antes", "Entrada del movimiento", "Stock disponible",
        "Salida solicitada", "Salida aplicada", "Salida sin existencia",
        "Costo Total Con Iva",
    ]

    cols_lifo = [
        "Fecha", "LLAVE", "Bodega", "Codigo Articulo",
        "Cantidad salida aplicada", "Fecha lote consumido",
        "Origen lote", "Costo unitario lote", "Costo salida LIFO",
    ]

    df_mov = pd.DataFrame(movs, columns=cols_mov)
    df_sin = pd.DataFrame(sin_ex, columns=cols_sin)
    df_lifo = pd.DataFrame(lifo, columns=cols_lifo)
    df_ch = pd.DataFrame(
        ctrl_hist, columns=["LLAVE", "MES", "TIPO", "CANTIDAD"]
    )

    # ========================================================
    # RESUMEN MENSUAL
    # (crea las columnas de los meses nuevos o sobrescribe las
    #  existentes; nunca duplica una columna de un mismo mes)
    # ========================================================

    primera = ~hist["LLAVE"].duplicated(keep="first")

    stock_prev = hist["STOCK MAYO 2026"].copy()
    coste_prev = hist["COSTE MAYO 2026"].copy()

    for nombre, num in meses:
        ini = pd.Timestamp(ANIO, num, 1)
        fin = _fin_mes(ANIO, num) + pd.Timedelta(
            hours=23, minutes=59, seconds=59
        )

        datos = df_mov[(df_mov["Fecha"] >= ini) & (df_mov["Fecha"] <= fin)]

        res = datos.groupby("LLAVE")[
            [
                "Entrada aplicada",
                "Salida aplicada",
                "Costo entrada aplicado",
                "Costo salida aplicado",
            ]
        ].sum()

        def mapear(col):
            return (
                hist["LLAVE"].map(res[col]).fillna(0.0).where(primera, 0.0)
            )

        sfx = f"{nombre} {ANIO}"

        hist[f"ENTRADA {sfx}"] = mapear("Entrada aplicada")
        hist[f"SALIDA {sfx}"] = mapear("Salida aplicada")
        hist[f"NETO {sfx}"] = hist[f"ENTRADA {sfx}"] + hist[f"SALIDA {sfx}"]
        hist[f"COSTO ENTRADA {sfx}"] = mapear("Costo entrada aplicado")
        hist[f"COSTO SALIDA {sfx}"] = mapear("Costo salida aplicado")
        hist[f"STOCK {sfx}"] = stock_prev + hist[f"NETO {sfx}"]
        hist[f"COSTE TOTAL {sfx}"] = (
            coste_prev
            + hist[f"COSTO ENTRADA {sfx}"]
            + hist[f"COSTO SALIDA {sfx}"]
        )

        # ROTACIÓN MENSUAL
        # Se conserva para compatibilidad con el tablero.
        hist[f"ROTACION {sfx}"] = np.where(
            stock_prev > 0,
            hist[f"SALIDA {sfx}"].abs() / stock_prev.replace(0, np.nan),
            np.nan,
        )

        # Continuar con stock/costo actual
        stock_prev = hist[f"STOCK {sfx}"]
        coste_prev = hist[f"COSTE TOTAL {sfx}"]

    # ========================================================
    # INDICADORES Y ANTIGÜEDAD (NUEVA LÓGICA)
    # Usa TODOS los meses disponibles para ubicar el primer stock
    # y los últimos 12 para la antigüedad.
    # ========================================================

    hist, info_periodo, control_periodo = calcular_indicadores_12_meses(
        hist,
        obtener_meses_disponibles(hist),
        avisos,
    )

    # Retirar los nombres antiguos de antigüedad: queda UNA sola columna
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
                "ROTACION", "CMV", "DIAS",
            )
        ):
            if pd.api.types.is_numeric_dtype(hist[c]):
                hist[c] = hist[c].astype(float).round(4)

    # ========================================================
    # VERIFICACIONES
    # ========================================================

    sfx_f = f"{meses[-1][0]} {ANIO}"

    verif = []

    d_stock = hist[f"STOCK {sfx_f}"].sum() - sum(stock_actual.values())
    d_coste = hist[f"COSTE TOTAL {sfx_f}"].sum() - sum(costo_actual.values())

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

    neg = sum(1 for v in stock_actual.values() if v < -0.000001)
    verif.append(("Sin stocks negativos", neg == 0, f"{neg} llaves"))

    desc = sum(
        1
        for ll in stock_actual
        if abs(
            sum(l["cantidad"] for l in lotes_lifo.get(ll, []))
            - stock_actual[ll]
        )
        > 0.001
    )
    verif.append(("Lotes LIFO cuadran con el stock", desc == 0, f"{desc} llaves"))

    resid = sum(
        1
        for ll in stock_actual
        if stock_actual[ll] <= EPS and abs(costo_actual[ll]) > 0.01
    )
    verif.append(
        ("Sin costo residual con stock en 0", resid == 0, f"{resid} llaves")
    )

    # Una sola columna de antigüedad y en la última posición
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
            "mes_final": meses[-1][0],
            "movimientos_procesados": len(df_mov),
            "con_salida_sin_existencia": len(df_sin),
            "unidades_sin_existencia": float(df_sin["Salida sin existencia"].sum()),
            "stock_mayo": float(hist[c_stock_mayo].sum()),
            "stock_final": float(hist[f"STOCK {sfx_f}"].sum()),
            "coste_mayo": float(hist[c_coste_mayo].sum()),
            "coste_final": float(hist[f"COSTE TOTAL {sfx_f}"].sum()),
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
        "resumen": pd.DataFrame(
            [
                {
                    "LLAVE": ll,
                    "STOCK MAYO": base[ll]["stock"] if ll in base else 0.0,
                    "COSTO MAYO": base[ll]["costo"] if ll in base else 0.0,
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


def _secuencia_meses():
    sec = [(NOMBRES_MES[m - 1], 2025) for m in range(6, 13)]
    sec += [(NOMBRES_MES[m - 1], 2026) for m in range(1, 13)]
    return sec


# ============================================================
# ESQUEMA
# ============================================================

def construir_esquema(df):
    """Detecta meses y columnas del tablero."""

    meses = []

    for nombre, anio in _secuencia_meses():
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
        "col_coste": (
            col_exacta(df, "COSTE TOTAL AGOSTO 2026")
            if col_exacta(df, "COSTE TOTAL AGOSTO 2026")
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
# ============================================================

def pagina_actualizar_kardex(st, usuario, archivo_actualizado, archivo_historico):
    """Renderiza la pestaña Actualizar Kardex."""

    try:
        admins = [str(x).strip() for x in list(st.secrets["admins"])]
    except Exception:
        admins = []

    if admins and usuario not in admins:
        st.title("Actualizar Kardex")
        st.warning("Tu usuario no tiene permiso para actualizar la información.")
        return

    st.title("Actualizar Kardex")

    st.caption(
        "Carga el Kardex detallado y el tablero recalcula stock, costos, "
        "rotación y antigüedad utilizando los últimos 12 meses "
        "disponibles en la base de datos."
    )

    hay_base = bool(archivo_historico and os.path.exists(archivo_historico))

    c1, c2 = st.columns([1.3, 1])

    with c1:
        kardex_file = st.file_uploader(
            "Kardex (Excel con el detalle de movimientos)",
            type=["xlsx", "xlsm"],
            key="up_kardex",
        )

        hist_file = st.file_uploader(
            (
                "Histórico base (opcional)"
                if hay_base
                else "Histórico base (obligatorio)"
            ),
            type=["xlsx", "xlsm"],
            key="up_historico",
            help=(
                "Si no lo cargas se usa el histórico guardado en el servidor."
                if hay_base
                else "No hay un histórico guardado en el servidor."
            ),
        )

    with c2:
        mes_final = st.selectbox(
            "Calcular hasta",
            [(NOMBRES_MES[m - 1], m) for m in range(6, 13)],
            index=3,
            format_func=lambda x: f"{x[0].title()} {ANIO}",
        )

        st.info(
            "Se excluyen movimientos **5-ANULADO** "
            "y las bodegas 11, 12, 18, 19, 20 y 21. "
            "Las salidas que superan el stock se "
            "registran como *salida sin existencia*. "
            "La antigüedad se determina mediante "
            "indicadores de los últimos 12 meses "
            "disponibles."
        )

    puede = kardex_file is not None and (hist_file is not None or hay_base)

    exito = False

    if st.button(
        "Procesar y actualizar el tablero",
        disabled=not puede,
        use_container_width=True,
    ):
        try:
            with st.spinner(
                "Procesando Kardex y calculando indicadores de inventario..."
            ):
                origen_h = hist_file if hist_file is not None else archivo_historico

                historico, _ = leer_historico(origen_h)
                kardex, hoja_k = leer_kardex(kardex_file)

                res = procesar_inventario(historico, kardex, mes_final[1])

                excel = resultado_a_excel(res)

            guardado = True

            try:
                with open(archivo_actualizado, "wb") as f:
                    f.write(excel)
            except Exception:
                guardado = False

            df_nuevo, _ = leer_historico(excel)

            st.session_state["df_actualizado"] = df_nuevo
            st.session_state["res_actualizacion"] = res
            st.session_state["excel_actualizado"] = excel
            st.session_state["guardado_en_disco"] = guardado

            try:
                st.cache_data.clear()
            except Exception:
                pass

            exito = True

        except Exception as e:
            st.error(f"No fue posible procesar los archivos.\n\n{e}")

    if exito:
        st.rerun()

    res = st.session_state.get("res_actualizacion")

    if res is None:
        return

    s = res["stats"]

    st.success(
        f"Tablero actualizado hasta {s['mes_final'].title()} {ANIO}. "
        f"El análisis de inventario utiliza {s['meses_inventario']} meses: "
        f"{s['periodo_inventario']}."
    )

    if not st.session_state.get("guardado_en_disco", True):
        st.warning(
            "No se pudo guardar el resultado en el servidor: los datos se "
            "verán solo en esta sesión. Descarga el Excel para conservarlo."
        )

    m1, m2, m3, m4, m5 = st.columns(5)

    m1.metric(
        "Movimientos procesados",
        f"{s['movimientos_procesados']:,}".replace(",", "."),
    )
    m2.metric("Llaves nuevas", f"{s['llaves_nuevas']:,}".replace(",", "."))
    m3.metric("Anulados excluidos", f"{s['anulados']:,}".replace(",", "."))
    m4.metric(
        "Salidas sin existencia",
        f"{s['con_salida_sin_existencia']:,}".replace(",", "."),
    )
    m5.metric("Sin trazabilidad", "No aplica")

    st.caption(
        f"Período indicadores: {s['periodo_inventario']} · "
        f"Filas Kardex leídas: {s['filas_kardex']:,}".replace(",", ".")
    )

    for aviso in res["avisos"]:
        st.warning(aviso)

    with st.expander("Verificaciones del cálculo", expanded=True):
        for nombre, ok, detalle in res["verificaciones"]:
            (st.success if ok else st.error)(f"{nombre} ({detalle})")

    if len(res["sin_existencia"]):
        with st.expander(f"Salidas sin existencia ({len(res['sin_existencia'])})"):
            st.dataframe(
                res["sin_existencia"],
                use_container_width=True,
                hide_index=True,
            )

    nuevas = res["historico"][res["historico"]["OBSERVACION"] == MARCA_NUEVO]

    if len(nuevas):
        with st.expander(f"Artículos nuevos desde el Kardex ({len(nuevas)})"):
            cols = [
                c
                for c in ["Bodega", "Codigo Articulo", "Articulo", "LLAVE"]
                if c in nuevas.columns
            ]
            st.dataframe(nuevas[cols], use_container_width=True, hide_index=True)

    st.download_button(
        "Descargar Excel actualizado (con hojas de control)",
        data=st.session_state["excel_actualizado"],
        file_name="INVENTARIO_ACTUALIZADO_LIFO.xlsx",
        mime=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        ),
    )
