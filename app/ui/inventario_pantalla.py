"""Pantalla de inventario: existencias por sucursal, compras, mermas, ajustes, traslados y kardex."""

from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk

from app.db import sesion_transaccional
from app.servicios.catalogo import obtener_por_codigo
from app.servicios.errores import ErrorDeNegocio
from app.servicios.inventario import (
    ajustar_stock,
    capas_de_producto,
    crear_proveedor,
    crear_sucursal,
    existencias,
    exportar_existencias_csv,
    exportar_kardex_csv,
    kardex,
    listar_proveedores,
    listar_sucursales,
    registrar_compra,
    registrar_merma,
    trasladar,
)
from app.servicios.usuarios import obtener_usuario

ROJO = "#d64545"
VERDE = "#2e9e5b"
NARANJA = "#d98a00"


def _producto_por_codigo(sesion: Any, actor: Any, codigo: str) -> dict:
    producto = obtener_por_codigo(sesion, actor, codigo)
    if producto is None:
        raise ErrorDeNegocio(f"No hay un producto activo con el código '{codigo.strip()}'.")
    return producto


class PantallaInventario(ctk.CTkFrame):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        usuario = app.usuario
        self.puede_crear = usuario.puede("inventario", "crear")
        self.puede_editar = usuario.puede("inventario", "editar")
        self.puede_exportar = usuario.puede("inventario", "exportar")
        self.sucursales: list[dict] = []

        ctk.CTkLabel(self, text="Inventario", font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")

        barra = ctk.CTkFrame(self, fg_color="transparent")
        barra.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(barra, text="Sucursal:").pack(side="left")
        self.selector = ctk.CTkOptionMenu(barra, values=["—"], width=170, command=lambda _v: self.recargar())
        self.selector.pack(side="left", padx=(6, 14))
        self.busqueda = ctk.CTkEntry(barra, width=240, placeholder_text="Buscar por nombre, SKU o código")
        self.busqueda.pack(side="left")
        self.busqueda.bind("<KeyRelease>", lambda _e: self.recargar())
        self.solo_bajo = ctk.CTkSwitch(barra, text="Solo stock bajo", command=self.recargar)
        self.solo_bajo.pack(side="left", padx=14)

        acciones = ctk.CTkFrame(self, fg_color="transparent")
        acciones.pack(fill="x", pady=4)
        botones = []
        if self.puede_crear:
            botones += [
                ("Compra", lambda: DialogoCompra(self)),
                ("Merma", lambda: DialogoMovimiento(self, "merma")),
                ("Traslado", lambda: DialogoMovimiento(self, "traslado")),
                ("Proveedor", lambda: DialogoNombre(self, "Nuevo proveedor", "Nombre", "Contacto", self._nuevo_proveedor)),
                ("Sucursal", lambda: DialogoNombre(self, "Nueva sucursal", "Nombre", "Dirección", self._nueva_sucursal)),
            ]
        if self.puede_editar:
            botones.append(("Ajuste de stock", lambda: DialogoMovimiento(self, "ajuste")))
        if self.puede_exportar:
            botones.append(("Exportar CSV", self.exportar))
        for texto, comando in botones:
            ctk.CTkButton(acciones, text=texto, width=100, command=comando).pack(side="left", padx=(0, 6))

        self.alerta = ctk.CTkLabel(self, text="", anchor="w", text_color=NARANJA)
        self.alerta.pack(fill="x", pady=(6, 0))
        self.mensaje = ctk.CTkLabel(self, text="", anchor="w")
        self.mensaje.pack(fill="x", pady=2)
        self.lista = ctk.CTkScrollableFrame(self)
        self.lista.pack(fill="both", expand=True)

        self.cargar_sucursales()
        self.recargar()

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

    def cargar_sucursales(self) -> None:
        ok, sucursales = self.ejecutar(lambda s, a: listar_sucursales(s, a))
        self.sucursales = sucursales if ok else []
        nombres = [s["nombre"] for s in self.sucursales] or ["—"]
        actual = self.selector.get()
        self.selector.configure(values=nombres)
        self.selector.set(actual if actual in nombres else nombres[0])

    @property
    def sucursal_id(self) -> int | None:
        for sucursal in self.sucursales:
            if sucursal["nombre"] == self.selector.get():
                return sucursal["id"]
        return None

    @property
    def sucursal_nombre(self) -> str:
        return self.selector.get()

    def _nuevo_proveedor(self, sesion: Any, actor: Any, nombre: str, contacto: str) -> None:
        crear_proveedor(sesion, actor, nombre, contacto)

    def _nueva_sucursal(self, sesion: Any, actor: Any, nombre: str, direccion: str) -> None:
        crear_sucursal(sesion, actor, nombre, direccion)

    # ---- tabla ----------------------------------------------------------------------

    def recargar(self) -> None:
        sucursal = self.sucursal_id
        texto = self.busqueda.get()
        solo_bajo = bool(self.solo_bajo.get())
        ok, filas = self.ejecutar(lambda s, a: existencias(s, a, sucursal, texto, solo_bajo))
        for widget in self.lista.winfo_children():
            widget.destroy()
        if not ok:
            return

        ok_alertas, alertas = self.ejecutar(lambda s, a: existencias(s, a, sucursal, solo_bajo_minimo=True))
        if ok_alertas and alertas:
            self.alerta.configure(text=f"⚠ {len(alertas)} producto(s) con stock bajo en {self.sucursal_nombre}.")
        else:
            self.alerta.configure(text="")

        negrita = ctk.CTkFont(weight="bold")
        for columna, titulo in enumerate(["SKU", "Producto", "Categoría", "Stock", "Mínimo", "Costo prom.", "Estado", ""]):
            ctk.CTkLabel(self.lista, text=titulo, font=negrita).grid(
                row=0, column=columna, padx=8, pady=4, sticky="w"
            )
        if not filas:
            ctk.CTkLabel(self.lista, text="No hay productos que mostrar.", text_color="gray").grid(
                row=1, column=0, columnspan=8, pady=20
            )
        for fila, f in enumerate(filas, start=1):
            textos = [f["sku"], f["nombre"], f["categoria"], str(f["stock"]), str(f["stock_minimo"]), "—" if f["costo"] is None else f"{f['costo']:,.2f}"]
            for columna, texto_celda in enumerate(textos):
                ctk.CTkLabel(
                    self.lista,
                    text=texto_celda,
                    text_color=ROJO if f["bajo_minimo"] and columna == 3 else None,
                ).grid(row=fila, column=columna, padx=8, pady=2, sticky="w" if columna < 3 else "e")
            ctk.CTkLabel(
                self.lista,
                text="⚠ Stock bajo" if f["bajo_minimo"] else "OK",
                text_color=NARANJA if f["bajo_minimo"] else VERDE,
            ).grid(row=fila, column=6, padx=8, sticky="w")
            acciones = ctk.CTkFrame(self.lista, fg_color="transparent")
            acciones.grid(row=fila, column=7, padx=8)
            ctk.CTkButton(acciones, text="Kardex", width=70, command=lambda x=f: DialogoKardex(self, x)).pack(side="left", padx=2)
            ctk.CTkButton(acciones, text="Capas", width=60, fg_color="gray40", command=lambda x=f: DialogoCapas(self, x)).pack(side="left", padx=2)

    def exportar(self) -> None:
        from tkinter import filedialog

        sucursal = self.sucursal_id
        ok, contenido = self.ejecutar(lambda s, a: exportar_existencias_csv(s, a, sucursal))
        if not ok:
            return
        ruta = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="existencias.csv"
        )
        if ruta:
            with open(ruta, "w", encoding="utf-8-sig", newline="") as archivo:
                archivo.write(contenido)
            self.mensaje.configure(text=f"Exportado a {ruta}", text_color=VERDE)


