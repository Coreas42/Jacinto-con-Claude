# PROGRESO

**Fase actual:** 3 (Inventario y kardex) — código subido a la rama `fase-3-inventario-kardex`; pruebas pendientes de correr en GitHub Actions.
**Fecha:** 2026-10-20

## Diagnóstico acordado

| Tema | Decisión |
|---|---|
| Catálogo | Productos simples: SKU/código de barras, categoría, precio, costo, stock mínimo. Sin lotes ni caducidad. |
| Alcance | POS (venta de mostrador), compras a proveedores, alertas de stock mínimo, **varias sucursales**. |
| Interfaz | Escritorio nativo: CustomTkinter + SQLite. |
| Roles | Administrador, Bodeguero, Vendedor/Cajero, Contador. |

## Supuestos (ajustables)

- Python 3.11+, SQLAlchemy 2 + Alembic. SQLite por defecto; `DATABASE_URL` permite pasar a PostgreSQL.
- Reglas de negocio en `app/servicios/`, sin depender de la ventana.
- Costeo: **promedio ponderado** (el usuario no eligió PEPS; es el valor por defecto). Stock negativo bloqueado. Dinero en `Decimal`.
- Multi-sucursal: existencias, movimientos y ventas llevarán `sucursal_id` desde su primera migración.
- Contraseñas con argon2, mínimo 8 caracteres.
- Un usuario no puede cambiar su propio rol, desactivarse ni editar sus propios permisos (evita quedarse sin administrador).
- El rol "vendedor" ve solo sus propias ventas/reportes: se aplica al consultar datos en las Fases 4 y 5 (el permiso base es `ver`).

## Esquema activo (migraciones `0001` a `0004`)

- `sucursales`, `configuracion`
- `roles`, `permisos` (módulo + acción, único), `roles_permisos`
- `usuarios` (correo único, hash argon2, rol, activo, último acceso)
- `usuarios_permisos` (excepción individual: concedido sí/no sobre el rol)
- `bitacora_auditoria` (usuario, acción, entidad, detalle JSON, fecha; solo se agregan registros)
- `categorias` (nombre único, activa)
- `productos` (sku único, código de barras único opcional, nombre, descripción, categoría, marca, costo_promedio, precio, stock_minimo, activo). **Sin columna de stock**: las existencias viven en `existencias` y solo cambian por movimientos.
- `historial_productos` (producto, campo, valor anterior, valor nuevo, usuario, fecha; solo se agregan filas)
- `proveedores` (nombre único, contacto, activo)
- `existencias` (producto + sucursal, cantidad; `CHECK cantidad >= 0`)
- `movimientos_inventario` (kardex: producto, sucursal, tipo, cantidad con signo, saldo_despues, costo_unitario, motivo, referencia, usuario, fecha; índice por producto; solo se agregan filas)
- `compras` + `compras_detalle`, `traslados`

## Permisos por módulo

Catálogo en `app/servicios/permisos.py` (`CATALOGO` y `MATRIZ_BASE`). Toda función de servicio sensible llama a `exigir_permiso`, que lanza `PermisoDenegado` (403). El menú solo muestra módulos con algún permiso efectivo.

Eventos auditados: `login`, `login_fallido`, `logout`, `usuario_creado`, `rol_cambiado`, `usuario_activado/desactivado`, `permiso_individual_cambiado`, `contrasena_cambiada/restablecida`.

## Catálogo (Fase 2)

- Servicio: `app/servicios/catalogo.py`. Pantalla: `app/ui/productos_pantalla.py`.
- SKU en mayúsculas y **no editable**. SKU y código de barras únicos, y ninguno puede coincidir con el código del otro en otro producto (los escaneos nunca son ambiguos).
- Productos y categorías se **desactivan, no se borran**. Un producto inactivo no sale en búsquedas ni en `obtener_por_codigo` (la venta de la Fase 4 usará esa función), pero conserva su historial.
- Permiso nuevo `productos.precios`: cambiar precio o costo. Solo lo tiene el administrador en la matriz base; se puede conceder por usuario. `productos.editar` cubre el resto de datos. La comprobación depende de los campos enviados.
- El historial registra precio, costo, stock mínimo, nombre y activo/inactivo, con el valor inicial desde el alta.
- Dinero: `Decimal` con 2 decimales; acepta `12.5`, `12,50` y `1,234.50`. SQLite guarda `Numeric` como número decimal (exacto a 2 decimales para estos importes); en PostgreSQL es exacto.
- `costo_promedio`: se fija al crear el producto o con `productos.precios`; desde la Fase 3 lo recalculan las compras.
- `seed.py` carga 4 categorías y 9 productos de ejemplo solo si no hay productos.

## Inventario (Fase 3)

