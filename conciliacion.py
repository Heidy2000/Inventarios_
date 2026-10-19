"""
conciliacion.py
Conciliación del stock calculado contra el inventario final real de
cada mes, por bodega y referencia.

Reglas:
  * Se comparan unidades y valor total de cada bodega + referencia.
  * Diferencia = calculado (Kardex) - real. Ajuste = real - calculado.
  * Comparar no modifica nada. Solo al APROBAR los ajustes (admin) el
    inventario real del cierre se guarda como AJUSTE CONCILIACION,
    separado de los movimientos del Kardex (ver gestion_kardex.py).
  * Un cero reportado es un dato; una celda vacía es "sin dato real".
  * Llaves duplicadas, cantidades no numéricas o filas sin código o
    bodega quedan "Pendiente de validación" (no se comparan).
  * Las bodegas excluidas del cálculo (11, 12, 18, 19, 20, 21) se
    retiran del archivo real y se informa cuántas filas eran.
"""
import io
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

import acceso
import motor_lifo as m
import ui

ESTADO_CONCILIADO = "Conciliado"
ESTADO_AJUSTADO = "Conciliado con ajuste"
ESTADO_DIFERENCIA = "Con diferencia"
ESTADO_SIN_REAL = "Sin dato real"
ESTADO_SIN_CALCULO = "Sin cálculo"
ESTADO_PENDIENTE = "Pendiente de validación"
ESTADO_CONSERVA_KARDEX = "Cierre en 0: se conserva el Kardex"

ORDEN_ESTADOS = [
    ESTADO_DIFERENCIA,
    ESTADO_PENDIENTE,
    ESTADO_SIN_CALCULO,
    ESTADO_CONSERVA_KARDEX,
    ESTADO_SIN_REAL,
    ESTADO_AJUSTADO,
    ESTADO_CONCILIADO,
]

COLUMNAS_RESULTADO = [
    "Periodo",
    "Codigo Articulo",
    "Articulo",
    "Bodega",
    "Stock inicial calculado",
    "Entradas del mes",
    "Salidas del mes",
    "Stock final calculado",
    "Stock final real reportado",
    "Diferencia",
    "Valor inicial calculado",
    "Costo entradas del mes",
    "Costo salidas del mes",
    "Valor final calculado",
    "Valor final real reportado",
    "Diferencia valor",
    "Ajuste unidades propuesto",
    "Ajuste valor propuesto",
    "Tipo de ajuste",
    "Ajuste vigente unidades",
    "Ajuste vigente valor",
    "Stock final ajustado",
    "Valor final ajustado",
    "En archivo real",
    "Estado",
    "Observación",
    "LLAVE",
]

COLUMNAS_NUMERICAS = [
    "Stock inicial calculado", "Entradas del mes", "Salidas del mes",
    "Stock final calculado", "Stock final real reportado", "Diferencia",
    "Valor inicial calculado", "Costo entradas del mes", "Costo salidas del mes",
    "Valor final calculado", "Valor final real reportado", "Diferencia valor",
    "Ajuste unidades propuesto", "Ajuste valor propuesto",
    "Ajuste vigente unidades", "Ajuste vigente valor",
    "Stock final ajustado", "Valor final ajustado",
]

CANDIDATOS = {
    "bodega": ["Bodega", "Nombre Bodega", "Almacen", "Almacén"],
    "codigo": [
        "Codigo Articulo", "Código Artículo", "Cod Articulo", "Codigo",
        "Código", "Referencia", "Id Articulo", "Item",
    ],
    "descripcion": ["Articulo", "Artículo", "Descripcion", "Descripción", "Nombre Articulo"],
    "cantidad": [
        "Stock Final", "Inventario Final", "Existencia", "Existencias",
        "Saldo Final", "Saldo", "Stock", "Cantidad Fisica", "Conteo",
        "Cantidad Disponible", "Disponible", "Cantidad",
    ],
    "valor": [
        "Valor Total", "Costo Total", "Coste Total", "Valor Inventario",
        "Costo Total Con Iva", "Valor Final", "Costo Final", "Valor",
        "Costo", "Coste",
    ],
}

PALABRAS_VALOR = ("COSTO", "COSTE", "VALOR", "PRECIO")


# ============================================================
# LECTURA DEL ARCHIVO REAL
# ============================================================

def leer_inventario_real(contenido, nombre_archivo=""):
    """Lee el Excel/CSV del inventario real y detecta la fila de encabezados."""
    if str(nombre_archivo).lower().endswith(".csv"):
        for codificacion in ("utf-8-sig", "latin-1"):
            try:
                df = pd.read_csv(
                    io.BytesIO(contenido), sep=None, engine="python",
                    encoding=codificacion, dtype=object,
                )
                break
            except UnicodeDecodeError:
                continue
        hoja = "CSV"
    else:
        xl = pd.ExcelFile(io.BytesIO(contenido))
        df, hoja = None, None
        for h in xl.sheet_names:
            fila = m.detectar_fila_encabezado(
                io.BytesIO(contenido), h, ["Bodega", "Cod", "Referencia"], minimo=2,
            )
            if fila is not None:
                df = pd.read_excel(io.BytesIO(contenido), sheet_name=h, header=fila, dtype=object)
                df["_FILA_ORIGEN"] = np.arange(len(df)) + fila + 2
                hoja = h
                break
        if df is None:
            raise ValueError(
                "No se encontró una hoja con columnas de bodega y código de "
                "artículo en las primeras 40 filas."
            )

    df.columns = [str(c).strip() for c in df.columns]
    if "_FILA_ORIGEN" not in df.columns:
        df["_FILA_ORIGEN"] = np.arange(len(df)) + 2

    datos = [c for c in df.columns if c != "_FILA_ORIGEN"]
    df = df.dropna(axis=0, how="all", subset=datos).reset_index(drop=True)

    if df.empty:
        raise ValueError("El archivo del inventario real no tiene registros.")

    return df, hoja


def detectar_columnas(df):
    """Mejor candidata para cada rol (puede ser None)."""
    columnas = [c for c in df.columns if c != "_FILA_ORIGEN"]
    resultado = {}
    usadas = set()

    for rol in ("codigo", "bodega", "descripcion", "cantidad", "valor"):
        elegida = None
        for cand in CANDIDATOS[rol]:
            for c in columnas:
                if c not in usadas and m.norm(c) == m.norm(cand):
                    elegida = c
                    break
            if elegida:
                break
        if elegida is None:
            for cand in CANDIDATOS[rol]:
                for c in columnas:
                    n = m.norm(c)
                    if c in usadas:
                        continue
                    es_valor = any(x in n for x in PALABRAS_VALOR)
                    # Cantidad: nunca una columna de valor.
                    # Valor: nunca un costo unitario o una columna de cantidad.
                    if rol != "valor" and es_valor:
                        continue
                    if rol == "valor" and (not es_valor or "UNIT" in n):
                        continue
                    if m.norm(cand) in n:
                        elegida = c
                        break
                if elegida:
                    break
        resultado[rol] = elegida
        if elegida:
            usadas.add(elegida)

    return resultado