class _Dialogo(ctk.CTkToplevel):
    def __init__(self, pantalla: PantallaInventario, titulo: str, tamano: str) -> None:
        super().__init__(pantalla)
        self.pantalla = pantalla
        self.title(titulo)
        self.geometry(tamano)
        self.after(150, self._tomar_foco)

    def _tomar_foco(self) -> None:
        try:
            self.grab_set()
        except Exception:  # noqa: BLE001  (la ventana pudo cerrarse antes)
            pass


class DialogoNombre(_Dialogo):
    """Formulario de dos campos (nombre + dato opcional) para proveedores y sucursales."""

    def __init__(self, pantalla: PantallaInventario, titulo: str, etiqueta1: str, etiqueta2: str, guardar: Callable) -> None:
        super().__init__(pantalla, titulo, "380x240")
        self._guardar = guardar
        self.primero = ctk.CTkEntry(self, width=300, placeholder_text=etiqueta1)
        self.primero.pack(pady=(28, 8))
        self.segundo = ctk.CTkEntry(self, width=300, placeholder_text=f"{etiqueta2} (opcional)")
        self.segundo.pack(pady=8)
        ctk.CTkButton(self, text="Guardar", command=self.guardar).pack(pady=12)

    def guardar(self) -> None:
        ok, _ = self.pantalla.ejecutar(
            lambda s, a: self._guardar(s, a, self.primero.get(), self.segundo.get()), exito="Guardado."
        )
        if ok:
            self.pantalla.cargar_sucursales()
            self.pantalla.recargar()
            self.destroy()


