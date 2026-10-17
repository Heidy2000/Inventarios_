# Inventarios ALDC

Tablero de análisis y seguimiento de inventarios de Área Limpia D.C. (Python + Streamlit).

## Estructura

| Archivo | Responsabilidad |
| --- | --- |
| `app.py` | Aplicación Streamlit: login, navegación, filtros y páginas de análisis y órdenes de compra. |
| `motor_lifo.py` | Motor de cálculo: lectura del histórico y del Kardex, stock y costos mensuales, lotes LIFO de control, indicadores de 12 meses y antigüedad, exportación a Excel. |
| `gestion_kardex.py` | Cargues mensuales del Kardex: periodos guardados, reemplazos controlados, continuidad, escritura atómica con respaldo y la página *Actualizar Kardex*. |
| `conciliacion.py` | Conciliación del stock calculado contra el inventario final real de cada mes, historial y la página *Conciliación mensual*. |
| `acceso.py` | Roles y páginas permitidas por usuario. |
| `ui.py` | Paleta corporativa, estilos y componentes visuales (encabezados, secciones, tarjetas KPI). |
| `HISTORICO_INVENTARIOS.xlsx` | Histórico base (cierre de mayo 2026). No se modifica. |
| `tests/` | Pruebas automáticas. |

Datos que la aplicación genera en el servidor (no se suben a git, ver `.gitignore`):

```
datos/kardex/AAAA-MM.csv.gz           movimientos guardados de cada periodo
datos/registro_cargues.json           quién cargó qué archivo y cuándo
datos/conciliaciones/                 resultados de cada conciliación
datos/respaldos/                      copia de los archivos antes de cada cargue (últimos 30)
INVENTARIO_ACTUALIZADO_LIFO.xlsx      resultado que lee el tablero
```

## Lógica del stock

```
stock final del mes = stock inicial del mes + entradas + salidas
```

* Las salidas conservan su signo. Si el Kardex las registra en negativo (`-15`) se suman tal cual; si las registra en positivo (`15`) se restan. La convención se detecta por archivo.
* Una salida con el signo contrario al del resto del archivo no se aplica y queda en *Movimientos para revisión*.
* El stock inicial de cada mes es el cierre del mes anterior; el primer mes parte del cierre del histórico base.
* Cada combinación bodega + código de artículo (`LLAVE`) se calcula por separado.
* Se conservan las reglas de negocio: bodegas 11, 12, 18, 19, 20 y 21 excluidas; movimientos `5-ANULADO` excluidos; costo con IVA; las salidas que superan el stock no se descuentan y se registran como *salida sin existencia*; coste mensual entre −1 y 1 → el inventario promedio usa el costo de entrada del mes.

## Cargue mensual del Kardex (usuario `admin`)

1. *Actualizar Kardex* → cargar el Excel del mes (o uno con varios meses).
2. La aplicación muestra los periodos detectados, las filas rechazadas y si algún periodo ya estaba cargado.
3. Un periodo ya cargado solo se reemplaza con confirmación; nunca se suma dos veces.
4. Si falta un mes intermedio, el cargue se bloquea.
5. Al procesar, el inventario se recalcula con todos los periodos guardados. Si algo falla no se guarda nada.

**Primera vez después de esta versión:** el registro de periodos empieza vacío. Carga el Kardex desde junio 2026 (puede ser un solo archivo con todos los meses).

## Usuarios y permisos

Las credenciales siguen en `.streamlit/secrets.toml` (`[usuarios]`).

| Usuario | Páginas |
| --- | --- |
| `admin` | Todas: Resumen e inventario, Evolución, Riesgos y detalle, Órdenes de compra, Conciliación mensual, Actualizar Kardex |
| `inventarios` | Resumen e inventario, Evolución, Riesgos y detalle |

Cualquier otro usuario recibe el perfil de consulta. Para asignar roles a usuarios nuevos se puede agregar en `secrets.toml`:

```toml
[roles]
supervisor = "admin"
```

## Ejecutar

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Pruebas

```bash
python -m unittest discover -s tests -v
```

`tests/test_app_simulada.py` ejecuta `app.py` completo con un simulador de Streamlit (y de Plotly si no está instalado) para detectar errores de ejecución y verificar la navegación por usuario. No reemplaza la revisión visual en el navegador.
