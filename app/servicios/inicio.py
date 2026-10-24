"""Datos del panel de inicio. Cada bloque respeta los permisos: si el usuario no puede verlo, llega ``None``.

- Ventas, ganancia, gráfica y más vendidos requieren ``reportes.ver`` (y alcance de ventas).
- Quien solo ve sus propias ventas recibe solo lo suyo y nunca costos ni ganancia.
- Inventario requiere ``inventario.ver``; últimas ventas y clientes, ``ventas.ver``.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.modelos import Usuario
from app.servicios.errores import PermisoDenegado
from app.servicios.inventario import existencias
from app.servicios.reportes import rango_local, resumen_ventas, ventas_agrupadas
from app.servicios.ventas import listar_clientes, listar_ventas

CERO = Decimal("0.00")


def _intentar(funcion: Callable[[], Any]) -> Any:
    try:
        return funcion()
    except PermisoDenegado:
        return None


def _cambio_porcentual(hoy: Decimal, ayer: Decimal) -> Decimal | None:
    if ayer <= 0:
        return None
    return ((hoy - ayer) * 100 / ayer).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def panel_inicio(sesion: Session, actor: Usuario, hoy: date | None = None, dias: int = 7) -> dict:
    hoy = hoy or date.today()
    ayer = hoy - timedelta(days=1)

    resumen_hoy = _intentar(lambda: resumen_ventas(sesion, actor, *rango_local(hoy, hoy)))
    resumen_ayer = _intentar(lambda: resumen_ventas(sesion, actor, *rango_local(ayer, ayer)))

    ve_costos = bool(resumen_hoy and resumen_hoy["utilidad"] is not None)

    def serie() -> list[dict]:
        primero = hoy - timedelta(days=dias - 1)
        por_dia = {f["clave"]: f for f in ventas_agrupadas(sesion, actor, "dia", *rango_local(primero, hoy))}
        filas = []
        for i in range(dias):
            dia = primero + timedelta(days=i)
            f = por_dia.get(dia.isoformat())
            filas.append(
                {
                    "dia": dia,
                    "ingreso": f["ingreso"] if f else CERO,
                    "utilidad": (f["utilidad"] if f else CERO) if ve_costos else None,
                }
            )
        return filas

    def inventario() -> dict:
        filas = existencias(sesion, actor)
        return {
            "productos": len(filas),
            "unidades": sum(f["stock"] for f in filas),
            "valor": None if any(f["valor"] is None for f in filas) else sum((f["valor"] for f in filas), CERO),
            "stock_bajo": sum(1 for f in filas if f["bajo_minimo"]),
        }

    clientes = _intentar(lambda: len(listar_clientes(sesion, actor)))
    return {
        "hoy": hoy,
        "ventas_hoy": resumen_hoy,
        "cambio_ventas": (
            _cambio_porcentual(resumen_hoy["ingreso"], resumen_ayer["ingreso"]) if resumen_hoy and resumen_ayer else None
        ),
        "cambio_ganancia": (
            _cambio_porcentual(resumen_hoy["utilidad"], resumen_ayer["utilidad"])
            if resumen_hoy and resumen_ayer and resumen_hoy["utilidad"] is not None
            else None
        ),
        "serie": _intentar(serie),
        "mas_vendidos": _intentar(lambda: ventas_agrupadas(sesion, actor, "producto", *rango_local(hoy - timedelta(days=29), hoy), limite=5)),
        "ultimas_ventas": _intentar(lambda: listar_ventas(sesion, actor, limite=8)),
        "inventario": _intentar(inventario),
        "clientes": clientes,
    }