# ============================================================
# STOCK Y VALOR CALCULADOS DEL PERIODO
# ============================================================

def stock_calculado(df_calc, anio, mes):
    """
    Por LLAVE y para el periodo, separando lo que viene del Kardex de los
    ajustes de conciliación vigentes:

      stock inicial + entradas Kardex + salidas Kardex = stock final calculado
      valor inicial + costo entradas Kardex + costo salidas Kardex
          (+ ajuste de costo residual)              = valor final calculado
      calculado + ajuste vigente                    = final ajustado
    """
    nombre = m.nombre_periodo(anio, mes)
    c_stock = m.col_exacta(df_calc, f"STOCK {nombre}")
    if c_stock is None:
        raise ValueError(f"El periodo {nombre.title()} no está calculado en la aplicación.")

    def col(texto):
        return m.col_exacta(df_calc, f"{texto} {nombre}")

    c_val = m.col_coste_mes(df_calc, NOMBRE_MES(mes), anio)

    anio_p, mes_p = m.periodo_de_num(m.periodo_num(anio, mes) - 1)
    c_prev = m.col_exacta(df_calc, f"STOCK {m.nombre_periodo(anio_p, mes_p)}") or m.col_exacta(df_calc, "STOCK INICIAL")
    c_val_prev = m.col_coste_mes(df_calc, NOMBRE_MES(mes_p), anio_p) or m.col_exacta(df_calc, "COSTE INICIAL")

    c_bod = m.col_buscar(df_calc, ["Bodega"])
    c_cod = m.col_buscar(df_calc, ["Codigo Articulo"])
    c_art = m.col_exacta(df_calc, "Articulo")

    def num(c):
        return m.a_numero(df_calc[c]) if c else pd.Series(0.0, index=df_calc.index)

    aj_e = num(col("AJUSTE CONCILIACION ENTRADA"))
    aj_s = num(col("AJUSTE CONCILIACION SALIDA"))
    aj_ce = num(col("AJUSTE CONCILIACION COSTO ENTRADA"))
    aj_cs = num(col("AJUSTE CONCILIACION COSTO SALIDA"))
    aj_u = aj_e + aj_s
    aj_v = aj_ce + aj_cs

    stock_aj = num(c_stock)
    valor_aj = num(c_val)

    base = pd.DataFrame({
        "LLAVE": (
            df_calc["LLAVE"].astype(str) if "LLAVE" in df_calc.columns
            else [m.crear_llave(b, c) for b, c in zip(df_calc[c_bod], df_calc[c_cod])]
        ),
        "Bodega": df_calc[c_bod].apply(m.bodega_txt),
        "Codigo Articulo": df_calc[c_cod].apply(m.codigo),
        "Articulo": df_calc[c_art].apply(m.texto) if c_art else "",
        "Stock inicial calculado": num(c_prev),
        "Entradas del mes": num(col("ENTRADA")) - aj_e,
        "Salidas del mes": num(col("SALIDA")) - aj_s,
        "Stock final calculado": stock_aj - aj_u,
        "Valor inicial calculado": num(c_val_prev),
        "Costo entradas del mes": num(col("COSTO ENTRADA")) - aj_ce,
        "Costo salidas del mes": num(col("COSTO SALIDA")) - aj_cs,
        "Valor final calculado": valor_aj - aj_v,
        "Ajuste vigente unidades": aj_u,
        "Ajuste vigente valor": aj_v,
        "Stock final ajustado": stock_aj,
        "Valor final ajustado": valor_aj,
    })

    sumas = [c for c in base.columns if c not in ("LLAVE", "Bodega", "Codigo Articulo", "Articulo")]
    agregado = base.groupby("LLAVE", as_index=False).agg(
        {"Bodega": "first", "Codigo Articulo": "first", "Articulo": "first", **{c: "sum" for c in sumas}}
    )
    return agregado


def NOMBRE_MES(mes):
    return m.NOMBRES_MES[int(mes) - 1]


# ============================================================
# CONCILIACIÓN
# ============================================================

