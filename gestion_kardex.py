"""
gestion_kardex.py
Cargues mensuales del Kardex con registro de periodos.

Por qué existe
--------------
Antes, cada cargue recalculaba todo desde el histórico base (mayo 2026)
usando SOLO el archivo recién cargado. Si se cargaba el Kardex de julio
por sí solo, los movimientos de junio desaparecían del resultado.

Ahora cada periodo cargado (AAAA-MM) se guarda una vez en
datos/kardex/AAAA-MM.csv.gz y el inventario se reconstruye siempre así:

    histórico base  +  movimientos de TODOS los periodos guardados,
    en orden cronológico (el cierre de un mes es el inicio del siguiente).

Consecuencias:
  * Cargar de nuevo un periodo REEMPLAZA sus movimientos (con
    confirmación); nunca los suma dos veces.
  * Corregir un mes anterior recalcula automáticamente los posteriores.
  * Si falta un mes intermedio, el cargue se bloquea (continuidad).
  * La escritura es atómica: se calcula todo en memoria, se respaldan
    los archivos afectados y, si algo falla, se restauran.
"""
import hashlib
import io
import json
import os
import shutil
import time
from contextlib import contextmanager
from datetime import datetime

import pandas as pd

import acceso
import motor_lifo as m
import ui


MAX_RESPALDOS = 30
MINUTOS_BLOQUEO = 15

COLUMNAS_GUARDADAS = m.COLUMNAS_MOVIMIENTO + ["_CONVENCION", "_FILA_ORIGEN", "_ARCHIVO"]


# ============================================================
# ESCRITURA SEGURA
# ============================================================

def escribir_atomico(ruta, contenido):
    """Escribe en un temporal del mismo directorio y lo reemplaza de una vez."""
    carpeta = os.path.dirname(ruta) or "."
    os.makedirs(carpeta, exist_ok=True)
    temporal = os.path.join(
        carpeta, f".{os.path.basename(ruta)}.{os.getpid()}.{time.time_ns()}.tmp"
    )
    try:
        with open(temporal, "wb") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporal, ruta)
    finally:
        if os.path.exists(temporal):
            os.remove(temporal)


def sha256(contenido):
    return hashlib.sha256(contenido).hexdigest()


# ============================================================
# ALMACÉN DE PERIODOS
# ============================================================

