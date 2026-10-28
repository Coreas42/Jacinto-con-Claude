"""Pagos mixtos y devoluciones parciales

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-28
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ventas_pagos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venta_id", sa.Integer(), nullable=False),
        sa.Column("metodo", sa.String(length=20), nullable=False),
        sa.Column("monto", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("recibido", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.CheckConstraint("monto >= 0", name=op.f("ck_ventas_pagos_monto_no_negativo")),
        sa.ForeignKeyConstraint(["venta_id"], ["ventas.id"], name=op.f("fk_ventas_pagos_venta_id_ventas")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ventas_pagos")),
    )
    op.create_index(op.f("ix_ventas_pagos_venta_id"), "ventas_pagos", ["venta_id"])
    op.create_table(
        "devoluciones",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venta_id", sa.Integer(), nullable=False),
        sa.Column("usuario_id", sa.Integer(), nullable=False),
        sa.Column("motivo", sa.String(length=200), nullable=False),
        sa.Column("metodo_reembolso", sa.String(length=20), nullable=False),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("creado_en", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["venta_id"], ["ventas.id"], name=op.f("fk_devoluciones_venta_id_ventas")),
        sa.ForeignKeyConstraint(["usuario_id"], ["usuarios.id"], name=op.f("fk_devoluciones_usuario_id_usuarios")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devoluciones")),
    )
    op.create_index(op.f("ix_devoluciones_venta_id"), "devoluciones", ["venta_id"])
    op.create_index(op.f("ix_devoluciones_creado_en"), "devoluciones", ["creado_en"])
    op.create_table(
        "devoluciones_detalle",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("devolucion_id", sa.Integer(), nullable=False),
        sa.Column("detalle_id", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Integer(), nullable=False),
        sa.Column("monto", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("costo_unitario", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.CheckConstraint("cantidad > 0", name=op.f("ck_devoluciones_detalle_cantidad_devuelta_positiva")),
        sa.ForeignKeyConstraint(
            ["devolucion_id"], ["devoluciones.id"], name=op.f("fk_devoluciones_detalle_devolucion_id_devoluciones")
        ),
        sa.ForeignKeyConstraint(
            ["detalle_id"], ["ventas_detalle.id"], name=op.f("fk_devoluciones_detalle_detalle_id_ventas_detalle")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_devoluciones_detalle")),
    )
    op.create_index(op.f("ix_devoluciones_detalle_devolucion_id"), "devoluciones_detalle", ["devolucion_id"])
    op.create_index(op.f("ix_devoluciones_detalle_detalle_id"), "devoluciones_detalle", ["detalle_id"])


def downgrade() -> None:
    op.drop_table("devoluciones_detalle")
    op.drop_table("devoluciones")
    op.drop_table("ventas_pagos")