def conciliar(
    df_calc,
    df_real,
    periodo,
    col_bodega,
    col_codigo,
    col_cantidad,
    col_descripcion=None,
    tolerancia=0.0,
    incluir_ceros_ausentes=False,
    col_valor=None,
    tolerancia_valor=1.0,
):
    """
    Compara, por bodega + referencia, las unidades y el valor que deja el
    Kardex al cierre del periodo con el inventario real.

    periodo: 'AAAA-MM'. Devuelve (tabla, resumen).

    Diferencia = calculado (Kardex) − real.
    Ajuste propuesto = real − calculado (lo que hay que sumar o restar
    para que el inventario reconstruido quede igual al real).
    """
    anio, mes = m.periodo_de_etiqueta(periodo)
    etiqueta = m.nombre_periodo(anio, mes).title()
    calc = stock_calculado(df_calc, anio, mes)

    for col, rol in ((col_bodega, "bodega"), (col_codigo, "código"), (col_cantidad, "cantidad")):
        if not col or col not in df_real.columns:
            raise ValueError(f"Selecciona la columna de {rol} del archivo real.")
    if col_valor and col_valor not in df_real.columns:
        raise ValueError("La columna de valor seleccionada no existe en el archivo real.")

    # ---------------- archivo real ----------------
    r = pd.DataFrame({
        "_fila": df_real["_FILA_ORIGEN"] if "_FILA_ORIGEN" in df_real.columns else np.arange(len(df_real)) + 2,
        "Bodega real": df_real[col_bodega].apply(m.bodega_txt),
        "Codigo real": df_real[col_codigo].apply(m.codigo),
        "Desc real": df_real[col_descripcion].apply(m.texto) if col_descripcion else "",
    })

    cantidad, invalida = m.a_numero_validado(df_real[col_cantidad])
    vacia = df_real[col_cantidad].apply(lambda v: m.texto(v) == "")
    r["Cantidad"] = cantidad.where(~vacia.values & ~invalida.values, np.nan)
    r["_invalida"] = invalida.values
    r["_vacia"] = vacia.values

    if col_valor:
        valor, valor_inv = m.a_numero_validado(df_real[col_valor])
        valor_vacio = df_real[col_valor].apply(lambda v: m.texto(v) == "")
        r["Valor"] = valor.where(~valor_vacio.values & ~valor_inv.values, np.nan)
        r["_valor_invalido"] = valor_inv.values
    else:
        r["Valor"] = np.nan
        r["_valor_invalido"] = False

    r["_num_bodega"] = r["Bodega real"].apply(m.numero_bodega)
    excluidas = r["_num_bodega"].isin(m.BODEGAS_EXCLUIDAS) & (r["Bodega real"] != "")
    filas_excluidas = int(excluidas.sum())
    r = r[~excluidas].copy()

    motivo = pd.Series("", index=r.index, dtype=object)

    def agregar(mascara, texto):
        nonlocal motivo
        motivo = pd.Series(
            np.where(mascara, np.where(motivo == "", texto, motivo + "; " + texto), motivo),
            index=r.index, dtype=object,
        )

    agregar(r["Bodega real"] == "", "Sin bodega")
    agregar(r["Codigo real"] == "", "Sin código de artículo")
    agregar(r["_invalida"], "Cantidad no numérica")
    agregar(r["_valor_invalido"], "Valor no numérico")

    llave_valida = (r["Bodega real"] != "") & (r["Codigo real"] != "")
    r["LLAVE"] = np.where(llave_valida, r["_num_bodega"] + "_" + r["Codigo real"], "")

    duplicada = llave_valida & r["LLAVE"].duplicated(keep=False)
    agregar(duplicada, "Llave (bodega + código) repetida en el archivo real")
    r["_motivo"] = motivo

    # Filas sin llave: no se pueden cruzar, se listan como pendientes.
    sin_llave = r[~llave_valida]

    con_llave = r[llave_valida].copy()
    reales = []
    for llave, g in con_llave.groupby("LLAVE", sort=False):
        motivos = sorted({x for x in g["_motivo"] if x})
        cantidades = g["Cantidad"].tolist()
        if len(g) > 1:
            detalle = "; ".join(
                "vacía" if pd.isna(c) else ui.formato_numero(c) for c in cantidades
            )
            motivos.append(f"{len(g)} filas (filas {', '.join(str(int(x)) for x in g['_fila'])}): {detalle}")
        reales.append({
            "LLAVE": llave,
            "Bodega real": g["Bodega real"].iloc[0],
            "Codigo real": g["Codigo real"].iloc[0],
            "Desc real": g["Desc real"].iloc[0],
            "Cantidad": cantidades[0] if len(g) == 1 else np.nan,
            "Valor": g["Valor"].iloc[0] if len(g) == 1 else np.nan,
            "_motivo": "; ".join(motivos),
            "_fila": int(g["_fila"].iloc[0]),
        })
    reales = pd.DataFrame(
        reales,
        columns=["LLAVE", "Bodega real", "Codigo real", "Desc real", "Cantidad", "Valor", "_motivo", "_fila"],
    )

    # ---------------- cruce ----------------
    t = calc.merge(reales, on="LLAVE", how="outer", indicator=True)
    for c in ("Stock final calculado", "Valor final calculado", "Ajuste vigente unidades",
              "Ajuste vigente valor", "Stock final ajustado", "Valor final ajustado"):
        t[c] = t[c].astype(float)

    estado, observ, prop_u, prop_v = [], [], [], []
    tol_u = float(tolerancia) + 1e-9
    tol_v = float(tolerancia_valor) + 1e-9

    for row in t.to_dict("records"):
        origen = row["_merge"]
        motivo_r = row["_motivo"] if isinstance(row["_motivo"], str) else ""
        real_u = row["Cantidad"]
        real_v = row["Valor"]
        con_valor = bool(col_valor) and not pd.isna(real_v)

        if origen == "left_only":
            estado.append(ESTADO_SIN_REAL)
            observ.append("No aparece en el archivo real")
            prop_u.append(np.nan)
            prop_v.append(np.nan)
            continue

        if motivo_r:
            estado.append(ESTADO_PENDIENTE)
            observ.append(motivo_r)
            prop_u.append(np.nan)
            prop_v.append(np.nan)
            continue

        if pd.isna(real_u):
            estado.append(ESTADO_PENDIENTE if origen == "right_only" else ESTADO_SIN_REAL)
            observ.append(
                "Sin cálculo y sin cantidad real" if origen == "right_only"
                else "Cantidad real vacía en el archivo"
            )
            prop_u.append(np.nan)
            prop_v.append(np.nan)
            continue

        calc_u = 0.0 if origen == "right_only" else float(row["Stock final calculado"])
        calc_v = 0.0 if origen == "right_only" else float(row["Valor final calculado"])
        vig_u = 0.0 if origen == "right_only" else float(row["Ajuste vigente unidades"])
        vig_v = 0.0 if origen == "right_only" else float(row["Ajuste vigente valor"])
        aj_u_final = calc_u + vig_u
        aj_v_final = calc_v + vig_v

        dif_u = calc_u - real_u
        dif_v = (calc_v - real_v) if con_valor else 0.0
        necesita_u = abs(dif_u) > tol_u
        necesita_v = con_valor and abs(dif_v) > tol_v

        # Ajuste propuesto = real - calculado, solo cuando hace falta.
        # Sin valor real, el valor del ajuste lo calcula el motor con el
        # costo unitario (queda vacío aquí).
        if necesita_u or necesita_v:
            prop_u.append(real_u - calc_u)
            prop_v.append(real_v - calc_v if con_valor else np.nan)
        else:
            prop_u.append(0.0)
            prop_v.append(0.0)

        partes = []
        if necesita_u:
            partes.append(
                f"{'Sobrante' if dif_u > 0 else 'Faltante'} en el cálculo: "
                f"{ui.formato_numero(abs(dif_u))} und."
            )
        if necesita_v:
            partes.append(
                f"Valor {'mayor' if dif_v > 0 else 'menor'} en el cálculo: "
                f"{ui.formato_moneda(abs(dif_v))}"
            )
        if bool(col_valor) and not con_valor:
            partes.append("Sin valor real: el ajuste de valor usará el costo unitario calculado")

        if origen == "right_only":
            estado.append(ESTADO_SIN_CALCULO)
            observ.append("La referencia no existe en el cálculo de esta bodega; el ajuste la crea")
            continue

        # Regla: cierre en 0 y Kardex con existencias positivas -> se
        # conserva el saldo del Kardex, sin ajuste.
        if abs(real_u) <= 1e-9 and calc_u > 1e-9:
            estado.append(ESTADO_CONSERVA_KARDEX)
            observ.append(
                f"El inventario de cierre reporta 0 y el Kardex {ui.formato_numero(calc_u)} und.: "
                "se conserva el saldo del Kardex (no se ajusta)"
            )
            prop_u[-1] = 0.0
            prop_v[-1] = 0.0
            continue

        vigente = abs(vig_u) > tol_u or abs(vig_v) > tol_v
        final_ok = abs(aj_u_final - real_u) <= tol_u and (
            not con_valor or abs(aj_v_final - real_v) <= tol_v
        )

        if not necesita_u and not necesita_v and not vigente:
            estado.append(ESTADO_CONCILIADO)
        elif vigente and final_ok:
            estado.append(ESTADO_AJUSTADO)
            partes.insert(0, "Concilia con el ajuste vigente")
        else:
            estado.append(ESTADO_DIFERENCIA)
            if vigente and not necesita_u and not necesita_v:
                partes.append("El Kardex ya concilia; el ajuste vigente se retira al aplicar")
            elif vigente:
                partes.append("El ajuste vigente no corresponde a este inventario real")
        observ.append("; ".join(partes))

    t["Estado"] = estado
    t["Observación"] = observ
    t["Ajuste unidades propuesto"] = prop_u
    t["Ajuste valor propuesto"] = prop_v
    t["Tipo de ajuste"] = [
        "" if pd.isna(u) or (abs(u) <= 1e-9 and (pd.isna(v) or abs(v) <= 1e-9))
        else "Entrada de conciliación" if u > 1e-9
        else "Salida de conciliación" if u < -1e-9
        else "Ajuste de valor"
        for u, v in zip(prop_u, prop_v)
    ]

    t["Bodega"] = t["Bodega"].where(t["Bodega"].notna() & (t["Bodega"] != ""), t["Bodega real"])
    t["Codigo Articulo"] = t["Codigo Articulo"].where(t["Codigo Articulo"].notna(), t["Codigo real"])
    t["Articulo"] = t["Articulo"].where(
        t["Articulo"].notna() & (t["Articulo"].astype(str) != ""), t["Desc real"]
    )
    t["Stock final real reportado"] = t["Cantidad"]
    t["Valor final real reportado"] = t["Valor"]
    comparables = t["Estado"].isin([ESTADO_CONCILIADO, ESTADO_DIFERENCIA, ESTADO_AJUSTADO, ESTADO_CONSERVA_KARDEX])
    t["Diferencia"] = np.where(comparables, t["Stock final calculado"] - t["Cantidad"], np.nan)
    t["Diferencia valor"] = np.where(
        comparables & t["Valor"].notna(), t["Valor final calculado"] - t["Valor"], np.nan
    )
    t["En archivo real"] = np.where(t["_merge"] == "left_only", "No", "Sí")
    t["Periodo"] = etiqueta

    # Referencias con stock calculado 0 que no figuran en el archivo
    # real: normalmente no son novedad (el real lista solo existencias).
    ceros_ausentes = (
        (t["_merge"] == "left_only")
        & (t["Stock final calculado"].abs() <= m.EPS)
        & (t["Ajuste vigente unidades"].abs() <= m.EPS)
    )
    n_ceros_ausentes = int(ceros_ausentes.sum())
    if not incluir_ceros_ausentes:
        t = t[~ceros_ausentes]

    pendientes_sin_llave = pd.DataFrame({
        "Periodo": etiqueta,
        "Codigo Articulo": sin_llave["Codigo real"],
        "Articulo": sin_llave["Desc real"],
        "Bodega": sin_llave["Bodega real"],
        "Stock final real reportado": sin_llave["Cantidad"],
        "Valor final real reportado": sin_llave["Valor"],
        "En archivo real": "Sí",
        "Estado": ESTADO_PENDIENTE,
        "Observación": [
            f"Fila {int(f)}: {mo}" for f, mo in zip(sin_llave["_fila"], sin_llave["_motivo"])
        ],
        "LLAVE": "",
    })

    tabla = pd.concat([t, pendientes_sin_llave], ignore_index=True)
    for c in COLUMNAS_RESULTADO:
        if c not in tabla.columns:
            tabla[c] = np.nan
    tabla = tabla[COLUMNAS_RESULTADO]

    tabla["_orden"] = tabla["Estado"].map({e: i for i, e in enumerate(ORDEN_ESTADOS)})
    tabla["_absdif"] = tabla["Diferencia"].abs().fillna(-1)
    tabla = (
        tabla.sort_values(["_orden", "_absdif"], ascending=[True, False])
        .drop(columns=["_orden", "_absdif"])
        .reset_index(drop=True)
    )

    conteo = tabla["Estado"].value_counts().to_dict()
    pu = tabla["Ajuste unidades propuesto"].fillna(0)
    pv = tabla["Ajuste valor propuesto"].fillna(0)
    resumen = {
        "periodo": periodo,
        "registros": int(len(tabla)),
        "por_estado": {e: int(conteo.get(e, 0)) for e in ORDEN_ESTADOS},
        "diferencia_neta": float(tabla["Diferencia"].sum(skipna=True)),
        "diferencia_absoluta": float(tabla["Diferencia"].abs().sum(skipna=True)),
        "diferencia_valor_neta": float(tabla["Diferencia valor"].sum(skipna=True)),
        "diferencia_valor_absoluta": float(tabla["Diferencia valor"].abs().sum(skipna=True)),
        "ajuste_unidades_positivo": float(pu[pu > 0].sum()),
        "ajuste_unidades_negativo": float(pu[pu < 0].sum()),
        "ajuste_valor_positivo": float(pv[pv > 0].sum()),
        "ajuste_valor_negativo": float(pv[pv < 0].sum()),
        "compara_valor": bool(col_valor),
        "filas_archivo_real": int(len(df_real)),
        "filas_bodegas_excluidas": filas_excluidas,
        "ceros_ausentes_omitidos": 0 if incluir_ceros_ausentes else n_ceros_ausentes,
        "tolerancia": float(tolerancia),
        "tolerancia_valor": float(tolerancia_valor),
    }
    return tabla, resumen


