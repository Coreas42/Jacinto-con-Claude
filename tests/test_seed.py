"""Pruebas de seed.py."""

from sqlalchemy import func, select

from app.db import crear_fabrica_sesiones
from app.modelos import Sucursal, Usuario
from app.servicios.autenticacion import iniciar_sesion
from seed import sembrar


def test_seed_crea_admin_roles_y_sucursal_una_sola_vez(motor):
    fabrica = crear_fabrica_sesiones(motor)
    with fabrica() as sesion:
        creado = sembrar(sesion, "Admin", "Admin@Ejemplo.com", "claveSegura1")
        sesion.commit()
        assert creado is not None
        assert creado.correo == "admin@ejemplo.com"

        repetido = sembrar(sesion, "Admin", "admin@ejemplo.com", "otraClave99")
        sesion.commit()
        assert repetido is None
        assert sesion.scalar(select(func.count()).select_from(Usuario)) == 1
        assert sesion.scalar(select(func.count()).select_from(Sucursal)) == 1

        # la contraseña original sigue funcionando: el seed no pisa lo existente
        assert iniciar_sesion(sesion, "admin@ejemplo.com", "claveSegura1").id == creado.id


def test_seed_sin_ejemplos_no_crea_productos_ni_compras(motor):
    from app.modelos import Producto

    fabrica = crear_fabrica_sesiones(motor)
    with fabrica() as sesion:
        sembrar(sesion, "Admin", "a@x.com", "claveSegura1", con_ejemplos=False)
        sesion.commit()
        assert sesion.scalar(select(func.count()).select_from(Producto)) == 0
