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
- Ventas: `ventas.ver` = solo las propias; `ventas.ver_todas` = las de todos los vendedores (contador y administrador). Reportes (Fase 5) seguirán la misma idea.

## Esquema activo (migraciones `0001` a `0005`)

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
- `clientes` (nombre, teléfono, correo, activo)
- `ventas` (número único, sucursal, vendedor, cliente, método de pago, subtotal, descuento, total, estado, nota, fecha; anulación: usuario, fecha, motivo) y `ventas_detalle` (cantidad, **precio y costo congelados**, descuento de línea)

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

## Ventas (Fase 4)

- `registrar_venta` valida todo primero y luego, dentro de un savepoint, asigna número consecutivo (`V-000001`), descuenta stock con `aplicar_movimiento` (tipo `salida`) y guarda la venta: o queda todo o nada. El vendedor es siempre el usuario de la sesión; el precio y el costo salen del producto y se congelan en el detalle (cambiar el precio después no altera ventas hechas). Descuentos son montos en dinero (por línea y general), nunca mayores al importe.
- `anular_venta` (permiso `ventas.anular`, motivo obligatorio): marca la venta, devuelve el stock con movimientos `anulacion` al costo original y guarda quién, cuándo y por qué. No se anula dos veces.
- Comprobante (`servicios/comprobante.py`): texto de 44 columnas y HTML escapado; el botón «Imprimir» lo abre en el navegador para imprimir con Ctrl+P.
- Pantalla de caja: lector de código de barras (envía el código + Enter), búsqueda por nombre/SKU, carrito, cliente, forma de pago, descuento; pestaña Historial con anulación.
- Actualizar una instalación existente: `sembrar_permisos_y_roles` (lo ejecuta `seed.py`) crea `ventas.ver_todas` y se lo da al contador sin quitar personalizaciones. Para que el administrador lo reciba basta con correr `python seed.py` tras migrar.
- Eventos auditados nuevos: `cliente_creado`, `venta_registrada`, `venta_anulada`.
- Pendientes conscientes: no hay devoluciones parciales (se anula la venta completa y se vuelve a vender); no hay pagos mixtos ni cálculo de cambio; el número de venta es global (no por sucursal). En SQLite, dos cajas en el mismo archivo pueden recibir «database is locked» bajo carga; el stock nunca se sobrevende. Para varias cajas reales conviene PostgreSQL (`DATABASE_URL`).
- Se descartó (sin poder probarlo) usar `BEGIN IMMEDIATE` en SQLite: bloquearía a cualquier sesión abierta, incluso solo de lectura.

## Reportes (Fase 5)

- `servicios/reportes.py`: `resumen_ventas`, `ventas_agrupadas` (por día, vendedor, producto, categoría o sucursal), `inventario_valorizado` y exportaciones CSV (`exportar_ventas_agrupadas_csv`, `exportar_detalle_ventas_csv`, `exportar_valorizado_csv`).
- Permisos: `reportes.ver` para consultar, `reportes.exportar` para el CSV. Quien solo tiene `ventas.ver` (vendedor) ve únicamente sus ventas y **no recibe costos ni utilidad** (llegan como `None`). Con `ventas.ver_todas` (contador, administrador) se ve todo. Sin permiso de ventas (bodeguero) los reportes de ventas dan 403.
- Solo cuentan ventas completadas; las anuladas se informan aparte (cantidad y monto).
- Ingreso por línea = precio × cantidad − descuento de línea − parte proporcional del descuento general (repartido al centavo). Así todas las agrupaciones suman exactamente el total de las ventas.
- Utilidad bruta = ingreso − costo congelado al vender. Margen % = utilidad / ingreso.
- Fechas: se guardan en UTC; la pantalla usa días del calendario local (`rango_local`) y agrupa por día local.
- CSV: se neutralizan textos que empiezan con `=`, `+`, `-` o `@` (inyección de fórmulas en Excel). Cada exportación queda en la bitácora (`reporte_exportado`).
- Límite consciente: se agrega en Python sobre las líneas del periodo (bien hasta decenas de miles de líneas); para más volumen conviene pasar la agregación a SQL. El inventario valorizado lo ve quien tenga `reportes.ver` e `inventario.ver` (el vendedor ya ve costos en la pantalla de inventario; se revisa en la Fase 6).
- No hay gráficos todavía: tablas y totales. Se evalúan en la fase de interfaz.

## Dependencias

SQLAlchemy 2.0.36, alembic 1.14.0, customtkinter 5.2.2, python-dotenv 1.0.1, argon2-cffi 23.1.0, pytest 8.3.4.

## Estado de pruebas

- Fases 0 y 1: pasaron en GitHub Actions. Fase 2 unida a `main` (PR #2).
- Fase 3: `tests/test_fase3.py` escrita (unas 35 pruebas); el código compila. **No se pudo ejecutar en la sesión de construcción** (PyPI bloqueado). Correr "Run workflow" en Actions sobre la rama `fase-3-inventario-kardex`.
- Riesgo a vigilar en esa corrida: el cambio de `crear_motor` (BEGIN explícito en SQLite) toca también las migraciones y las pruebas anteriores.
- Fase 4: `tests/test_fase4.py` escrita (unas 40 pruebas con casos); el código compila. **No se pudo ejecutar en la sesión de construcción**. Correr "Run workflow" en Actions sobre la rama `fase-4-ventas`.
- Fase 4: unida a `main` (PR #4), pruebas en verde.
- Fase 5: `tests/test_fase5.py` escrita (unas 25 pruebas); el código compila. **No se pudo ejecutar en la sesión de construcción**. Correr "Run workflow" en Actions sobre la rama `fase-5-reportes`.
- Las pantallas de CustomTkinter no tienen pruebas automáticas: hay que probarlas a mano (login, menú, usuarios, permisos, bitácora, productos, inventario, caja, historial de ventas y reportes).

## Fases planificadas

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Cimientos | Validada en GitHub Actions |
| 1 | Usuarios, roles, permisos por módulo, login, bitácora | Validada y unida a `main` |
| 2 | Catálogo de productos e historial de precios | Unida a `main` (PR #2) |
| 3 | Inventario, compras, kardex, alertas de stock mínimo, traslados entre sucursales | Unida a `main` (PR #3) |
| 4 | Ventas (POS), anulaciones, comprobante | Unida a `main` (PR #4) |
| 5 | Histórico y reportes | Código subido a rama, pruebas por correr |
| 5.5 | Interfaz: diseño visual, tablas, tarjetas, caja cómoda | Pendiente (acordada) |
| 6 | Pulido, respaldos, empaquetado, guía de GitHub | Pendiente |

## Siguiente paso

Fase de interfaz (acordada con el usuario, antes del pulido final): paleta y tipografía coherentes, tablas más legibles, tarjetas de totales en el inicio, iconos en el menú, caja cómoda (letra grande, atajos de teclado). Preguntar: colores o logo del negocio, tema claro u oscuro, pantalla táctil o teclado con lector.

Después, Fase 6: validaciones, paginación, respaldos, Dockerfile, README completo, guía de GitHub, revisión de seguridad y `verificar_consistencia` en `--salud`.