# ============================================================
# AJUSTES PROPUESTOS
# ============================================================

def ajustes_propuestos(tabla):
    """
    Inventario de cierre a fijar en cada LLAVE que lo necesita (el motor
    lo aplica al cierre del periodo como entrada o salida de conciliación):

      * Con diferencia / Conciliado con ajuste / Sin cálculo con cantidad
        real válida -> stock y valor del inventario de cierre.

    No se ajustan: pendientes de validación, cantidades vacías,
    referencias ausentes del archivo de cierre y cierres en 0 con
    existencias positivas en el Kardex (se conserva el Kardex).
    """
    validos = tabla[
        tabla["Estado"].isin([ESTADO_DIFERENCIA, ESTADO_AJUSTADO, ESTADO_SIN_CALCULO])
        & tabla["Stock final real reportado"].notna()
        & (tabla["LLAVE"].astype(str) != "")
    ]
    requiere = (
        validos["Ajuste unidades propuesto"].fillna(0).abs() > 1e-9
    ) | (
        validos["Ajuste valor propuesto"].fillna(0).abs() > 1e-9
    )
    validos = validos[requiere]

    return pd.DataFrame({
        "Bodega": validos["Bodega"],
        "Codigo Articulo": validos["Codigo Articulo"],
        "Articulo": validos["Articulo"],
        "Tipo de ajuste": validos["Tipo de ajuste"],
        "Stock real": validos["Stock final real reportado"],
        "Valor real": validos["Valor final real reportado"],
        "Ajuste unidades aprobado": validos["Ajuste unidades propuesto"],
        "Ajuste valor aprobado": validos["Ajuste valor propuesto"],
    }).reset_index(drop=True)


