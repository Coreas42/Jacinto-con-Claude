"""Gastos: registro, listado por periodo y resultado (utilidad bruta − gastos = utilidad neta)."""

from __future__ import annotations

from datetime import date
from typing import Any

import customtkinter as ctk

from app.servicios.errores import ErrorDeNegocio
from app.servicios.gastos import CATEGORIAS, anular_gasto, crear_gasto, gastos_por_categoria, listar_gastos, total_gastos
from app.servicios.inventario import listar_sucursales
from app.servicios.reportes import resultado_del_periodo
from app.ui import tema
from app.ui.comun import Dialogo, DialogoMotivo, PantallaBase, pintar_tabla
from app.ui.tema import TarjetaKPI

TODAS = "Todas"


class PantallaGastos(PantallaBase):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, app, "Gastos")
        u = app.usuario
        self.puede_crear = u.puede("gastos", "crear")
        self.puede_anular = u.puede("gastos", "anular")
        self.sucursales: list[dict] = []

        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", pady=(4, 6))
        hoy = date.today()
        ctk.CTkLabel(barra, text="Desde:").pack(side="left")
        self.desde = ctk.CTkEntry(barra, width=100)
        self.desde.insert(0, hoy.replace(day=1).isoformat())
        self.desde.pack(side="left", padx=(4, 10))
        ctk.CTkLabel(barra, text="Hasta:").pack(side="left")
        self.hasta = ctk.CTkEntry(barra, width=100)
        self.hasta.insert(0, hoy.isoformat())
        self.hasta.pack(side="left", padx=(4, 10))
        self.categoria = ctk.CTkOptionMenu(barra, values=[TODAS, *CATEGORIAS], width=140, command=lambda _v: self.recargar())
        self.categoria.pack(side="left", padx=4)
        ctk.CTkButton(barra, text="Filtrar", width=80, command=self.recargar).pack(side="left", padx=6)
        if self.puede_crear:
            ctk.CTkButton(barra, text="+ Nuevo gasto", command=lambda: DialogoGasto(self)).pack(side="right")

        self.indicadores = ctk.CTkFrame(self, fg_color="transparent")
        self.indicadores.pack(fill="x", pady=(0, 6))
        self.resumen_categorias = ctk.CTkLabel(self, text="", anchor="w", text_color=tema.TEXTO_SUAVE)
        self.resumen_categorias.pack(fill="x")
        self.tabla = ctk.CTkScrollableFrame(self)
        self.tabla.pack(fill="both", expand=True)

        ok, sucursales = self.ejecutar(lambda s, a: listar_sucursales(s, a))
        self.sucursales = sucursales if ok else []
        self.recargar()

    def _fechas(self) -> tuple[date | None, date | None]:
        def leer(entrada: ctk.CTkEntry) -> date | None:
            texto = entrada.get().strip()
            if not texto:
                return None
            try:
                return date.fromisoformat(texto)
            except ValueError:
                raise ErrorDeNegocio(f"Fecha no válida: «{texto}». Usa AAAA-MM-DD, por ejemplo 2026-10-31.") from None

        return leer(self.desde), leer(self.hasta)

    def recargar(self) -> None:
        try:
            desde, hasta = self._fechas()
        except ErrorDeNegocio as error:
            self.mensaje.configure(text=str(error), text_color=tema.ROJO)
            return
        categoria = None if self.categoria.get() == TODAS else self.categoria.get()
        ok, datos = self.ejecutar(
            lambda s, a: (
                listar_gastos(s, a, desde, hasta, categoria),
                total_gastos(s, a, desde, hasta, categoria),
                gastos_por_categoria(s, a, desde, hasta),
            )
        )
        if not ok:
            return
        gastos, total, por_categoria = datos
        self.mensaje.configure(text="", text_color=tema.TEXTO_SUAVE)

        # Resultado del periodo: solo quien puede ver costos (contador, administrador).
        ok_r, resultado = self.ejecutar(lambda s, a: resultado_del_periodo(s, a, desde, hasta))
        if not ok_r:
            self.mensaje.configure(text="")
            resultado = None
        for widget in self.indicadores.winfo_children():
            widget.destroy()
        tarjetas = []
        if resultado is not None:
            t = TarjetaKPI(self.indicadores, "💰", "Utilidad bruta")
            t.poner(tema.dinero(resultado["utilidad_bruta"]), "ventas − costo")
            tarjetas.append(t)
        t = TarjetaKPI(self.indicadores, "💸", "Gastos del periodo")
        t.poner(tema.dinero(total), f"{len(gastos)} registro(s)")
        tarjetas.append(t)
        if resultado is not None:
            t = TarjetaKPI(self.indicadores, "📈", "Utilidad neta")
            neta = resultado["utilidad_neta"]
            margen = "" if resultado["margen_neto"] is None else f"margen {resultado['margen_neto']}%"
            t.poner(tema.dinero(neta), margen, tema.VERDE if neta >= 0 else tema.ROJO)
            tarjetas.append(t)
        for columna, tarjeta in enumerate(tarjetas):
            self.indicadores.grid_columnconfigure(columna, weight=1, uniform="g")
            tarjeta.grid(row=0, column=columna, sticky="nsew", padx=(0 if columna == 0 else 8, 0))
        self.resumen_categorias.configure(
            text=" · ".join(f"{c['categoria']}: {c['total']:,.2f}" for c in por_categoria)
        )

        def accion(g: dict):
            def crear(master: Any) -> ctk.CTkButton:
                return ctk.CTkButton(
                    master, text="Anular", width=70, fg_color=tema.SUPERFICIE_2,
                    command=lambda: DialogoMotivo(
                        self, "Anular gasto", f"¿Anular el gasto «{g['descripcion']}» por {g['monto']:,.2f}?",
                        lambda s, a, motivo: anular_gasto(s, a, g["id"], motivo), "Gasto anulado.",
                    ),
                )
            return crear

        pintar_tabla(
            self.tabla, ["Fecha", "Categoría", "Descripción", "Sucursal", "Monto", "Registró", ""],
            [[g["fecha"].isoformat(), g["categoria"], g["descripcion"], g["sucursal"], f"{g['monto']:,.2f}",
              g["registrado_por"], accion(g) if self.puede_anular else ""] for g in gastos],
            derecha={4}, vacio="No hay gastos en este periodo.",
        )


