"""Pruebas de pulido: costos ocultos, bloqueo de acceso, respaldos, salud y paginación."""

import json
import sqlite3
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from app.db import ahora_utc, crear_fabrica_sesiones
from app.modelos import BitacoraAuditoria, Existencia
from app.respaldo import (
    archivo_de_la_base,
    crear_respaldo,
    listar_respaldos,
    respaldo_automatico,
    restaurar_respaldo,
)
from app.salud import verificar_salud
from app.servicios.autenticacion import iniciar_sesion
from app.servicios.catalogo import (
    buscar_productos,
    crear_categoria,
    crear_producto,
    editar_producto,
    historial_producto,
    obtener_por_codigo,
)
from app.servicios.errores import CredencialesInvalidas, ErrorDeNegocio, PermisoDenegado
from app.servicios.inicio import panel_inicio
from app.servicios.inventario import (
    crear_proveedor,
    crear_sucursal,
    exportar_existencias_csv,
    exportar_kardex_csv,
    existencias,
    kardex,
    registrar_compra,
)
from app.servicios.reportes import inventario_valorizado
from app.servicios.usuarios import establecer_permiso_individual
from app.servicios.ventas import listar_ventas, registrar_venta
import main as programa

CLAVE_PRUEBA = "claveSegura1"


@pytest.fixture()
def t(sesion_servicios, administrador):
    """P1 (precio 10, costo 4, 10 u.), cambiado una vez de precio para que haya historial de costo."""
    s = sesion_servicios
    principal = crear_sucursal(s, administrador, "Principal")
    proveedor = crear_proveedor(s, administrador, "Distribuidora")
    categoria = crear_categoria(s, administrador, "General")
    p1 = crear_producto(s, administrador, sku="P1", nombre="Producto 1", categoria_id=categoria.id, precio="10", costo="3", codigo_barras="111")
    registrar_compra(
        s, administrador, sucursal_id=principal.id, proveedor_id=proveedor.id,
        lineas=[{"producto_id": p1.id, "cantidad": 10, "costo_unitario": "4"}],
    )
    s.commit()
    return SimpleNamespace(principal=principal, p1=p1)


# ---- costos ocultos ------------------------------------------------------------------


def test_el_vendedor_no_ve_costos(sesion_servicios, crear_con_rol, t):
    s = sesion_servicios
    vendedor = crear_con_rol("vendedor")
    assert buscar_productos(s, vendedor)[0]["costo"] is None
    assert obtener_por_codigo(s, vendedor, "111")["costo"] is None
    fila = existencias(s, vendedor)[0]
    assert fila["stock"] == 10 and fila["costo"] is None and fila["valor"] is None
    assert all(m["costo"] is None for m in kardex(s, vendedor, t.p1.id))
    assert "costo" not in {h["campo"] for h in historial_producto(s, vendedor, t.p1.id)}
    assert buscar_productos(s, vendedor)[0]["precio"] == Decimal("10.00")  # el precio sí lo ve
    with pytest.raises(PermisoDenegado):
        inventario_valorizado(s, vendedor)
    assert panel_inicio(s, vendedor)["inventario"]["valor"] is None


def test_quienes_trabajan_con_costos_si_los_ven(sesion_servicios, administrador, crear_con_rol, t):
    s = sesion_servicios
    for actor in (administrador, crear_con_rol("bodeguero"), crear_con_rol("contador")):
        assert buscar_productos(s, actor)[0]["costo"] == Decimal("4.00")
        assert existencias(s, actor)[0]["valor"] == Decimal("40.00")
        assert kardex(s, actor, t.p1.id)[0]["costo"] == Decimal("4.00")
        assert "costo" in {h["campo"] for h in historial_producto(s, actor, t.p1.id)}


def test_un_permiso_individual_de_precios_o_inventario_permite_ver_costos(sesion_servicios, administrador, crear_con_rol, t):
    s = sesion_servicios
    vendedor = crear_con_rol("vendedor")
    establecer_permiso_individual(s, administrador, vendedor.id, "productos", "precios", True)
    s.commit()
    assert buscar_productos(s, vendedor)[0]["costo"] == Decimal("4.00")