def ajustes_que_se_retiran(tabla, propuesta):
    """Llaves con ajuste vigente que el nuevo inventario real ya no respalda."""
    llaves_prop = {
        m.crear_llave(b, c) for b, c in zip(propuesta["Bodega"], propuesta["Codigo Articulo"])
    }
    vig = tabla[
        (tabla["Ajuste vigente unidades"].fillna(0).abs() > 1e-9)
        | (tabla["Ajuste vigente valor"].fillna(0).abs() > 0.5)
    ]
    return vig[~vig["LLAVE"].isin(llaves_prop)]


def resumen_por_bodega(tabla):
    if tabla.empty:
        return pd.DataFrame()
    dif_valor = tabla["Diferencia valor"] if "Diferencia valor" in tabla.columns else pd.Series(np.nan, index=tabla.index)
    g = tabla.assign(
        _con_dif=tabla["Estado"].eq(ESTADO_DIFERENCIA),
        _conc=tabla["Estado"].isin([ESTADO_CONCILIADO, ESTADO_AJUSTADO]),
        _absdif=tabla["Diferencia"].abs(),
        _difv=dif_valor,
        _absdifv=dif_valor.abs(),
    ).groupby("Bodega", dropna=False).agg(
        Registros=("Estado", "size"),
        Conciliados=("_conc", "sum"),
        Con_diferencia=("_con_dif", "sum"),
        Diferencia_neta=("Diferencia", "sum"),
        Diferencia_absoluta=("_absdif", "sum"),
        Diferencia_valor_neta=("_difv", "sum"),
        Diferencia_valor_absoluta=("_absdifv", "sum"),
    ).reset_index()
    g["% conciliado"] = np.where(g["Registros"] > 0, g["Conciliados"] / g["Registros"] * 100, 0)
    return g.rename(columns={
        "Con_diferencia": "Con diferencia",
        "Diferencia_neta": "Diferencia neta (und.)",
        "Diferencia_absoluta": "Diferencia absoluta (und.)",
        "Diferencia_valor_neta": "Diferencia neta (valor)",
        "Diferencia_valor_absoluta": "Diferencia absoluta (valor)",
    }).sort_values("Diferencia absoluta (und.)", ascending=False)


def a_excel(tabla, resumen, propuesta=None):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        tabla.to_excel(w, sheet_name="Conciliacion", index=False)
        resumen_por_bodega(tabla).to_excel(w, sheet_name="Resumen por bodega", index=False)
        if propuesta is not None and len(propuesta):
            propuesta.to_excel(w, sheet_name="Ajustes propuestos", index=False)
        filas = [{"Concepto": "Periodo", "Valor": resumen["periodo"]}]
        filas += [{"Concepto": e, "Valor": n} for e, n in resumen["por_estado"].items()]
        filas += [
            {"Concepto": "Diferencia neta en unidades (calculado - real)", "Valor": resumen["diferencia_neta"]},
            {"Concepto": "Diferencia absoluta en unidades", "Valor": resumen["diferencia_absoluta"]},
            {"Concepto": "Diferencia neta en valor (calculado - real)", "Valor": resumen.get("diferencia_valor_neta", 0)},
            {"Concepto": "Ajuste propuesto: unidades a sumar", "Valor": resumen.get("ajuste_unidades_positivo", 0)},
            {"Concepto": "Ajuste propuesto: unidades a restar", "Valor": resumen.get("ajuste_unidades_negativo", 0)},
            {"Concepto": "Ajuste propuesto: valor a sumar", "Valor": resumen.get("ajuste_valor_positivo", 0)},
            {"Concepto": "Ajuste propuesto: valor a restar", "Valor": resumen.get("ajuste_valor_negativo", 0)},
            {"Concepto": "Filas del archivo real", "Valor": resumen["filas_archivo_real"]},
            {"Concepto": "Filas de bodegas excluidas", "Valor": resumen["filas_bodegas_excluidas"]},
            {"Concepto": "Referencias con stock 0 ausentes (omitidas)", "Valor": resumen["ceros_ausentes_omitidos"]},
            {"Concepto": "Tolerancia (unidades)", "Valor": resumen["tolerancia"]},
            {"Concepto": "Tolerancia (valor)", "Valor": resumen.get("tolerancia_valor", 0)},
        ]
        pd.DataFrame(filas).to_excel(w, sheet_name="Resumen", index=False)
        for hoja in w.sheets.values():
            hoja.freeze_panes = "A2"
            for col in hoja.columns:
                largo = max(len("" if c.value is None else str(c.value)) for c in col)
                hoja.column_dimensions[col[0].column_letter].width = min(max(largo + 2, 10), 45)
    return buf.getvalue()


# ============================================================
# HISTORIAL DE CONCILIACIONES
# ============================================================

class HistorialConciliaciones:
    def __init__(self, base_dir):
        self.dir = os.path.join(base_dir, "datos", "conciliaciones")
        self.ruta_registro = os.path.join(self.dir, "registro_conciliaciones.json")

    def registro(self):
        if not os.path.exists(self.ruta_registro):
            return []
        with open(self.ruta_registro, "r", encoding="utf-8") as f:
            return json.load(f)

    def guardar(self, tabla, resumen, archivo, usuario):
        from gestion_kardex import escribir_atomico

        os.makedirs(self.dir, exist_ok=True)
        marca = datetime.now().strftime("%Y%m%d_%H%M%S")
        ident = f"{resumen['periodo']}__{marca}"
        ruta = os.path.join(self.dir, f"{ident}.csv.gz")
        buf = io.BytesIO()
        tabla.to_csv(buf, index=False, compression={"method": "gzip", "mtime": 0})
        escribir_atomico(ruta, buf.getvalue())

        registro = self.registro()
        registro.append({
            "id": ident,
            "periodo": resumen["periodo"],
            "archivo": archivo,
            "usuario": usuario,
            "fecha": datetime.now().isoformat(timespec="seconds"),
            "resumen": resumen,
        })
        escribir_atomico(
            self.ruta_registro,
            json.dumps(registro, ensure_ascii=False, indent=1).encode("utf-8"),
        )
        return ident

    def leer(self, ident):
        return pd.read_csv(
            os.path.join(self.dir, f"{ident}.csv.gz"),
            dtype={"Codigo Articulo": str, "Bodega": str, "LLAVE": str},
            keep_default_na=True,
        )


# ============================================================
# PÁGINA
# ============================================================

