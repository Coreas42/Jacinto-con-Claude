"""Panel de inicio: indicadores del día, últimas ventas, más vendidos y gráfica de 7 días.

Cada bloque aparece solo si el usuario tiene permiso para verlo (el servicio devuelve ``None``).
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

import customtkinter as ctk

from app.db import sesion_transaccional
from app.servicios.comprobante import a_hora_local
from app.servicios.errores import ErrorDeNegocio
from app.servicios.inicio import panel_inicio
from app.servicios.usuarios import obtener_usuario
from app.ui import tema
from app.ui.tema import Tarjeta, TarjetaKPI


class PantallaInicio(ctk.CTkFrame):
    def __init__(self, master: Any, app: Any, navegar: Callable[[str], None]) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.navegar = navegar
        self.datos: dict = {}

        cabecera = ctk.CTkFrame(self, fg_color="transparent")
        cabecera.pack(fill="x")
        ctk.CTkLabel(cabecera, text="Inicio", font=tema.fuente(22, True)).pack(side="left")
        ctk.CTkButton(cabecera, text="⟳ Actualizar", width=110, fg_color=tema.SUPERFICIE_2, command=self.recargar).pack(side="right")
        if app.usuario.puede("ventas", "crear"):
            ctk.CTkButton(
                cabecera, text="🛒 Nueva venta", width=130, command=lambda: navegar("ventas")
            ).pack(side="right", padx=8)
        self.mensaje = ctk.CTkLabel(self, text="", anchor="w", text_color=tema.ROJO)
        self.mensaje.pack(fill="x")

        self.indicadores = ctk.CTkFrame(self, fg_color="transparent")
        self.indicadores.pack(fill="x", pady=(6, 8))
        self.aviso = ctk.CTkButton(
            self, text="", anchor="w", fg_color="#3a2a10", hover_color="#4d3813", text_color=tema.NARANJA,
            command=lambda: navegar("inventario"),
        )

        medio = self.medio = ctk.CTkFrame(self, fg_color="transparent")
        medio.pack(fill="both", expand=True)
        medio.grid_columnconfigure(0, weight=3)
        medio.grid_columnconfigure(1, weight=2)
        medio.grid_rowconfigure(0, weight=1)
        medio.grid_rowconfigure(1, weight=1)

        self.caja_ventas = Tarjeta(medio, "Últimas ventas")
        self.caja_ventas.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        self.tabla_ventas = ctk.CTkFrame(self.caja_ventas, fg_color="transparent")
        self.tabla_ventas.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.caja_top = Tarjeta(medio, "Más vendidos (30 días)")
        self.caja_top.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        self.lista_top = ctk.CTkFrame(self.caja_top, fg_color="transparent")
        self.lista_top.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self.caja_grafica = Tarjeta(medio, "Últimos 7 días")
        self.caja_grafica.grid(row=1, column=0, columnspan=2, sticky="nsew")
        self.lienzo = tk.Canvas(self.caja_grafica, height=190, highlightthickness=0, bg=tema.SUPERFICIE)
        self.lienzo.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.lienzo.bind("<Configure>", lambda _e: self._dibujar_grafica())

        self.recargar()

    # ---- datos ----------------------------------------------------------------------

    def recargar(self) -> None:
        try:
            with sesion_transaccional(self.app.fabrica) as sesion:
                actor = obtener_usuario(sesion, self.app.usuario.id)
                self.datos = panel_inicio(sesion, actor)
        except ErrorDeNegocio as error:
            self.mensaje.configure(text=str(error))
            return
        self.mensaje.configure(text="")
        self._pintar_indicadores()
        self._pintar_ventas()
        self._pintar_top()
        self._dibujar_grafica()

    # ---- indicadores ----------------------------------------------------------------

    def _pintar_indicadores(self) -> None:
        for widget in self.indicadores.winfo_children():
            widget.destroy()
        d = self.datos
        tarjetas: list[TarjetaKPI] = []

        hoy = d["ventas_hoy"]
        if hoy is not None:
            solo_propias = hoy["utilidad"] is None
            t = TarjetaKPI(self.indicadores, "🛒", "Mis ventas del día" if solo_propias else "Ventas del día")
            texto, color = tema.texto_cambio(d["cambio_ventas"])
            t.poner(tema.dinero(hoy["ingreso"]), texto or f"{hoy['ventas']} venta(s)", color)
            tarjetas.append(t)
            if not solo_propias:
                t = TarjetaKPI(self.indicadores, "💰", "Ganancia del día")
                texto, color = tema.texto_cambio(d["cambio_ganancia"])
                t.poner(tema.dinero(hoy["utilidad"]), texto or "utilidad bruta", color)
                tarjetas.append(t)
            t = TarjetaKPI(self.indicadores, "📦", "Productos vendidos")
            t.poner(str(hoy["unidades"]), "unidades hoy")
            tarjetas.append(t)

        inventario = d["inventario"]
        if inventario is not None:
            t = TarjetaKPI(self.indicadores, "🏬", "Inventario total")
            t.poner(str(inventario["unidades"]), f"{inventario['productos']} productos")
            tarjetas.append(t)
        if d["clientes"] is not None:
            t = TarjetaKPI(self.indicadores, "👥", "Clientes")
            t.poner(str(d["clientes"]), "activos")
            tarjetas.append(t)

        for columna, tarjeta in enumerate(tarjetas):
            self.indicadores.grid_columnconfigure(columna, weight=1, uniform="kpi")
            tarjeta.grid(row=0, column=columna, sticky="nsew", padx=(0 if columna == 0 else 8, 0))

        if inventario is not None and inventario["stock_bajo"]:
            self.aviso.configure(text=f"  ⚠  {inventario['stock_bajo']} producto(s) con stock bajo. Clic para revisar el inventario.")
            self.aviso.pack(fill="x", pady=(0, 8), before=self.medio)
        else:
            self.aviso.pack_forget()

    # ---- listas ---------------------------------------------------------------------

    def _pintar_ventas(self) -> None:
        for widget in self.tabla_ventas.winfo_children():
            widget.destroy()
        ventas = self.datos["ultimas_ventas"]
        if ventas is None:
            ctk.CTkLabel(self.tabla_ventas, text="Sin permiso para ver ventas.", text_color=tema.TEXTO_SUAVE).pack(pady=20)
            return
        negrita = tema.fuente(12, True)
        for columna, titulo in enumerate(["Venta", "Fecha", "Cliente", "Total", "Vendedor", "Estado"]):
            ctk.CTkLabel(self.tabla_ventas, text=titulo, font=negrita, text_color=tema.TEXTO_SUAVE).grid(
                row=0, column=columna, padx=8, sticky="e" if columna == 3 else "w"
            )
        if not ventas:
            ctk.CTkLabel(self.tabla_ventas, text="Aún no hay ventas.", text_color=tema.TEXTO_SUAVE).grid(
                row=1, column=0, columnspan=6, pady=18
            )
        for fila, v in enumerate(ventas, start=1):
            anulada = v["estado"] == "anulada"
            valores = [v["codigo"], a_hora_local(v["fecha"]), v["cliente"] or "Cliente general",
                       f"{v['total']:,.2f}", v["vendedor"], "Anulada" if anulada else "OK"]
            for columna, valor in enumerate(valores):
                color = tema.ROJO if anulada and columna == 5 else (tema.VERDE if columna == 5 else None)
                ctk.CTkLabel(self.tabla_ventas, text=valor, text_color=color).grid(
                    row=fila, column=columna, padx=8, pady=1, sticky="e" if columna == 3 else "w"
                )

    def _pintar_top(self) -> None:
        for widget in self.lista_top.winfo_children():
            widget.destroy()
        top = self.datos["mas_vendidos"]
        if top is None:
            ctk.CTkLabel(self.lista_top, text="Sin permiso para ver reportes.", text_color=tema.TEXTO_SUAVE).pack(pady=20)
            return
        if not top:
            ctk.CTkLabel(self.lista_top, text="Aún no hay ventas.", text_color=tema.TEXTO_SUAVE).pack(pady=18)
        for posicion, fila in enumerate(sorted(top, key=lambda f: (-f["unidades"], f["clave"])), start=1):
            linea = ctk.CTkFrame(self.lista_top, fg_color="transparent")
            linea.pack(fill="x", pady=2)
            ctk.CTkLabel(
                linea, text=str(posicion), width=26, height=26, corner_radius=13, fg_color=tema.SUPERFICIE_2,
                text_color=tema.ACENTO_SUAVE,
            ).pack(side="left", padx=(0, 8))
            ctk.CTkLabel(linea, text=str(fila["clave"]), anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(linea, text=str(fila["unidades"]), font=tema.fuente(13, True)).pack(side="right")

    # ---- gráfica --------------------------------------------------------------------

    def _dibujar_grafica(self) -> None:
        c = self.lienzo
        c.delete("all")
        serie = self.datos.get("serie") if self.datos else None
        ancho, alto = c.winfo_width(), c.winfo_height()
        if serie is None:
            c.create_text(ancho / 2, alto / 2, text="Sin permiso para ver reportes.", fill=tema.TEXTO_SUAVE)
            return
        if ancho < 120 or alto < 80:
            return
        con_utilidad = serie[0]["utilidad"] is not None
        maximo = max([f["ingreso"] for f in serie] + ([f["utilidad"] for f in serie] if con_utilidad else []) + [1])
        izq, der, arriba, abajo = 56, 12, 22, 26
        area_alto, area_ancho = alto - arriba - abajo, ancho - izq - der

        for i in range(5):  # líneas guía con su valor
            y = arriba + area_alto * i / 4
            c.create_line(izq, y, ancho - der, y, fill=tema.BORDE)
            c.create_text(izq - 6, y, text=f"{float(maximo) * (4 - i) / 4:,.0f}", anchor="e", fill=tema.TEXTO_SUAVE, font=("TkDefaultFont", 9))

        paso = area_ancho / len(serie)
        barra = min(26.0, paso / (3 if con_utilidad else 2))
        for i, fila in enumerate(serie):
            centro = izq + paso * (i + 0.5)
            series = [(fila["ingreso"], tema.ACENTO)] + ([(fila["utilidad"], tema.ACENTO_SUAVE)] if con_utilidad else [])
            inicio = centro - barra * len(series) / 2
            for k, (valor, color) in enumerate(series):
                altura = float(valor) / float(maximo) * area_alto if valor > 0 else 0
                x0 = inicio + k * barra
                c.create_rectangle(x0 + 1, arriba + area_alto - altura, x0 + barra - 1, arriba + area_alto, fill=color, outline="")
            c.create_text(centro, alto - 10, text=fila["dia"].strftime("%d/%m"), fill=tema.TEXTO_SUAVE, font=("TkDefaultFont", 9))

        c.create_rectangle(ancho - 190, 4, ancho - 178, 16, fill=tema.ACENTO, outline="")
        c.create_text(ancho - 174, 10, text="Ventas", anchor="w", fill=tema.TEXTO_SUAVE, font=("TkDefaultFont", 9))
        if con_utilidad:
            c.create_rectangle(ancho - 110, 4, ancho - 98, 16, fill=tema.ACENTO_SUAVE, outline="")
            c.create_text(ancho - 94, 10, text="Ganancia", anchor="w", fill=tema.TEXTO_SUAVE, font=("TkDefaultFont", 9))