class DialogoCompra(_Dialogo):
    def __init__(self, pantalla: PantallaInventario) -> None:
        super().__init__(pantalla, f"Compra · {pantalla.sucursal_nombre}", "620x600")
        self.lineas: list[dict] = []

        ok, proveedores = pantalla.ejecutar(lambda s, a: listar_proveedores(s, a))
        self.proveedores = proveedores if ok else []
        if not self.proveedores:
            ctk.CTkLabel(
                self, text="Primero crea un proveedor (botón «Proveedor»).", text_color=ROJO
            ).pack(pady=40)
            return

        marco = ctk.CTkFrame(self, fg_color="transparent")
        marco.pack(fill="x", padx=20, pady=(16, 6))
        ctk.CTkLabel(marco, text="Proveedor").pack(side="left")
        self.proveedor = ctk.CTkOptionMenu(marco, values=[p["nombre"] for p in self.proveedores], width=240)
        self.proveedor.pack(side="left", padx=10)

        fila = ctk.CTkFrame(self, fg_color="transparent")
        fila.pack(fill="x", padx=20, pady=6)
        self.codigo = ctk.CTkEntry(fila, width=170, placeholder_text="SKU o código de barras")
        self.cantidad = ctk.CTkEntry(fila, width=80, placeholder_text="Cantidad")
        self.costo = ctk.CTkEntry(fila, width=100, placeholder_text="Costo unit.")
        for widget in (self.codigo, self.cantidad, self.costo):
            widget.pack(side="left", padx=4)
        ctk.CTkButton(fila, text="Agregar", width=80, command=self.agregar).pack(side="left", padx=4)
        self.costo.bind("<Return>", lambda _e: self.agregar())

        self.detalle = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Courier", size=12), wrap="none", height=260)
        self.detalle.pack(fill="both", expand=True, padx=20, pady=8)
        self.detalle.configure(state="disabled")

        self.nota = ctk.CTkEntry(self, width=400, placeholder_text="Nota o número de factura (opcional)")
        self.nota.pack(pady=4)
        pie = ctk.CTkFrame(self, fg_color="transparent")
        pie.pack(pady=10)
        ctk.CTkButton(pie, text="Quitar última", width=110, command=self.quitar).pack(side="left", padx=6)
        ctk.CTkButton(pie, text="Registrar compra", command=self.registrar).pack(side="left", padx=6)

    def _refrescar(self) -> None:
        self.detalle.configure(state="normal")
        self.detalle.delete("1.0", "end")
        for l in self.lineas:
            self.detalle.insert(
                "end", f"{l['sku']:<10} {l['nombre'][:28]:<28} x{l['cantidad']:<5} a {l['costo']}\n"
            )
        self.detalle.configure(state="disabled")

    def agregar(self) -> None:
        codigo, cantidad, costo = self.codigo.get(), self.cantidad.get(), self.costo.get()
        ok, producto = self.pantalla.ejecutar(lambda s, a: _producto_por_codigo(s, a, codigo))
        if not ok:
            return
        self.lineas.append(
            {
                "producto_id": producto["id"],
                "sku": producto["sku"],
                "nombre": producto["nombre"],
                "cantidad": cantidad,
                "costo": costo.strip() or str(producto["costo"]),
            }
        )
        for campo in (self.codigo, self.cantidad, self.costo):
            campo.delete(0, "end")
        self._refrescar()
        self.codigo.focus()

    def quitar(self) -> None:
        if self.lineas:
            self.lineas.pop()
            self._refrescar()

    def registrar(self) -> None:
        sucursal = self.pantalla.sucursal_id
        proveedor = next(p["id"] for p in self.proveedores if p["nombre"] == self.proveedor.get())
        lineas = [
            {"producto_id": l["producto_id"], "cantidad": l["cantidad"], "costo_unitario": l["costo"]}
            for l in self.lineas
        ]
        ok, _ = self.pantalla.ejecutar(
            lambda s, a: registrar_compra(
                s, a, sucursal_id=sucursal, proveedor_id=proveedor, lineas=lineas, nota=self.nota.get()
            ),
            exito="Compra registrada.",
        )
        if ok:
            self.pantalla.recargar()
            self.destroy()