def _colores_estado(valor):
    colores = {
        ESTADO_CONCILIADO: f"background-color: {ui.VERDE_SUAVE}; color: {ui.VERDE}",
        ESTADO_AJUSTADO: f"background-color: {ui.VERDE_SUAVE}; color: {ui.AZUL}",
        ESTADO_DIFERENCIA: f"background-color: {ui.ROJO_SUAVE}; color: {ui.ROJO}",
        ESTADO_PENDIENTE: f"background-color: {ui.NARANJA_SUAVE}; color: {ui.NARANJA_OSCURO}",
        ESTADO_SIN_CALCULO: f"background-color: {ui.AZUL_SUAVE}; color: {ui.AZUL}",
        ESTADO_SIN_REAL: "background-color: #F1F3F6; color: #5F7189",
        ESTADO_CONSERVA_KARDEX: "background-color: #F1F3F6; color: #5F7189",
    }
    return colores.get(valor, "")


FORMATO_UNIDADES = [
    "Stock inicial calculado", "Entradas del mes", "Salidas del mes",
    "Stock final calculado", "Stock final real reportado", "Diferencia",
    "Ajuste unidades propuesto", "Ajuste vigente unidades", "Stock final ajustado",
]
FORMATO_VALOR = [
    "Valor final calculado", "Valor final real reportado", "Diferencia valor",
    "Ajuste valor propuesto", "Ajuste vigente valor", "Valor final ajustado",
]


def _config_columnas(st, columnas):
    conf = {c: st.column_config.NumberColumn(c, format="%.2f") for c in FORMATO_UNIDADES if c in columnas}
    conf.update({c: st.column_config.NumberColumn(c, format="$ %,.0f") for c in FORMATO_VALOR if c in columnas})
    return conf


def _mostrar_tabla(st, tabla, resumen, clave):
    pe = resumen["por_estado"]
    total = max(resumen["registros"], 1)
    conciliados = pe.get(ESTADO_CONCILIADO, 0) + pe.get(ESTADO_AJUSTADO, 0)

    ui.fila_kpis(st, [
        ("Conciliados", ui.formato_entero(conciliados),
         f"{conciliados / total * 100:.1f}% · {pe.get(ESTADO_AJUSTADO, 0)} con ajuste", "verde"),
        ("Con diferencia", ui.formato_entero(pe.get(ESTADO_DIFERENCIA, 0)),
         f"{ui.formato_numero(resumen['diferencia_absoluta'])} und. · "
         f"{ui.formato_moneda(resumen.get('diferencia_valor_absoluta', 0))}", "rojo"),
        ("Pendientes de validación", ui.formato_entero(pe.get(ESTADO_PENDIENTE, 0)),
         "duplicados o datos inválidos", "naranja"),
        ("Sin cálculo", ui.formato_entero(pe.get(ESTADO_SIN_CALCULO, 0)), "solo en el archivo real", "azul"),
        ("Sin dato real", ui.formato_entero(pe.get(ESTADO_SIN_REAL, 0) + pe.get(ESTADO_CONSERVA_KARDEX, 0)),
         f"{pe.get(ESTADO_CONSERVA_KARDEX, 0)} con cierre en 0 (se conserva el Kardex)", "gris"),
    ])

    notas = []
    if not resumen.get("compara_valor", False):
        notas.append("No se seleccionó columna de valor: solo se compararon unidades.")
    if resumen["filas_bodegas_excluidas"]:
        notas.append(f"{resumen['filas_bodegas_excluidas']} filas del archivo real son de bodegas excluidas del cálculo y no se comparan.")
    if resumen["ceros_ausentes_omitidos"]:
        notas.append(
            f"{resumen['ceros_ausentes_omitidos']} referencias con stock calculado 0 no aparecen en el archivo real; "
            "no se muestran (actívalas con la opción 'Incluir referencias con stock calculado 0')."
        )
    for n in notas:
        st.caption(n)

    c1, c2, c3 = st.columns([1.4, 1.2, 1.2])
    with c1:
        estados = st.multiselect(
            "Estado", ORDEN_ESTADOS,
            default=[e for e in ORDEN_ESTADOS if e not in (ESTADO_CONCILIADO, ESTADO_AJUSTADO) and pe.get(e)] or ORDEN_ESTADOS,
            key=f"{clave}_estados",
        )
    with c2:
        bodegas = sorted(tabla["Bodega"].dropna().astype(str).unique().tolist())
        bodega = st.selectbox("Bodega", ["Todas"] + bodegas, key=f"{clave}_bodega")
    with c3:
        buscar = st.text_input("Buscar código o artículo", key=f"{clave}_buscar")

    vista = tabla[tabla["Estado"].isin(estados)]
    if bodega != "Todas":
        vista = vista[vista["Bodega"].astype(str) == bodega]
    if buscar.strip():
        b = buscar.strip().upper()
        vista = vista[
            vista["Codigo Articulo"].astype(str).str.upper().str.contains(b, regex=False)
            | vista["Articulo"].astype(str).str.upper().str.contains(b, regex=False)
        ]

    st.caption(f"{ui.formato_entero(len(vista))} de {ui.formato_entero(len(tabla))} registros")

    try:
        datos = vista.style.map(_colores_estado, subset=["Estado"])
    except Exception:
        datos = vista
    st.dataframe(
        datos, use_container_width=True, hide_index=True, height=460,
        column_config=_config_columnas(st, vista.columns),
    )

    with st.expander("Resumen por bodega"):
        st.dataframe(
            resumen_por_bodega(tabla), use_container_width=True, hide_index=True,
            column_config={"% conciliado": st.column_config.NumberColumn(format="%.1f%%")},
        )

    st.download_button(
        "Descargar conciliación (Excel)",
        data=a_excel(tabla, resumen, ajustes_propuestos(tabla) if "Ajuste unidades propuesto" in tabla.columns else None),
        file_name=f"Conciliacion_{resumen['periodo']}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{clave}_descarga",
    )


