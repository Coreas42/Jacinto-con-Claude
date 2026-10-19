# PROGRESO

**Fase actual:** 2 (Catálogo de productos) — código subido a la rama `fase-2-catalogo-productos`; pruebas pendientes de correr en GitHub Actions.
**Fecha:** 2026-10-19

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
- Costeo: promedio ponderado (cambiable a PEPS en la Fase 3). Stock negativo bloqueado. Dinero en `Decimal`.
- Multi-sucursal: existencias, movimientos y ventas llevarán `sucursal_id` desde su primera migración.
- Contraseñas con argon2, mínimo 8 caracteres.
- Un usuario no puede cambiar su propio rol, desactivarse ni editar sus propios permisos (evita quedarse sin administrador).
- El rol "vendedor" ve solo sus propias ventas/reportes: se aplica al consultar datos en las Fases 4 y 5 (el permiso base es `ver`).

## Esquema activo (migraciones `0001`, `0002` y `0003`)

- `sucursales`, `configuracion`
- `roles`, `permisos` (módulo + acción, único), `roles_permisos`
- `usuarios` (correo único, hash argon2, rol, activo, último acceso)
- `usuarios_permisos` (excepción individual: concedido sí/no sobre el rol)
- `bitacora_auditoria` (usuario, acción, entidad, detalle JSON, fecha; solo se agregan registros)
- `categorias` (nombre único, activa)
- `productos` (sku único, código de barras único opcional, nombre, descripción, categoría, marca, costo_promedio, precio, stock_minimo, activo). **Sin columna de stock**: las existencias llegan en la Fase 3 y solo cambian por movimientos.
- `historial_productos` (producto, campo, valor anterior, valor nuevo, usuario, fecha; solo se agregan filas)

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
- `costo_promedio` se fija a mano en esta fase; desde la Fase 3 lo recalcularán las compras.
- `seed.py` carga 4 categorías y 9 productos de ejemplo solo si no hay productos.

## Dependencias

SQLAlchemy 2.0.36, alembic 1.14.0, customtkinter 5.2.2, python-dotenv 1.0.1, argon2-cffi 23.1.0, pytest 8.3.4.

## Estado de pruebas

- Fase 0 y Fase 1: pasaron en GitHub Actions (ejecución manual del usuario). Fase 1 unida a `main` (PR #1).
- Fase 2: `tests/test_fase2.py` escrita; el código compila. **No se pudo ejecutar en la sesión de construcción** (PyPI bloqueado). Correr "Run workflow" en Actions sobre la rama `fase-2-catalogo-productos`.
- Las pantallas de CustomTkinter no tienen pruebas automáticas: hay que probarlas a mano (login, menú, usuarios, permisos, bitácora, productos).

## Nota

Existen archivos que no escribí y que nada importa: `app/servicios/catalogo_permisos.py`, `app/errores.py` y `app/utiles.py` (fecha 13:08-13:09 del 2026-10-19, en la carpeta de trabajo de la sesión, no en el repositorio). Definen alternativas a errores, utilidades y catálogo de permisos que ya existen. No se subieron. Decidir si se adopta algo o se descartan.

## Fases planificadas

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Cimientos | Validada en GitHub Actions |
| 1 | Usuarios, roles, permisos por módulo, login, bitácora | Validada y unida a `main` |
| 2 | Catálogo de productos e historial de precios | Código subido a rama, pruebas por correr |
| 3 | Inventario, compras, kardex, alertas de stock mínimo, traslados entre sucursales | Pendiente |
| 4 | Ventas (POS), anulaciones, comprobante | Pendiente |
| 5 | Histórico y reportes | Pendiente |
| 6 | Pulido, respaldos, empaquetado, guía de GitHub | Pendiente |

## Siguiente paso

Fase 3: inventario y kardex (movimientos, compras, existencias por sucursal, costo promedio ponderado, alertas de stock mínimo, traslados entre sucursales).
