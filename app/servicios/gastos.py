"""Gastos del negocio: registro, consulta y anulación.

- ``gastos.crear`` registra; ``gastos.ver`` consulta; ``gastos.anular`` anula (con motivo).
- Un gasto no se edita ni se borra: si hubo un error se anula y se registra de nuevo.
- Los gastos anulados no cuentan en ningún total.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import ahora_utc
from app.modelos import Gasto, Sucursal, Usuario
from app.servicios.auditoria import registrar
from app.servicios.catalogo import a_dinero
from app.servicios.errores import ErrorDeNegocio
from app.servicios.permisos import exigir_permiso

CATEGORIAS = ("alquiler", "servicios", "salarios", "insumos", "transporte", "mantenimiento", "publicidad", "otros")
CERO = Decimal("0.00")


def _texto(valor: Any, campo: str, largo: int) -> str:
    texto = "" if valor is None else str(valor).strip()
    if not texto:
        raise ErrorDeNegocio(f"El campo {campo} es obligatorio.")
    if len(texto) > largo:
        raise ErrorDeNegocio(f"El campo {campo} admite como máximo {largo} caracteres.")
    return texto


def _fecha(valor: Any) -> date:
    if isinstance(valor, datetime):
        valor = valor.date()
    if isinstance(valor, str):
        try:
            valor = date.fromisoformat(valor.strip())
        except ValueError:
            raise ErrorDeNegocio("La fecha no es válida. Usa el formato AAAA-MM-DD.") from None
    if not isinstance(valor, date):
        raise ErrorDeNegocio("La fecha no es válida.")
    return valor


def crear_gasto(
    sesion: Session, actor: Usuario, *, categoria: str, descripcion: str, monto: Any,
    fecha: Any = None, sucursal_id: int | None = None,
) -> Gasto:
    exigir_permiso(sesion, actor, "gastos", "crear")
    categoria = str(categoria or "").strip().lower()
    if categoria not in CATEGORIAS:
        raise ErrorDeNegocio(f"Categoría no válida. Usa: {', '.join(CATEGORIAS)}.")
    monto = a_dinero(monto, "monto")
    if monto <= 0:
        raise ErrorDeNegocio("El monto debe ser mayor que cero.")
    dia = _fecha(fecha) if fecha not in (None, "") else date.today()
    if dia > date.today():
        raise ErrorDeNegocio("La fecha del gasto no puede ser futura.")
    if sucursal_id is not None:
        sucursal = sesion.get(Sucursal, sucursal_id)
        if sucursal is None or not sucursal.activa:
            raise ErrorDeNegocio("La sucursal no existe o está desactivada.")
    gasto = Gasto(
        fecha=dia, categoria=categoria, descripcion=_texto(descripcion, "descripción", 200),
        monto=monto, sucursal_id=sucursal_id, usuario_id=actor.id,
    )
    sesion.add(gasto)
    sesion.flush()
    registrar(
        sesion, "gasto_registrado", usuario_id=actor.id, entidad="gastos", entidad_id=gasto.id,
        detalle={"categoria": categoria, "monto": str(monto), "fecha": dia.isoformat()},
    )
    return gasto


def anular_gasto(sesion: Session, actor: Usuario, gasto_id: int, motivo: str) -> Gasto:
    exigir_permiso(sesion, actor, "gastos", "anular")
    motivo = _texto(motivo, "motivo", 200)
    gasto = sesion.get(Gasto, gasto_id)
    if gasto is None:
        raise ErrorDeNegocio("El gasto no existe.")
    if gasto.estado == "anulado":
        raise ErrorDeNegocio("El gasto ya está anulado.")
    gasto.estado = "anulado"
    gasto.anulado_por = actor.id
    gasto.anulado_en = ahora_utc()
    gasto.motivo_anulacion = motivo
    registrar(
        sesion, "gasto_anulado", usuario_id=actor.id, entidad="gastos", entidad_id=gasto.id,
        detalle={"monto": str(gasto.monto), "motivo": motivo},
    )
    return gasto


def _filtros(desde: date | None, hasta: date | None, categoria: str | None, sucursal_id: int | None) -> list[Any]:
    condiciones: list[Any] = []
    if desde is not None:
        condiciones.append(Gasto.fecha >= desde)
    if hasta is not None:
        condiciones.append(Gasto.fecha <= hasta)
    if categoria:
        condiciones.append(Gasto.categoria == categoria)
    if sucursal_id is not None:
        condiciones.append(Gasto.sucursal_id == sucursal_id)
    return condiciones


def listar_gastos(
    sesion: Session, actor: Usuario, desde: date | None = None, hasta: date | None = None,
    categoria: str | None = None, sucursal_id: int | None = None, incluir_anulados: bool = False,
    limite: int = 500,
) -> list[dict]:
    exigir_permiso(sesion, actor, "gastos", "ver")
    consulta = (
        select(Gasto, Usuario.nombre, Sucursal.nombre)
        .join(Usuario, Usuario.id == Gasto.usuario_id)
        .outerjoin(Sucursal, Sucursal.id == Gasto.sucursal_id)
        .where(*_filtros(desde, hasta, categoria, sucursal_id))
        .order_by(Gasto.fecha.desc(), Gasto.id.desc())
        .limit(limite)
    )
    if not incluir_anulados:
        consulta = consulta.where(Gasto.estado == "activo")
    return [
        {
            "id": g.id, "fecha": g.fecha, "categoria": g.categoria, "descripcion": g.descripcion,
            "monto": g.monto, "sucursal": sucursal or "General", "registrado_por": usuario,
            "estado": g.estado, "motivo_anulacion": g.motivo_anulacion,
        }
        for g, usuario, sucursal in sesion.execute(consulta)
    ]


def total_gastos(
    sesion: Session, actor: Usuario, desde: date | None = None, hasta: date | None = None,
    categoria: str | None = None, sucursal_id: int | None = None,
) -> Decimal:
    """Suma de gastos activos del periodo (los anulados no cuentan)."""
    exigir_permiso(sesion, actor, "gastos", "ver")
    total = sesion.scalar(
        select(func.coalesce(func.sum(Gasto.monto), 0)).where(
            Gasto.estado == "activo", *_filtros(desde, hasta, categoria, sucursal_id)
        )
    )
    return Decimal(total).quantize(Decimal("0.01"))


def gastos_por_categoria(
    sesion: Session, actor: Usuario, desde: date | None = None, hasta: date | None = None,
    sucursal_id: int | None = None,
) -> list[dict]:
    exigir_permiso(sesion, actor, "gastos", "ver")
    filas = sesion.execute(
        select(Gasto.categoria, func.sum(Gasto.monto), func.count())
        .where(Gasto.estado == "activo", *_filtros(desde, hasta, None, sucursal_id))
        .group_by(Gasto.categoria)
    )
    resultado = [
        {"categoria": c, "total": Decimal(t).quantize(Decimal("0.01")), "cantidad": int(n)} for c, t, n in filas
    ]
    return sorted(resultado, key=lambda f: (-f["total"], f["categoria"]))