def _seccion_ajustes(st, tabla, resumen, ident, base_dir, archivo_historico,
                     archivo_actualizado, usuario, secretos):
    """Propuesta y aplicación de los ajustes de conciliación (solo admin)."""
    import gestion_kardex as g

    periodo = resumen["periodo"]
    texto_periodo = m.nombre_periodo(*m.periodo_de_etiqueta(periodo)).title()
    almacen = g.Almacen(base_dir)

    ui.seccion(
        st,
        "4. Ajustes de conciliación",
        "Llevan el inventario reconstruido con el Kardex al inventario real del "
        "cierre. Se guardan aparte como AJUSTE CONCILIACION: los movimientos "
        "originales y los signos de las salidas no cambian.",
    )

    if periodo not in almacen.periodos():
        st.info(
            f"{texto_periodo} no tiene Kardex cargado en el registro de cargues "
            "(por ejemplo, el mes base del histórico). Solo se pueden ajustar "
            "periodos cargados desde Actualizar Kardex."
        )
        return

    st.caption(
        "Faltante → entrada de conciliación (unidades y costo de entrada). "
        "Sobrante → salida de conciliación (unidades negativas y costo de salida). "
        "Sin valor de cierre, las unidades se valoran al costo promedio vigente. "
        "Cierres en 0 con existencias en el Kardex y referencias ausentes del "
        "archivo no se ajustan."
    )

    propuesta = ajustes_propuestos(tabla)
    retirados = ajustes_que_se_retiran(tabla, propuesta)

    pu = propuesta["Ajuste unidades aprobado"].fillna(0)
    pv = propuesta["Ajuste valor aprobado"].fillna(0)
    ui.fila_kpis(st, [
        ("Referencias a ajustar", ui.formato_entero(len(propuesta)),
         f"{len(retirados)} ajustes vigentes se retiran", "azul"),
        ("Unidades a sumar", ui.formato_numero(pu[pu > 0].sum()), "faltantes en el cálculo", "verde"),
        ("Unidades a restar", ui.formato_numero(pu[pu < 0].sum()), "sobrantes en el cálculo", "rojo"),
        ("Valor a sumar", ui.formato_moneda(pv[pv > 0].sum()), "", "verde"),
        ("Valor a restar", ui.formato_moneda(pv[pv < 0].sum()),
         "sin valor real: se calcula con el costo unitario" if propuesta["Ajuste valor aprobado"].isna().any() else "",
         "rojo"),
    ])

    if len(propuesta):
        st.dataframe(
            propuesta, use_container_width=True, hide_index=True, height=300,
            column_config={
                "Stock real": st.column_config.NumberColumn(format="%.2f"),
                "Ajuste unidades aprobado": st.column_config.NumberColumn("Ajuste unidades", format="%.2f"),
                "Valor real": st.column_config.NumberColumn(format="$ %,.0f"),
                "Ajuste valor aprobado": st.column_config.NumberColumn("Ajuste valor", format="$ %,.0f"),
            },
        )

    if len(retirados):
        with st.expander(f"Ajustes vigentes que se retiran ({len(retirados)})"):
            st.dataframe(
                retirados[["Bodega", "Codigo Articulo", "Articulo", "Ajuste vigente unidades",
                           "Ajuste vigente valor", "Estado", "Observación"]],
                use_container_width=True, hide_index=True,
            )

    if not len(propuesta) and not len(retirados):
        st.success("No hay ajustes por aplicar: el inventario reconstruido ya concilia.")
    else:
        confirmar = st.checkbox(
            f"Confirmo que quiero aplicar estos ajustes al cierre de {texto_periodo}. "
            "Reemplazan los ajustes de conciliación anteriores de este periodo.",
            key="conc_confirmar_ajustes",
        )
        if st.button("Aplicar ajustes al inventario", type="primary",
                     disabled=not confirmar, use_container_width=True,
                     key="conc_aplicar_ajustes"):
            exito = False
            try:
                base_df = g._leer_base(st, archivo_historico)
                with st.spinner("Aplicando ajustes y recalculando el inventario..."):
                    res, _ = g.aplicar_ajustes_conciliacion(
                        periodo, propuesta, base_df, almacen,
                        acceso.usuario_sesion(st) or usuario, archivo_actualizado,
                        archivo=st.session_state.get("conc_params", {}).get("archivo", ""),
                        id_conciliacion=ident or "", secretos=secretos,
                    )
                aplicados = res["ajustes_conciliacion"]
                aplicados = aplicados[aplicados["Periodo"] == periodo]
                st.session_state["conc_mensaje"] = (
                    f"Se aplicaron {len(aplicados)} ajustes al cierre de {texto_periodo}: "
                    f"{ui.formato_numero(aplicados['Ajuste unidades'].sum())} und. y "
                    f"{ui.formato_moneda(aplicados['Ajuste valor'].sum())} netos. "
                    "La conciliación se recalculó con el inventario actualizado."
                )
                st.session_state["conc_recalcular"] = True
                st.session_state["res_actualizacion"] = res
                st.session_state.pop("conc_confirmar_ajustes", None)
                try:
                    st.cache_data.clear()
                except Exception:
                    pass
                exito = True
            except acceso.AccesoDenegado as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"No fue posible aplicar los ajustes. No se modificó nada.\n\n{type(e).__name__}: {e}")
            if exito:
                st.rerun()

    if periodo in almacen.periodos_ajustados():
        with st.expander("Retirar los ajustes de conciliación de este periodo"):
            st.caption(
                "El inventario vuelve a quedar exactamente como lo reconstruye el Kardex. "
                "La acción queda registrada."
            )
            if st.button("Retirar ajustes del periodo", key="conc_retirar_ajustes"):
                exito = False
                try:
                    base_df = g._leer_base(st, archivo_historico)
                    with st.spinner("Retirando ajustes y recalculando..."):
                        res, _ = g.retirar_ajustes_conciliacion(
                            periodo, base_df, almacen,
                            acceso.usuario_sesion(st) or usuario, archivo_actualizado,
                            secretos=secretos,
                        )
                    st.session_state["conc_mensaje"] = f"Se retiraron los ajustes de {texto_periodo}."
                    st.session_state["conc_recalcular"] = True
                    st.session_state["res_actualizacion"] = res
                    try:
                        st.cache_data.clear()
                    except Exception:
                        pass
                    exito = True
                except Exception as e:
                    st.error(f"No fue posible retirar los ajustes. No se modificó nada.\n\n{e}")
                if exito:
                    st.rerun()


