"""Pantalla de ventas: caja (POS) con lector de código de barras e historial con anulación.

Toda la lógica vive en ``app.servicios.ventas``; aquí solo se arma el carrito y se muestran
resultados. El vendedor lo decide la sesión, no esta pantalla.
"""

from __future__ import annotations

import tempfile
import webbrowser
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import customtkinter as ctk

from app.db import sesion_transaccional
from app.servicios.comprobante import comprobante_html, comprobante_texto
from app.servicios.errores import ErrorDeNegocio
from app.servicios.inventario import listar_sucursales
from app.servicios.usuarios import obtener_usuario
from app.servicios.ventas import (
    METODOS_PAGO,
    anular_venta,
    buscar_para_venta,
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
TAMANO_PAGINA = 25


class PantallaVentas(ctk.CTkFrame):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        usuario = app.usuario
        self.puede_crear = usuario.puede("ventas", "crear")
        self.puede_anular = usuario.puede("ventas", "anular")
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
        self.caja_sucursal = ctk.CTkOptionMenu(barra, values=["—"], width=160)
        self.caja_sucursal.pack(side="left", padx=(6, 14))
        self.caja_codigo = ctk.CTkEntry(
            barra, width=300, placeholder_text="Escanea el código o escribe SKU / nombre y pulsa Enter"
        )
        self.caja_codigo.pack(side="left")
        self.caja_codigo.bind("<Return>", lambda _e: self.agregar_por_texto())
        ctk.CTkButton(barra, text="Agregar", width=80, command=self.agregar_por_texto).pack(side="left", padx=6)

        self.resultados = ctk.CTkFrame(marco, fg_color="transparent")
        self.resultados.pack(fill="x")

        self.lista_carrito = ctk.CTkScrollableFrame(marco, height=260)
        self.lista_carrito.pack(fill="both", expand=True, pady=6)

        pie = ctk.CTkFrame(marco, fg_color="transparent")
        pie.pack(fill="x")
        ctk.CTkLabel(pie, text="Cliente:").grid(row=0, column=0, sticky="w")
        self.caja_cliente = ctk.CTkOptionMenu(pie, values=[CONSUMIDOR_FINAL], width=170)
        self.caja_cliente.grid(row=0, column=1, padx=6, sticky="w")
        ctk.CTkButton(pie, text="Nuevo cliente", width=110, command=self._dialogo_cliente).grid(row=0, column=2, padx=4)
        ctk.CTkLabel(pie, text="Pago:").grid(row=0, column=3, padx=(16, 0))
        self.caja_pago = ctk.CTkOptionMenu(pie, values=list(METODOS_PAGO), width=130)
        self.caja_pago.grid(row=0, column=4, padx=6)
        ctk.CTkLabel(pie, text="Descuento ($):").grid(row=0, column=5, padx=(16, 0))
        self.caja_descuento = ctk.CTkEntry(pie, width=90, placeholder_text="0")
        self.caja_descuento.grid(row=0, column=6, padx=6)
        self.caja_descuento.bind("<KeyRelease>", lambda _e: self._actualizar_total())

        cobro = ctk.CTkFrame(marco, fg_color="transparent")
        cobro.pack(fill="x", pady=(8, 0))
        self.caja_total = ctk.CTkLabel(cobro, text="Total: 0.00", font=ctk.CTkFont(size=22, weight="bold"))
        self.caja_total.pack(side="left")
        ctk.CTkButton(cobro, text="Cobrar", width=140, height=40, command=self.cobrar).pack(side="right")
        ctk.CTkButton(
            cobro, text="Vaciar", width=90, height=40, fg_color="gray40", command=self.vaciar
        ).pack(side="right", padx=8)

        self._pintar_carrito()

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
        self._pintar_carrito()

    def _subtotal(self) -> Decimal:
        return sum((Decimal(x["cantidad"]) * x["precio"] for x in self.carrito), Decimal("0"))

    def _descuento(self) -> Decimal:
        try:
            return Decimal(self.caja_descuento.get().strip().replace(",", ".") or "0")
        except Exception:  # noqa: BLE001  (texto no numérico: el servicio lo rechazará al cobrar)
            return Decimal("0")

    def _actualizar_total(self) -> None:
        total = self._subtotal() - self._descuento()
        self.caja_total.configure(text=f"Total: {max(total, Decimal('0')):,.2f}")

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

        ok, venta_id = self.ejecutar(
            lambda s, a: registrar_venta(
                s, a, sucursal_id=sucursal, lineas=lineas, metodo_pago=metodo,
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
        if pantalla.puede_anular and venta["estado"] == "completada":
            ctk.CTkButton(botones, text="Anular venta", width=110, fg_color=ROJO, command=self.anular).pack(side="right", padx=6)

        self.motivo = ctk.CTkEntry(self, placeholder_text="Motivo de la anulación (obligatorio para anular)")
        if pantalla.puede_anular and venta["estado"] == "completada":
            self.motivo.pack(fill="x", padx=16, pady=(0, 14))
        self.aviso = ctk.CTkLabel(self, text="", text_color=ROJO)
        self.aviso.pack(pady=(0, 8))

    def imprimir(self) -> None:
        """Abre el comprobante en el navegador, desde donde se imprime (Ctrl+P)."""
        ruta = Path(tempfile.gettempdir()) / f"comprobante_{self.venta['codigo']}.html"
        ruta.write_text(comprobante_html(self.venta, self.empresa), encoding="utf-8")
        webbrowser.open(ruta.as_uri())

    def anular(self) -> None:
        if not self.motivo.get().strip():
            self.aviso.configure(text="Escribe el motivo para anular la venta.")
            return
        if self.pantalla.anular(self.venta["id"], self.motivo.get()):
            self.destroy()
        else:
            self.aviso.configure(text=self.pantalla.mensaje.cget("text"))
