"""
acceso.py
Control de acceso por usuario para Inventarios ALDC.

Roles:
  * admin    -> todas las páginas y operaciones (carga del Kardex,
                conciliación, órdenes de compra).
  * consulta -> solo las páginas de análisis.

El rol se resuelve así (la primera regla que aplique):
  1. st.secrets["roles"][usuario], si existe esa sección.
  2. Los usuarios conocidos: "admin" -> admin, "inventarios" -> consulta.
  3. st.secrets["admins"] (lista existente de administradores).
  4. Cualquier otro usuario -> consulta (menor privilegio).

Las operaciones restringidas vuelven a verificar el rol en el momento
de ejecutarse (no basta con ocultar la página).
"""

ROL_ADMIN = "admin"
ROL_CONSULTA = "consulta"

PAGINAS_CONSULTA = [
    "Resumen e inventario",
    "Evolución",
    "Riesgos y detalle",
]

PAGINAS_ADMIN = PAGINAS_CONSULTA + [
    "Órdenes de compra",
    "Conciliación mensual",
    "Actualizar Kardex",
]

ROLES_POR_DEFECTO = {
    "admin": ROL_ADMIN,
    "inventarios": ROL_CONSULTA,
}


class AccesoDenegado(PermissionError):
    """Operación restringida solicitada por un usuario sin permiso."""


def _leer_secretos(secretos, clave):
    try:
        return secretos[clave]
    except Exception:
        return None


def rol_usuario(usuario, secretos=None):
    usuario = str(usuario or "").strip()

    if not usuario:
        return ROL_CONSULTA

    roles = _leer_secretos(secretos, "roles") if secretos is not None else None
    if roles is not None:
        try:
            valor = dict(roles).get(usuario)
        except Exception:
            valor = None
        if valor is not None:
            valor = str(valor).strip().lower()
            return ROL_ADMIN if valor == ROL_ADMIN else ROL_CONSULTA

    if usuario in ROLES_POR_DEFECTO:
        return ROLES_POR_DEFECTO[usuario]

    admins = _leer_secretos(secretos, "admins") if secretos is not None else None
    if admins is not None:
        try:
            if usuario in {str(x).strip() for x in list(admins)}:
                return ROL_ADMIN
        except Exception:
            pass

    return ROL_CONSULTA


def es_admin(usuario, secretos=None):
    return rol_usuario(usuario, secretos) == ROL_ADMIN


def paginas_permitidas(usuario, secretos=None):
    if es_admin(usuario, secretos):
        return list(PAGINAS_ADMIN)
    return list(PAGINAS_CONSULTA)


def puede_ver(usuario, pagina, secretos=None):
    return pagina in paginas_permitidas(usuario, secretos)


def exigir_admin(usuario, secretos=None, operacion="esta operación"):
    """Lanza AccesoDenegado si el usuario no es administrador."""
    if not es_admin(usuario, secretos):
        raise AccesoDenegado(
            f"Tu usuario no tiene permiso para {operacion}."
        )


def usuario_sesion(st):
    """Usuario autenticado de la sesión actual (no el que diga un parámetro)."""
    try:
        if not st.session_state.get("autenticado"):
            return ""
        return str(st.session_state.get("usuario", "")).strip()
    except Exception:
        return ""


def secretos_de(st):
    try:
        return st.secrets
    except Exception:
        return None
