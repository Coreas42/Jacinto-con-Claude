"""Pantalla de reportes: ventas agrupadas (con utilidad si el rol la puede ver) e inventario valorizado."""

from __future__ import annotations

from datetime import date
from typing import Any, Callable

import customtkinter as ctk

from app.db import sesion_transaccional
from app.servicios.errores import ErrorDeNegocio
from app.servicios.inventario import listar_sucursales
from app.servicios.reportes import (
    exportar_detalle_ventas_csv,
    exportar_valorizado_csv,
    exportar_ventas_agrupadas_csv,
    inventario_valorizado,
    rango_local,
    resumen_ventas,
    ventas_agrupadas,
)
from app.servicios.usuarios import obtener_usuario

ROJO = "#d64545"
VERDE = "#2e9e5b"
TODAS = "Todas"
AGRUPAR = {"Por día": "dia", "Por vendedor": "vendedor", "Por producto": "producto",
           "Por categoría": "categoria", "Por sucursal": "sucursal"}


class PantallaReportes(ctk.CTkFrame):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.puede_exportar = app.usuario.puede("reportes", "exportar")
        self.sucursales: list[dict] = []

        ctk.CTkLabel(self, text="Reportes", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        self.mensaje = ctk.CTkLabel(self, text="", anchor="w")
        self.mensaje.pack(fill="x", pady=2)

        pestanas = ctk.CTkTabview(self)
        pestanas.pack(fill="both", expand=True)
        self._armar_ventas(pestanas.add("Ventas"))
        self._armar_valorizado(pestanas.add("Inventario valorizado"))

        ok, sucursales = self.ejecutar(lambda s, a: listar_sucursales(s, a))
        self.sucursales = sucursales if ok else []
        nombres = [TODAS] + [s["nombre"] for s in self.sucursales]
        for selector in (self.v_sucursal, self.i_sucursal):
            selector.configure(values=nombres)
            selector.set(TODAS)
        self.generar_ventas()
        self.generar_valorizado()

    # ---- utilidades -----------------------------------------------------------------

    def ejecutar(self, funcion: Callable[[Any, Any], Any], exito: str | None = None) -> tuple[bool, Any]:
        try:
            with sesion_transaccional(self.app.fabrica) as sesion:
                actor = obtener_usuario(sesion, self.app.usuario.id)
                resultado = funcion(sesion, actor)
        except ErrorDeNegocio as error:
            self.mensaje.configure(text=str(error), text_color=ROJO)
            return False, None
        if exito:
            self.mensaje.configure(text=exito, text_color=VERDE)
        return True, resultado

    def _sucursal_id(self, selector: Any) -> int | None:
        for sucursal in self.sucursales:
            if sucursal["nombre"] == selector.get():
                return sucursal["id"]
        return None

    @staticmethod
    def _leer_fecha(entrada: Any) -> date | None:
        texto = entrada.get().strip()
        if not texto:
            return None
        try:
            return date.fromisoformat(texto)
        except ValueError:
            raise ErrorDeNegocio(f"Fecha no válida: «{texto}». Usa el formato AAAA-MM-DD, por ejemplo 2026-10-31.") from None

    def _guardar_csv(self, contenido: str, nombre: str) -> None:
        from tkinter import filedialog

        ruta = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile=nombre)
        if ruta:
            with open(ruta, "w", encoding="utf-8-sig", newline="") as archivo:
                archivo.write(contenido)
            self.mensaje.configure(text=f"Exportado a {ruta}", text_color=VERDE)

    @staticmethod
    def _tabla(marco: Any, encabezados: list[str], filas: list[list[str]], derecha_desde: int = 1) -> None:
        for widget in marco.winfo_children():
            widget.destroy()
        negrita = ctk.CTkFont(weight="bold")
        for columna, titulo in enumerate(encabezados):
            ctk.CTkLabel(marco, text=titulo, font=negrita).grid(
                row=0, column=columna, padx=8, pady=4, sticky="e" if columna >= derecha_desde else "w"
            )
        if not filas:
            ctk.CTkLabel(marco, text="No hay datos para mostrar.", text_color="gray").grid(
                row=1, column=0, columnspan=len(encabezados), pady=20
            )
        for fila, valores in enumerate(filas, start=1):
            for columna, valor in enumerate(valores):
                ctk.CTkLabel(marco, text=valor).grid(
                    row=fila, column=columna, padx=8, pady=2, sticky="e" if columna >= derecha_desde else "w"
                )

    # ---- ventas ---------------------------------------------------------------------

    def _armar_ventas(self, marco: Any) -> None:
        barra = ctk.CTkFrame(marco, fg_color="transparent")
        barra.pack(fill="x", pady=(4, 6))
        hoy = date.today()
        ctk.CTkLabel(barra, text="Desde:").pack(side="left")
        self.v_desde = ctk.CTkEntry(barra, width=100)
        self.v_desde.insert(0, hoy.replace(day=1).isoformat())
        self.v_desde.pack(side="left", padx=(4, 10))
        ctk.CTkLabel(barra, text="Hasta:").pack(side="left")
        self.v_hasta = ctk.CTkEntry(barra, width=100)
        self.v_hasta.insert(0, hoy.isoformat())
        self.v_hasta.pack(side="left", padx=(4, 10))
        self.v_sucursal = ctk.CTkOptionMenu(barra, values=[TODAS], width=130)
        self.v_sucursal.pack(side="left", padx=4)
        self.v_agrupar = ctk.CTkOptionMenu(barra, values=list(AGRUPAR), width=130)
        self.v_agrupar.pack(side="left", padx=4)
        ctk.CTkButton(barra, text="Generar", width=80, command=self.generar_ventas).pack(side="left", padx=6)
        if self.puede_exportar:
            ctk.CTkButton(barra, text="Exportar resumen", width=120, command=self.exportar_resumen).pack(side="left", padx=2)
            ctk.CTkButton(barra, text="Exportar ventas", width=110, command=self.exportar_detalle).pack(side="left", padx=2)

        self.v_resumen = ctk.CTkLabel(marco, text="", anchor="w", justify="left", font=ctk.CTkFont(size=14))
        self.v_resumen.pack(fill="x", pady=4)
        self.v_tabla = ctk.CTkScrollableFrame(marco)
        self.v_tabla.pack(fill="both", expand=True)

    def _filtros_ventas(self) -> tuple[Any, Any, int | None]:
        desde, hasta = rango_local(self._leer_fecha(self.v_desde), self._leer_fecha(self.v_hasta))
        return desde, hasta, self._sucursal_id(self.v_sucursal)

    def generar_ventas(self) -> None:
        try:
            desde, hasta, sucursal = self._filtros_ventas()
        except ErrorDeNegocio as error:
            self.mensaje.configure(text=str(error), text_color=ROJO)
            return
        por = AGRUPAR[self.v_agrupar.get()]
        ok, datos = self.ejecutar(
            lambda s, a: (
                resumen_ventas(s, a, desde, hasta, sucursal),
                ventas_agrupadas(s, a, por, desde, hasta, sucursal),
            )
        )
        if not ok:
            return
        self.mensaje.configure(text="", text_color="gray")
        resumen, filas = datos
        texto = (
            f"{resumen['ventas']} ventas · {resumen['unidades']} unidades · Ingreso {resumen['ingreso']:,.2f} · "
            f"Ticket promedio {resumen['ticket_promedio']:,.2f}"
        )
        if resumen["utilidad"] is not None:
            margen = "" if resumen["margen"] is None else f" ({resumen['margen']}%)"
            texto += f"\nCosto {resumen['costo']:,.2f} · Utilidad bruta {resumen['utilidad']:,.2f}{margen}"
        if resumen["anuladas"]:
            texto += f"\nAnuladas (no cuentan): {resumen['anuladas']} por {resumen['total_anuladas']:,.2f}"
        self.v_resumen.configure(text=texto)

        con_costos = resumen["utilidad"] is not None
        encabezados = [self.v_agrupar.get().replace("Por ", "").capitalize(), "Ventas", "Unidades", "Ingreso"]
        if con_costos:
            encabezados += ["Costo", "Utilidad", "Margen %"]
        tabla = []
        for f in filas:
            fila = [str(f["clave"]), str(f["ventas"]), str(f["unidades"]), f"{f['ingreso']:,.2f}"]
            if con_costos:
                fila += [f"{f['costo']:,.2f}", f"{f['utilidad']:,.2f}", "—" if f["margen"] is None else f"{f['margen']}"]
            tabla.append(fila)
        self._tabla(self.v_tabla, encabezados, tabla)

    def exportar_resumen(self) -> None:
        try:
            desde, hasta, sucursal = self._filtros_ventas()
        except ErrorDeNegocio as error:
            self.mensaje.configure(text=str(error), text_color=ROJO)
            return
        por = AGRUPAR[self.v_agrupar.get()]
        ok, contenido = self.ejecutar(lambda s, a: exportar_ventas_agrupadas_csv(s, a, por, desde, hasta, sucursal))
        if ok:
            self._guardar_csv(contenido, f"ventas_por_{por}.csv")

    def exportar_detalle(self) -> None:
        try:
            desde, hasta, sucursal = self._filtros_ventas()
        except ErrorDeNegocio as error:
            self.mensaje.configure(text=str(error), text_color=ROJO)
            return
        ok, contenido = self.ejecutar(lambda s, a: exportar_detalle_ventas_csv(s, a, desde, hasta, sucursal))
        if ok:
            self._guardar_csv(contenido, "ventas.csv")

    # ---- inventario valorizado ------------------------------------------------------

    def _armar_valorizado(self, marco: Any) -> None:
        barra = ctk.CTkFrame(marco, fg_color="transparent")
        barra.pack(fill="x", pady=(4, 6))
        ctk.CTkLabel(barra, text="Sucursal:").pack(side="left")
        self.i_sucursal = ctk.CTkOptionMenu(barra, values=[TODAS], width=150, command=lambda _v: self.generar_valorizado())
        self.i_sucursal.pack(side="left", padx=6)
        if self.puede_exportar:
            ctk.CTkButton(barra, text="Exportar CSV", width=110, command=self.exportar_valorizado).pack(side="left", padx=6)
        self.i_resumen = ctk.CTkLabel(marco, text="", anchor="w", justify="left", font=ctk.CTkFont(size=14))
        self.i_resumen.pack(fill="x", pady=4)
        self.i_tabla = ctk.CTkScrollableFrame(marco)
        self.i_tabla.pack(fill="both", expand=True)

    def generar_valorizado(self) -> None:
        sucursal = self._sucursal_id(self.i_sucursal)
        ok, datos = self.ejecutar(lambda s, a: inventario_valorizado(s, a, sucursal))
        if not ok:
            self.i_resumen.configure(text="")
            self._tabla(self.i_tabla, [], [])
            return
        categorias = " · ".join(f"{c['categoria']}: {c['valor']:,.2f}" for c in datos["por_categoria"])
        self.i_resumen.configure(
            text=f"{datos['total_unidades']} unidades · Valor total {datos['total_valor']:,.2f}\n{categorias}"
        )
        self._tabla(
            self.i_tabla,
            ["SKU", "Producto", "Categoría", "Stock", "Costo prom.", "Valor"],
            [[f["sku"], f["nombre"], f["categoria"], str(f["stock"]), f"{f['costo']:,.2f}", f"{f['valor']:,.2f}"]
             for f in datos["filas"]],
            derecha_desde=3,
        )

    def exportar_valorizado(self) -> None:
        sucursal = self._sucursal_id(self.i_sucursal)
        ok, contenido = self.ejecutar(lambda s, a: exportar_valorizado_csv(s, a, sucursal))
        if ok:
            self._guardar_csv(contenido, "inventario_valorizado.csv")
