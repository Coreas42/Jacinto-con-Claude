"""Modelos de la base de datos.

Importar aquí cada módulo de modelos nuevo para que Alembic los detecte.
"""

from app.modelos.base_sistema import Configuracion, Sucursal  # noqa: F401
from app.modelos.seguridad import (  # noqa: F401
    BitacoraAuditoria,
    Permiso,
    Rol,
    Usuario,
    UsuarioPermiso,
    roles_permisos,
)