class Almacen:
    """Periodos del Kardex cargados, registro de cargues y respaldos."""

    def __init__(self, base_dir):
        self.dir = os.path.join(base_dir, "datos")
        self.dir_kardex = os.path.join(self.dir, "kardex")
        self.dir_respaldos = os.path.join(self.dir, "respaldos")
        self.ruta_registro = os.path.join(self.dir, "registro_cargues.json")
        self.ruta_bloqueo = os.path.join(self.dir, ".cargue_en_curso")

    # ---------------- lectura ----------------

    def ruta_periodo(self, etiqueta):
        return os.path.join(self.dir_kardex, f"{etiqueta}.csv.gz")

    def periodos(self):
        if not os.path.isdir(self.dir_kardex):
            return []
        salida = []
        for nombre in os.listdir(self.dir_kardex):
            if nombre.endswith(".csv.gz") and not nombre.startswith("."):
                etiqueta = nombre[: -len(".csv.gz")]
                try:
                    m.periodo_de_etiqueta(etiqueta)
                except Exception:
                    continue
                salida.append(etiqueta)
        return sorted(salida)

    def leer_periodo(self, etiqueta):
        df = pd.read_csv(
            self.ruta_periodo(etiqueta),
            dtype=str,
            keep_default_na=False,
            compression="gzip",
        )
        for c in ("Cantidad Entrada", "Cantidad Salida", "Costo Total Con Iva"):
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        df["_FILA_ORIGEN"] = pd.to_numeric(df["_FILA_ORIGEN"], errors="coerce")
        df["Fecha Movimiento"] = pd.to_datetime(
            df["Fecha Movimiento"], format="%Y-%m-%d %H:%M:%S", errors="coerce"
        )
        return df

    def leer_todos(self, excluir=()):
        partes = [
            self.leer_periodo(p) for p in self.periodos() if p not in excluir
        ]
        if not partes:
            return pd.DataFrame(columns=COLUMNAS_GUARDADAS)
        return pd.concat(partes, ignore_index=True)

    def registro(self):
        if not os.path.exists(self.ruta_registro):
            return []
        with open(self.ruta_registro, "r", encoding="utf-8") as f:
            return json.load(f)

    def registro_vigente(self):
        """Último cargue vigente de cada periodo guardado."""
        vigentes = {}
        for r in self.registro():
            if r.get("vigente", True):
                vigentes[r["periodo"]] = r
        return [vigentes[p] for p in sorted(vigentes) if p in set(self.periodos())]

    # ---------------- escritura ----------------

    @staticmethod
    def serializar_periodo(df):
        salida = df.copy()
        for c in COLUMNAS_GUARDADAS:
            if c not in salida.columns:
                salida[c] = ""
        salida = salida[COLUMNAS_GUARDADAS]
        salida["Fecha Movimiento"] = pd.to_datetime(
            salida["Fecha Movimiento"]
        ).dt.strftime("%Y-%m-%d %H:%M:%S")
        texto = salida.to_csv(index=False)
        buf = io.BytesIO()
        import gzip
        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
            gz.write(texto.encode("utf-8"))
        return buf.getvalue()

    @contextmanager
    def bloqueo(self):
        os.makedirs(self.dir, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.ruta_bloqueo, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(time.time()).encode())
                os.close(fd)
                break
            except FileExistsError:
                edad = time.time() - os.path.getmtime(self.ruta_bloqueo)
                if edad > MINUTOS_BLOQUEO * 60:
                    os.remove(self.ruta_bloqueo)
                    continue
                raise RuntimeError(
                    "Hay otro cargue del Kardex en curso. Espera a que "
                    "termine e inténtalo de nuevo."
                )
        try:
            yield
        finally:
            if os.path.exists(self.ruta_bloqueo):
                os.remove(self.ruta_bloqueo)

    @contextmanager
    def transaccion(self, rutas):
        """
        Respalda los archivos que se van a modificar. Si algo falla
        dentro del bloque, restaura los que existían y elimina los
        creados: el histórico nunca queda a medio actualizar.
        """
        marca = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        carpeta = os.path.join(self.dir_respaldos, marca)
        os.makedirs(carpeta, exist_ok=True)

        copias = {}
        for i, ruta in enumerate(rutas):
            if os.path.exists(ruta):
                destino = os.path.join(carpeta, f"{i:03d}_{os.path.basename(ruta)}")
                shutil.copy2(ruta, destino)
                copias[ruta] = destino

        with open(os.path.join(carpeta, "manifiesto.json"), "w", encoding="utf-8") as f:
            json.dump(
                {"rutas": list(rutas), "respaldadas": copias},
                f, ensure_ascii=False, indent=1,
            )

        try:
            yield carpeta
        except BaseException:
            for ruta in rutas:
                if ruta in copias:
                    shutil.copy2(copias[ruta], ruta)
                elif os.path.exists(ruta):
                    os.remove(ruta)
            raise
        finally:
            self._podar_respaldos()

    def _podar_respaldos(self):
        if not os.path.isdir(self.dir_respaldos):
            return
        carpetas = sorted(os.listdir(self.dir_respaldos))
        for vieja in carpetas[:-MAX_RESPALDOS]:
            shutil.rmtree(os.path.join(self.dir_respaldos, vieja), ignore_errors=True)


# ============================================================
# ANÁLISIS PREVIO DEL ARCHIVO (no escribe nada)
# ============================================================

