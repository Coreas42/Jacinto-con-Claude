# PROGRESO

**Fase actual:** 0 (Diagnóstico y cimientos) — código entregado, **pruebas pendientes de ejecutar** (ver "Estado de pruebas").
**Fecha:** 2026-10-19

## Diagnóstico acordado

| Tema | Decisión |
|---|---|
| Catálogo | Productos simples: SKU/código de barras, categoría, precio, costo, stock mínimo. Sin lotes ni caducidad. |
| Alcance | POS (venta de mostrador), compras a proveedores, alertas de stock mínimo, **varias sucursales**. |
| Interfaz | Escritorio nativo: CustomTkinter + SQLite. |
| Roles | Administrador, Bodeguero, Vendedor/Cajero, Contador. |

## Supuestos (ajustables)

- Python 3.11+, SQLAlchemy 2 + Alembic. SQLite por defecto; `DATABASE_URL` permite pasar a PostgreSQL sin tocar los modelos.
- Interfaz en CustomTkinter, pero las reglas de negocio viven en `app/servicios/`, sin depender de la ventana.
- Costeo: promedio ponderado (cambiable a PEPS en la Fase 3 si se prefiere).
- Stock negativo bloqueado por defecto.
- Dinero en `Numeric(12, 2)`/`Decimal`, nunca `float`.
- Multi-sucursal: existencias, movimientos y ventas llevarán `sucursal_id` desde su primera migración.
- Nombres de tablas, modelos y rutas en español.

## Esquema activo (migración `0001`)

- `sucursales`: id, nombre (único), direccion, activa, creada_en
- `configuracion`: clave, valor, descripcion

## Esquema planificado

Ver `modelo-datos` de crearp: usuarios, roles, permisos, bitácora (Fase 1); categorías, productos, historial de precios (Fase 2); proveedores, compras, movimientos_inventario, existencias por sucursal (Fase 3); clientes, ventas, ventas_detalle (Fase 4).

## Dependencias

SQLAlchemy 2.0.36, alembic 1.14.0, customtkinter 5.2.2, python-dotenv 1.0.1, pytest 8.3.4 (ver `requirements.txt`).

## Estado de pruebas

- Compilación de todo el código (`compileall`): OK.
- `pytest` (8 pruebas en `tests/test_fase0.py`): **no se pudo ejecutar en la sesión de construcción** porque el entorno bloqueó el acceso a PyPI (403) y no se pudieron instalar las dependencias. Ejecutar `pytest` localmente (ver README) y reportar cualquier fallo para corregirlo en la Fase 1.

## Fases planificadas

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Cimientos: estructura, config, BD, migración inicial, salud | Código entregado, pruebas por ejecutar |
| 1 | Usuarios, roles, permisos por módulo, login, bitácora | Pendiente |
| 2 | Catálogo de productos e historial de precios | Pendiente |
| 3 | Inventario, compras, kardex, alertas de stock mínimo, traslados entre sucursales | Pendiente |
| 4 | Ventas (POS), anulaciones, comprobante | Pendiente |
| 5 | Histórico y reportes | Pendiente |
| 6 | Pulido, respaldos, empaquetado (ejecutable), guía de GitHub | Pendiente |

## Siguiente paso

Fase 1: usuarios, roles y permisos (con pantalla de login en CustomTkinter).
