"""Pantalla de ventas: caja (POS) con lector de código de barras e historial con anulación.

Toda la lógica vive en ``app.servicios.ventas``; aquí solo se arma el carrito y se muestran
resultados. El vendedor lo decide la sesión, no esta pantalla.
"""

from __future__ import annotations

import tempfile
import webbrowser
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk

from app.db import sesion_transaccional
from app.servicios.devoluciones import previsualizar_devolucion, registrar_devolucion
from app.servicios.comprobante import comprobante_html, comprobante_texto
from app.servicios.errores import ErrorDeNegocio
from app.servicios.inventario import listar_sucursales
from app.servicios.usuarios import obtener_usuario
from app.ui import tema
from app.servicios.ventas import (
    METODOS_PAGO,
    anular_venta,
    buscar_para_venta,
    catalogo_para_venta,
    categorias_para_venta,
    crear_cliente,
    listar_clientes,
    listar_ventas,
    obtener_venta,
    producto_para_venta,
    registrar_venta,
)

ROJO = "#d64545"
VERDE = "#2e9e5b"
NARANJA = "#d98a00"
CONSUMIDOR_FINAL = "Consumidor final"
TODAS_CATEGORIAS = "Todas"
TAMANO_PAGINA = 25


class PantallaVentas(ctk.CTkFrame):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        usuario = app.usuario
        self.puede_crear = usuario.puede("ventas", "crear")
        self.puede_anular = usuario.puede("ventas", "anular")
        self.puede_devolver = usuario.puede("ventas", "devolver")
        self.pagos_mixtos: list[dict] | None = None
        self.puede_ver = usuario.puede("ventas", "ver") or usuario.puede("ventas", "ver_todas")
        self.sucursales: list[dict] = []
        self.clientes: list[dict] = []
        self.carrito: list[dict] = []  # {id, sku, nombre, precio, stock, cantidad}

        ctk.CTkLabel(self, text="Ventas", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        self.mensaje = ctk.CTkLabel(self, text="", anchor="w")
        self.mensaje.pack(fill="x", pady=2)

        self.pestanas = ctk.CTkTabview(self)
        self.pestanas.pack(fill="both", expand=True)
        if self.puede_crear:
            self._armar_caja(self.pestanas.add("Caja"))
        if self.puede_ver:
            self._armar_historial(self.pestanas.add("Historial"))

        self._cargar_sucursales()
        if self.puede_crear:
            self._cargar_clientes()
            self.caja_codigo.focus_set()
        if self.puede_ver:
            self.recargar_historial()

    # ---- utilidades -----------------------------------------------------------------

    def ejecutar(self, funcion: Callable[[Any, Any], Any], exito: str | None = None) -> tuple[bool, Any]:
        """Corre ``funcion(sesion, actor)`` en una transacción; el actor sale de la sesión."""
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

    def _cargar_sucursales(self) -> None:
        ok, sucursales = self.ejecutar(lambda s, a: listar_sucursales(s, a))
        self.sucursales = sucursales if ok else []
        if self.puede_crear:
            nombres = [s["nombre"] for s in self.sucursales] or ["—"]
            actual = self.caja_sucursal.get()
            self.caja_sucursal.configure(values=nombres)
            self.caja_sucursal.set(actual if actual in nombres else nombres[0])

    def _cargar_clientes(self) -> None:
        ok, clientes = self.ejecutar(lambda s, a: listar_clientes(s, a))
        self.clientes = clientes if ok else []
        nombres = [CONSUMIDOR_FINAL] + [c["nombre"] for c in self.clientes]
        actual = self.caja_cliente.get()
        self.caja_cliente.configure(values=nombres)
        self.caja_cliente.set(actual if actual in nombres else CONSUMIDOR_FINAL)

    def _sucursal_id(self) -> int | None:
        for sucursal in self.sucursales:
            if sucursal["nombre"] == self.caja_sucursal.get():
                return sucursal["id"]
        return None

    # ---- caja -----------------------------------------------------------------------

    def _armar_caja(self, marco: Any) -> None:
        barra = ctk.CTkFrame(marco, fg_color="transparent")
        barra.pack(fill="x", pady=(4, 6))
        ctk.CTkLabel(barra, text="Sucursal:").pack(side="left")
        self.caja_sucursal = ctk.CTkOptionMenu(
            barra, values=["—"], width=160, command=lambda _v: self._sucursal_cambiada()
        )
        self.caja_sucursal.pack(side="left", padx=(6, 14))
        self.caja_codigo = ctk.CTkEntry(
            barra, width=300, placeholder_text="Escanea el código o escribe SKU / nombre y pulsa Enter"
        )
        self.caja_codigo.pack(side="left")
        self.caja_codigo.bind("<Return>", lambda _e: self.agregar_por_texto())
        ctk.CTkButton(barra, text="Agregar", width=80, command=self.agregar_por_texto).pack(side="left", padx=6)
        self.boton_catalogo = ctk.CTkButton(
            barra, text="📋 Catálogo", width=110, fg_color=tema.SUPERFICIE_2, command=self._alternar_catalogo
        )
        self.boton_catalogo.pack(side="left")

        self.resultados = ctk.CTkFrame(marco, fg_color="transparent")
        self.resultados.pack(fill="x")

        # Catálogo: elegir productos con un clic (oculto hasta pulsar «Catálogo»).
        self.panel_catalogo = ctk.CTkFrame(marco, fg_color=tema.SUPERFICIE, border_width=1, border_color=tema.BORDE)
        filtro = ctk.CTkFrame(self.panel_catalogo, fg_color="transparent")
        filtro.pack(fill="x", padx=8, pady=(6, 2))
        ctk.CTkLabel(filtro, text="Categoría:").pack(side="left")
        self.catalogo_categoria = ctk.CTkOptionMenu(
            filtro, values=[TODAS_CATEGORIAS], width=170, command=lambda _v: self._pintar_catalogo()
        )
        self.catalogo_categoria.pack(side="left", padx=6)
        ctk.CTkLabel(filtro, text="Un clic agrega una unidad al carrito.", text_color=tema.TEXTO_SUAVE).pack(side="left", padx=10)
        self.catalogo_lista = ctk.CTkScrollableFrame(self.panel_catalogo, height=170, fg_color="transparent")
        self.catalogo_lista.pack(fill="x", padx=6, pady=(0, 6))
        self.categorias_catalogo: list[dict] = []

        self.lista_carrito = ctk.CTkScrollableFrame(marco, height=260)
        self.lista_carrito.pack(fill="both", expand=True, pady=6)

        pie = ctk.CTkFrame(marco, fg_color="transparent")
        pie.pack(fill="x")
        ctk.CTkLabel(pie, text="Cliente:").grid(row=0, column=0, sticky="w")
        self.caja_cliente = ctk.CTkOptionMenu(pie, values=[CONSUMIDOR_FINAL], width=170)
        self.caja_cliente.grid(row=0, column=1, padx=6, sticky="w")
        ctk.CTkButton(pie, text="Nuevo cliente", width=110, command=self._dialogo_cliente).grid(row=0, column=2, padx=4)
        ctk.CTkLabel(pie, text="Pago:").grid(row=0, column=3, padx=(16, 0))
        self.caja_pago = ctk.CTkOptionMenu(
            pie, values=list(METODOS_PAGO), width=130, command=lambda _v: self._actualizar_cambio()
        )
        self.caja_pago.grid(row=0, column=4, padx=6)
        ctk.CTkLabel(pie, text="Descuento ($):").grid(row=0, column=5, padx=(16, 0))
        self.caja_descuento = ctk.CTkEntry(pie, width=90, placeholder_text="0")
        self.caja_descuento.grid(row=0, column=6, padx=6)
        self.caja_descuento.bind("<KeyRelease>", lambda _e: self._actualizar_total())

        ctk.CTkLabel(pie, text="Efectivo recibido ($):").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.caja_recibido = ctk.CTkEntry(pie, width=110, placeholder_text="opcional")
        self.caja_recibido.grid(row=1, column=2, padx=4, pady=(6, 0), sticky="w")
        self.caja_recibido.bind("<KeyRelease>", lambda _e: self._actualizar_cambio())
        self.caja_cambio = ctk.CTkLabel(pie, text="", font=tema.fuente(13, True))
        self.caja_cambio.grid(row=1, column=3, columnspan=2, padx=(16, 0), pady=(6, 0), sticky="w")
        self.boton_mixto = ctk.CTkButton(
            pie, text="Dividir pago…", width=110, fg_color=tema.SUPERFICIE_2, command=self._dialogo_pago_mixto
        )
        self.boton_mixto.grid(row=1, column=5, columnspan=2, padx=(16, 0), pady=(6, 0), sticky="w")
        self.aviso_mixto = ctk.CTkLabel(marco, text="", anchor="w", text_color=tema.ACENTO_SUAVE)
        self.aviso_mixto.pack(fill="x", before=pie)

        cobro = ctk.CTkFrame(marco, fg_color="transparent")
        cobro.pack(fill="x", pady=(8, 0))
        self.caja_total = ctk.CTkLabel(cobro, text="Total: 0.00", font=ctk.CTkFont(size=22, weight="bold"))
        self.caja_total.pack(side="left")
        ctk.CTkButton(cobro, text="Cobrar", width=140, height=40, command=self.cobrar).pack(side="right")
        ctk.CTkButton(
            cobro, text="Vaciar", width=90, height=40, fg_color="gray40", command=self.vaciar
        ).pack(side="right", padx=8)

        self._pintar_carrito()

    def _sucursal_cambiada(self) -> None:
        if self.panel_catalogo.winfo_ismapped():
            self._pintar_catalogo()

    def _alternar_catalogo(self) -> None:
        if self.panel_catalogo.winfo_ismapped():
            self.panel_catalogo.pack_forget()
            return
        self.panel_catalogo.pack(fill="x", pady=(0, 4), before=self.lista_carrito)
        ok, categorias = self.ejecutar(lambda s, a: categorias_para_venta(s, a))
        self.categorias_catalogo = categorias if ok else []
        nombres = [TODAS_CATEGORIAS] + [c["nombre"] for c in self.categorias_catalogo]
        actual = self.catalogo_categoria.get()
        self.catalogo_categoria.configure(values=nombres)
        self.catalogo_categoria.set(actual if actual in nombres else TODAS_CATEGORIAS)
        self._pintar_catalogo()

    def _pintar_catalogo(self) -> None:
        sucursal = self._sucursal_id()
        for widget in self.catalogo_lista.winfo_children():
            widget.destroy()
        if sucursal is None:
            return
        categoria = next((c["id"] for c in self.categorias_catalogo if c["nombre"] == self.catalogo_categoria.get()), None)
        ok, productos = self.ejecutar(lambda s, a: catalogo_para_venta(s, a, sucursal, categoria))
        if not ok:
            return
        if not productos:
            ctk.CTkLabel(self.catalogo_lista, text="No hay productos en esta categoría.", text_color=tema.TEXTO_SUAVE).pack(pady=12)
            return
        columnas = 3
        for c in range(columnas):
            self.catalogo_lista.grid_columnconfigure(c, weight=1, uniform="cat")
        for i, p in enumerate(productos):
            stock = "servicio" if p["stock"] is None else f"stock {p['stock']}"
            agotado = p["stock"] is not None and p["stock"] <= 0
            ctk.CTkButton(
                self.catalogo_lista, text=f"{p['nombre']}\n{p['precio']:,.2f} · {stock}", height=46,
                fg_color=tema.SUPERFICIE_2, hover_color=tema.ACENTO, text_color=tema.ROJO if agotado else tema.TEXTO,
                command=lambda x=p: self._agregar_desde_catalogo(x),
            ).grid(row=i // columnas, column=i % columnas, padx=3, pady=3, sticky="ew")

    def _agregar_desde_catalogo(self, producto: dict) -> None:
        self.agregar_al_carrito(producto)

    def agregar_por_texto(self) -> None:
        texto = self.caja_codigo.get().strip()
        sucursal = self._sucursal_id()
        if not texto or sucursal is None:
            return
        for widget in self.resultados.winfo_children():
            widget.destroy()
        ok, producto = self.ejecutar(lambda s, a: producto_para_venta(s, a, texto, sucursal))
        if not ok:
            return
        if producto is not None:  # coincidencia exacta (lector de código de barras)
            self.agregar_al_carrito(producto)
            self.caja_codigo.delete(0, "end")
            return
        ok, encontrados = self.ejecutar(lambda s, a: buscar_para_venta(s, a, texto, sucursal))
        if not ok:
            return
        if not encontrados:
            self.mensaje.configure(text=f"No se encontró ningún producto activo con «{texto}».", text_color=ROJO)
            return
        self.mensaje.configure(text="Elige el producto:", text_color="gray")
        for p in encontrados:
            ctk.CTkButton(
                self.resultados,
                text=f"{p['sku']} · {p['nombre']} · {p['precio']:,.2f} · "
                f"{'servicio' if p['stock'] is None else 'stock ' + str(p['stock'])}",
                anchor="w",
                fg_color="gray30",
                command=lambda x=p: self._elegir(x),
            ).pack(fill="x", pady=1)

    def _elegir(self, producto: dict) -> None:
        for widget in self.resultados.winfo_children():
            widget.destroy()
        self.agregar_al_carrito(producto)
        self.caja_codigo.delete(0, "end")
        self.caja_codigo.focus_set()

    def agregar_al_carrito(self, producto: dict) -> None:
        for linea in self.carrito:
            if linea["id"] == producto["id"]:
                linea["cantidad"] += 1
                linea["stock"] = producto["stock"]
                break
        else:
            self.carrito.append({**producto, "cantidad": 1})
        linea = next(x for x in self.carrito if x["id"] == producto["id"])
        if linea["stock"] is not None and linea["cantidad"] > linea["stock"]:
            self.mensaje.configure(
                text=f"Aviso: {linea['nombre']} tiene {linea['stock']} en stock; la venta se rechazará si no alcanza.",
                text_color=NARANJA,
            )
        else:
            self.mensaje.configure(text="", text_color="gray")
        self._pintar_carrito()

    def _cambiar_cantidad(self, producto_id: int, delta: int) -> None:
        for linea in list(self.carrito):
            if linea["id"] == producto_id:
                linea["cantidad"] += delta
                if linea["cantidad"] <= 0:
                    self.carrito.remove(linea)
        self._pintar_carrito()

    def _quitar(self, producto_id: int) -> None:
        self.carrito = [x for x in self.carrito if x["id"] != producto_id]
        self._pintar_carrito()

    def vaciar(self) -> None:
        self.carrito = []
        self.caja_descuento.delete(0, "end")
        self._limpiar_recibido()
        self._quitar_pago_mixto("")
        self._pintar_carrito()

    def _subtotal(self) -> Decimal:
        return sum((Decimal(x["cantidad"]) * x["precio"] for x in self.carrito), Decimal("0"))

    def _descuento(self) -> Decimal:
        try:
            return Decimal(self.caja_descuento.get().strip().replace(",", ".") or "0")
        except Exception:  # noqa: BLE001  (texto no numérico: el servicio lo rechazará al cobrar)
            return Decimal("0")

    def _total_cobrar(self) -> Decimal:
        """Total a cobrar con las mismas reglas de redondeo del servicio (centavos, mitad hacia arriba)."""
        cent = Decimal("0.01")
        descuento = self._descuento().quantize(cent, rounding=ROUND_HALF_UP)
        return max((self._subtotal() - descuento).quantize(cent, rounding=ROUND_HALF_UP), Decimal("0.00"))

    def _actualizar_total(self) -> None:
        self.caja_total.configure(text=f"Total: {self._total_cobrar():,.2f}")
        if self.pagos_mixtos is not None and sum((p["monto"] for p in self.pagos_mixtos), Decimal("0")) != self._total_cobrar():
            self._quitar_pago_mixto("El total cambió: vuelve a dividir el pago.")
        self._actualizar_cambio()

    # ---- pago: efectivo recibido, cambio y pago mixto -------------------------------

    def _recibido(self) -> Decimal | None:
        texto = self.caja_recibido.get().strip().replace(",", ".")
        if not texto:
            return None
        try:
            return Decimal(texto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:  # noqa: BLE001  (el servicio lo rechazará al cobrar)
            return None

    def _limpiar_recibido(self) -> None:
        self.caja_recibido.configure(state="normal")  # un campo deshabilitado no deja borrar
        self.caja_recibido.delete(0, "end")

    def _actualizar_cambio(self) -> None:
        recibido = self._recibido()
        solo_efectivo = self.pagos_mixtos is None and self.caja_pago.get() == "efectivo"
        self.caja_recibido.configure(state="normal" if solo_efectivo else "disabled")
        if not solo_efectivo or recibido is None:
            self.caja_cambio.configure(text="", text_color=tema.TEXTO)
            return
        diferencia = recibido - self._total_cobrar()
        if diferencia >= 0:
            self.caja_cambio.configure(text=f"Cambio: {diferencia:,.2f}", text_color=tema.VERDE)
        else:
            self.caja_cambio.configure(text=f"Faltan: {-diferencia:,.2f}", text_color=tema.ROJO)

    def _dialogo_pago_mixto(self) -> None:
        total = self._total_cobrar()
        if not self.carrito or total <= 0:
            self.mensaje.configure(text="Agrega productos al carrito antes de dividir el pago.", text_color=ROJO)
            return
        DialogoPagoMixto(self, total)

    def _poner_pago_mixto(self, pagos: list[dict]) -> None:
        self.pagos_mixtos = pagos
        resumen = " + ".join(f"{p['metodo'].capitalize()} {p['monto']:,.2f}" for p in pagos)
        cambios = [p for p in pagos if p.get("recibido") is not None]
        if cambios:
            resumen += f"  (cambio {cambios[0]['recibido'] - cambios[0]['monto']:,.2f})"
        self.aviso_mixto.configure(text=f"Pago dividido: {resumen}")
        self.boton_mixto.configure(text="Quitar división", command=lambda: self._quitar_pago_mixto(""))
        self._limpiar_recibido()
        self._actualizar_cambio()

    def _quitar_pago_mixto(self, aviso: str = "") -> None:
        self.pagos_mixtos = None
        self.aviso_mixto.configure(text=aviso, text_color=NARANJA if aviso else tema.ACENTO_SUAVE)
        self.boton_mixto.configure(text="Dividir pago…", command=self._dialogo_pago_mixto)
        self._actualizar_cambio()

    def _pintar_carrito(self) -> None:
        for widget in self.lista_carrito.winfo_children():
            widget.destroy()
        negrita = ctk.CTkFont(weight="bold")
        for columna, titulo in enumerate(["SKU", "Producto", "Precio", "Cant.", "", "", "Importe", ""]):
            ctk.CTkLabel(self.lista_carrito, text=titulo, font=negrita).grid(row=0, column=columna, padx=6, sticky="w")
        if not self.carrito:
            ctk.CTkLabel(self.lista_carrito, text="El carrito está vacío.", text_color="gray").grid(
                row=1, column=0, columnspan=8, pady=24
            )
        for fila, x in enumerate(self.carrito, start=1):
            ctk.CTkLabel(self.lista_carrito, text=x["sku"]).grid(row=fila, column=0, padx=6, sticky="w")
            ctk.CTkLabel(self.lista_carrito, text=x["nombre"]).grid(row=fila, column=1, padx=6, sticky="w")
            ctk.CTkLabel(self.lista_carrito, text=f"{x['precio']:,.2f}").grid(row=fila, column=2, padx=6, sticky="e")
            ctk.CTkLabel(
                self.lista_carrito,
                text=str(x["cantidad"]),
                text_color=ROJO if x["stock"] is not None and x["cantidad"] > x["stock"] else None,
            ).grid(row=fila, column=3, padx=6)
            ctk.CTkButton(
                self.lista_carrito, text="−", width=28, command=lambda i=x["id"]: self._cambiar_cantidad(i, -1)
            ).grid(row=fila, column=4)
            ctk.CTkButton(
                self.lista_carrito, text="+", width=28, command=lambda i=x["id"]: self._cambiar_cantidad(i, 1)
            ).grid(row=fila, column=5, padx=2)
            ctk.CTkLabel(self.lista_carrito, text=f"{Decimal(x['cantidad']) * x['precio']:,.2f}").grid(
                row=fila, column=6, padx=6, sticky="e"
            )
            ctk.CTkButton(
                self.lista_carrito, text="✕", width=28, fg_color=ROJO, command=lambda i=x["id"]: self._quitar(i)
            ).grid(row=fila, column=7, padx=4)
        self._actualizar_total()

    def cobrar(self) -> None:
        sucursal = self._sucursal_id()
        if sucursal is None:
            self.mensaje.configure(text="Elige una sucursal.", text_color=ROJO)
            return
        cliente = next((c["id"] for c in self.clientes if c["nombre"] == self.caja_cliente.get()), None)
        lineas = [{"producto_id": x["id"], "cantidad": x["cantidad"]} for x in self.carrito]
        descuento = self.caja_descuento.get().strip().replace(",", ".") or "0"
        metodo = self.caja_pago.get()
        pagos: list[dict] | None = self.pagos_mixtos
        if pagos is None and metodo == "efectivo" and self.caja_recibido.get().strip():
            # El servicio comprueba que lo recibido alcance y calcula el cambio.
            pagos = [{"metodo": "efectivo", "monto": self._total_cobrar(), "recibido": self.caja_recibido.get().strip()}]

        ok, venta_id = self.ejecutar(
            lambda s, a: registrar_venta(
                s, a, sucursal_id=sucursal, lineas=lineas, metodo_pago=metodo, pagos=pagos,
                cliente_id=cliente, descuento=descuento,
            ).id
        )
        if not ok:
            return
        self.vaciar()
        if self.puede_ver:
            self.recargar_historial()
        # La venta ya quedó guardada; mostrar el comprobante es aparte (si no hay permiso de ver, solo se avisa).
        ok, venta = self.ejecutar(lambda s, a: obtener_venta(s, a, venta_id))
        if ok:
            self.mensaje.configure(text=f"Venta {venta['codigo']} registrada.", text_color=VERDE)
            DialogoComprobante(self, venta)
        else:
            self.mensaje.configure(text="Venta registrada (no tienes permiso para ver el comprobante).", text_color=VERDE)

    def _dialogo_cliente(self) -> None:
        DialogoCliente(self)

    # ---- historial ------------------------------------------------------------------

    def _armar_historial(self, marco: Any) -> None:
        barra = ctk.CTkFrame(marco, fg_color="transparent")
        barra.pack(fill="x", pady=(4, 6))
        ctk.CTkLabel(barra, text="Estado:").pack(side="left")
        self.hist_pagina = 0
        self.hist_estado = ctk.CTkOptionMenu(
            barra, values=["todas", "completada", "anulada"], width=130, command=lambda _v: self._ir_a_pagina(0)
        )
        self.hist_estado.pack(side="left", padx=6)
        ctk.CTkButton(barra, text="Actualizar", width=90, command=self.recargar_historial).pack(side="left", padx=6)
        self.hist_nota = ctk.CTkLabel(barra, text="", text_color="gray")
        self.hist_nota.pack(side="left", padx=10)
        self.hist_siguiente = ctk.CTkButton(barra, text="▶", width=36, command=lambda: self._ir_a_pagina(self.hist_pagina + 1))
        self.hist_siguiente.pack(side="right", padx=2)
        self.hist_numero = ctk.CTkLabel(barra, text="Página 1")
        self.hist_numero.pack(side="right", padx=6)
        self.hist_anterior = ctk.CTkButton(barra, text="◀", width=36, command=lambda: self._ir_a_pagina(self.hist_pagina - 1))
        self.hist_anterior.pack(side="right", padx=2)
        self.hist_lista = ctk.CTkScrollableFrame(marco)
        self.hist_lista.pack(fill="both", expand=True)

    def _ir_a_pagina(self, pagina: int) -> None:
        self.hist_pagina = max(pagina, 0)
        self.recargar_historial()

    def recargar_historial(self) -> None:
        estado = self.hist_estado.get()
        estado = None if estado == "todas" else estado
        desplazamiento = self.hist_pagina * TAMANO_PAGINA
        ok, ventas = self.ejecutar(
            lambda s, a: listar_ventas(s, a, estado=estado, limite=TAMANO_PAGINA + 1, desplazamiento=desplazamiento)
        )
        for widget in self.hist_lista.winfo_children():
            widget.destroy()
        if not ok:
            return
        hay_mas = len(ventas) > TAMANO_PAGINA
        ventas = ventas[:TAMANO_PAGINA]
        if not ventas and self.hist_pagina > 0:  # la página ya no existe (por ejemplo, tras filtrar)
            self._ir_a_pagina(self.hist_pagina - 1)
            return
        self.hist_numero.configure(text=f"Página {self.hist_pagina + 1}")
        self.hist_anterior.configure(state="normal" if self.hist_pagina > 0 else "disabled")
        self.hist_siguiente.configure(state="normal" if hay_mas else "disabled")
        ve_todas = self.app.usuario.puede("ventas", "ver_todas")
        self.hist_nota.configure(text="" if ve_todas else "Ves solo tus propias ventas.")
        negrita = ctk.CTkFont(weight="bold")
        for columna, titulo in enumerate(["Venta", "Fecha", "Vendedor", "Cliente", "Pago", "Total", "Estado", ""]):
            ctk.CTkLabel(self.hist_lista, text=titulo, font=negrita).grid(row=0, column=columna, padx=8, pady=4, sticky="w")
        if not ventas:
            ctk.CTkLabel(self.hist_lista, text="No hay ventas que mostrar.", text_color="gray").grid(
                row=1, column=0, columnspan=8, pady=20
            )
        from app.servicios.comprobante import a_hora_local

        for fila, v in enumerate(ventas, start=1):
            anulada = v["estado"] == "anulada"
            textos = [v["codigo"], a_hora_local(v["fecha"]), v["vendedor"], v["cliente"] or CONSUMIDOR_FINAL,
                      v["metodo_pago"], f"{v['total']:,.2f}", v["estado"]]
            for columna, texto in enumerate(textos):
                ctk.CTkLabel(
                    self.hist_lista, text=texto, text_color=ROJO if anulada and columna == 6 else None
                ).grid(row=fila, column=columna, padx=8, pady=2, sticky="e" if columna == 5 else "w")
            ctk.CTkButton(
                self.hist_lista, text="Ver", width=60, command=lambda i=v["id"]: self.ver_venta(i)
            ).grid(row=fila, column=7, padx=8)

    def ver_venta(self, venta_id: int) -> None:
        ok, venta = self.ejecutar(lambda s, a: obtener_venta(s, a, venta_id))
        if ok:
            DialogoComprobante(self, venta)

    def anular(self, venta_id: int, motivo: str) -> bool:
        ok, _ = self.ejecutar(lambda s, a: anular_venta(s, a, venta_id, motivo), exito="Venta anulada y stock devuelto.")
        if ok:
            self.recargar_historial()
        return ok


class _Dialogo(ctk.CTkToplevel):
    def __init__(self, pantalla: PantallaVentas, titulo: str, tamano: str) -> None:
        super().__init__(pantalla)
        self.pantalla = pantalla
        self.title(titulo)
        self.geometry(tamano)
        self.after(150, self._tomar_foco)

    def _tomar_foco(self) -> None:
        try:
            self.grab_set()
            self.focus_set()
        except Exception:  # noqa: BLE001  (la ventana pudo cerrarse antes)
            pass


class DialogoCliente(_Dialogo):
    def __init__(self, pantalla: PantallaVentas) -> None:
        super().__init__(pantalla, "Nuevo cliente", "380x280")
        self.nombre = ctk.CTkEntry(self, width=300, placeholder_text="Nombre")
        self.nombre.pack(pady=(28, 8))
        self.telefono = ctk.CTkEntry(self, width=300, placeholder_text="Teléfono (opcional)")
        self.telefono.pack(pady=8)
        self.correo = ctk.CTkEntry(self, width=300, placeholder_text="Correo (opcional)")
        self.correo.pack(pady=8)
        ctk.CTkButton(self, text="Guardar", command=self.guardar).pack(pady=12)

    def guardar(self) -> None:
        ok, cliente = self.pantalla.ejecutar(
            lambda s, a: _crear_y_devolver(s, a, self.nombre.get(), self.telefono.get(), self.correo.get()),
            exito="Cliente guardado.",
        )
        if ok:
            self.pantalla._cargar_clientes()
            self.pantalla.caja_cliente.set(cliente["nombre"])
            self.destroy()


def _crear_y_devolver(sesion: Any, actor: Any, nombre: str, telefono: str, correo: str) -> dict:
    cliente = crear_cliente(sesion, actor, nombre, telefono, correo)
    return {"id": cliente.id, "nombre": cliente.nombre}


class DialogoComprobante(_Dialogo):
    """Comprobante de la venta, con impresión (vía navegador) y, si corresponde, anulación."""

    def __init__(self, pantalla: PantallaVentas, venta: dict) -> None:
        super().__init__(pantalla, f"Comprobante {venta['codigo']}", "470x640")
        self.venta = venta
        self.empresa = pantalla.app.configuracion.nombre_empresa
        caja = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Courier", size=12), wrap="none")
        caja.pack(fill="both", expand=True, padx=16, pady=(16, 8))
        caja.insert("1.0", comprobante_texto(venta, self.empresa))
        caja.configure(state="disabled")

        botones = ctk.CTkFrame(self, fg_color="transparent")
        botones.pack(fill="x", padx=16, pady=(0, 6))
        ctk.CTkButton(botones, text="Imprimir", width=100, command=self.imprimir).pack(side="left", padx=(0, 6))
        ctk.CTkButton(botones, text="Cerrar", width=90, fg_color="gray40", command=self.destroy).pack(side="right")
        puede_anular = pantalla.puede_anular and venta["estado"] == "completada" and not venta["devoluciones"]
        if puede_anular:
            ctk.CTkButton(botones, text="Anular venta", width=110, fg_color=ROJO, command=self.anular).pack(side="right", padx=6)
        if (
            pantalla.puede_devolver and venta["estado"] == "completada"
            and any(l["disponible"] > 0 for l in venta["lineas"])
        ):
            ctk.CTkButton(botones, text="Devolver…", width=100, fg_color=tema.NARANJA, text_color="black", command=self.devolver).pack(side="right", padx=6)

        self.motivo = ctk.CTkEntry(self, placeholder_text="Motivo de la anulación (obligatorio para anular)")
        if puede_anular:
            self.motivo.pack(fill="x", padx=16, pady=(0, 14))
        self.aviso = ctk.CTkLabel(self, text="", text_color=ROJO)
        self.aviso.pack(pady=(0, 8))

    def imprimir(self) -> None:
        """Abre el comprobante en el navegador, desde donde se imprime (Ctrl+P)."""
        ruta = Path(tempfile.gettempdir()) / f"comprobante_{self.venta['codigo']}.html"
        ruta.write_text(comprobante_html(self.venta, self.empresa), encoding="utf-8")
        webbrowser.open(ruta.as_uri())

    def devolver(self) -> None:
        DialogoDevolucion(self.pantalla, self.venta, self)

    def anular(self) -> None:
        if not self.motivo.get().strip():
            self.aviso.configure(text="Escribe el motivo para anular la venta.")
            return
        if self.pantalla.anular(self.venta["id"], self.motivo.get()):
            self.destroy()
        else:
            self.aviso.configure(text=self.pantalla.mensaje.cget("text"))


class DialogoPagoMixto(_Dialogo):
    """Reparte el total entre varias formas de pago. El efectivo admite indicar lo recibido."""

    def __init__(self, pantalla: PantallaVentas, total: Decimal) -> None:
        super().__init__(pantalla, "Dividir pago", "440x420")
        self.total = total
        self.montos: dict[str, ctk.CTkEntry] = {}
        ctk.CTkLabel(self, text=f"Total a cobrar: {total:,.2f}", font=tema.fuente(18, True)).pack(pady=(16, 8))
        marco = ctk.CTkFrame(self, fg_color="transparent")
        marco.pack(padx=20)
        for fila, metodo in enumerate(METODOS_PAGO):
            ctk.CTkLabel(marco, text=metodo.capitalize(), width=100, anchor="w").grid(row=fila, column=0, pady=4)
            entrada = ctk.CTkEntry(marco, width=110, placeholder_text="0.00")
            entrada.grid(row=fila, column=1, padx=6)
            entrada.bind("<KeyRelease>", lambda _e: self._resumen())
            self.montos[metodo] = entrada
        ctk.CTkLabel(marco, text="Efectivo recibido", width=100, anchor="w").grid(row=len(METODOS_PAGO), column=0, pady=(10, 4))
        self.recibido = ctk.CTkEntry(marco, width=110, placeholder_text="opcional")
        self.recibido.grid(row=len(METODOS_PAGO), column=1, padx=6, pady=(10, 4))
        self.recibido.bind("<KeyRelease>", lambda _e: self._resumen())
        self.estado = ctk.CTkLabel(self, text="", font=tema.fuente(14, True))
        self.estado.pack(pady=(14, 4))
        self.aviso = ctk.CTkLabel(self, text="", text_color=ROJO, wraplength=380)
        self.aviso.pack()
        ctk.CTkButton(self, text="Aceptar", width=140, command=self.aceptar).pack(pady=12)
        self._resumen()

    def _numero(self, entrada: ctk.CTkEntry) -> Decimal | None:
        texto = entrada.get().strip().replace(",", ".")
        if not texto:
            return Decimal("0.00")
        try:
            return Decimal(texto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except Exception:  # noqa: BLE001
            return None

    def _resumen(self) -> None:
        montos = [self._numero(e) for e in self.montos.values()]
        if any(m is None for m in montos):
            self.estado.configure(text="Hay un monto que no es un número.", text_color=ROJO)
            return
        suma = sum(montos, Decimal("0.00"))
        diferencia = self.total - suma
        if diferencia == 0:
            self.estado.configure(text="Cuadra con el total ✔", text_color=tema.VERDE)
        elif diferencia > 0:
            self.estado.configure(text=f"Faltan {diferencia:,.2f}", text_color=tema.NARANJA)
        else:
            self.estado.configure(text=f"Sobran {-diferencia:,.2f}", text_color=tema.ROJO)

    def aceptar(self) -> None:
        pagos = []
        for metodo, entrada in self.montos.items():
            monto = self._numero(entrada)
            if monto is None:
                self.aviso.configure(text=f"El monto en {metodo} no es un número.")
                return
            if monto > 0:
                pagos.append({"metodo": metodo, "monto": monto, "recibido": None})
        if len(pagos) < 2:
            self.aviso.configure(text="Para dividir el pago usa al menos dos formas de pago.")
            return
        if sum((p["monto"] for p in pagos), Decimal("0.00")) != self.total:
            self.aviso.configure(text="Los montos deben sumar exactamente el total.")
            return
        recibido = self._numero(self.recibido)
        if recibido:
            efectivo = next((p for p in pagos if p["metodo"] == "efectivo"), None)
            if efectivo is None:
                self.aviso.configure(text="Indicaste efectivo recibido, pero no hay monto en efectivo.")
                return
            if recibido < efectivo["monto"]:
                self.aviso.configure(text="El efectivo recibido es menor que el monto en efectivo.")
                return
            efectivo["recibido"] = recibido
        self.pantalla._poner_pago_mixto(pagos)
        self.destroy()


class DialogoDevolucion(_Dialogo):
    """Elige qué unidades se devuelven, calcula el reembolso y registra la devolución."""

    def __init__(self, pantalla: PantallaVentas, venta: dict, comprobante: DialogoComprobante | None = None) -> None:
        super().__init__(pantalla, f"Devolución · {venta['codigo']}", "620x560")
        self.venta = venta
        self.comprobante = comprobante
        ctk.CTkLabel(self, text=f"Devolver de la venta {venta['codigo']}", font=tema.fuente(16, True)).pack(pady=(14, 4))
        ctk.CTkLabel(self, text="Escribe cuántas unidades regresan de cada línea.", text_color=tema.TEXTO_SUAVE).pack()
        cuerpo = ctk.CTkScrollableFrame(self, height=230)
        cuerpo.pack(fill="x", padx=14, pady=8)
        self.entradas: dict[int, ctk.CTkEntry] = {}
        for fila, linea in enumerate(venta["lineas"]):
            ctk.CTkLabel(cuerpo, text=linea["nombre"], anchor="w", width=260).grid(row=fila, column=0, padx=6, pady=3, sticky="w")
            ctk.CTkLabel(
                cuerpo, text=f"vendidas {linea['cantidad']} · devueltas {linea['devuelta']}", text_color=tema.TEXTO_SUAVE
            ).grid(row=fila, column=1, padx=6)
            if linea["disponible"] > 0:
                entrada = ctk.CTkEntry(cuerpo, width=60, placeholder_text="0")
                entrada.grid(row=fila, column=2, padx=6)
                self.entradas[linea["detalle_id"]] = entrada
            else:
                ctk.CTkLabel(cuerpo, text="—", text_color=tema.TEXTO_SUAVE).grid(row=fila, column=2)
        pie = ctk.CTkFrame(self, fg_color="transparent")
        pie.pack(fill="x", padx=14)
        self.motivo = ctk.CTkEntry(pie, placeholder_text="Motivo de la devolución (obligatorio)")
        self.motivo.pack(fill="x", pady=4)
        fila = ctk.CTkFrame(pie, fg_color="transparent")
        fila.pack(fill="x", pady=4)
        ctk.CTkLabel(fila, text="Reembolso en:").pack(side="left")
        self.metodo = ctk.CTkOptionMenu(fila, values=list(METODOS_PAGO), width=140)
        self.metodo.pack(side="left", padx=8)
        ctk.CTkButton(fila, text="Calcular reembolso", width=150, fg_color=tema.SUPERFICIE_2, command=self.calcular).pack(side="right")
        self.total = ctk.CTkLabel(self, text="", font=tema.fuente(18, True))
        self.total.pack(pady=(8, 2))
        self.aviso = ctk.CTkLabel(self, text="", text_color=ROJO, wraplength=560)
        self.aviso.pack()
        ctk.CTkButton(self, text="Registrar devolución", width=180, height=38, fg_color=tema.NARANJA, text_color="black", command=self.registrar).pack(pady=10)

    def _lineas(self) -> list[dict]:
        lineas = []
        for detalle_id, entrada in self.entradas.items():
            texto = entrada.get().strip()
            if texto and texto != "0":
                lineas.append({"detalle_id": detalle_id, "cantidad": texto})
        return lineas

    def calcular(self) -> None:
        lineas = self._lineas()
        if not lineas:
            self.aviso.configure(text="Indica al menos una cantidad a devolver.")
            return
        ok, previa = self.pantalla.ejecutar(lambda s, a: previsualizar_devolucion(s, a, self.venta["id"], lineas))
        if ok:
            self.aviso.configure(text="")
            self.total.configure(text=f"Reembolso: {previa['total']:,.2f}")
        else:
            self.aviso.configure(text=self.pantalla.mensaje.cget("text"))

    def registrar(self) -> None:
        lineas = self._lineas()
        if not lineas:
            self.aviso.configure(text="Indica al menos una cantidad a devolver.")
            return
        ok, resultado = self.pantalla.ejecutar(
            lambda s, a: registrar_devolucion(s, a, self.venta["id"], lineas, self.motivo.get(), self.metodo.get())
        )
        if not ok:
            self.aviso.configure(text=self.pantalla.mensaje.cget("text"))
            return
        self.pantalla.mensaje.configure(
            text=f"Devolución {resultado['codigo']} registrada: reembolsa {resultado['total']:,.2f}.", text_color=VERDE
        )
        if self.pantalla.puede_ver:
            self.pantalla.recargar_historial()
        if self.comprobante is not None:
            self.comprobante.destroy()
        self.destroy()
        self.pantalla.ver_venta(self.venta["id"])