def analizar_kardex(kardex_crudo, base_df, almacen, nombre_archivo, contenido):
    """
    Revisa un Kardex antes de procesarlo y devuelve el plan:
    periodos que contiene, cuáles son nuevos o reemplazos, filas
    rechazadas, faltantes de continuidad y bloqueos.
    """
    kn = m.normalizar_kardex(kardex_crudo)
    kn["_ARCHIVO"] = nombre_archivo

    meses_base = m.meses_con_stock(base_df)
    if not meses_base:
        raise ValueError("El histórico base no tiene columnas de stock mensual.")

    num_base = m.periodo_num(*meses_base[-1])
    etiqueta_base = m.etiqueta_periodo(*meses_base[-1])

    rechazo = kn["_MOTIVO_RECHAZO"] != ""
    validas = kn[~rechazo].copy()
    rechazados = m._tabla_motivo(kn[rechazo], kn.loc[rechazo, "_MOTIVO_RECHAZO"])

    nums = (
        validas["Fecha Movimiento"].dt.year * 12
        + validas["Fecha Movimiento"].dt.month
    )

    anteriores = int((nums <= num_base).sum())

    por_periodo = {}
    for n in sorted(nums[nums > num_base].unique()):
        etiqueta = m.etiqueta_periodo(*m.periodo_de_num(n))
        por_periodo[etiqueta] = validas[nums == n].copy()

    existentes = set(almacen.periodos())
    reemplazos = sorted(set(por_periodo) & existentes)
    nuevos = sorted(set(por_periodo) - existentes)
    ultimo = max(existentes) if existentes else None
    anteriores_al_ultimo = sorted(p for p in por_periodo if ultimo and p < ultimo)

    huella = sha256(contenido)
    mismo_archivo = [
        r for r in almacen.registro()
        if r.get("sha256") == huella and r.get("vigente", True)
    ]

    # Continuidad: del mes siguiente a la base hasta el último periodo,
    # sin huecos.
    finales = existentes | set(por_periodo)
    faltantes = []
    if finales:
        num_max = max(m.periodo_num(*m.periodo_de_etiqueta(p)) for p in finales)
        for n in range(num_base + 1, num_max + 1):
            et = m.etiqueta_periodo(*m.periodo_de_num(n))
            if et not in finales:
                faltantes.append(et)

    duplicadas = {
        p: int(df.duplicated(subset=m.COLUMNAS_MOVIMIENTO, keep="first").sum())
        for p, df in por_periodo.items()
    }

    bloqueos = []
    if not por_periodo:
        bloqueos.append(
            "El archivo no tiene movimientos válidos posteriores a "
            f"{etiqueta_base} (mes base del histórico)."
        )
    if faltantes:
        bloqueos.append(
            "Falta cargar el Kardex de: " + ", ".join(faltantes)
            + ". Cada mes parte del cierre del anterior; carga primero "
            "los meses faltantes (o un archivo que los incluya)."
        )

    return {
        "archivo": nombre_archivo,
        "sha256": huella,
        "filas_leidas": len(kn),
        "rechazados": rechazados,
        "anteriores_a_base": anteriores,
        "periodo_base": etiqueta_base,
        "por_periodo": por_periodo,
        "nuevos": nuevos,
        "reemplazos": reemplazos,
        "anteriores_al_ultimo": anteriores_al_ultimo,
        "ultimo_guardado": ultimo,
        "mismo_archivo": mismo_archivo,
        "faltantes": faltantes,
        "duplicadas": duplicadas,
        "bloqueos": bloqueos,
    }


# ============================================================
# EJECUCIÓN
# ============================================================

def _recalcular(base_df, movimientos, periodo_final, plan=None):
    res = m.procesar_inventario(base_df, movimientos, periodo_final=periodo_final)

    # Las filas rechazadas al leer el archivo no se guardan (no se
    # pueden procesar), pero sí deben figurar en el resultado.
    if plan is not None:
        rech = plan["rechazados"]
        if len(rech):
            res["rechazados"] = pd.concat([rech, res["rechazados"]], ignore_index=True)
            res["stats"]["rechazados"] = len(res["rechazados"])
            res["avisos"].insert(
                0,
                f"{len(rech)} filas del archivo '{plan['archivo']}' fueron "
                "rechazadas por datos inválidos y no se procesaron "
                "(ver 'Movimientos rechazados').",
            )
        if plan["anteriores_a_base"]:
            res["stats"]["anteriores_a_base"] = (
                res["stats"].get("anteriores_a_base", 0) + plan["anteriores_a_base"]
            )
            res["avisos"].append(
                f"{plan['anteriores_a_base']} movimientos del archivo son "
                f"anteriores o iguales al mes base ({plan['periodo_base']}) y "
                "ya están incluidos en el histórico: no se procesaron."
            )

    excel = m.resultado_a_excel(res)
    return res, excel


