"""Pruebas de la Fase 7b: fotos de producto."""

import pytest
from PIL import Image
from sqlalchemy import inspect, select

from app.modelos import BitacoraAuditoria, Producto
from app.servicios.catalogo import crear_categoria, crear_producto
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado
from app.servicios.fotos import asignar_foto, carpeta_fotos, quitar_foto, rutas_de_fotos


@pytest.fixture()
def carpeta(tmp_path, monkeypatch):
    destino = tmp_path / "fotos_prueba"
    monkeypatch.setenv("CARPETA_FOTOS", str(destino))
    return destino


@pytest.fixture()
def producto(sesion_servicios, administrador):
    categoria = crear_categoria(sesion_servicios, administrador, "General")
    p = crear_producto(sesion_servicios, administrador, sku="F1", nombre="Con foto", categoria_id=categoria.id, precio="10", costo="4")
    sesion_servicios.commit()
    return p


def _imagen(ruta, tamano=(1600, 900), modo="RGB", color="red"):
    Image.new(modo, tamano, color).save(ruta)
    return ruta


def test_la_migracion_agrega_la_columna_foto(motor):
    assert "foto" in {c["name"] for c in inspect(motor).get_columns("productos")}


def test_asignar_foto_reduce_la_imagen_y_guarda_solo_el_nombre(sesion_servicios, administrador, producto, carpeta, tmp_path):
    origen = _imagen(tmp_path / "grande.png")
    nombre = asignar_foto(sesion_servicios, administrador, producto.id, origen)
    sesion_servicios.commit()
    destino = carpeta / nombre
    assert destino.is_file() and nombre.endswith(".jpg") and "/" not in nombre
    with Image.open(destino) as guardada:
        assert max(guardada.size) == 800
    assert sesion_servicios.get(Producto, producto.id).foto == nombre
    assert origen.is_file()  # el original no se toca
    assert rutas_de_fotos(sesion_servicios, administrador, [producto.id]) == {producto.id: carpeta / nombre}


def test_imagen_con_transparencia_se_convierte(sesion_servicios, administrador, producto, carpeta, tmp_path):
    origen = _imagen(tmp_path / "t.png", (50, 50), "RGBA", (0, 0, 0, 0))
    nombre = asignar_foto(sesion_servicios, administrador, producto.id, origen)
    with Image.open(carpeta / nombre) as guardada:
        assert guardada.mode == "RGB"
        assert guardada.getpixel((5, 5)) == (255, 255, 255)  # transparente -> fondo blanco


def test_cambiar_la_foto_borra_la_anterior(sesion_servicios, administrador, producto, carpeta, tmp_path):
    primera = asignar_foto(sesion_servicios, administrador, producto.id, _imagen(tmp_path / "a.png", (40, 40)))
    segunda = asignar_foto(sesion_servicios, administrador, producto.id, _imagen(tmp_path / "b.png", (40, 40), color="blue"))
    assert primera != segunda
    assert not (carpeta / primera).exists() and (carpeta / segunda).is_file()


def test_quitar_foto_borra_archivo_y_referencia(sesion_servicios, administrador, producto, carpeta, tmp_path):
    nombre = asignar_foto(sesion_servicios, administrador, producto.id, _imagen(tmp_path / "a.png", (40, 40)))
    quitar_foto(sesion_servicios, administrador, producto.id)
    sesion_servicios.commit()
    assert not (carpeta / nombre).exists()
    assert sesion_servicios.get(Producto, producto.id).foto is None
    quitar_foto(sesion_servicios, administrador, producto.id)  # sin foto: no falla
    acciones = [b.accion for b in sesion_servicios.scalars(select(BitacoraAuditoria))]
    assert "foto_asignada" in acciones and "foto_quitada" in acciones


def test_archivos_no_validos_se_rechazan(sesion_servicios, administrador, producto, carpeta, tmp_path):
    falso = tmp_path / "falso.png"
    falso.write_text("esto no es una imagen")
    with pytest.raises(ErrorDeNegocio, match="imagen válida"):
        asignar_foto(sesion_servicios, administrador, producto.id, falso)
    texto = tmp_path / "nota.txt"
    texto.write_text("x")
    with pytest.raises(ErrorDeNegocio, match="Formato"):
        asignar_foto(sesion_servicios, administrador, producto.id, texto)
    with pytest.raises(ErrorDeNegocio, match="No se encontró"):
        asignar_foto(sesion_servicios, administrador, producto.id, tmp_path / "noexiste.png")
    assert sesion_servicios.get(Producto, producto.id).foto is None
    assert not carpeta.exists() or list(carpeta.iterdir()) == []


def test_imagen_demasiado_pesada_se_rechaza(sesion_servicios, administrador, producto, carpeta, tmp_path, monkeypatch):
    monkeypatch.setattr("app.servicios.fotos.TAMANO_MAXIMO_BYTES", 10)
    with pytest.raises(ErrorDeNegocio, match="10 MB"):
        asignar_foto(sesion_servicios, administrador, producto.id, _imagen(tmp_path / "a.png", (60, 60)))


def test_producto_inexistente(sesion_servicios, administrador, carpeta, tmp_path):
    with pytest.raises(ErrorDeNegocio, match="no existe"):
        asignar_foto(sesion_servicios, administrador, 999, _imagen(tmp_path / "a.png", (10, 10)))


def test_permisos_de_fotos(sesion_servicios, administrador, producto, carpeta, tmp_path, crear_con_rol):
    vendedor = crear_con_rol("vendedor")
    bodeguero = crear_con_rol("bodeguero")
    origen = _imagen(tmp_path / "a.png", (20, 20))
    with pytest.raises(PermisoDenegado):
        asignar_foto(sesion_servicios, vendedor, producto.id, origen)
    with pytest.raises(PermisoDenegado):
        quitar_foto(sesion_servicios, vendedor, producto.id)
    asignar_foto(sesion_servicios, bodeguero, producto.id, origen)  # el bodeguero edita productos
    assert producto.id in rutas_de_fotos(sesion_servicios, vendedor, [producto.id])  # y el vendedor las ve


def test_si_el_archivo_desaparece_no_se_informa_ruta(sesion_servicios, administrador, producto, carpeta, tmp_path):
    nombre = asignar_foto(sesion_servicios, administrador, producto.id, _imagen(tmp_path / "a.png", (20, 20)))
    (carpeta / nombre).unlink()
    assert rutas_de_fotos(sesion_servicios, administrador, [producto.id]) == {}
    assert rutas_de_fotos(sesion_servicios, administrador, []) == {}


def test_la_carpeta_relativa_cuelga_de_la_raiz_del_proyecto(monkeypatch):
    monkeypatch.setenv("CARPETA_FOTOS", "mis_fotos")
    assert carpeta_fotos().name == "mis_fotos" and carpeta_fotos().is_absolute()