class DialogoGasto(Dialogo):
    def __init__(self, pantalla: PantallaGastos) -> None:
        super().__init__(pantalla, "Nuevo gasto", "420x430")
        self.fecha = ctk.CTkEntry(self, width=340, placeholder_text="Fecha AAAA-MM-DD")
        self.fecha.insert(0, date.today().isoformat())
        self.fecha.pack(pady=(24, 8))
        self.categoria = ctk.CTkOptionMenu(self, values=list(CATEGORIAS), width=340)
        self.categoria.pack(pady=8)
        self.descripcion = ctk.CTkEntry(self, width=340, placeholder_text="Descripción (ej. Recibo de luz de octubre)")
        self.descripcion.pack(pady=8)
        self.monto = ctk.CTkEntry(self, width=340, placeholder_text="Monto")
        self.monto.pack(pady=8)
        nombres = ["General (todo el negocio)"] + [s["nombre"] for s in pantalla.sucursales]
        self.sucursal = ctk.CTkOptionMenu(self, values=nombres, width=340)
        self.sucursal.pack(pady=8)
        ctk.CTkButton(self, text="Guardar", command=self.guardar).pack(pady=16)

    def guardar(self) -> None:
        sucursal = next((s["id"] for s in self.pantalla.sucursales if s["nombre"] == self.sucursal.get()), None)
        ok, _ = self.pantalla.ejecutar(
            lambda s, a: crear_gasto(
                s, a, categoria=self.categoria.get(), descripcion=self.descripcion.get(),
                monto=self.monto.get(), fecha=self.fecha.get(), sucursal_id=sucursal,
            ),
            exito="Gasto registrado.",
        )
        if ok:
            self.pantalla.recargar()
            self.destroy()
