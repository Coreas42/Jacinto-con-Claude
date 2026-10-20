"""Inventario: proveedores, existencias, kardex, compras y traslados

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proveedores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("contacto", sa.String(length=200), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proveedores")),
        sa.UniqueConstraint("nombre", name=op.f("uq_proveedores_nombre")),
    )
    op.create_table(
        "existencias",
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("cantidad >= 0", name=op.f("ck_existencias_cantidad_no_negativa")),
        sa.ForeignKeyConstraint(
            ["producto_id"], ["productos.id"], name=op.f("fk_existencias_producto_id_productos")
        ),
        sa.ForeignKeyConstraint(
            ["sucursal_id"], ["sucursales.id"], name=op.f("fk_existencias_sucursal_id_sucursales")
        ),
        sa.PrimaryKeyConstraint("producto_id", "sucursal_id", name=op.f("pk_existencias")),
    )
    op.create_table(
        "movimientos_inventario",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("tipo", sa.String(length=20), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("saldo_despues", sa.Integer(), nullable=False),
        sa.Column("costo_unitario", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("motivo", sa.String(length=200), nullable=True),
        sa.Column("referencia_tipo", sa.String(length=30), nullable=True),
        sa.Column("referencia_id", sa.Integer(), nullable=True),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("creado_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("cantidad <> 0", name=op.f("ck_movimientos_inventario_cantidad_distinta_de_cero")),
        sa.ForeignKeyConstraint(
            ["producto_id"], ["productos.id"], name=op.f("fk_movimientos_inventario_producto_id_productos")
        ),
        sa.ForeignKeyConstraint(
            ["sucursal_id"], ["sucursales.id"], name=op.f("fk_movimientos_inventario_sucursal_id_sucursales")
        ),
        sa.ForeignKeyConstraint(
            ["usuario_id"], ["usuarios.id"], name=op.f("fk_movimientos_inventario_usuario_id_usuarios")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_movimientos_inventario")),
    )
    op.create_index(
        op.f("ix_movimientos_inventario_producto_id"), "movimientos_inventario", ["producto_id"]
    )
    op.create_table(
        "compras",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proveedor_id", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("nota", sa.String(length=200), nullable=True),
        sa.Column("total", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
        sa.Column("estado", sa.String(length=20), server_default="completada", nullable=False),
        sa.Column("creado_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["proveedor_id"], ["proveedores.id"], name=op.f("fk_compras_proveedor_id_proveedores")
        ),
        sa.ForeignKeyConstraint(
            ["sucursal_id"], ["sucursales.id"], name=op.f("fk_compras_sucursal_id_sucursales")
        ),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], name=op.f("fk_compras_usuario_id_usuarios")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compras")),
    )
    op.create_table(
        "compras_detalle",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("compra_id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("costo_unitario", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.ForeignKeyConstraint(
            ["compra_id"], ["compras.id"], name=op.f("fk_compras_detalle_compra_id_compras")
        ),
        sa.ForeignKeyConstraint(
            ["producto_id"], ["productos.id"], name=op.f("fk_compras_detalle_producto_id_productos")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compras_detalle")),
    )
    op.create_table(
        "traslados",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("origen_id", sa.Integer(), nullable=False),
        sa.Column("destino_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("nota", sa.String(length=200), nullable=True),
        sa.Column("creado_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("origen_id <> destino_id", name=op.f("ck_traslados_origen_distinto_de_destino")),
        sa.ForeignKeyConstraint(
            ["producto_id"], ["productos.id"], name=op.f("fk_traslados_producto_id_productos")
        ),
        sa.ForeignKeyConstraint(
            ["origen_id"], ["sucursales.id"], name=op.f("fk_traslados_origen_id_sucursales")
        ),
        sa.ForeignKeyConstraint(
            ["destino_id"], ["sucursales.id"], name=op.f("fk_traslados_destino_id_sucursales")
        ),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], name=op.f("fk_traslados_usuario_id_usuarios")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_traslados")),
    )


def downgrade() -> None:
    op.drop_table("traslados")
    op.drop_table("compras_detalle")
    op.drop_table("compras")
    op.drop_index(op.f("ix_movimientos_inventario_producto_id"), table_name="movimientos_inventario")
    op.drop_table("movimientos_inventario")
    op.drop_table("existencias")
    op.drop_table("proveedores")
