"""Pantalla del catálogo de productos: búsqueda, filtros, alta, edición e historial."""

from __future__ import annotations

from typing import Any, Callable

import customtkinter as ctk

from app.db import sesion_transaccional
from app.servicios.catalogo import (
    buscar_productos,
    crear_categoria,
    crear_producto,
    editar_producto,
    establecer_activo,
    historial_producto,
    listar_categorias,
)
from app.servicios.errores import ErrorDeNegocio
from app.servicios.fotos import asignar_foto, quitar_foto, rutas_de_fotos
from app.servicios.usuarios import obtener_usuario
from app.ui import tema

_CACHE_MINIATURAS: dict[tuple[str, int], Any] = {}


def imagen_de(ruta: Any, lado: int) -> Any:
    """CTkImage cuadrada (con proporción conservada) o ``None`` si no se puede abrir."""
    clave = (str(ruta), lado)
    if clave in _CACHE_MINIATURAS:
        return _CACHE_MINIATURAS[clave]
    try:
        from PIL import Image

        with Image.open(ruta) as original:
            imagen = original.copy()
        imagen.thumbnail((lado * 2, lado * 2))
        ancho = max(1, round(imagen.width * lado / max(imagen.size)))
        alto = max(1, round(imagen.height * lado / max(imagen.size)))
        resultado = ctk.CTkImage(light_image=imagen, dark_image=imagen, size=(ancho, alto))
    except Exception:  # noqa: BLE001
        resultado = None
    _CACHE_MINIATURAS[clave] = resultado
    return resultado


ROJO = "#d64545"
VERDE = "#2e9e5b"
TODAS = "Todas las categorías"


def _dinero(valor: Any) -> str:
    return "—" if valor is None else f"{valor:,.2f}"