def ejecutar_cargue(
    plan,
    base_df,
    almacen,
    usuario,
    ruta_actualizado,
    secretos=None,
    confirmar_reemplazo=False,
    excluir_filas_identicas=False,
):
    """
    Guarda los periodos del plan y recalcula el inventario completo.
    Devuelve (resultado, excel_bytes). No deja cambios parciales.
    """
    acceso.exigir_admin(usuario, secretos, "actualizar el Kardex")

    if plan["bloqueos"]:
        raise ValueError(" ".join(plan["bloqueos"]))

    if (plan["reemplazos"] or plan["mismo_archivo"]) and not confirmar_reemplazo:
        raise ValueError(
            "Este cargue reemplaza periodos ya procesados "
            f"({', '.join(plan['reemplazos']) or 'mismo archivo'}). "
            "Confirma el reemplazo para continuar."
        )

    nuevos = {}
    excluidas = {}
    for p, df in plan["por_periodo"].items():
        if excluir_filas_identicas:
            mascara = df.duplicated(subset=m.COLUMNAS_MOVIMIENTO, keep="first")
            excluidas[p] = int(mascara.sum())
            df = df[~mascara]
        else:
            excluidas[p] = 0
        nuevos[p] = df

    with almacen.bloqueo():
        # Segunda verificación dentro del bloqueo: otro administrador
        # pudo cargar periodos después de revisar este plan.
        todos = sorted(set(almacen.periodos()) | set(nuevos))
        num_base = m.periodo_num(*m.periodo_de_etiqueta(plan["periodo_base"]))
        esperados = [
            m.etiqueta_periodo(*m.periodo_de_num(n))
            for n in range(num_base + 1, m.periodo_num(*m.periodo_de_etiqueta(todos[-1])) + 1)
        ]
        if todos != esperados:
            raise ValueError(
                "Los periodos cargados cambiaron mientras se revisaba el "
                "archivo. Vuelve a cargarlo para revisar el plan actualizado."
            )
        nuevos_reemplazos = set(nuevos) & set(almacen.periodos())
        if nuevos_reemplazos - set(plan["reemplazos"]) and not confirmar_reemplazo:
            raise ValueError(
                "Otro cargue guardó estos periodos mientras se revisaba el "
                "archivo: " + ", ".join(sorted(nuevos_reemplazos))
                + ". Vuelve a cargarlo y confirma el reemplazo."
            )

        guardados = almacen.leer_todos(excluir=set(nuevos))
        movimientos = pd.concat(
            [guardados] + [nuevos[p] for p in sorted(nuevos)], ignore_index=True
        )
        periodo_final = todos[-1]

        # 1) Cálculo completo en memoria: si falla, no se toca el disco.
        res, excel = _recalcular(base_df, movimientos, periodo_final, plan)

        # 2) Escritura con respaldo y restauración ante cualquier error.
        registro = almacen.registro()
        ahora = datetime.now().isoformat(timespec="seconds")

        for p in nuevos:
            for r in registro:
                if r["periodo"] == p and r.get("vigente", True):
                    r["vigente"] = False
                    r["reemplazado_el"] = ahora
            registro.append(
                {
                    "periodo": p,
                    "archivo": plan["archivo"],
                    "sha256": plan["sha256"],
                    "movimientos": int(len(nuevos[p])),
                    "duplicados_excluidos": excluidas[p],
                    "usuario": usuario,
                    "fecha_cargue": ahora,
                    "accion": "reemplazo" if p in plan["reemplazos"] else "nuevo",
                    "vigente": True,
                }
            )

        rutas = [almacen.ruta_periodo(p) for p in nuevos] + [
            almacen.ruta_registro,
            ruta_actualizado,
        ]

        with almacen.transaccion(rutas):
            for p, df in nuevos.items():
                escribir_atomico(almacen.ruta_periodo(p), Almacen.serializar_periodo(df))
            escribir_atomico(ruta_actualizado, excel)
            escribir_atomico(
                almacen.ruta_registro,
                json.dumps(registro, ensure_ascii=False, indent=1).encode("utf-8"),
            )

    return res, excel


