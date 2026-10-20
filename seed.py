"""Datos iniciales: permisos, roles, una sucursal y el primer administrador.

Uso:
    python seed.py

Variables opcionales (también se leen del archivo .env):
    ADMIN_NOMBRE       nombre del administrador (por defecto "Administrador")
    ADMIN_CORREO       correo de acceso (por defecto "admin@ejemplo.com")
    ADMIN_CONTRASENA   contraseña; si no se define, se pide por consola y, si se
                       deja vacía, se genera una aleatoria y se muestra una sola vez.

Se puede ejecutar varias veces: no duplica ni modifica lo que ya existe.
"""

from __future__ import annotations

import getpass
import os
import secrets
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import crear_fabrica_sesiones, crear_motor, sesion_transaccional
from app.migraciones import migrar_a_ultima
from app.modelos import Categoria, Compra, Producto, Proveedor, Sucursal, Usuario
from app.servicios.catalogo import crear_categoria, crear_producto
from app.servicios.inventario import crear_proveedor, registrar_compra
from app.servicios.permisos import sembrar_permisos_y_roles
from app.servicios.usuarios import crear_administrador_inicial


CATEGORIAS_EJEMPLO = ["Bebidas", "Snacks", "Limpieza", "Papelería"]

# (sku, nombre, categoría, costo, precio, stock mínimo, código de barras)
PRODUCTOS_EJEMPLO = [
    ("BEB-001", "Agua purificada 600 ml", "Bebidas", "0.35", "0.60", 24, "7500000000011"),
    ("BEB-002", "Gaseosa cola 500 ml", "Bebidas", "0.50", "0.90", 24, "7500000000028"),
    ("BEB-003", "Jugo de naranja 1 L", "Bebidas", "0.95", "1.50", 12, "7500000000035"),
    ("SNK-001", "Papas fritas 45 g", "Snacks", "0.40", "0.75", 20, "7500000000042"),
    ("SNK-002", "Galletas de chocolate", "Snacks", "0.55", "1.00", 20, "7500000000059"),
    ("LIM-001", "Detergente en polvo 1 kg", "Limpieza", "1.80", "2.75", 10, "7500000000066"),
    ("LIM-002", "Jabón de baño", "Limpieza", "0.45", "0.85", 15, "7500000000073"),
    ("PAP-001", "Cuaderno rayado 100 hojas", "Papelería", "0.90", "1.60", 10, "7500000000080"),
    ("PAP-002", "Lapicero azul", "Papelería", "0.15", "0.35", 30, "7500000000097"),
]


def sembrar_catalogo_ejemplo(sesion: Session, actor: Usuario) -> int:
    """Crea categorías y productos de ejemplo solo si todavía no hay productos."""
    if sesion.scalar(select(Producto.id).limit(1)) is not None:
        return 0
    categorias = {c.nombre: c for c in sesion.scalars(select(Categoria))}
    for nombre in CATEGORIAS_EJEMPLO:
        if nombre not in categorias:
            categorias[nombre] = crear_categoria(sesion, actor, nombre)
    for sku, nombre, categoria, costo, precio, minimo, barras in PRODUCTOS_EJEMPLO:
        crear_producto(
            sesion,
            actor,
            sku=sku,
            nombre=nombre,
            categoria_id=categorias[categoria].id,
            precio=precio,
            costo=costo,
            stock_minimo=minimo,
            codigo_barras=barras,
        )
    return len(PRODUCTOS_EJEMPLO)


# Existencias iniciales de ejemplo. SNK-002 queda por debajo de su mínimo (20) para mostrar la alerta.
STOCK_INICIAL_EJEMPLO = {
    "BEB-001": 60, "BEB-002": 48, "BEB-003": 24, "SNK-001": 40, "SNK-002": 15,
    "LIM-001": 12, "LIM-002": 30, "PAP-001": 20, "PAP-002": 100,
}


def sembrar_inventario_ejemplo(sesion: Session, actor: Usuario) -> bool:
    """Registra una compra inicial con stock de ejemplo, solo si aún no hay compras."""
    if sesion.scalar(select(Compra.id).limit(1)) is not None:
        return False
    sucursal = sesion.scalar(select(Sucursal).order_by(Sucursal.id))
    productos = list(sesion.scalars(select(Producto).where(Producto.sku.in_(STOCK_INICIAL_EJEMPLO))))
    if sucursal is None or not productos:
        return False
    proveedor = sesion.scalar(select(Proveedor).where(Proveedor.nombre == "Distribuidora Central"))
    if proveedor is None:
        proveedor = crear_proveedor(sesion, actor, "Distribuidora Central", "Proveedor de ejemplo")
    registrar_compra(
        sesion,
        actor,
        sucursal_id=sucursal.id,
        proveedor_id=proveedor.id,
        lineas=[
            {"producto_id": p.id, "cantidad": STOCK_INICIAL_EJEMPLO[p.sku], "costo_unitario": p.costo_promedio}
            for p in productos
        ],
        nota="Stock inicial de ejemplo",
    )
    return True


def sembrar(sesion: Session, nombre: str, correo: str, clave: str) -> Usuario | None:
    """Siembra lo básico. Devuelve el administrador creado, o ``None`` si ya existía."""
    sembrar_permisos_y_roles(sesion)

    if sesion.scalar(select(Sucursal.id).limit(1)) is None:
        sesion.add(Sucursal(nombre="Principal"))

    correo = correo.strip().lower()
    admin = sesion.scalar(select(Usuario).where(Usuario.correo == correo))
    creado = None
    if admin is None:
        admin = creado = crear_administrador_inicial(sesion, nombre, correo, clave)
    sembrar_catalogo_ejemplo(sesion, admin)
    sembrar_inventario_ejemplo(sesion, admin)
    return creado


def _obtener_clave() -> tuple[str, bool]:
    """Devuelve (clave, fue_generada)."""
    clave = os.getenv("ADMIN_CONTRASENA", "")
    if not clave and sys.stdin.isatty():
        clave = getpass.getpass("Contraseña del administrador (Enter para generar una): ")
    if clave:
        return clave, False
    return secrets.token_urlsafe(12), True


def main() -> int:
    from app.config import cargar_configuracion  # noqa: F401  (carga .env)

    migrar_a_ultima()
    nombre = os.getenv("ADMIN_NOMBRE", "Administrador")
    correo = os.getenv("ADMIN_CORREO", "admin@ejemplo.com")
    clave, generada = _obtener_clave()

    motor = crear_motor()
    fabrica = crear_fabrica_sesiones(motor)
    with sesion_transaccional(fabrica) as sesion:
        admin = sembrar(sesion, nombre, correo, clave)

    if admin is None:
        print(f"Permisos y roles al día. El administrador {correo} ya existía; no se modificó.")
        return 0

    print(f"Administrador creado: {correo}")
    if generada:
        print(f"Contraseña generada (guárdala, no se vuelve a mostrar): {clave}")
    print("IMPORTANTE: cambia esta contraseña después del primer ingreso.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
