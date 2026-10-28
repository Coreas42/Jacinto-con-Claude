"""Modelos de la base de datos.

Importar aquí cada módulo de modelos nuevo para que Alembic los detecte.
"""

from app.modelos.base_sistema import Configuracion, Sucursal  # noqa: F401
from app.modelos.catalogo import Categoria, HistorialProducto, Producto  # noqa: F401
from app.modelos.inventario import (  # noqa: F401
    Compra,
    CompraDetalle,
    Existencia,
    MovimientoInventario,
    Proveedor,
    Traslado,
)
from app.modelos.seguridad import (  # noqa: F401
    BitacoraAuditoria,
    Permiso,
    Rol,
    Usuario,
    UsuarioPermiso,
    roles_permisos,
)
from app.modelos.ventas import (  # noqa: E402,F401
    Cliente,
    Devolucion,
    DevolucionDetalle,
    PagoVenta,
    Venta,
    VentaDetalle,
)
from app.modelos.gastos import Gasto  # noqa: E402,F401
