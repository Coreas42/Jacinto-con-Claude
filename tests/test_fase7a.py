"""Pruebas de la Fase 7a: configuración guardada y cierre por inactividad."""

import pytest
from sqlalchemy import select

from app.modelos import BitacoraAuditoria
from app.servicios.configuracion import (
    guardar_configuracion,
    registrar_expiracion,
    sesion_expirada,
    valores_actuales,
    ver_configuracion,
)
from app.servicios.errores import ErrorDeNegocio, PermisoDenegado


def _acciones(s, accion):
    return list(s.scalars(select(BitacoraAuditoria).where(BitacoraAuditoria.accion == accion)))


def test_valores_por_defecto_salen_del_entorno(sesion_servicios, monkeypatch):
    monkeypatch.setenv("NOMBRE_EMPRESA", "Taller Uno")
    monkeypatch.setenv("ESLOGAN_EMPRESA", "Autos")
    v = valores_actuales(sesion_servicios)
    assert v == {"nombre_empresa": "Taller Uno", "eslogan": "Autos", "inactividad_minutos": 15, "metodo_costeo": "promedio"}


def test_guardar_cambia_valores_y_deja_bitacora(sesion_servicios, administrador):
    s = sesion_servicios
    v = guardar_configuracion(s, administrador, {"nombre_empresa": "  The Garage  ", "eslogan": "", "inactividad_minutos": "30"})
    s.commit()
    assert v["nombre_empresa"] == "The Garage"
    assert v["eslogan"] == ""
    assert v["inactividad_minutos"] == 30
    eventos = _acciones(s, "configuracion_cambiada")
    assert len(eventos) == 1
    assert eventos[0].detalle["inactividad_minutos"] == [15, 30]


def test_eslogan_vacio_guardado_no_vuelve_al_del_entorno(sesion_servicios, administrador, monkeypatch):
    monkeypatch.setenv("ESLOGAN_EMPRESA", "Del entorno")
    guardar_configuracion(sesion_servicios, administrador, {"eslogan": "Propio"})
    guardar_configuracion(sesion_servicios, administrador, {"eslogan": ""})
    assert valores_actuales(sesion_servicios)["eslogan"] == ""


def test_guardar_sin_cambios_no_ensucia_la_bitacora(sesion_servicios, administrador):
    guardar_configuracion(sesion_servicios, administrador, {"inactividad_minutos": 15})
    assert _acciones(sesion_servicios, "configuracion_cambiada") == []


@pytest.mark.parametrize(
    "cambios",
    [
        {"nombre_empresa": "   "},
        {"nombre_empresa": "x" * 81},
        {"eslogan": "x" * 121},
        {"inactividad_minutos": "abc"},
        {"inactividad_minutos": -1},
        {"inactividad_minutos": 481},
        {"desconocida": "1"},
    ],
)
def test_valores_invalidos_se_rechazan_y_no_guardan_nada(sesion_servicios, administrador, cambios):
    antes = valores_actuales(sesion_servicios)
    with pytest.raises(ErrorDeNegocio):
        guardar_configuracion(sesion_servicios, administrador, {"inactividad_minutos": 20, **cambios})
    sesion_servicios.rollback()
    assert valores_actuales(sesion_servicios) == antes


def test_solo_el_administrador_configura(sesion_servicios, crear_con_rol):
    for rol in ("vendedor", "bodeguero", "contador"):
        usuario = crear_con_rol(rol)
        with pytest.raises(PermisoDenegado):
            ver_configuracion(sesion_servicios, usuario)
        with pytest.raises(PermisoDenegado):
            guardar_configuracion(sesion_servicios, usuario, {"inactividad_minutos": 5})


def test_el_administrador_ve_el_modulo_en_el_menu(sesion_servicios, administrador):
    from app.servicios.permisos import modulos_permitidos

    assert "configuracion" in modulos_permitidos(sesion_servicios, administrador)


def test_sesion_expirada():
    assert sesion_expirada(15 * 60, 15) is True
    assert sesion_expirada(15 * 60 - 1, 15) is False
    assert sesion_expirada(10**6, 0) is False  # 0 = nunca


def test_la_expiracion_queda_en_bitacora(sesion_servicios, administrador):
    registrar_expiracion(sesion_servicios, administrador.id, 15)
    sesion_servicios.commit()
    eventos = _acciones(sesion_servicios, "sesion_expirada")
    assert len(eventos) == 1 and eventos[0].detalle == {"minutos": 15}