def pagina_conciliacion(st, df_calc, base_dir, archivo_historico=None, archivo_actualizado=None):
    secretos = acceso.secretos_de(st)
    usuario = acceso.usuario_sesion(st)

    archivo_historico = archivo_historico or os.path.join(base_dir, "HISTORICO_INVENTARIOS.xlsx")
    archivo_actualizado = archivo_actualizado or os.path.join(base_dir, "INVENTARIO_ACTUALIZADO_LIFO.xlsx")

    ui.encabezado_pagina(
        st,
        "Conciliación mensual",
        "Compara unidades y valor del inventario reconstruido con el Kardex contra "
        "el inventario real del cierre, por bodega y referencia, y ajusta las "
        "diferencias de forma trazable.",
        eyebrow="Control",
        pills=[("Diferencia = calculado − real", "primary"), ("Ajuste = real − calculado", "accent")],
    )

    if not acceso.es_admin(usuario, secretos):
        st.error("Tu usuario no tiene permiso para esta página.")
        return

    periodos = [m.etiqueta_periodo(a, mm) for a, mm in m.meses_con_stock(df_calc)]
    if not periodos:
        st.error("No hay periodos calculados para conciliar.")
        return

    historial = HistorialConciliaciones(base_dir)

    mensaje = st.session_state.pop("conc_mensaje", None)
    if mensaje:
        st.success(mensaje)

    # Tras aplicar o retirar ajustes se vuelve a conciliar con los datos nuevos.
    if st.session_state.pop("conc_recalcular", False) and "conc_params" in st.session_state:
        prm = st.session_state["conc_params"]
        try:
            tabla, resumen = conciliar(df_calc, prm["df_real"], **prm["argumentos"])
            ident = None
            try:
                ident = historial.guardar(tabla, resumen, prm["archivo"], usuario)
            except OSError:
                pass
            st.session_state["conc_resultado"] = (tabla, resumen, ident)
        except Exception as e:
            st.warning(f"No fue posible recalcular la conciliación: {e}")

    ui.seccion(st, "1. Periodo y archivo del inventario real")
    c1, c2 = st.columns([1, 2])
    with c1:
        periodo = st.selectbox(
            "Periodo a verificar",
            periodos[::-1],
            format_func=lambda p: m.nombre_periodo(*m.periodo_de_etiqueta(p)).title(),
            key="conc_periodo",
        )
    with c2:
        archivo = st.file_uploader(
            "Inventario final real del periodo (Excel o CSV)",
            type=["xlsx", "xlsm", "xls", "csv"],
            key="conc_archivo",
        )

    if archivo is not None:
        try:
            df_real, hoja = leer_inventario_real(archivo.getvalue(), archivo.name)
        except Exception as e:
            st.error(f"No fue posible leer el archivo: {e}")
            df_real = None

        if df_real is not None:
            columnas = [c for c in df_real.columns if c != "_FILA_ORIGEN"]
            detectadas = detectar_columnas(df_real)

            ui.seccion(
                st, "2. Columnas del archivo",
                f"Hoja '{hoja}' · {ui.formato_entero(len(df_real))} filas. Revisa que cada columna sea la correcta.",
            )

            def selector(titulo, rol, col, opcional=False):
                opciones = (["(ninguna)"] if opcional else []) + columnas
                actual = detectadas.get(rol)
                indice = opciones.index(actual) if actual in opciones else 0
                with col:
                    valor = st.selectbox(titulo, opciones, index=indice, key=f"conc_col_{rol}")
                return None if valor == "(ninguna)" else valor

            a, b, c, d, e = st.columns(5)
            col_bod = selector("Bodega", "bodega", a)
            col_cod = selector("Código del artículo", "codigo", b)
            col_cant = selector("Cantidad real (stock final)", "cantidad", c)
            col_valor = selector("Valor total real (opcional)", "valor", d, opcional=True)
            col_desc = selector("Descripción (opcional)", "descripcion", e, opcional=True)

            o1, o2, o3 = st.columns(3)
            with o1:
                tolerancia = st.number_input(
                    "Tolerancia (unidades)", min_value=0.0, value=0.0, step=0.01,
                    help="Diferencias menores o iguales se consideran conciliadas. 0 = exacto.",
                    key="conc_tol_unidades",
                )
            with o2:
                tolerancia_valor = st.number_input(
                    "Tolerancia (valor $)", min_value=0.0, value=1.0, step=1.0,
                    help="Diferencias de valor menores o iguales se consideran conciliadas (redondeos).",
                    key="conc_tol_valor",
                )
            with o3:
                incluir_ceros = st.checkbox(
                    "Incluir referencias con stock calculado 0 que no están en el archivo real",
                    value=False, key="conc_incluir_ceros",
                )

            if st.button("Conciliar", type="primary", use_container_width=True):
                try:
                    acceso.exigir_admin(usuario, secretos, "conciliar el inventario")
                    argumentos = dict(
                        periodo=periodo, col_bodega=col_bod, col_codigo=col_cod,
                        col_cantidad=col_cant, col_descripcion=col_desc,
                        tolerancia=tolerancia, incluir_ceros_ausentes=incluir_ceros,
                        col_valor=col_valor, tolerancia_valor=tolerancia_valor,
                    )
                    with st.spinner("Comparando unidades y valores..."):
                        tabla, resumen = conciliar(df_calc, df_real, **argumentos)
                    ident = None
                    try:
                        ident = historial.guardar(tabla, resumen, archivo.name, usuario)
                    except OSError as e:
                        st.warning(f"La conciliación no se pudo guardar en el historial: {e}")
                    st.session_state["conc_resultado"] = (tabla, resumen, ident)
                    st.session_state["conc_params"] = {
                        "df_real": df_real, "argumentos": argumentos, "archivo": archivo.name,
                    }
                except Exception as e:
                    st.error(f"No fue posible conciliar: {e}")

    resultado = st.session_state.get("conc_resultado")
    if resultado is not None:
        tabla, resumen, ident = resultado
        ui.seccion(
            st, "3. Resultado",
            f"{m.nombre_periodo(*m.periodo_de_etiqueta(resumen['periodo'])).title()}"
            + (" · guardado en el historial" if ident else ""),
        )
        _mostrar_tabla(st, tabla, resumen, "conc_actual")
        _seccion_ajustes(
            st, tabla, resumen, ident, base_dir, archivo_historico,
            archivo_actualizado, usuario, secretos,
        )

    registro = historial.registro()
    if registro:
        ui.seccion(st, "Historial de conciliaciones")
        resumen_hist = pd.DataFrame([
            {
                "id": r["id"],
                "Periodo": m.nombre_periodo(*m.periodo_de_etiqueta(r["periodo"])).title(),
                "Fecha": r["fecha"].replace("T", " "),
                "Usuario": r["usuario"],
                "Archivo": r["archivo"],
                "Conciliados": r["resumen"]["por_estado"].get(ESTADO_CONCILIADO, 0)
                + r["resumen"]["por_estado"].get(ESTADO_AJUSTADO, 0),
                "Con diferencia": r["resumen"]["por_estado"].get(ESTADO_DIFERENCIA, 0),
                "Pendientes": r["resumen"]["por_estado"].get(ESTADO_PENDIENTE, 0),
            }
            for r in reversed(registro)
        ])
        st.dataframe(resumen_hist.drop(columns=["id"]), use_container_width=True, hide_index=True)
        elegido = st.selectbox(
            "Consultar una conciliación anterior",
            ["(ninguna)"] + resumen_hist["id"].tolist(),
            format_func=lambda i: i if i == "(ninguna)" else
            f"{resumen_hist.set_index('id').loc[i, 'Periodo']} — {resumen_hist.set_index('id').loc[i, 'Fecha']}",
            key="conc_hist",
        )
        if elegido != "(ninguna)":
            r = next(x for x in registro if x["id"] == elegido)
            try:
                anterior = historial.leer(elegido)
                for c in COLUMNAS_RESULTADO:
                    if c not in anterior.columns:
                        anterior[c] = np.nan
                _mostrar_tabla(st, anterior, r["resumen"], f"conc_{elegido}")
            except Exception as e:
                st.error(f"No fue posible abrir esa conciliación: {e}")