class PantallaProductos(ctk.CTkFrame):
    def __init__(self, master: Any, app: Any) -> None:
        super().__init__(master, fg_color="transparent")
        self.app = app
        usuario = app.usuario
        self.puede_crear = usuario.puede("productos", "crear")
        self.puede_editar = usuario.puede("productos", "editar")
        self.puede_precios = usuario.puede("productos", "precios")
        self.categorias: list[dict] = []

        cabecera = ctk.CTkFrame(self, fg_color="transparent")
        cabecera.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(cabecera, text="Productos", font=ctk.CTkFont(size=22, weight="bold")).pack(side="left")
        if self.puede_crear:
            ctk.CTkButton(cabecera, text="Nuevo producto", width=130, command=self.nuevo).pack(side="right")
            ctk.CTkButton(
                cabecera, text="Nueva categoría", width=130, command=self.nueva_categoria
            ).pack(side="right", padx=8)

        filtros = ctk.CTkFrame(self, fg_color="transparent")
        filtros.pack(fill="x")
        self.busqueda = ctk.CTkEntry(filtros, width=300, placeholder_text="Buscar por nombre, SKU, código o marca")
        self.busqueda.pack(side="left")
        self.busqueda.bind("<KeyRelease>", lambda _e: self.recargar())
        self.filtro_categoria = ctk.CTkOptionMenu(
            filtros, values=[TODAS], width=190, command=lambda _v: self.recargar()
        )
        self.filtro_categoria.pack(side="left", padx=8)
        self.ver_inactivos = ctk.CTkSwitch(filtros, text="Mostrar inactivos", command=self.recargar)
        self.ver_inactivos.pack(side="left", padx=8)

        self.mensaje = ctk.CTkLabel(self, text="", anchor="w")
        self.mensaje.pack(fill="x", pady=6)
        self.lista = ctk.CTkScrollableFrame(self)
        self.lista.pack(fill="both", expand=True)

        self.cargar_categorias()
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

    def cargar_categorias(self) -> None:
        ok, categorias = self.ejecutar(lambda s, a: listar_categorias(s, a))
        self.categorias = categorias if ok else []
        valores = [TODAS] + [c["nombre"] for c in self.categorias]
        actual = self.filtro_categoria.get()
        self.filtro_categoria.configure(values=valores)
        self.filtro_categoria.set(actual if actual in valores else TODAS)

    def _categoria_filtrada(self) -> int | None:
        nombre = self.filtro_categoria.get()
        for categoria in self.categorias:
            if categoria["nombre"] == nombre:
                return categoria["id"]
        return None

    # ---- lista ----------------------------------------------------------------------

    def recargar(self) -> None:
        texto = self.busqueda.get()
        categoria_id = self._categoria_filtrada()
        inactivos = bool(self.ver_inactivos.get())
        ok, filas = self.ejecutar(
            lambda s, a: buscar_productos(s, a, texto, categoria_id, incluir_inactivos=inactivos)
        )
        for widget in self.lista.winfo_children():
            widget.destroy()
        if not ok:
            return

        negrita = ctk.CTkFont(weight="bold")
        fotos: dict = {}
        if filas:
            _, fotos = self.ejecutar(lambda s, a: rutas_de_fotos(s, a, [f["id"] for f in filas]))
            fotos = fotos or {}
        titulos = ["Foto", "SKU", "Nombre", "Categoría", "Costo", "Precio", "Mínimo", "Estado", ""]
        for columna, titulo in enumerate(titulos):
            ctk.CTkLabel(self.lista, text=titulo, font=negrita).grid(
                row=0, column=columna, padx=8, pady=4, sticky="w"
            )
        if not filas:
            ctk.CTkLabel(self.lista, text="No hay productos que coincidan.", text_color="gray").grid(
                row=1, column=0, columnspan=9, pady=20
            )
        for fila, p in enumerate(filas, start=1):
            miniatura = imagen_de(fotos[p["id"]], 40) if p["id"] in fotos else None
            ctk.CTkLabel(self.lista, text="" if miniatura else "—", image=miniatura, width=44, text_color="gray").grid(
                row=fila, column=0, padx=8, pady=2
            )
            textos = [
                p["sku"],
                p["nombre"] + ("  · servicio" if p["es_servicio"] else ""),
                p["categoria"],
                _dinero(p["costo"]),
                _dinero(p["precio"]),
                "—" if p["es_servicio"] else str(p["stock_minimo"]),
            ]
            for columna, texto in enumerate(textos, start=1):
                ctk.CTkLabel(self.lista, text=texto).grid(
                    row=fila, column=columna, padx=8, pady=2, sticky="w" if columna < 4 else "e"
                )
            ctk.CTkLabel(
                self.lista,
                text="Activo" if p["activo"] else "Inactivo",
                text_color=VERDE if p["activo"] else ROJO,
            ).grid(row=fila, column=7, padx=8, sticky="w")

            acciones = ctk.CTkFrame(self.lista, fg_color="transparent")
            acciones.grid(row=fila, column=8, padx=8, sticky="w")
            ctk.CTkButton(acciones, text="Historial", width=70, command=lambda x=p: DialogoHistorial(self, x)).pack(
                side="left", padx=2
            )
            if self.puede_editar or self.puede_precios:
                ctk.CTkButton(acciones, text="Editar", width=60, command=lambda x=p: self.editar(x)).pack(
                    side="left", padx=2
                )
            if self.puede_editar:
                ctk.CTkButton(
                    acciones,
                    text="Desactivar" if p["activo"] else "Activar",
                    width=80,
                    command=lambda x=p: self.alternar_activo(x),
                ).pack(side="left", padx=2)

    # ---- acciones -------------------------------------------------------------------

    def nuevo(self) -> None:
        if not self.categorias:
            self.mensaje.configure(text="Primero crea una categoría.", text_color=ROJO)
            return
        DialogoProducto(self, None)

    def editar(self, producto: dict) -> None:
        DialogoProducto(self, producto)

    def nueva_categoria(self) -> None:
        DialogoCategoria(self)

    def alternar_activo(self, producto: dict) -> None:
        nuevo = not producto["activo"]
        self.ejecutar(
            lambda s, a: establecer_activo(s, a, producto["id"], nuevo),
            exito="Producto activado." if nuevo else "Producto desactivado.",
        )
        self.recargar()


class _Dialogo(ctk.CTkToplevel):
    def __init__(self, pantalla: PantallaProductos, titulo: str, tamano: str) -> None:
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


class DialogoCategoria(_Dialogo):
    def __init__(self, pantalla: PantallaProductos) -> None:
        super().__init__(pantalla, "Nueva categoría", "360x170")
        self.nombre = ctk.CTkEntry(self, width=280, placeholder_text="Nombre de la categoría")
        self.nombre.pack(pady=(30, 10))
        self.nombre.bind("<Return>", lambda _e: self.guardar())
        ctk.CTkButton(self, text="Guardar", command=self.guardar).pack()

    def guardar(self) -> None:
        ok, _ = self.pantalla.ejecutar(
            lambda s, a: crear_categoria(s, a, self.nombre.get()), exito="Categoría creada."
        )
        if ok:
            self.pantalla.cargar_categorias()
            self.destroy()


