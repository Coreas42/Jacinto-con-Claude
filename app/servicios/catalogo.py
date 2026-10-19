"""Catálogo de productos: categorías, altas, ediciones, búsqueda e historial.

Reglas:
- El SKU no se puede editar una vez creado (es la identidad del producto).
- Los productos no se borran: se desactivan y conservan su historia.
- Todo cambio de precio o costo deja una fila en ``historial_productos`` con
  valor anterior, valor nuevo, usuario y fecha. Cambiarlos exige el permiso
  ``productos.precios``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.modelos import Categoria, HistorialProducto, Producto, Usuario
from app.servicios.auditoria import registrar
from app.servicios.errores import ErrorDeNegocio
from app.servicios.permisos import exigir_permiso

CENTAVO = Decimal("0.01")
MAXIMO_DINERO = Decimal("9999999999.99")

CAMPOS_PRECIO = {"precio", "costo"}
CAMPOS_EDITABLES = {
    "nombre",
    "descripcion",
    "categoria_id",
    "marca",
    "stock_minimo",
    "codigo_barras",
    "precio",
    "costo",
}
# Campos del producto cuyo cambio queda en el historial.
CAMPOS_CON_HISTORIAL = ("precio", "costo", "stock_minimo", "nombre", "activo")
# Nombre del campo del formulario -> atributo del modelo.
ATRIBUTO = {"costo": "costo_promedio"}


# ---- validación y normalización --------------------------------------------------


def _dinero(valor: Any, campo: str) -> Decimal:
    """Convierte a Decimal con 2 decimales. Acepta ``12.5``, ``"12,50"`` o ``"1,234.50"``."""
    if isinstance(valor, float):
        texto = repr(valor)
    else:
        texto = str(valor).strip()
    if "," in texto and "." not in texto:
        texto = texto.replace(",", ".")
    else:
        texto = texto.replace(",", "")
    try:
        numero = Decimal(texto)
    except (InvalidOperation, ValueError):
        raise ErrorDeNegocio(f"El campo {campo} no es un número válido.") from None
    if not numero.is_finite():
        raise ErrorDeNegocio(f"El campo {campo} no es un número válido.")
    numero = numero.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    if numero < 0:
        raise ErrorDeNegocio(f"El campo {campo} no puede ser negativo.")
    if numero > MAXIMO_DINERO:
        raise ErrorDeNegocio(f"El campo {campo} es demasiado grande.")
    return numero


def _entero(valor: Any, campo: str) -> int:
    try:
        numero = int(str(valor).strip() or 0)
    except ValueError:
        raise ErrorDeNegocio(f"El campo {campo} debe ser un número entero.") from None
    if numero < 0:
        raise ErrorDeNegocio(f"El campo {campo} no puede ser negativo.")
    return numero


def _texto(valor: Any, campo: str, largo: int, obligatorio: bool = False) -> str | None:
    texto = (valor or "").strip() if isinstance(valor, str) or valor is None else str(valor).strip()
    if not texto:
        if obligatorio:
            raise ErrorDeNegocio(f"El campo {campo} es obligatorio.")
        return None
    if len(texto) > largo:
        raise ErrorDeNegocio(f"El campo {campo} admite como máximo {largo} caracteres.")
    return texto


def _mostrar(campo: str, valor: Any) -> str | None:
    if valor is None:
        return None
    if isinstance(valor, bool):
        return "activo" if valor else "inactivo"
    if isinstance(valor, Decimal):
        return f"{valor:.2f}"
    return str(valor)


# ---- consultas internas ----------------------------------------------------------


def _obtener(sesion: Session, producto_id: int) -> Producto:
    producto = sesion.get(Producto, producto_id)
    if producto is None:
        raise ErrorDeNegocio("El producto no existe.")
    return producto


def _obtener_categoria(sesion: Session, categoria_id: int) -> Categoria:
    categoria = sesion.get(Categoria, categoria_id)
    if categoria is None:
        raise ErrorDeNegocio("La categoría no existe.")
    return categoria


def _validar_codigos(
    sesion: Session, sku: str | None, barras: str | None, excepto_id: int | None = None
) -> None:
    """SKU y código de barras únicos, y sin que uno coincida con el otro de otro producto
    (así un escaneo o una búsqueda por código nunca es ambigua)."""
    for codigo, etiqueta in ((sku, "SKU"), (barras, "código de barras")):
        if codigo is None:
            continue
        consulta = select(Producto.id).where(
            or_(Producto.sku == codigo, Producto.codigo_barras == codigo)
        )
        if excepto_id is not None:
            consulta = consulta.where(Producto.id != excepto_id)
        if sesion.scalar(consulta.limit(1)) is not None:
            raise ErrorDeNegocio(f"Ya existe un producto con el {etiqueta} '{codigo}'.")
    if sku is not None and barras is not None and sku == barras:
        raise ErrorDeNegocio("El SKU y el código de barras no pueden ser iguales.")


def _historial(
    sesion: Session, producto_id: int, campo: str, anterior: Any, nuevo: Any, usuario_id: int
) -> None:
    sesion.add(
        HistorialProducto(
            producto_id=producto_id,
            campo=campo,
            valor_anterior=_mostrar(campo, anterior),
            valor_nuevo=_mostrar(campo, nuevo),
            usuario_id=usuario_id,
        )
    )


def _a_dict(producto: Producto) -> dict:
    return {
        "id": producto.id,
        "sku": producto.sku,
        "codigo_barras": producto.codigo_barras,
        "nombre": producto.nombre,
        "descripcion": producto.descripcion,
        "categoria_id": producto.categoria_id,
        "categoria": producto.categoria.nombre,
        "marca": producto.marca,
        "costo": producto.costo_promedio,
        "precio": producto.precio,
        "stock_minimo": producto.stock_minimo,
        "activo": producto.activo,
    }


# ---- categorías ------------------------------------------------------------------


def crear_categoria(sesion: Session, actor: Usuario, nombre: str) -> Categoria:
    exigir_permiso(sesion, actor, "productos", "crear")
    nombre = _texto(nombre, "nombre", 80, obligatorio=True)
    existe = sesion.scalar(select(Categoria.id).where(Categoria.nombre.ilike(nombre)))
    if existe is not None:
        raise ErrorDeNegocio(f"Ya existe la categoría '{nombre}'.")
    categoria = Categoria(nombre=nombre)
    sesion.add(categoria)
    sesion.flush()
    registrar(
        sesion,
        "categoria_creada",
        usuario_id=actor.id,
        entidad="categorias",
        entidad_id=categoria.id,
        detalle={"nombre": nombre},
    )
    return categoria


def listar_categorias(sesion: Session, actor: Usuario, incluir_inactivas: bool = False) -> list[dict]:
    exigir_permiso(sesion, actor, "productos", "ver")
    consulta = select(Categoria).order_by(Categoria.nombre)
    if not incluir_inactivas:
        consulta = consulta.where(Categoria.activa.is_(True))
    return [{"id": c.id, "nombre": c.nombre, "activa": c.activa} for c in sesion.scalars(consulta)]


def establecer_categoria_activa(sesion: Session, actor: Usuario, categoria_id: int, activa: bool) -> None:
    exigir_permiso(sesion, actor, "productos", "editar")
    categoria = _obtener_categoria(sesion, categoria_id)
    if categoria.activa == activa:
        return
    categoria.activa = activa
    registrar(
        sesion,
        "categoria_activada" if activa else "categoria_desactivada",
        usuario_id=actor.id,
        entidad="categorias",
        entidad_id=categoria.id,
    )


# ---- productos -------------------------------------------------------------------


def crear_producto(
    sesion: Session,
    actor: Usuario,
    *,
    sku: str,
    nombre: str,
    categoria_id: int,
    precio: Any,
    costo: Any = 0,
    stock_minimo: Any = 0,
    codigo_barras: str | None = None,
    descripcion: str | None = None,
    marca: str | None = None,
) -> Producto:
    exigir_permiso(sesion, actor, "productos", "crear")
    sku = (_texto(sku, "SKU", 50, obligatorio=True) or "").upper()
    nombre = _texto(nombre, "nombre", 150, obligatorio=True)
    barras = _texto(codigo_barras, "código de barras", 50)
    descripcion = _texto(descripcion, "descripción", 500)
    marca = _texto(marca, "marca", 80)
    precio = _dinero(precio, "precio")
    costo = _dinero(costo, "costo")
    minimo = _entero(stock_minimo, "stock mínimo")

    categoria = _obtener_categoria(sesion, categoria_id)
    if not categoria.activa:
        raise ErrorDeNegocio("La categoría está desactivada.")
    _validar_codigos(sesion, sku, barras)

    producto = Producto(
        sku=sku,
        codigo_barras=barras,
        nombre=nombre,
        descripcion=descripcion,
        categoria_id=categoria.id,
        marca=marca,
        costo_promedio=costo,
        precio=precio,
        stock_minimo=minimo,
    )
    sesion.add(producto)
    sesion.flush()
    # Valores iniciales: el historial arranca desde el alta.
    _historial(sesion, producto.id, "precio", None, precio, actor.id)
    _historial(sesion, producto.id, "costo", None, costo, actor.id)
    registrar(
        sesion,
        "producto_creado",
        usuario_id=actor.id,
        entidad="productos",
        entidad_id=producto.id,
        detalle={"sku": sku, "nombre": nombre},
    )
    return producto


def editar_producto(sesion: Session, actor: Usuario, producto_id: int, cambios: dict[str, Any]) -> list[str]:
    """Aplica solo los campos indicados y devuelve los que realmente cambiaron.

    Tocar datos generales exige ``productos.editar``; tocar precio o costo exige
    ``productos.precios`` (se comprueba según los campos enviados). El SKU no se puede modificar.
    """
    desconocidos = set(cambios) - CAMPOS_EDITABLES
    if desconocidos:
        raise ErrorDeNegocio(f"No se puede editar: {', '.join(sorted(desconocidos))}.")
    # La autorización depende de QUÉ campos se intentan tocar, no de si cambian.
    if cambios.keys() & CAMPOS_PRECIO:
        exigir_permiso(sesion, actor, "productos", "precios")
    if cambios.keys() - CAMPOS_PRECIO:
        exigir_permiso(sesion, actor, "productos", "editar")
    producto = _obtener(sesion, producto_id)

    nuevos: dict[str, Any] = {}
    if "nombre" in cambios:
        nuevos["nombre"] = _texto(cambios["nombre"], "nombre", 150, obligatorio=True)
    if "descripcion" in cambios:
        nuevos["descripcion"] = _texto(cambios["descripcion"], "descripción", 500)
    if "marca" in cambios:
        nuevos["marca"] = _texto(cambios["marca"], "marca", 80)
    if "codigo_barras" in cambios:
        nuevos["codigo_barras"] = _texto(cambios["codigo_barras"], "código de barras", 50)
    if "stock_minimo" in cambios:
        nuevos["stock_minimo"] = _entero(cambios["stock_minimo"], "stock mínimo")
    if "precio" in cambios:
        nuevos["precio"] = _dinero(cambios["precio"], "precio")
    if "costo" in cambios:
        nuevos["costo"] = _dinero(cambios["costo"], "costo")
    if "categoria_id" in cambios:
        categoria = _obtener_categoria(sesion, int(cambios["categoria_id"]))
        if not categoria.activa and categoria.id != producto.categoria_id:
            raise ErrorDeNegocio("La categoría está desactivada.")
        nuevos["categoria_id"] = categoria.id

    diferencias: dict[str, tuple[Any, Any]] = {}
    for campo, valor in nuevos.items():
        actual = getattr(producto, ATRIBUTO.get(campo, campo))
        if actual != valor:
            diferencias[campo] = (actual, valor)
    if not diferencias:
        return []

    if "codigo_barras" in diferencias:
        _validar_codigos(sesion, None, diferencias["codigo_barras"][1], excepto_id=producto.id)
        if diferencias["codigo_barras"][1] == producto.sku:
            raise ErrorDeNegocio("El SKU y el código de barras no pueden ser iguales.")

    for campo, (_, valor) in diferencias.items():
        setattr(producto, ATRIBUTO.get(campo, campo), valor)
    sesion.flush()

    for campo, (anterior, valor) in diferencias.items():
        if campo in CAMPOS_CON_HISTORIAL:
            _historial(sesion, producto.id, campo, anterior, valor, actor.id)
    registrar(
        sesion,
        "producto_editado",
        usuario_id=actor.id,
        entidad="productos",
        entidad_id=producto.id,
        detalle={campo: [_mostrar(campo, a), _mostrar(campo, n)] for campo, (a, n) in diferencias.items()},
    )
    return sorted(diferencias)


def establecer_activo(sesion: Session, actor: Usuario, producto_id: int, activo: bool) -> None:
    """Desactiva o reactiva un producto. Nunca se borra."""
    exigir_permiso(sesion, actor, "productos", "editar")
    producto = _obtener(sesion, producto_id)
    if producto.activo == activo:
        return
    producto.activo = activo
    _historial(sesion, producto.id, "activo", not activo, activo, actor.id)
    registrar(
        sesion,
        "producto_activado" if activo else "producto_desactivado",
        usuario_id=actor.id,
        entidad="productos",
        entidad_id=producto.id,
    )


# ---- consultas -------------------------------------------------------------------


def buscar_productos(
    sesion: Session,
    actor: Usuario,
    texto: str = "",
    categoria_id: int | None = None,
    incluir_inactivos: bool = False,
    limite: int = 500,
) -> list[dict]:
    """Busca por nombre, SKU, código de barras o marca. Por defecto solo activos."""
    exigir_permiso(sesion, actor, "productos", "ver")
    consulta = select(Producto).options(joinedload(Producto.categoria)).order_by(Producto.nombre)
    texto = (texto or "").strip()
    if texto:
        patron = f"%{texto}%"
        consulta = consulta.where(
            or_(
                Producto.nombre.ilike(patron),
                Producto.sku.ilike(patron),
                Producto.codigo_barras.ilike(patron),
                Producto.marca.ilike(patron),
            )
        )
    if categoria_id is not None:
        consulta = consulta.where(Producto.categoria_id == categoria_id)
    if not incluir_inactivos:
        consulta = consulta.where(Producto.activo.is_(True))
    return [_a_dict(p) for p in sesion.scalars(consulta.limit(limite))]


def obtener_por_codigo(
    sesion: Session, actor: Usuario, codigo: str, solo_activos: bool = True
) -> dict | None:
    """Coincidencia exacta por código de barras o SKU (lo que envía un lector USB).

    Por defecto ignora los productos desactivados, para que no se puedan vender.
    """
    exigir_permiso(sesion, actor, "productos", "ver")
    codigo = (codigo or "").strip()
    if not codigo:
        return None
    consulta = (
        select(Producto)
        .options(joinedload(Producto.categoria))
        .where(or_(Producto.codigo_barras == codigo, Producto.sku == codigo.upper()))
    )
    if solo_activos:
        consulta = consulta.where(Producto.activo.is_(True))
    producto = sesion.scalar(consulta)
    return _a_dict(producto) if producto else None


def historial_producto(sesion: Session, actor: Usuario, producto_id: int) -> list[dict]:
    """Cambios del producto, del más reciente al más antiguo."""
    exigir_permiso(sesion, actor, "productos", "ver")
    _obtener(sesion, producto_id)
    filas = sesion.execute(
        select(HistorialProducto, Usuario.nombre)
        .outerjoin(Usuario, Usuario.id == HistorialProducto.usuario_id)
        .where(HistorialProducto.producto_id == producto_id)
        .order_by(HistorialProducto.id.desc())
    ).all()
    return [
        {
            "fecha": h.creado_en,
            "campo": h.campo,
            "anterior": h.valor_anterior,
            "nuevo": h.valor_nuevo,
            "usuario": nombre or "—",
        }
        for h, nombre in filas
    ]
