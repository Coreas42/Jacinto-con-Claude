"""Capas de costo (PEPS): un lote por cada entrada de stock

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capas_costo",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("producto_id", sa.Integer(), nullable=False),
        sa.Column("sucursal_id", sa.Integer(), nullable=False),
        sa.Column("cantidad_inicial", sa.Integer(), nullable=False),
        sa.Column("cantidad_restante", sa.Integer(), nullable=False),
        sa.Column("costo_unitario", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("origen", sa.String(length=20), nullable=False),
        sa.Column("referencia_tipo", sa.String(length=20), nullable=True),
        sa.Column("referencia_id", sa.Integer(), nullable=True),
        sa.Column("creada_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("cantidad_inicial > 0", name=op.f("ck_capas_costo_cantidad_inicial_positiva")),
        sa.CheckConstraint("cantidad_restante >= 0", name=op.f("ck_capas_costo_cantidad_restante_no_negativa")),
        sa.ForeignKeyConstraint(["producto_id"], ["productos.id"], name=op.f("fk_capas_costo_producto_id_productos")),
        sa.ForeignKeyConstraint(["sucursal_id"], ["sucursales.id"], name=op.f("fk_capas_costo_sucursal_id_sucursales")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capas_costo")),
    )
    op.create_index(op.f("ix_capas_costo_producto_id"), "capas_costo", ["producto_id"])
    # El stock que ya existe pasa a una capa inicial por producto y sucursal, al costo promedio vigente.
    op.execute(
        """
        INSERT INTO capas_costo
            (producto_id, sucursal_id, cantidad_inicial, cantidad_restante, costo_unitario, origen, creada_en)
        SELECT e.producto_id, e.sucursal_id, e.cantidad, e.cantidad, p.costo_promedio, 'inicial', CURRENT_TIMESTAMP
        FROM existencias e JOIN productos p ON p.id = e.producto_id
        WHERE e.cantidad > 0
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_capas_costo_producto_id"), table_name="capas_costo")
    op.drop_table("capas_costo")