- Servicio: `app/servicios/inventario.py`. Pantalla: `app/ui/inventario_pantalla.py`.
- **Único punto que toca el stock:** `aplicar_movimiento`. Escribe el movimiento y actualiza `existencias` en la misma transacción, con un `UPDATE` condicional (`cantidad + delta >= 0`): dos operaciones sobre la última unidad no pueden pasar las dos. Además la base tiene `CHECK cantidad >= 0`. La Fase 4 (ventas) debe usar esta función; no comprueba permisos, los comprueba quien la llama.
- Tipos de movimiento: `entrada`, `salida`, `merma`, `ajuste` (con signo), `devolucion`, `anulacion`, `traslado_entrada`, `traslado_salida`. Cantidades enteras (sin fracciones).
- Costo promedio ponderado global por producto: cada compra recalcula con el stock total de todas las sucursales (redondeo a centavos, mitad hacia arriba) y deja el cambio en `historial_productos`. Salidas y traslados valoran al costo vigente; un traslado no cambia el costo. Recalcular el costo no exige `productos.precios` (se deriva de una compra autorizada).
- Compras y traslados son atómicos por sí mismos (savepoint): si algo falla no queda nada a medias. Para que los savepoints funcionen, `crear_motor` aplica en SQLite la receta oficial de SQLAlchemy (BEGIN explícito).
- Permisos: `ver` consulta existencias, kardex, proveedores y sucursales; `crear` hace compras, mermas, traslados y crea proveedores y sucursales; `editar` hace ajustes de stock y desactiva proveedores; `exportar` genera los CSV. Vendedor y contador solo consultan; el bodeguero opera todo.
- Merma y ajuste exigen motivo. El ajuste recibe el conteo físico y registra la diferencia. Alerta de stock bajo: `stock_minimo > 0` y `stock <= stock_minimo` (por sucursal o total).
- `verificar_consistencia(sesion)` compara cada existencia con la suma de sus movimientos y con el último saldo; vacía = todo cuadra. Conviene llamarla desde `--salud` en la Fase 6.
- Pendientes conscientes: no hay anulación de compras (se corrige con un ajuste); no hay stock negativo diferido; los usuarios no están limitados a una sucursal (cualquiera con permiso opera cualquier sucursal activa).
- `seed.py` registra una compra inicial de ejemplo (9 productos en la sucursal Principal; SNK-002 queda en alerta) solo si no hay compras.

## Dependencias

SQLAlchemy 2.0.36, alembic 1.14.0, customtkinter 5.2.2, python-dotenv 1.0.1, argon2-cffi 23.1.0, pytest 8.3.4.

## Estado de pruebas

- Fases 0 y 1: pasaron en GitHub Actions. Fase 2 unida a `main` (PR #2).
- Fase 3: `tests/test_fase3.py` escrita (unas 35 pruebas); el código compila. **No se pudo ejecutar en la sesión de construcción** (PyPI bloqueado). Correr "Run workflow" en Actions sobre la rama `fase-3-inventario-kardex`.
- Riesgo a vigilar en esa corrida: el cambio de `crear_motor` (BEGIN explícito en SQLite) toca también las migraciones y las pruebas anteriores.
- Las pantallas de CustomTkinter no tienen pruebas automáticas: hay que probarlas a mano (login, menú, usuarios, permisos, bitácora, productos, inventario).

## Nota

Existen archivos que no escribí y que nada importa: `app/servicios/catalogo_permisos.py`, `app/errores.py` y `app/utiles.py` (fecha 13:08-13:09 del 2026-10-19, en la carpeta de trabajo de la sesión `inventario/`, no en el repositorio). Definen alternativas a errores, utilidades y catálogo de permisos que ya existen. No se subieron. Decidir si se adopta algo o se descartan.

## Fases planificadas

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Cimientos | Validada en GitHub Actions |
| 1 | Usuarios, roles, permisos por módulo, login, bitácora | Validada y unida a `main` |
| 2 | Catálogo de productos e historial de precios | Unida a `main` (PR #2) |
| 3 | Inventario, compras, kardex, alertas de stock mínimo, traslados entre sucursales | Código subido a rama, pruebas por correr |
| 4 | Ventas (POS), anulaciones, comprobante | Pendiente |
| 5 | Histórico y reportes | Pendiente |
| 6 | Pulido, respaldos, empaquetado, guía de GitHub | Pendiente |

## Siguiente paso

Fase 4: ventas (POS): venta con líneas, precio y costo congelados, descuento, método de pago, vendedor tomado de la sesión, búsqueda por código de barras (`obtener_por_codigo`), descuento de stock atómico con `aplicar_movimiento`, anulación con motivo que revierte stock (tipo `anulacion`) y comprobante imprimible.
