"""Comprobante de venta imprimible (HTML y texto). Funciones puras, sin acceso a datos."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape


def a_hora_local(fecha: datetime | None) -> str:
    """Convierte una fecha UTC de la base de datos a texto en la hora de este equipo."""
    if fecha is None:
        return ""
    return fecha.replace(tzinfo=timezone.utc).astimezone().strftime("%d/%m/%Y %H:%M")


def _pagos(venta: dict) -> list[dict]:
    """Formas de pago de la venta (compatible con datos sin el detalle de pagos)."""
    return venta.get("pagos") or [{"metodo": venta["metodo_pago"], "monto": venta["total"], "recibido": None, "cambio": None}]


def _texto_pagos(venta: dict, ancho: int) -> list[str]:
    pagos = _pagos(venta)
    if len(pagos) == 1 and pagos[0]["recibido"] is None:
        return [f"Pago: {pagos[0]['metodo']}"]
    salida = ["Pagos:"] if len(pagos) > 1 else []
    for p in pagos:
        etiqueta = f"  {p['metodo'].capitalize()}" if len(pagos) > 1 else f"Pago: {p['metodo']}"
        salida.append(etiqueta.ljust(ancho - 12) + f"{p['monto']:>12.2f}")
        if p["recibido"] is not None:
            salida.append("  Recibido".ljust(ancho - 12) + f"{p['recibido']:>12.2f}")
            salida.append("  Cambio".ljust(ancho - 12) + f"{p['cambio']:>12.2f}")
    return salida


def comprobante_texto(venta: dict, empresa: str) -> str:
    ancho = 44
    lineas = [empresa.center(ancho), f"Comprobante {venta['codigo']}".center(ancho), "-" * ancho]
    if venta["estado"] == "anulada":
        lineas += ["*** VENTA ANULADA ***".center(ancho), f"Motivo: {venta['motivo_anulacion']}", "-" * ancho]
    lineas += [
        f"Fecha: {a_hora_local(venta['fecha'])}",
        f"Sucursal: {venta['sucursal']}",
        f"Atendió: {venta['vendedor']}",
        f"Cliente: {venta['cliente'] or 'Consumidor final'}",
        "-" * ancho,
    ]
    for l in venta["lineas"]:
        lineas.append(f"{l['nombre']}")
        lineas.append(f"  {l['cantidad']} x {l['precio']:.2f}".ljust(ancho - 12) + f"{l['total']:>12.2f}")
        if l["descuento"]:
            lineas.append(f"  Descuento: -{l['descuento']:.2f}")
    lineas += [
        "-" * ancho,
        "Subtotal".ljust(ancho - 12) + f"{venta['subtotal']:>12.2f}",
        "Descuento".ljust(ancho - 12) + f"{-venta['descuento']:>12.2f}",
        "TOTAL".ljust(ancho - 12) + f"{venta['total']:>12.2f}",
        *_texto_pagos(venta, ancho),
    ]
    devoluciones = venta.get("devoluciones") or []
    if devoluciones:
        lineas += ["-" * ancho, "DEVOLUCIONES".center(ancho)]
        for d in devoluciones:
            lineas.append(f"{d['codigo']} · {a_hora_local(d['fecha'])} · {d['usuario']}")
            for l in d["lineas"]:
                lineas.append(f"  {l['cantidad']} x {l['nombre']}".ljust(ancho - 12) + f"{-l['monto']:>12.2f}")
            lineas.append(f"  Motivo: {d['motivo']} ({d['metodo_reembolso']})")
        lineas += [
            "Total devuelto".ljust(ancho - 12) + f"{-venta['total_devuelto']:>12.2f}",
            "NETO".ljust(ancho - 12) + f"{venta['total'] - venta['total_devuelto']:>12.2f}",
        ]
    lineas += ["-" * ancho, "Gracias por su compra".center(ancho)]
    return "\n".join(lineas)


def comprobante_html(venta: dict, empresa: str) -> str:
    """Página lista para imprimir desde el navegador. Todo texto se escapa."""
    e = escape
    filas = "".join(
        f"<tr><td>{e(l['nombre'])}</td><td class='n'>{l['cantidad']}</td>"
        f"<td class='n'>{l['precio']:.2f}</td><td class='n'>{l['total']:.2f}</td></tr>"
        + (f"<tr class='d'><td colspan='3'>Descuento</td><td class='n'>-{l['descuento']:.2f}</td></tr>" if l["descuento"] else "")
        for l in venta["lineas"]
    )
    pagos_html = "".join(
        f"<br>{e(p['metodo'].capitalize())}: {p['monto']:.2f}"
        + (f" (recibido {p['recibido']:.2f} · cambio {p['cambio']:.2f})" if p["recibido"] is not None else "")
        for p in _pagos(venta)
    )
    devueltas = "".join(
        f"<tr class='d'><td colspan='4'><b>{e(d['codigo'])}</b> · {e(a_hora_local(d['fecha']))} · {e(d['usuario'])} · "
        f"{e(d['motivo'])}</td></tr>"
        + "".join(
            f"<tr class='d'><td>{e(l['nombre'])}</td><td class='n'>{l['cantidad']}</td><td></td><td class='n'>-{l['monto']:.2f}</td></tr>"
            for l in d["lineas"]
        )
        for d in (venta.get("devoluciones") or [])
    )
    if devueltas:
        devueltas = (
            "<tr><th colspan='4'>Devoluciones</th></tr>" + devueltas
            + f"<tr class='t'><td colspan='3'>NETO</td><td class='n'>{venta['total'] - venta['total_devuelto']:.2f}</td></tr>"
        )
    anulada = ""
    if venta["estado"] == "anulada":
        anulada = (
            f"<p class='anulada'>VENTA ANULADA<br><small>{e(venta['motivo_anulacion'] or '')} · "
            f"{e(venta['anulada_por'] or '')} · {e(a_hora_local(venta['anulada_en']))}</small></p>"
        )
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Comprobante {e(venta['codigo'])}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 380px; margin: 24px auto; color: #111; }}
  h1 {{ font-size: 1.2rem; text-align: center; margin: 0; }}
  .c {{ text-align: center; color: #555; margin: 2px 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
  th, td {{ padding: 3px 0; text-align: left; border-bottom: 1px dotted #bbb; }}
  .n {{ text-align: right; }} .d td {{ color: #666; font-size: .8rem; }}
  .t td {{ font-weight: bold; border-bottom: 0; font-size: 1.05rem; }}
  .anulada {{ text-align: center; color: #b00020; font-weight: bold; border: 2px solid #b00020; padding: 6px; }}
  .meta {{ font-size: .85rem; margin: 10px 0; }}
  @media print {{ body {{ margin: 0; }} }}
</style></head><body>
<h1>{e(empresa)}</h1>
<p class="c">Comprobante {e(venta['codigo'])}</p>
{anulada}
<p class="meta">Fecha: {e(a_hora_local(venta['fecha']))}<br>
Sucursal: {e(venta['sucursal'])}<br>
Atendió: {e(venta['vendedor'])}<br>
Cliente: {e(venta['cliente'] or 'Consumidor final')}</p>
<table><tr><th>Producto</th><th class="n">Cant.</th><th class="n">Precio</th><th class="n">Importe</th></tr>
{filas}
<tr><td colspan="3">Subtotal</td><td class="n">{venta['subtotal']:.2f}</td></tr>
<tr><td colspan="3">Descuento</td><td class="n">-{venta['descuento']:.2f}</td></tr>
<tr class="t"><td colspan="3">TOTAL</td><td class="n">{venta['total']:.2f}</td></tr>
{devueltas}</table>
<p class="meta">Forma de pago:{pagos_html}</p>
<p class="c">Gracias por su compra</p>
</body></html>
"""