class DialogoMovimiento(_Dialogo):
    """Merma, ajuste de stock (conteo físico) o traslado a otra sucursal."""

    TITULOS = {"merma": "Registrar merma", "ajuste": "Ajuste de stock", "traslado": "Traslado entre sucursales"}
    ETIQUETA_CANTIDAD = {
        "merma": "Cantidad a dar de baja",
        "ajuste": "Conteo físico real",
        "traslado": "Cantidad a trasladar",
    }

    def __init__(self, pantalla: PantallaInventario, modo: str) -> None:
        super().__init__(pantalla, f"{self.TITULOS[modo]} · {pantalla.sucursal_nombre}", "440x360")
        self.modo = modo
        self.destinos = [s for s in pantalla.sucursales if s["id"] != pantalla.sucursal_id]

        self.codigo = ctk.CTkEntry(self, width=320, placeholder_text="SKU o código de barras")
        self.codigo.pack(pady=(24, 8))
        self.cantidad = ctk.CTkEntry(self, width=320, placeholder_text=self.ETIQUETA_CANTIDAD[modo])
        self.cantidad.pack(pady=8)

        if modo == "traslado":
            if not self.destinos:
                ctk.CTkLabel(self, text="Necesitas al menos otra sucursal.", text_color=ROJO).pack(pady=8)
            else:
                self.destino = ctk.CTkOptionMenu(self, values=[d["nombre"] for d in self.destinos], width=320)
                self.destino.pack(pady=8)
            self.texto = ctk.CTkEntry(self, width=320, placeholder_text="Nota (opcional)")
        else:
            self.texto = ctk.CTkEntry(self, width=320, placeholder_text="Motivo (obligatorio)")
        self.texto.pack(pady=8)
        ctk.CTkButton(self, text="Guardar", command=self.guardar).pack(pady=14)

    def guardar(self) -> None:
        sucursal = self.pantalla.sucursal_id
        codigo, cantidad, texto = self.codigo.get(), self.cantidad.get(), self.texto.get()

        def operar(sesion: Any, actor: Any) -> None:
            producto = _producto_por_codigo(sesion, actor, codigo)
            if self.modo == "merma":
                registrar_merma(sesion, actor, producto_id=producto["id"], sucursal_id=sucursal, cantidad=cantidad, motivo=texto)
            elif self.modo == "ajuste":
                ajustar_stock(sesion, actor, producto_id=producto["id"], sucursal_id=sucursal, conteo_fisico=cantidad, motivo=texto)
            else:
                if not self.destinos:
                    raise ErrorDeNegocio("Necesitas al menos otra sucursal.")
                destino = next(d["id"] for d in self.destinos if d["nombre"] == self.destino.get())
                trasladar(sesion, actor, producto_id=producto["id"], origen_id=sucursal, destino_id=destino, cantidad=cantidad, nota=texto)

        ok, _ = self.pantalla.ejecutar(operar, exito="Movimiento registrado.")
        if ok:
            self.pantalla.recargar()
            self.destroy()


