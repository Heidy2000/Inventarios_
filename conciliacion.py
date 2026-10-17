"""
conciliacion.py
Conciliación del stock calculado contra el inventario final real de
cada mes, por bodega y referencia.

Reglas:
  * Diferencia = Stock calculado - Stock real.
  * El inventario real es solo referencia de control: nunca reemplaza
    el stock calculado ni modifica movimientos.
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
ESTADO_DIFERENCIA = "Con diferencia"
ESTADO_SIN_REAL = "Sin dato real"
ESTADO_SIN_CALCULO = "Sin cálculo"
ESTADO_PENDIENTE = "Pendiente de validación"

ORDEN_ESTADOS = [
    ESTADO_DIFERENCIA,
    ESTADO_PENDIENTE,
    ESTADO_SIN_CALCULO,
    ESTADO_SIN_REAL,
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
    "Estado",
    "Observación",
    "LLAVE",
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
}


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

    for rol in ("codigo", "bodega", "descripcion", "cantidad"):
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
                    if c in usadas or any(x in n for x in ("COSTO", "COSTE", "VALOR", "PRECIO")):
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
# STOCK CALCULADO DEL PERIODO
# ============================================================

def stock_calculado(df_calc, anio, mes):
    """
    Stock inicial, entradas, salidas y stock final calculados por LLAVE
    para el periodo. Las salidas se muestran con su signo (negativas).
    """
    nombre = m.nombre_periodo(anio, mes)
    c_stock = m.col_exacta(df_calc, f"STOCK {nombre}")
    if c_stock is None:
        raise ValueError(f"El periodo {nombre.title()} no está calculado en la aplicación.")

    c_ent = m.col_exacta(df_calc, f"ENTRADA {nombre}")
    c_sal = m.col_exacta(df_calc, f"SALIDA {nombre}")

    anio_p, mes_p = m.periodo_de_num(m.periodo_num(anio, mes) - 1)
    c_prev = m.col_exacta(df_calc, f"STOCK {m.nombre_periodo(anio_p, mes_p)}")
    if c_prev is None:
        c_prev = m.col_exacta(df_calc, "STOCK INICIAL")

    c_bod = m.col_buscar(df_calc, ["Bodega"])
    c_cod = m.col_buscar(df_calc, ["Codigo Articulo"])
    c_art = m.col_exacta(df_calc, "Articulo")

    base = pd.DataFrame({
        "LLAVE": (
            df_calc["LLAVE"].astype(str) if "LLAVE" in df_calc.columns
            else [m.crear_llave(b, c) for b, c in zip(df_calc[c_bod], df_calc[c_cod])]
        ),
        "Bodega": df_calc[c_bod].apply(m.bodega_txt),
        "Codigo Articulo": df_calc[c_cod].apply(m.codigo),
        "Articulo": df_calc[c_art].apply(m.texto) if c_art else "",
        "Stock inicial calculado": m.a_numero(df_calc[c_prev]) if c_prev else 0.0,
        "Entradas del mes": m.a_numero(df_calc[c_ent]) if c_ent else 0.0,
        "Salidas del mes": m.a_numero(df_calc[c_sal]) if c_sal else 0.0,
        "Stock final calculado": m.a_numero(df_calc[c_stock]),
    })

    agregado = base.groupby("LLAVE", as_index=False).agg({
        "Bodega": "first",
        "Codigo Articulo": "first",
        "Articulo": "first",
        "Stock inicial calculado": "sum",
        "Entradas del mes": "sum",
        "Salidas del mes": "sum",
        "Stock final calculado": "sum",
    })
    return agregado


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
):
    """
    periodo: 'AAAA-MM'. Devuelve (tabla, resumen).
    """
    anio, mes = m.periodo_de_etiqueta(periodo)
    etiqueta = m.nombre_periodo(anio, mes).title()
    calc = stock_calculado(df_calc, anio, mes)

    for col, rol in ((col_bodega, "bodega"), (col_codigo, "código"), (col_cantidad, "cantidad")):
        if not col or col not in df_real.columns:
            raise ValueError(f"Selecciona la columna de {rol} del archivo real.")

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
            "_vacia": bool(g["_vacia"].iloc[0]) if len(g) == 1 else False,
            "_motivo": "; ".join(motivos),
            "_fila": int(g["_fila"].iloc[0]),
        })
    reales = pd.DataFrame(
        reales,
        columns=["LLAVE", "Bodega real", "Codigo real", "Desc real", "Cantidad", "_vacia", "_motivo", "_fila"],
    )

    # ---------------- cruce ----------------
    t = calc.merge(reales, on="LLAVE", how="outer", indicator=True)

    estado = []
    observ = []
    for row in t.itertuples(index=False):
        origen = row[t.columns.get_loc("_merge")]
        motivo_r = row[t.columns.get_loc("_motivo")]
        cant = row[t.columns.get_loc("Cantidad")]
        calc_f = row[t.columns.get_loc("Stock final calculado")]

        if origen == "right_only":
            if isinstance(motivo_r, str) and motivo_r:
                estado.append(ESTADO_PENDIENTE)
                observ.append(motivo_r)
            elif pd.isna(cant):
                estado.append(ESTADO_PENDIENTE)
                observ.append("Sin cálculo y sin cantidad real")
            else:
                estado.append(ESTADO_SIN_CALCULO)
                observ.append("La referencia no existe en el cálculo de esta bodega")
            continue

        if origen == "left_only":
            estado.append(ESTADO_SIN_REAL)
            observ.append("No aparece en el archivo real")
            continue

        if isinstance(motivo_r, str) and motivo_r:
            estado.append(ESTADO_PENDIENTE)
            observ.append(motivo_r)
        elif pd.isna(cant):
            estado.append(ESTADO_SIN_REAL)
            observ.append("Cantidad real vacía en el archivo")
        elif abs(float(calc_f) - float(cant)) <= tolerancia + 1e-9:
            estado.append(ESTADO_CONCILIADO)
            observ.append("")
        else:
            estado.append(ESTADO_DIFERENCIA)
            dif = float(calc_f) - float(cant)
            observ.append("Sobrante en el cálculo" if dif > 0 else "Faltante en el cálculo")

    t["Estado"] = estado
    t["Observación"] = observ

    t["Bodega"] = t["Bodega"].where(t["Bodega"].notna() & (t["Bodega"] != ""), t["Bodega real"])
    t["Codigo Articulo"] = t["Codigo Articulo"].where(t["Codigo Articulo"].notna(), t["Codigo real"])
    t["Articulo"] = t["Articulo"].where(
        t["Articulo"].notna() & (t["Articulo"].astype(str) != ""), t["Desc real"]
    )
    t["Stock final real reportado"] = t["Cantidad"]
    t["Diferencia"] = np.where(
        t["Estado"].isin([ESTADO_CONCILIADO, ESTADO_DIFERENCIA]),
        t["Stock final calculado"] - t["Cantidad"],
        np.nan,
    )
    t["Periodo"] = etiqueta

    # Referencias con stock calculado 0 que no figuran en el archivo
    # real: normalmente no son novedad (el real lista solo existencias).
    ceros_ausentes = (t["_merge"] == "left_only") & (t["Stock final calculado"].abs() <= m.EPS)
    n_ceros_ausentes = int(ceros_ausentes.sum())
    if not incluir_ceros_ausentes:
        t = t[~ceros_ausentes]

    pendientes_sin_llave = pd.DataFrame({
        "Periodo": etiqueta,
        "Codigo Articulo": sin_llave["Codigo real"],
        "Articulo": sin_llave["Desc real"],
        "Bodega": sin_llave["Bodega real"],
        "Stock final real reportado": sin_llave["Cantidad"],
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
    resumen = {
        "periodo": periodo,
        "registros": int(len(tabla)),
        "por_estado": {e: int(conteo.get(e, 0)) for e in ORDEN_ESTADOS},
        "diferencia_neta": float(tabla["Diferencia"].sum(skipna=True)),
        "diferencia_absoluta": float(tabla["Diferencia"].abs().sum(skipna=True)),
        "filas_archivo_real": int(len(df_real)),
        "filas_bodegas_excluidas": filas_excluidas,
        "ceros_ausentes_omitidos": 0 if incluir_ceros_ausentes else n_ceros_ausentes,
        "tolerancia": float(tolerancia),
    }
    return tabla, resumen


def resumen_por_bodega(tabla):
    if tabla.empty:
        return pd.DataFrame()
    g = tabla.assign(
        _con_dif=tabla["Estado"].eq(ESTADO_DIFERENCIA),
        _conc=tabla["Estado"].eq(ESTADO_CONCILIADO),
        _absdif=tabla["Diferencia"].abs(),
    ).groupby("Bodega", dropna=False).agg(
        Registros=("Estado", "size"),
        Conciliados=("_conc", "sum"),
        Con_diferencia=("_con_dif", "sum"),
        Diferencia_neta=("Diferencia", "sum"),
        Diferencia_absoluta=("_absdif", "sum"),
    ).reset_index()
    g["% conciliado"] = np.where(g["Registros"] > 0, g["Conciliados"] / g["Registros"] * 100, 0)
    return g.rename(columns={
        "Con_diferencia": "Con diferencia",
        "Diferencia_neta": "Diferencia neta",
        "Diferencia_absoluta": "Diferencia absoluta",
    }).sort_values("Diferencia absoluta", ascending=False)


def a_excel(tabla, resumen):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        tabla.to_excel(w, sheet_name="Conciliacion", index=False)
        resumen_por_bodega(tabla).to_excel(w, sheet_name="Resumen por bodega", index=False)
        filas = [{"Concepto": "Periodo", "Valor": resumen["periodo"]}]
        filas += [{"Concepto": e, "Valor": n} for e, n in resumen["por_estado"].items()]
        filas += [
            {"Concepto": "Diferencia neta (calculado - real)", "Valor": resumen["diferencia_neta"]},
            {"Concepto": "Diferencia absoluta", "Valor": resumen["diferencia_absoluta"]},
            {"Concepto": "Filas del archivo real", "Valor": resumen["filas_archivo_real"]},
            {"Concepto": "Filas de bodegas excluidas", "Valor": resumen["filas_bodegas_excluidas"]},
            {"Concepto": "Referencias con stock 0 ausentes (omitidas)", "Valor": resumen["ceros_ausentes_omitidos"]},
            {"Concepto": "Tolerancia (unidades)", "Valor": resumen["tolerancia"]},
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
        ESTADO_DIFERENCIA: f"background-color: {ui.ROJO_SUAVE}; color: {ui.ROJO}",
        ESTADO_PENDIENTE: f"background-color: {ui.NARANJA_SUAVE}; color: {ui.NARANJA_OSCURO}",
        ESTADO_SIN_CALCULO: f"background-color: {ui.AZUL_SUAVE}; color: {ui.AZUL}",
        ESTADO_SIN_REAL: "background-color: #F1F3F6; color: #5F7189",
    }
    return colores.get(valor, "")


def _mostrar_tabla(st, tabla, resumen, clave):
    pe = resumen["por_estado"]
    total = max(resumen["registros"], 1)
    ui.fila_kpis(st, [
        ("Conciliados", ui.formato_entero(pe[ESTADO_CONCILIADO]),
         f"{pe[ESTADO_CONCILIADO] / total * 100:.1f}% de los registros", "verde"),
        ("Con diferencia", ui.formato_entero(pe[ESTADO_DIFERENCIA]),
         f"diferencia absoluta {ui.formato_numero(resumen['diferencia_absoluta'])} und.", "rojo"),
        ("Pendientes de validación", ui.formato_entero(pe[ESTADO_PENDIENTE]),
         "duplicados o datos inválidos", "naranja"),
        ("Sin cálculo", ui.formato_entero(pe[ESTADO_SIN_CALCULO]), "solo en el archivo real", "azul"),
        ("Sin dato real", ui.formato_entero(pe[ESTADO_SIN_REAL]), "solo en el cálculo", "gris"),
    ])

    notas = []
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
            default=[e for e in ORDEN_ESTADOS if e != ESTADO_CONCILIADO and pe.get(e)] or ORDEN_ESTADOS,
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

    formato = {
        c: st.column_config.NumberColumn(c, format="%.2f")
        for c in [
            "Stock inicial calculado", "Entradas del mes", "Salidas del mes",
            "Stock final calculado", "Stock final real reportado", "Diferencia",
        ]
    }
    try:
        datos = vista.style.map(_colores_estado, subset=["Estado"])
    except Exception:
        datos = vista
    st.dataframe(
        datos, use_container_width=True, hide_index=True, height=460,
        column_config=formato,
    )

    with st.expander("Resumen por bodega"):
        st.dataframe(
            resumen_por_bodega(tabla), use_container_width=True, hide_index=True,
            column_config={"% conciliado": st.column_config.NumberColumn(format="%.1f%%")},
        )

    st.download_button(
        "Descargar conciliación (Excel)",
        data=a_excel(tabla, resumen),
        file_name=f"Conciliacion_{resumen['periodo']}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"{clave}_descarga",
    )


def pagina_conciliacion(st, df_calc, base_dir):
    secretos = acceso.secretos_de(st)
    usuario = acceso.usuario_sesion(st)

    ui.encabezado_pagina(
        st,
        "Conciliación mensual",
        "Compara el stock final calculado con el inventario real reportado por "
        "bodega y referencia. El real es solo referencia de control: no modifica el cálculo.",
        eyebrow="Control",
        pills=[("Diferencia = calculado − real", "primary")],
    )

    if not acceso.es_admin(usuario, secretos):
        st.error("Tu usuario no tiene permiso para esta página.")
        return

    periodos = [m.etiqueta_periodo(a, mm) for a, mm in m.meses_con_stock(df_calc)]
    if not periodos:
        st.error("No hay periodos calculados para conciliar.")
        return

    historial = HistorialConciliaciones(base_dir)

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

            a, b, c, d = st.columns(4)
            col_bod = selector("Bodega", "bodega", a)
            col_cod = selector("Código del artículo", "codigo", b)
            col_cant = selector("Cantidad real (stock final)", "cantidad", c)
            col_desc = selector("Descripción (opcional)", "descripcion", d, opcional=True)

            o1, o2 = st.columns(2)
            with o1:
                tolerancia = st.number_input(
                    "Tolerancia (unidades)", min_value=0.0, value=0.0, step=0.01,
                    help="Diferencias menores o iguales se consideran conciliadas. 0 = exacto.",
                )
            with o2:
                incluir_ceros = st.checkbox(
                    "Incluir referencias con stock calculado 0 que no están en el archivo real",
                    value=False,
                )

            if st.button("Conciliar", type="primary", use_container_width=True):
                try:
                    acceso.exigir_admin(usuario, secretos, "conciliar el inventario")
                    with st.spinner("Comparando stock calculado y real..."):
                        tabla, resumen = conciliar(
                            df_calc, df_real, periodo, col_bod, col_cod, col_cant,
                            col_desc, tolerancia, incluir_ceros,
                        )
                    ident = None
                    try:
                        ident = historial.guardar(tabla, resumen, archivo.name, usuario)
                    except OSError as e:
                        st.warning(f"La conciliación no se pudo guardar en el historial: {e}")
                    st.session_state["conc_resultado"] = (tabla, resumen, ident)
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
                "Conciliados": r["resumen"]["por_estado"].get(ESTADO_CONCILIADO, 0),
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
                _mostrar_tabla(st, historial.leer(elegido), r["resumen"], f"conc_{elegido}")
            except Exception as e:
                st.error(f"No fue posible abrir esa conciliación: {e}")