def reprocesar_todo(base_df, almacen, usuario, ruta_actualizado, secretos=None):
    """Recalcula el inventario con los periodos ya guardados (sin cargar nada)."""
    acceso.exigir_admin(usuario, secretos, "reprocesar el Kardex")

    periodos = almacen.periodos()
    if not periodos:
        raise ValueError("No hay periodos del Kardex guardados para reprocesar.")

    with almacen.bloqueo():
        movimientos = almacen.leer_todos()
        res, excel = _recalcular(base_df, movimientos, periodos[-1])
        with almacen.transaccion([ruta_actualizado]):
            escribir_atomico(ruta_actualizado, excel)

    return res, excel


# ============================================================
# PÁGINA "ACTUALIZAR KARDEX"
# ============================================================

def _texto_periodo(etiqueta):
    anio, mes = m.periodo_de_etiqueta(etiqueta)
    return m.nombre_periodo(anio, mes).title()


def _leer_base(st, archivo_historico):
    clave = ("base_df", os.path.getmtime(archivo_historico))
    if st.session_state.get("_base_cache_clave") != clave:
        base, _ = m.leer_historico(archivo_historico)
        st.session_state["_base_cache"] = base
        st.session_state["_base_cache_clave"] = clave
    return st.session_state["_base_cache"]


def _mostrar_resultado(st, res):
    s = res["stats"]

    st.success(
        f"Inventario recalculado hasta {_texto_periodo(s['periodo_final'])}. "
        f"Periodos incluidos: {', '.join(_texto_periodo(p) for p in s['periodos'])}. "
        f"Indicadores de antigüedad: {s['periodo_inventario']}."
    )

    ui.fila_kpis(
        st,
        [
            ("Movimientos procesados", ui.formato_entero(s["movimientos_procesados"]),
             f"{ui.formato_entero(s['filas_kardex'])} filas leídas", "azul"),
            ("Rechazados", ui.formato_entero(s["rechazados"]),
             "datos inválidos, no procesados", "rojo" if s["rechazados"] else "verde"),
            ("Para revisión", ui.formato_entero(s["para_revision"]),
             "signo, duplicado, fila mixta, sin costo", "naranja" if s["para_revision"] else "verde"),
            ("Salidas sin existencia", ui.formato_entero(s["con_salida_sin_existencia"]),
             f"{ui.formato_numero(s['unidades_sin_existencia'])} unidades no descontadas", "naranja"),
            ("Referencias nuevas", ui.formato_entero(s["llaves_nuevas"]),
             f"{ui.formato_entero(s['anulados'])} anulados excluidos", "oscuro"),
        ],
    )

    for aviso in res["avisos"]:
        st.warning(aviso)

    with st.expander("Verificaciones del cálculo", expanded=True):
        for nombre, ok, detalle in res["verificaciones"]:
            (st.success if ok else st.error)(f"{nombre} ({detalle})")

    tablas = [
        ("rechazados", "Movimientos rechazados"),
        ("revision", "Movimientos para revisión"),
        ("sin_existencia", "Salidas sin existencia"),
        ("ajustes_costo", "Ajustes de costo residual (stock en 0)"),
    ]
    for clave, titulo in tablas:
        df = res.get(clave)
        if df is not None and len(df):
            with st.expander(f"{titulo} ({len(df)})"):
                st.dataframe(df, use_container_width=True, hide_index=True, height=320)

    nuevas = res["historico"][res["historico"]["OBSERVACION"] == m.MARCA_NUEVO]
    if len(nuevas):
        with st.expander(f"Artículos nuevos desde el Kardex ({len(nuevas)})"):
            cols = [c for c in ["Bodega", "Codigo Articulo", "Articulo", "LLAVE"] if c in nuevas.columns]
            st.dataframe(nuevas[cols], use_container_width=True, hide_index=True)