class DialogoCapas(_Dialogo):
    """Lotes con unidades restantes y su costo, del más antiguo al más nuevo (el orden de salida con PEPS)."""

    def __init__(self, pantalla: PantallaInventario, producto: dict) -> None:
        super().__init__(pantalla, f"Capas de costo · {producto['sku']}", "760x420")
        ctk.CTkLabel(
            self, text=f"{producto['nombre']} · {pantalla.sucursal_nombre}", font=ctk.CTkFont(size=16, weight="bold")
        ).pack(pady=(12, 2))
        ctk.CTkLabel(
            self, text="Cada compra, devolución o ajuste positivo forma una capa. Con PEPS se vende primero la más antigua.",
            text_color="gray", wraplength=700,
        ).pack(pady=(0, 6))
        texto = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Courier", size=12), wrap="none")
        texto.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        sucursal = pantalla.sucursal_id
        ok, capas = pantalla.ejecutar(lambda s, a: capas_de_producto(s, a, producto["producto_id"], sucursal))
        if ok and capas:
            texto.insert("end", f"{'Fecha (UTC)':<17} {'Origen':<17} {'Inicial':>8} {'Quedan':>7} {'Costo':>9} {'Valor':>11}\n")
            for c in capas:
                costo = "—" if c["costo"] is None else format(c["costo"], ".2f")
                valor = "—" if c["valor"] is None else format(c["valor"], ",.2f")
                texto.insert(
                    "end",
                    f"{c['fecha']:%Y-%m-%d %H:%M}  {c['origen']:<17} {c['cantidad_inicial']:>8} {c['restante']:>7} {costo:>9} {valor:>11}\n",
                )
        elif ok:
            texto.insert("end", "No hay capas con unidades en esta sucursal.")
        texto.configure(state="disabled")


class DialogoKardex(_Dialogo):
    def __init__(self, pantalla: PantallaInventario, producto: dict) -> None:
        super().__init__(pantalla, f"Kardex · {producto['sku']}", "900x480")
        self.producto = producto
        cabecera = ctk.CTkFrame(self, fg_color="transparent")
        cabecera.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(
            cabecera, text=f"{producto['nombre']} · {pantalla.sucursal_nombre}", font=ctk.CTkFont(size=16, weight="bold")
        ).pack(side="left")
        if pantalla.puede_exportar:
            ctk.CTkButton(cabecera, text="Exportar CSV", width=110, command=self.exportar).pack(side="right")

        texto = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Courier", size=12), wrap="none")
        texto.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        sucursal = pantalla.sucursal_id
        ok, movimientos = pantalla.ejecutar(lambda s, a: kardex(s, a, producto["producto_id"], sucursal))
        if ok and movimientos:
            texto.insert("end", f"{'Fecha (UTC)':<17} {'Tipo':<17} {'Cant.':>6} {'Saldo':>6} {'Costo':>8}  Motivo / referencia / usuario\n")
            for m in movimientos:
                detalle = " · ".join(x for x in (m["motivo"], m["referencia"], m["usuario"]) if x)
                texto.insert(
                    "end",
                    f"{m['fecha']:%Y-%m-%d %H:%M}  {m['tipo']:<17} {m['cantidad']:>+6} {m['saldo']:>6} {('—' if m['costo'] is None else format(m['costo'], '.2f')):>8}  {detalle}\n",
                )
        elif ok:
            texto.insert("end", "Este producto aún no tiene movimientos en esta sucursal.")
        texto.configure(state="disabled")

    def exportar(self) -> None:
        from tkinter import filedialog

        sucursal = self.pantalla.sucursal_id
        ok, contenido = self.pantalla.ejecutar(
            lambda s, a: exportar_kardex_csv(s, a, self.producto["producto_id"], sucursal)
        )
        if not ok:
            return
        ruta = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile=f"kardex_{self.producto['sku']}.csv"
        )
        if ruta:
            with open(ruta, "w", encoding="utf-8-sig", newline="") as archivo:
                archivo.write(contenido)
            self.pantalla.mensaje.configure(text=f"Exportado a {ruta}", text_color=VERDE)