def test_exportar_sin_permiso_de_costos_deja_las_columnas_vacias(sesion_servicios, administrador, crear_con_rol, t):
    s = sesion_servicios
    vendedor = crear_con_rol("vendedor")
    establecer_permiso_individual(s, administrador, vendedor.id, "inventario", "exportar", True)
    s.commit()
    existencias_csv = exportar_existencias_csv(s, vendedor).splitlines()[1]
    assert existencias_csv.split(",")[5:7] == ["", ""]
    assert "4.00" not in exportar_kardex_csv(s, vendedor, t.p1.id)
    assert "4.00" in exportar_kardex_csv(s, administrador, t.p1.id)


# ---- bloqueo por intentos fallidos ---------------------------------------------------


def fallar(s, correo, veces):
    for _ in range(veces):
        with pytest.raises(CredencialesInvalidas):
            iniciar_sesion(s, correo, "clave-incorrecta")


def test_cinco_fallos_bloquean_el_acceso_aunque_la_clave_sea_correcta(sesion_servicios, administrador, crear_con_rol):
    s = sesion_servicios
    crear_con_rol("vendedor")
    fallar(s, "admin@x.com", 5)
    with pytest.raises(ErrorDeNegocio, match="Demasiados"):
        iniciar_sesion(s, "admin@x.com", CLAVE_PRUEBA)
    s.rollback()
    assert s.query(BitacoraAuditoria).filter_by(accion="login_bloqueado").count() == 1
    assert iniciar_sesion(s, "vendedor@x.com", CLAVE_PRUEBA).correo == "vendedor@x.com"  # otro usuario no se afecta


def test_el_bloqueo_se_aplica_igual_a_correos_inexistentes(sesion_servicios):
    s = sesion_servicios
    fallar(s, "nadie@x.com", 5)
    with pytest.raises(ErrorDeNegocio, match="Demasiados"):
        iniciar_sesion(s, "nadie@x.com", "otra")


def test_un_acceso_correcto_reinicia_la_cuenta(sesion_servicios, administrador):
    s = sesion_servicios
    fallar(s, "admin@x.com", 4)
    iniciar_sesion(s, "admin@x.com", CLAVE_PRUEBA)
    s.commit()
    fallar(s, "admin@x.com", 4)
    assert iniciar_sesion(s, "admin@x.com", CLAVE_PRUEBA)


def test_el_bloqueo_termina_con_el_tiempo(sesion_servicios, administrador):
    s = sesion_servicios
    fallar(s, "admin@x.com", 5)
    s.execute(update(BitacoraAuditoria).values(creado_en=ahora_utc() - timedelta(minutes=20)))
    s.commit()
    assert iniciar_sesion(s, "admin@x.com", CLAVE_PRUEBA)


# ---- respaldos -----------------------------------------------------------------------


