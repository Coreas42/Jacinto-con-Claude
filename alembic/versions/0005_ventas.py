"""Ventas: clientes, ventas y detalle

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clientes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nombre", sa.String(length=120), nullable=False),
        sa.Column("telefono", sa.String(length=30), nullable=True),
        sa.Column("correo", sa.String(length=150), nullable=True),
        sa.Column("activo", sa.Boolean(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_clientes")),
    )
    op.create_table(
        "ventas",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("numero", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("vendedor_id", sa.Integer(), nullable=False),
        sa.Column("cliente_id", sa.Integer(), nullable=True),
        sa.Column("metodo_pago", sa.String(length=20), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("descuento", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("estado", sa.String(length=20), server_default="completada", nullable=False),
        sa.Column("nota", sa.String(length=200), nullable=True),
        sa.Column("creado_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("anulada_por", sa.Integer(), nullable=True),
        sa.Column("anulada_en", sa.DateTime(), nullable=True),
        sa.Column("motivo_anulacion", sa.String(length=200), nullable=True),
        sa.CheckConstraint("total >= 0", name=op.f("ck_ventas_total_no_negativo")),
        sa.CheckConstraint("descuento >= 0", name=op.f("ck_ventas_descuento_no_negativo")),
        sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"], name=op.f("fk_ventas_sucursal_id_sucursales")),
        sa.ForeignKeyConstraint(["vendedor_id"], ["usuarios.id"], name=op.f("fk_ventas_vendedor_id_usuarios")),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], name=op.f("fk_ventas_cliente_id_clientes")),
        sa.ForeignKeyConstraint(["anulada_por"], ["usuarios.id"], name=op.f("fk_ventas_anulada_por_usuarios")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ventas")),
        sa.UniqueConstraint("numero", name=op.f("uq_ventas_numero")),
    )
    op.create_index(op.f("ix_ventas_vendedor_id"), "ventas", ["vendedor_id"])
    op.create_index(op.f("ix_ventas_creado_en"), "ventas", ["creado_en"])
    op.create_table(
        "ventas_detalle",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venta_id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("precio_unitario", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("costo_unitario", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("descuento_linea", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
        sa.CheckConstraint("cantidad > 0", name=op.f("ck_ventas_detalle_cantidad_positiva")),
        sa.ForeignKeyConstraint(["venta_id"], ["ventas.id"], name=op.f("fk_ventas_detalle_venta_id_ventas")),
        sa.ForeignKeyConstraint(
            ["producto_id"], ["productos.id"], name=op.f("fk_ventas_detalle_producto_id_productos")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ventas_detalle")),
    )


def downgrade() -> None:
    op.drop_table("ventas_detalle")
    op.drop_index(op.f("ix_ventas_creado_en"), table_name="ventas")
    op.drop_index(op.f("ix_ventas_vendedor_id"), table_name="ventas")
    op.drop_table("ventas")
    op.drop_table("clientes")