def pagina_actualizar_kardex(st, usuario, archivo_actualizado, archivo_historico):
    """Renderiza la página 'Actualizar Kardex' (solo administradores)."""

    secretos = acceso.secretos_de(st)
    usuario_real = acceso.usuario_sesion(st) or usuario

    if not acceso.es_admin(usuario_real, secretos):
        ui.encabezado_pagina(st, "Actualizar Kardex", eyebrow="Administración")
        st.error("Tu usuario no tiene permiso para actualizar la información.")
        return

    base_dir = os.path.dirname(os.path.abspath(archivo_historico))
    almacen = Almacen(base_dir)

    ui.encabezado_pagina(
        st,
        "Actualizar Kardex",
        "Carga el Kardex de cada mes. Cada periodo se guarda una sola vez y "
        "el inventario se reconstruye en orden: el cierre de un mes es el "
        "inicio del siguiente.",
        eyebrow="Administración",
    )

    # --------------------------------------------------------
    # HISTÓRICO BASE
    # --------------------------------------------------------
    if not os.path.exists(archivo_historico):
        st.warning(
            "No hay un histórico base en el servidor. Cárgalo una vez; "
            "se guardará y no se volverá a sobrescribir."
        )
        base_file = st.file_uploader(
            "Histórico base (Excel)", type=["xlsx", "xlsm"], key="up_historico"
        )
        if base_file is not None and st.button("Guardar histórico base"):
            try:
                acceso.exigir_admin(usuario_real, secretos, "guardar el histórico base")
                m.leer_historico(base_file.getvalue())
                if os.path.exists(archivo_historico):
                    st.error("Ya existe un histórico base; no se sobrescribe.")
                else:
                    escribir_atomico(archivo_historico, base_file.getvalue())
                    st.success("Histórico base guardado. Recarga la página para continuar.")
            except Exception as e:
                st.error(f"El archivo no es un histórico válido: {e}")
        return

    try:
        base_df = _leer_base(st, archivo_historico)
    except Exception as e:
        st.error(f"No fue posible leer el histórico base: {e}")
        return

    meses_base = m.meses_con_stock(base_df)
    etiqueta_base = m.etiqueta_periodo(*meses_base[-1])
    periodos = almacen.periodos()
    siguiente = m.etiqueta_periodo(
        *m.periodo_de_num(
            m.periodo_num(*m.periodo_de_etiqueta(periodos[-1] if periodos else etiqueta_base)) + 1
        )
    )

    ui.fila_kpis(
        st,
        [
            ("Mes base del histórico", _texto_periodo(etiqueta_base), "punto de partida fijo", "oscuro"),
            ("Periodos cargados", str(len(periodos)),
             ", ".join(_texto_periodo(p) for p in periodos[-3:]) or "ninguno", "azul"),
            ("Último periodo", _texto_periodo(periodos[-1]) if periodos else "—",
             "cierre vigente del tablero", "azul"),
            ("Próximo periodo esperado", _texto_periodo(siguiente), "para mantener la continuidad", "naranja"),
        ],
    )

    if not periodos and os.path.exists(archivo_actualizado):
        st.info(
            "El tablero muestra un cálculo hecho antes de este registro de "
            "cargues. Para continuar, carga el Kardex desde "
            f"{_texto_periodo(m.etiqueta_periodo(*m.periodo_de_num(m.periodo_num(*meses_base[-1]) + 1)))}: "
            "puede ser un archivo con varios meses o un archivo por mes."
        )

    vigentes = almacen.registro_vigente()
    if vigentes:
        with st.expander(f"Historial de cargues ({len(vigentes)} periodos vigentes)"):
            st.dataframe(
                pd.DataFrame(vigentes)[
                    ["periodo", "archivo", "movimientos", "accion", "usuario", "fecha_cargue"]
                ].rename(columns={
                    "periodo": "Periodo", "archivo": "Archivo", "movimientos": "Movimientos",
                    "accion": "Acción", "usuario": "Usuario", "fecha_cargue": "Fecha de cargue",
                }),
                use_container_width=True,
                hide_index=True,
            )

    # --------------------------------------------------------
    # CARGA DEL ARCHIVO
    # --------------------------------------------------------
    ui.seccion(
        st,
        "1. Cargar el Kardex",
        "Excel con el detalle de movimientos (Bodega, Codigo Articulo, Fecha "
        "Movimiento, Cantidad Entrada, Cantidad Salida, Costo Total Con Iva).",
    )

    col_a, col_b = st.columns([1.35, 1])

    with col_a:
        kardex_file = st.file_uploader(
            "Kardex del mes (o de varios meses)",
            type=["xlsx", "xlsm"],
            key="up_kardex",
        )

    with col_b:
        st.markdown(
            ui.insignia("Se excluye 5-ANULADO", "info")
            + ui.insignia("Bodegas 11, 12, 18, 19, 20 y 21 excluidas", "info")
            + ui.insignia("Costo con IVA", "info")
            + ui.insignia("Salidas sin existencia: no se descuentan", "warn"),
            unsafe_allow_html=True,
        )
        st.caption(
            "Las salidas conservan su signo: si el archivo las registra en "
            "negativo (-15) se suman tal cual (stock + entradas + salidas)."
        )

    if kardex_file is not None:
        contenido = kardex_file.getvalue()
        huella = sha256(contenido)

        if st.session_state.get("plan_kardex_huella") != huella:
            try:
                with st.spinner("Leyendo y validando el Kardex..."):
                    kardex, hoja = m.leer_kardex(contenido)
                    plan = analizar_kardex(kardex, base_df, almacen, kardex_file.name, contenido)
                plan["hoja"] = hoja
                st.session_state["plan_kardex"] = plan
                st.session_state["plan_kardex_huella"] = huella
            except Exception as e:
                st.session_state.pop("plan_kardex", None)
                st.session_state.pop("plan_kardex_huella", None)
                st.error(f"El archivo no se puede usar como Kardex: {e}")
                plan = None
        else:
            plan = st.session_state.get("plan_kardex")

        if plan:
            ui.seccion(st, "2. Revisar antes de procesar")

            filas = []
            for p, df in plan["por_periodo"].items():
                filas.append(
                    {
                        "Periodo": _texto_periodo(p),
                        "Movimientos válidos": len(df),
                        "Filas idénticas": plan["duplicadas"].get(p, 0),
                        "Acción": "Reemplaza el periodo guardado" if p in plan["reemplazos"] else "Nuevo periodo",
                    }
                )

            st.caption(
                f"Hoja '{plan.get('hoja', '')}' · {ui.formato_entero(plan['filas_leidas'])} filas leídas · "
                f"{ui.formato_entero(len(plan['rechazados']))} rechazadas · "
                f"{ui.formato_entero(plan['anteriores_a_base'])} anteriores al mes base (ya están en el histórico)"
            )

            if filas:
                st.dataframe(pd.DataFrame(filas), use_container_width=True, hide_index=True)

            for b in plan["bloqueos"]:
                st.error(b)

            if len(plan["rechazados"]):
                with st.expander(f"Filas rechazadas ({len(plan['rechazados'])}) — no se procesarán"):
                    st.dataframe(plan["rechazados"], use_container_width=True, hide_index=True, height=300)

            if plan["mismo_archivo"]:
                st.warning(
                    "Este mismo archivo ya fue cargado el "
                    + ", ".join(sorted({r["fecha_cargue"][:16].replace('T', ' ') for r in plan["mismo_archivo"]}))
                    + ". Procesarlo de nuevo reemplaza esos periodos; no suma los movimientos otra vez."
                )

            if plan["anteriores_al_ultimo"]:
                st.warning(
                    "Este archivo modifica periodos anteriores al último cargado ("
                    + ", ".join(_texto_periodo(p) for p in plan["anteriores_al_ultimo"])
                    + "). Los meses posteriores se recalcularán para conservar la continuidad del stock."
                )

            confirmar = True
            if plan["reemplazos"] or plan["mismo_archivo"]:
                confirmar = st.checkbox(
                    "Confirmo que quiero reemplazar los movimientos guardados de "
                    + (", ".join(_texto_periodo(p) for p in plan["reemplazos"]) or "estos periodos")
                    + " por los de este archivo.",
                    key="confirmar_reemplazo",
                )

            excluir = False
            if sum(plan["duplicadas"].values()):
                excluir = st.checkbox(
                    f"Excluir {sum(plan['duplicadas'].values())} filas idénticas "
                    "(misma fecha, bodega, artículo, cantidades, costo y estado). "
                    "Déjalo sin marcar si pueden ser movimientos reales repetidos.",
                    key="excluir_identicas",
                )

            procesar = st.button(
                "Procesar y actualizar el tablero",
                disabled=bool(plan["bloqueos"]) or not confirmar,
                use_container_width=True,
                type="primary",
            )

            if procesar:
                exito = False
                try:
                    with st.spinner("Recalculando el inventario con todos los periodos..."):
                        res, excel = ejecutar_cargue(
                            plan,
                            base_df,
                            almacen,
                            acceso.usuario_sesion(st) or usuario_real,
                            archivo_actualizado,
                            secretos=secretos,
                            confirmar_reemplazo=confirmar,
                            excluir_filas_identicas=excluir,
                        )
                    st.session_state["res_actualizacion"] = res
                    st.session_state["excel_actualizado"] = excel
                    st.session_state.pop("df_actualizado", None)
                    st.session_state.pop("plan_kardex", None)
                    st.session_state.pop("plan_kardex_huella", None)
                    try:
                        st.cache_data.clear()
                    except Exception:
                        pass
                    exito = True
                except acceso.AccesoDenegado as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(
                        "No fue posible procesar el Kardex. No se modificó "
                        f"ningún dato guardado.\n\n{type(e).__name__}: {e}"
                    )
                if exito:
                    st.rerun()

    # --------------------------------------------------------
    # RESULTADO DEL ÚLTIMO PROCESO
    # --------------------------------------------------------
    res = st.session_state.get("res_actualizacion")
    if res is not None:
        ui.seccion(st, "Resultado del último proceso")
        _mostrar_resultado(st, res)
        st.download_button(
            "Descargar Excel actualizado (con hojas de control)",
            data=st.session_state["excel_actualizado"],
            file_name="INVENTARIO_ACTUALIZADO_LIFO.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    # --------------------------------------------------------
    # HERRAMIENTAS
    # --------------------------------------------------------
    if periodos:
        with st.expander("Herramientas de administración"):
            st.caption(
                "Recalcula el inventario con los periodos ya guardados, sin "
                "cargar archivos (útil tras una actualización de la aplicación)."
            )
            if st.button("Reprocesar todos los periodos guardados"):
                exito = False
                try:
                    with st.spinner("Recalculando..."):
                        res, excel = reprocesar_todo(
                            base_df, almacen, acceso.usuario_sesion(st) or usuario_real,
                            archivo_actualizado, secretos=secretos,
                        )
                    st.session_state["res_actualizacion"] = res
                    st.session_state["excel_actualizado"] = excel
                    try:
                        st.cache_data.clear()
                    except Exception:
                        pass
                    exito = True
                except Exception as e:
                    st.error(f"No fue posible reprocesar. No se modificó nada.\n\n{e}")
                if exito:
                    st.rerun()