def tablas(archivo):
    conexion = sqlite3.connect(str(archivo))
    try:
        return {fila[0] for fila in conexion.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conexion.close()


def test_crear_respaldo(motor, url_bd, tmp_path):
    archivo = crear_respaldo(url_bd, tmp_path / "r")
    assert archivo.parent == tmp_path / "r" and archivo.name.startswith("respaldo_") and archivo.suffix == ".db"
    assert tablas(archivo) == tablas(archivo_de_la_base(url_bd))


def test_los_respaldos_viejos_se_rotan(motor, url_bd, tmp_path):
    for _ in range(4):
        ultimo = crear_respaldo(url_bd, tmp_path / "r", conservar=2)
    restantes = listar_respaldos(tmp_path / "r")
    assert len(restantes) == 2 and restantes[0] == ultimo


def test_respaldo_automatico_una_vez_al_dia(motor, url_bd, tmp_path):
    assert respaldo_automatico(url_bd, tmp_path / "r") is not None
    assert respaldo_automatico(url_bd, tmp_path / "r") is None
    assert len(listar_respaldos(tmp_path / "r")) == 1


def test_respaldo_solo_con_sqlite_y_base_existente(tmp_path):
    with pytest.raises(ErrorDeNegocio, match="pg_dump"):
        crear_respaldo("postgresql+psycopg://u:p@localhost/db", tmp_path)
    with pytest.raises(ErrorDeNegocio, match="No existe"):
        crear_respaldo(f"sqlite:///{tmp_path / 'no_existe.db'}", tmp_path)


def test_restaurar_recupera_los_datos_y_guarda_la_version_anterior(motor, url_bd, tmp_path):
    base = archivo_de_la_base(url_bd)
    conexion = sqlite3.connect(str(base))
    conexion.execute("CREATE TABLE prueba_respaldo (x integer)")
    conexion.commit()
    conexion.close()
    respaldo = crear_respaldo(url_bd, tmp_path / "r")

    conexion = sqlite3.connect(str(base))
    conexion.execute("DROP TABLE prueba_respaldo")
    conexion.commit()
    conexion.close()
    assert "prueba_respaldo" not in tablas(base)

    seguridad = restaurar_respaldo(respaldo, url_bd, tmp_path / "r")
    assert "prueba_respaldo" in tablas(base)
    assert seguridad.name.startswith("antes_de_restaurar_") and "prueba_respaldo" not in tablas(seguridad)
    assert seguridad not in listar_respaldos(tmp_path / "r")  # la copia de seguridad no entra en la rotación


def test_restaurar_rechaza_archivos_invalidos(motor, url_bd, tmp_path):
    roto = tmp_path / "roto.db"
    roto.write_text("esto no es una base de datos")
    with pytest.raises(ErrorDeNegocio, match="dañado"):
        restaurar_respaldo(roto, url_bd, tmp_path / "r")
    with pytest.raises(ErrorDeNegocio, match="No existe"):
        restaurar_respaldo(tmp_path / "nada.db", url_bd, tmp_path / "r")


# ---- salud con inventario ------------------------------------------------------------


def test_salud_revisa_que_el_inventario_cuadre(motor, sesion_servicios, t):
    ok = verificar_salud(motor, revisar_inventario=True)
    assert ok["estado"] == "ok" and ok["diferencias_de_inventario"] == 0
    assert "diferencias_de_inventario" not in verificar_salud(motor)

    sesion_servicios.execute(update(Existencia).values(cantidad=Existencia.cantidad + 1))  # alteración "a mano"
    sesion_servicios.commit()
    malo = verificar_salud(motor, revisar_inventario=True)
    assert malo["estado"] == "error" and malo["diferencias_de_inventario"] == 1 and "no cuadra" in malo["detalle"]
    assert verificar_salud(motor)["estado"] == "ok"  # la revisión de inventario es opcional


# ---- línea de comandos ---------------------------------------------------------------


def test_comandos_de_respaldo_y_salud(motor, url_bd, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", url_bd)
    monkeypatch.setenv("CARPETA_RESPALDOS", str(tmp_path / "r"))
    assert programa.main(["--respaldo"]) == 0
    assert "Respaldo creado" in capsys.readouterr().out
    archivo = listar_respaldos(tmp_path / "r")[0]
    assert programa.main(["--restaurar", str(archivo)]) == 0
    assert "Base restaurada" in capsys.readouterr().out
    assert programa.main(["--restaurar", str(tmp_path / "nada.db")]) == 1
    capsys.readouterr()
    assert programa.main(["--salud"]) == 0
    assert '"estado": "ok"' in capsys.readouterr().out


# ---- paginación ----------------------------------------------------------------------


def test_listar_ventas_con_desplazamiento(sesion_servicios, administrador, t):
    s = sesion_servicios
    for _ in range(5):
        registrar_venta(
            s, administrador, sucursal_id=t.principal.id, metodo_pago="efectivo",
            lineas=[{"producto_id": t.p1.id, "cantidad": 1}],
        )
    s.commit()
    numeros = lambda **kw: [v["numero"] for v in listar_ventas(s, administrador, **kw)]
    assert numeros() == [5, 4, 3, 2, 1]
    assert numeros(limite=2) == [5, 4]
    assert numeros(limite=2, desplazamiento=2) == [3, 2]
    assert numeros(limite=2, desplazamiento=4) == [1]
    assert numeros(limite=2, desplazamiento=10) == []
    assert numeros(desplazamiento=-3, limite=1) == [5]  # un desplazamiento negativo se trata como 0