class DialogoProducto(_Dialogo):
    CAMPOS = [
        ("sku", "SKU"),
        ("codigo_barras", "Código de barras"),
        ("nombre", "Nombre"),
        ("descripcion", "Descripción"),
        ("marca", "Marca"),
        ("costo", "Costo"),
        ("precio", "Precio"),
        ("stock_minimo", "Stock mínimo"),
    ]

    def __init__(self, pantalla: PantallaProductos, producto: dict | None) -> None:
        super().__init__(pantalla, "Editar producto" if producto else "Nuevo producto", "460x790")
        self.producto = producto
        self.foto_pendiente: str | None = None
        self.entradas: dict[str, ctk.CTkEntry] = {}

        marco = ctk.CTkFrame(self, fg_color="transparent")
        marco.pack(fill="both", expand=True, padx=20, pady=16)

        ctk.CTkLabel(marco, text="Categoría").grid(row=0, column=0, sticky="w", pady=5)
        nombres = [c["nombre"] for c in pantalla.categorias]
        self.categoria = ctk.CTkOptionMenu(marco, values=nombres, width=250)
        if producto and producto["categoria"] in nombres:
            self.categoria.set(producto["categoria"])
        self.categoria.grid(row=0, column=1, pady=5, sticky="w")

        for fila, (clave, etiqueta) in enumerate(self.CAMPOS, start=1):
            ctk.CTkLabel(marco, text=etiqueta).grid(row=fila, column=0, sticky="w", pady=5, padx=(0, 12))
            entrada = ctk.CTkEntry(marco, width=250)
            entrada.grid(row=fila, column=1, pady=5, sticky="w")
            self.entradas[clave] = entrada
            if producto is not None:
                valor = producto["costo" if clave == "costo" else clave]
                entrada.insert(0, "" if valor is None else str(valor))

        self.es_servicio = ctk.CTkSwitch(
            marco, text="Es un servicio (no controla stock)", command=self._alternar_servicio
        )
        self.es_servicio.grid(row=len(self.CAMPOS) + 1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        if producto is not None:
            # El tipo se decide al crear: cambiarlo después dejaría el kardex sin sentido.
            if producto["es_servicio"]:
                self.es_servicio.select()
                self.entradas["stock_minimo"].configure(state="disabled")
            self.es_servicio.configure(state="disabled")

        if producto is not None:
            self.entradas["sku"].configure(state="disabled")  # el SKU no se edita
            if not pantalla.puede_precios:
                for clave in ("costo", "precio"):
                    self.entradas[clave].configure(state="disabled")
            if not pantalla.puede_editar:
                for clave, entrada in self.entradas.items():
                    if clave not in ("costo", "precio"):
                        entrada.configure(state="disabled")
                self.categoria.configure(state="disabled")
        else:
            self.entradas["costo"].insert(0, "0")
            self.entradas["stock_minimo"].insert(0, "0")

        self._armar_foto(marco, len(self.CAMPOS) + 2)
        ctk.CTkButton(self, text="Guardar", command=self.guardar).pack(pady=(0, 18))

    # ---- foto -----------------------------------------------------------------------

    def _armar_foto(self, marco: Any, fila: int) -> None:
        self.vista_foto = ctk.CTkLabel(marco, text="Sin foto", width=170, height=120, fg_color=tema.SUPERFICIE_2, corner_radius=8)
        self.vista_foto.grid(row=fila, column=0, columnspan=2, pady=(12, 4))
        botones = ctk.CTkFrame(marco, fg_color="transparent")
        botones.grid(row=fila + 1, column=0, columnspan=2)
        self.puede_foto = self.pantalla.puede_editar
        if self.puede_foto:
            ctk.CTkButton(botones, text="Elegir foto…", width=110, command=self._elegir_foto).pack(side="left", padx=4)
            ctk.CTkButton(botones, text="Quitar foto", width=100, fg_color="gray40", command=self._quitar_foto).pack(side="left", padx=4)
        if self.producto is not None:
            _, rutas = self.pantalla.ejecutar(lambda s, a: rutas_de_fotos(s, a, [self.producto["id"]]))
            if rutas and self.producto["id"] in rutas:
                self._mostrar_foto(rutas[self.producto["id"]])

    def _mostrar_foto(self, ruta: Any) -> None:
        imagen = imagen_de(ruta, 110)
        self.vista_foto.configure(image=imagen, text="" if imagen else "No se pudo mostrar")
        self.vista_foto.image = imagen

    def _elegir_foto(self) -> None:
        from tkinter import filedialog

        ruta = filedialog.askopenfilename(
            parent=self, title="Elegir foto", filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.gif *.bmp *.webp")]
        )
        if not ruta:
            return
        if self.producto is None:  # aún no existe: se guarda junto con el producto
            self.foto_pendiente = ruta
            self._mostrar_foto(ruta)
            return
        ok, nombre = self.pantalla.ejecutar(lambda s, a: asignar_foto(s, a, self.producto["id"], ruta), exito="Foto guardada.")
        if ok:
            _, rutas = self.pantalla.ejecutar(lambda s, a: rutas_de_fotos(s, a, [self.producto["id"]]))
            if rutas and self.producto["id"] in rutas:
                self._mostrar_foto(rutas[self.producto["id"]])
            self.pantalla.recargar()

    def _quitar_foto(self) -> None:
        self.foto_pendiente = None
        self.vista_foto.configure(image=None, text="Sin foto")
        self.vista_foto.image = None
        if self.producto is not None:
            ok, _ = self.pantalla.ejecutar(lambda s, a: quitar_foto(s, a, self.producto["id"]), exito="Foto quitada.")
            if ok:
                self.pantalla.recargar()

    def _alternar_servicio(self) -> None:
        """Un servicio no maneja existencias: el stock mínimo no aplica."""
        entrada = self.entradas["stock_minimo"]
        entrada.configure(state="normal")
        entrada.delete(0, "end")
        entrada.insert(0, "0")
        if self.es_servicio.get():
            entrada.configure(state="disabled")

    def _id_categoria(self) -> int:
        nombre = self.categoria.get()
        return next(c["id"] for c in self.pantalla.categorias if c["nombre"] == nombre)

    def guardar(self) -> None:
        datos = {clave: entrada.get() for clave, entrada in self.entradas.items()}
        if self.producto is None:
            def crear(s: Any, a: Any) -> None:
                nuevo = crear_producto(
                    s,
                    a,
                    sku=datos["sku"],
                    nombre=datos["nombre"],
                    categoria_id=self._id_categoria(),
                    precio=datos["precio"],
                    costo=datos["costo"],
                    stock_minimo=datos["stock_minimo"],
                    codigo_barras=datos["codigo_barras"],
                    descripcion=datos["descripcion"],
                    marca=datos["marca"],
                    es_servicio=bool(self.es_servicio.get()),
                )
                if self.foto_pendiente:  # misma transacción: si la foto falla, no se crea el producto
                    asignar_foto(s, a, nuevo.id, self.foto_pendiente)

            ok, _ = self.pantalla.ejecutar(
                crear,
                exito="Producto creado.",
            )
        else:
            # Se envían solo los campos modificados: así un usuario sin permiso de precios
            # puede editar el resto sin que su formulario "toque" el precio.
            original = self.producto
            cambios: dict[str, Any] = {}
            for clave, valor in datos.items():
                if clave == "sku":
                    continue
                anterior = original["costo" if clave == "costo" else clave]
                if valor.strip() != ("" if anterior is None else str(anterior)).strip():
                    cambios[clave] = valor
            if self._id_categoria() != original["categoria_id"]:
                cambios["categoria_id"] = self._id_categoria()
            if not cambios:
                self.destroy()
                return
            ok, cambiados = self.pantalla.ejecutar(
                lambda s, a: editar_producto(s, a, original["id"], cambios),
                exito="Producto actualizado.",
            )
        if ok:
            self.pantalla.cargar_categorias()
            self.pantalla.recargar()
            self.destroy()


class DialogoHistorial(_Dialogo):
    def __init__(self, pantalla: PantallaProductos, producto: dict) -> None:
        super().__init__(pantalla, f"Historial · {producto['sku']}", "640x420")
        ctk.CTkLabel(self, text=producto["nombre"], font=ctk.CTkFont(size=16, weight="bold")).pack(pady=(14, 6))
        texto = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Courier", size=12), wrap="none")
        texto.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        ok, eventos = pantalla.ejecutar(lambda s, a: historial_producto(s, a, producto["id"]))
        if ok and eventos:
            for e in eventos:
                texto.insert(
                    "end",
                    f"{e['fecha']:%Y-%m-%d %H:%M} UTC | {e['usuario']:<16} | {e['campo']:<12} | "
                    f"{e['anterior'] if e['anterior'] is not None else '—'} -> "
                    f"{e['nuevo'] if e['nuevo'] is not None else '—'}\n",
                )
        elif ok:
            texto.insert("end", "Sin cambios registrados.")
        texto.configure(state="disabled")
