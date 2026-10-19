# PROGRESO

**Fase actual:** 1 (Usuarios, roles y permisos) — código entregado; pruebas pendientes de correr en GitHub Actions.
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

## Esquema activo (migraciones `0001` y `0002`)

- `sucursales`, `configuracion`
- `roles`, `permisos` (módulo + acción, único), `roles_permisos`
- `usuarios` (correo único, hash argon2, rol, activo, último acceso)
- `usuarios_permisos` (excepción individual: concedido sí/no sobre el rol)
- `bitacora_auditoria` (usuario, acción, entidad, detalle JSON, fecha; solo se agregan registros)

## Permisos por módulo

Catálogo en `app/servicios/permisos.py` (`CATALOGO` y `MATRIZ_BASE`). Toda función de servicio sensible llama a `exigir_permiso`, que lanza `PermisoDenegado` (403). El menú solo muestra módulos con algún permiso efectivo.

Eventos auditados: `login`, `login_fallido`, `logout`, `usuario_creado`, `rol_cambiado`, `usuario_activado/desactivado`, `permiso_individual_cambiado`, `contrasena_cambiada/restablecida`.

## Dependencias

SQLAlchemy 2.0.36, alembic 1.14.0, customtkinter 5.2.2, python-dotenv 1.0.1, argon2-cffi 23.1.0, pytest 8.3.4.

## Estado de pruebas

- Fase 0: 8 pruebas pasaron en GitHub Actions (ejecución manual del usuario).
- Fase 1: `tests/test_fase1.py` y `tests/test_seed.py` escritas; el código compila y los imports internos resuelven. **No se pudieron ejecutar en la sesión de construcción** (PyPI bloqueado). Correr "Run workflow" en GitHub Actions o `pytest` local.
- Las pantallas de CustomTkinter no tienen pruebas automáticas: hay que probarlas a mano (login, menú, usuarios, permisos, bitácora).

## Nota

Existe `app/servicios/catalogo_permisos.py`, un archivo que no escribí en esta fase (fecha 13:09) y que nada importa; define un catálogo alternativo con la acción `ver_propias`. Se dejó intacto y fuera del .zip. Decidir si se adopta o se borra.

## Fases planificadas

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Cimientos | Validada en GitHub Actions |
| 1 | Usuarios, roles, permisos por módulo, login, bitácora | Código entregado, pruebas por correr |
| 2 | Catálogo de productos e historial de precios | Pendiente |
| 3 | Inventario, compras, kardex, alertas de stock mínimo, traslados entre sucursales | Pendiente |
| 4 | Ventas (POS), anulaciones, comprobante | Pendiente |
| 5 | Histórico y reportes | Pendiente |
| 6 | Pulido, respaldos, empaquetado, guía de GitHub | Pendiente |

## Siguiente paso

Fase 2: catálogo de productos (categorías, SKU/código de barras, costo, precio, stock mínimo, historial de cambios de precio).
