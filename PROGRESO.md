# PROGRESO

**Fase actual:** 6c (documentación) — código subido a la rama `fase-6c-documentacion`.
**Fecha:** 2026-10-24

## Diagnóstico acordado

| Tema | Decisión |
|---|---|
| Catálogo | Productos simples: SKU/código de barras, categoría, precio, costo, stock mínimo. Sin lotes ni caducidad. |
| Alcance | POS (venta de mostrador), compras a proveedores, alertas de stock mínimo, **varias sucursales**. |
| Interfaz | Escritorio nativo: CustomTkinter + SQLite. |
| Roles | Administrador, Bodeguero, Vendedor/Cajero, Contador. |

## Supuestos (ajustables)

- Python 3.11+, SQLAlchemy 2 + Alembic. SQLite por defecto; `DATABASE_URL` permite pasar a PostgreSQL.
- Reglas de negocio en `app/servicios/`, sin depender de la ventana.
- Costeo: **promedio ponderado** (el usuario no eligió PEPS; es el valor por defecto). Stock negativo bloqueado. Dinero en `Decimal`.
- Multi-sucursal: existencias, movimientos y ventas llevarán `sucursal_id` desde su primera migración.
- Contraseñas con argon2, mínimo 8 caracteres.
- Un usuario no puede cambiar su propio rol, desactivarse ni editar sus propios permisos (evita quedarse sin administrador).
- Ventas: `ventas.ver` = solo las propias; `ventas.ver_todas` = las de todos los vendedores (contador y administrador). Reportes (Fase 5) seguirán la misma idea.

## Esquema activo (migraciones `0001` a `0010`)

- `sucursales`, `configuracion`
- `roles`, `permisos` (módulo + acción, único), `roles_permisos`
- `usuarios` (correo único, hash argon2, rol, activo, último acceso)
- `usuarios_permisos` (excepción individual: concedido sí/no sobre el rol)
- `bitacora_auditoria` (usuario, acción, entidad, detalle JSON, fecha; solo se agregan registros)
- `categorias` (nombre único, activa)
- `productos` (sku único, código de barras único opcional, nombre, descripción, categoría, marca, costo_promedio, precio, stock_minimo, activo). **Sin columna de stock**: las existencias viven en `existencias` y solo cambian por movimientos.
- `historial_productos` (producto, campo, valor anterior, valor nuevo, usuario, fecha; solo se agregan filas)
- `proveedores` (nombre único, contacto, activo)
- `existencias` (producto + sucursal, cantidad; `CHECK cantidad >= 0`)
- `movimientos_inventario` (kardex: producto, sucursal, tipo, cantidad con signo, saldo_despues, costo_unitario, motivo, referencia, usuario, fecha; índice por producto; solo se agregan filas)
- `compras` + `compras_detalle`, `traslados`
- `clientes` (nombre, teléfono, correo, activo)
- `ventas` (número único, sucursal, vendedor, cliente, método de pago, subtotal, descuento, total, estado, nota, fecha; anulación: usuario, fecha, motivo) y `ventas_detalle` (cantidad, **precio y costo congelados**, descuento de línea)
- `productos.es_servicio` (booleano, por defecto falso)
- `gastos` (fecha, categoría, descripción, monto > 0, sucursal opcional, usuario, estado activo/anulado, quién/cuándo/por qué se anuló)

## Permisos por módulo

Catálogo en `app/servicios/permisos.py` (`CATALOGO` y `MATRIZ_BASE`). Toda función de servicio sensible llama a `exigir_permiso`, que lanza `PermisoDenegado` (403). El menú solo muestra módulos con algún permiso efectivo.

Eventos auditados: `login`, `login_fallido`, `logout`, `usuario_creado`, `rol_cambiado`, `usuario_activado/desactivado`, `permiso_individual_cambiado`, `contrasena_cambiada/restablecida`.

## Catálogo (Fase 2)

- Servicio: `app/servicios/catalogo.py`. Pantalla: `app/ui/productos_pantalla.py`.
- SKU en mayúsculas y **no editable**. SKU y código de barras únicos, y ninguno puede coincidir con el código del otro en otro producto (los escaneos nunca son ambiguos).
- Productos y categorías se **desactivan, no se borran**. Un producto inactivo no sale en búsquedas ni en `obtener_por_codigo` (la venta de la Fase 4 usará esa función), pero conserva su historial.
- Permiso nuevo `productos.precios`: cambiar precio o costo. Solo lo tiene el administrador en la matriz base; se puede conceder por usuario. `productos.editar` cubre el resto de datos. La comprobación depende de los campos enviados.
- El historial registra precio, costo, stock mínimo, nombre y activo/inactivo, con el valor inicial desde el alta.
- Dinero: `Decimal` con 2 decimales; acepta `12.5`, `12,50` y `1,234.50`. SQLite guarda `Numeric` como número decimal (exacto a 2 decimales para estos importes); en PostgreSQL es exacto.
- `costo_promedio`: se fija al crear el producto o con `productos.precios`; desde la Fase 3 lo recalculan las compras.
- `seed.py` carga 4 categorías y 9 productos de ejemplo solo si no hay productos.

## Inventario (Fase 3)

- Servicio: `app/servicios/inventario.py`. Pantalla: `app/ui/inventario_pantalla.py`.
- **Único punto que toca el stock:** `aplicar_movimiento`. Escribe el movimiento y actualiza `existencias` en la misma transacción, con un `UPDATE` condicional (`cantidad + delta >= 0`): dos operaciones sobre la última unidad no pueden pasar las dos. Además la base tiene `CHECK cantidad >= 0`. La Fase 4 (ventas) debe usar esta función; no comprueba permisos, los comprueba quien la llama.
- Tipos de movimiento: `entrada`, `salida`, `merma`, `ajuste` (con signo), `devolucion`, `anulacion`, `traslado_entrada`, `traslado_salida`. Cantidades enteras (sin fracciones).
- Costo promedio ponderado global por producto: cada compra recalcula con el stock total de todas las sucursales (redondeo a centavos, mitad hacia arriba) y deja el cambio en `historial_productos`. Salidas y traslados valoran al costo vigente; un traslado no cambia el costo. Recalcular el costo no exige `productos.precios` (se deriva de una compra autorizada).
- Compras y traslados son atómicos por sí mismos (savepoint): si algo falla no queda nada a medias. Para que los savepoints funcionen, `crear_motor` aplica en SQLite la receta oficial de SQLAlchemy (BEGIN explícito).
- Permisos: `ver` consulta existencias, kardex, proveedores y sucursales; `crear` hace compras, mermas, traslados y crea proveedores y sucursales; `editar` hace ajustes de stock y desactiva proveedores; `exportar` genera los CSV. Vendedor y contador solo consultan; el bodeguero opera todo.
- Merma y ajuste exigen motivo. El ajuste recibe el conteo físico y registra la diferencia. Alerta de stock bajo: `stock_minimo > 0` y `stock <= stock_minimo` (por sucursal o total).
- `verificar_consistencia(sesion)` compara cada existencia con la suma de sus movimientos y con el último saldo; vacía = todo cuadra. Conviene llamarla desde `--salud` en la Fase 6.
- Pendientes conscientes: no hay anulación de compras (se corrige con un ajuste); no hay stock negativo diferido; los usuarios no están limitados a una sucursal (cualquiera con permiso opera cualquier sucursal activa).
- `seed.py` registra una compra inicial de ejemplo (9 productos en la sucursal Principal; SNK-002 queda en alerta) solo si no hay compras.

## Ventas (Fase 4)

- `registrar_venta` valida todo primero y luego, dentro de un savepoint, asigna número consecutivo (`V-000001`), descuenta stock con `aplicar_movimiento` (tipo `salida`) y guarda la venta: o queda todo o nada. El vendedor es siempre el usuario de la sesión; el precio y el costo salen del producto y se congelan en el detalle (cambiar el precio después no altera ventas hechas). Descuentos son montos en dinero (por línea y general), nunca mayores al importe.
- `anular_venta` (permiso `ventas.anular`, motivo obligatorio): marca la venta, devuelve el stock con movimientos `anulacion` al costo original y guarda quién, cuándo y por qué. No se anula dos veces.
- Comprobante (`servicios/comprobante.py`): texto de 44 columnas y HTML escapado; el botón «Imprimir» lo abre en el navegador para imprimir con Ctrl+P.
- Pantalla de caja: lector de código de barras (envía el código + Enter), búsqueda por nombre/SKU, carrito, cliente, forma de pago, descuento; pestaña Historial con anulación.
- Actualizar una instalación existente: `sembrar_permisos_y_roles` (lo ejecuta `seed.py`) crea `ventas.ver_todas` y se lo da al contador sin quitar personalizaciones. Para que el administrador lo reciba basta con correr `python seed.py` tras migrar.
- Eventos auditados nuevos: `cliente_creado`, `venta_registrada`, `venta_anulada`.
- Pendientes conscientes: no hay devoluciones parciales (se anula la venta completa y se vuelve a vender); no hay pagos mixtos ni cálculo de cambio; el número de venta es global (no por sucursal). En SQLite, dos cajas en el mismo archivo pueden recibir «database is locked» bajo carga; el stock nunca se sobrevende. Para varias cajas reales conviene PostgreSQL (`DATABASE_URL`).
- Se descartó (sin poder probarlo) usar `BEGIN IMMEDIATE` en SQLite: bloquearía a cualquier sesión abierta, incluso solo de lectura.

## Reportes (Fase 5)

- `servicios/reportes.py`: `resumen_ventas`, `ventas_agrupadas` (por día, vendedor, producto, categoría o sucursal), `inventario_valorizado` y exportaciones CSV (`exportar_ventas_agrupadas_csv`, `exportar_detalle_ventas_csv`, `exportar_valorizado_csv`).
- Permisos: `reportes.ver` para consultar, `reportes.exportar` para el CSV. Quien solo tiene `ventas.ver` (vendedor) ve únicamente sus ventas y **no recibe costos ni utilidad** (llegan como `None`). Con `ventas.ver_todas` (contador, administrador) se ve todo. Sin permiso de ventas (bodeguero) los reportes de ventas dan 403.
- Solo cuentan ventas completadas; las anuladas se informan aparte (cantidad y monto).
- Ingreso por línea = precio × cantidad − descuento de línea − parte proporcional del descuento general (repartido al centavo). Así todas las agrupaciones suman exactamente el total de las ventas.
- Utilidad bruta = ingreso − costo congelado al vender. Margen % = utilidad / ingreso.
- Fechas: se guardan en UTC; la pantalla usa días del calendario local (`rango_local`) y agrupa por día local.
- CSV: se neutralizan textos que empiezan con `=`, `+`, `-` o `@` (inyección de fórmulas en Excel). Cada exportación queda en la bitácora (`reporte_exportado`).
- Límite consciente: se agrega en Python sobre las líneas del periodo (bien hasta decenas de miles de líneas); para más volumen conviene pasar la agregación a SQL. El inventario valorizado lo ve quien tenga `reportes.ver` e `inventario.ver` (el vendedor ya ve costos en la pantalla de inventario; se revisa en la Fase 6).
- No hay gráficos todavía: tablas y totales. Se evalúan en la fase de interfaz.

## Interfaz y módulos nuevos (Fase 5.5)

- **Estilo** (`ui/tema.py`): oscuro con acento morado (paleta inspirada en la imagen del negocio). `aplicar_tema()` recolorea el tema azul de CustomTkinter; si algo falla, queda el tema por defecto. Encabezado con nombre del negocio (`NOMBRE_EMPRESA`), línea opcional (`ESLOGAN_EMPRESA`), reloj y usuario; logo opcional en `assets/logo.png` (no se dibuja ni se incluye ningún logo). Menú con iconos emoji según permisos.
- **Inicio** (`servicios/inicio.py`, `ui/inicio_pantalla.py`): ventas y ganancia del día con variación frente a ayer, unidades vendidas, inventario total, clientes, aviso de stock bajo, últimas ventas, más vendidos (30 días) y gráfica de 7 días. Cada bloque llega `None` si el rol no puede verlo; el vendedor ve solo lo suyo y sin ganancia.
- **Gastos** (`servicios/gastos.py`): categorías fijas (alquiler, servicios, salarios, insumos, transporte, mantenimiento, publicidad, otros); sin edición ni borrado, solo anulación con motivo. Permiso `gastos` (ver, crear, anular): administrador y contador. `reportes.resultado_del_periodo` = utilidad bruta − gastos = utilidad neta (exige ver costos). Al filtrar por sucursal solo entran los gastos asignados a ella.
- **Clientes**: editar (permiso `ventas.crear`) y desactivar/reactivar (`ventas.anular`); un cliente desactivado no se puede usar en ventas nuevas. **Proveedores**: editar con `inventario.editar` (nombre único).
- Eventos auditados nuevos: `gasto_registrado`, `gasto_anulado`, `cliente_editado`, `cliente_activado/desactivado`, `proveedor_editado`.
- Actualizar una instalación existente: `python main.py --migrar` y luego `python seed.py` (crea los permisos de `gastos` y se los da al contador sin quitar personalizaciones).
- Pendiente consciente: no se incluyen fotos de producto ni la pantalla de configuración de la imagen original; son candidatos para una fase posterior. Los iconos son emoji (en Linux requieren una fuente de emoji instalada).

## Servicios sin stock (Fase 6a)

- Un producto puede ser **servicio** (polarizado, instalación, car wash): se marca al crearlo y no se puede cambiar después. Su stock mínimo es siempre 0.
- `aplicar_movimiento` rechaza cualquier movimiento de un servicio (compras, mermas, ajustes, traslados). `existencias`, alertas de stock bajo e inventario valorizado lo excluyen.
- `registrar_venta` vende servicios sin descontar nada y congela precio y costo como siempre (el costo del servicio es lo que se anotó en «Costo»: materiales, comisión...). `anular_venta` no devuelve stock de servicios. Los reportes de ventas y utilidad lo incluyen normalmente.
- La caja muestra «servicio» en lugar de stock; la pantalla de productos tiene el interruptor «Es un servicio».
- Una venta con servicio y producto sigue siendo todo o nada.
- Actualizar una instalación existente: `python main.py --migrar` (migración 0007; los productos existentes quedan como productos normales).

## Pulido y seguridad (Fase 6b)

- **Costos ocultos:** `permisos.puede_ver_costos` (tiene `ventas.ver_todas`, `productos.precios` o `inventario.crear`: administrador, contador, bodeguero). Quien no, recibe `costo`/`valor` en `None` en catálogo, existencias, kardex, historial de producto (se omiten los cambios de costo), inicio y CSV (columnas vacías); el inventario valorizado le da 403. El precio de venta sí lo ve.
- **Bloqueo de acceso:** 5 intentos fallidos con el mismo correo en 15 minutos bloquean el inicio de sesión (aunque la clave sea correcta) hasta que pasen; vale también para correos inexistentes, no revela cuáles existen y un acceso correcto reinicia la cuenta. Eventos: `login_fallido`, `login_bloqueado`.
- **Respaldos** (`app/respaldo.py`, solo SQLite): `python main.py --respaldo` crea `respaldos/respaldo_AAAAMMDD_HHMMSS_micro.db` con la API de respaldo de SQLite y verifica su integridad; se conservan los 14 más recientes. Un respaldo automático por día al abrir la aplicación (`RESPALDO_AUTOMATICO=false` lo desactiva; `CARPETA_RESPALDOS` cambia la carpeta). `python main.py --restaurar ARCHIVO` (con la aplicación cerrada) guarda antes la base actual como `antes_de_restaurar_*.db`. Con PostgreSQL usar `pg_dump`.
- **Salud:** `python main.py --salud` ahora también compara cada existencia con su kardex (`verificar_consistencia`) y sale con error si no cuadra. El login sigue usando la versión liviana.
- **Paginación:** el historial de ventas muestra 25 por página (`listar_ventas(..., desplazamiento=)`).
- **Revisión de seguridad hecha:** contraseñas con argon2, permisos comprobados en servicios (no solo en la interfaz), vendedor limitado a sus ventas, CSV protegido contra fórmulas, auditoría de eventos sensibles, ventas y gastos sin borrado. Pendientes conscientes: no hay cierre de sesión por inactividad; los archivos de respaldo no van cifrados (guárdalos en un lugar seguro); `.env` y `*.db` están fuera de Git.

## Configuración e inactividad (Fase 7a)

- `servicios/configuracion.py` guarda parámetros en la tabla `configuracion` (sin migración nueva): `nombre_empresa`, `eslogan` (si no hay valor guardado se usa el `.env`) e `inactividad_minutos` (por defecto 15; 0 = nunca; máximo 480). Cambios auditados como `configuracion_cambiada` (valor anterior y nuevo).
- Permiso nuevo `configuracion` (`ver`, `editar`), solo administrador. En una instalación existente: `python seed.py` (crea el permiso y se lo da al administrador).
- Cierre por inactividad en `ui/aplicacion.py`: cualquier tecla, mouse o clic reinicia el reloj; revisa cada 10 s; al vencer cierra la sesión (`logout` + `sesion_expirada` en bitácora) y el login avisa. La lógica pura es `sesion_expirada`. Una venta sin cobrar en la caja se pierde.

## Fotos de producto (Fase 7b)

- Migración `0008`: `productos.foto` (nombre de archivo, no la imagen). La imagen se copia a `fotos/` (`CARPETA_FOTOS`), reducida a 800 px y convertida a JPEG; el original no se toca. Formatos: PNG, JPG, GIF, BMP, WEBP; máximo 10 MB; se valida con Pillow. Pillow 11.0.0 ahora está en `requirements.txt`.
- `servicios/fotos.py`: `asignar_foto` y `quitar_foto` (permiso `productos.editar`, auditados como `foto_asignada` / `foto_quitada`; reemplazar o quitar borra el archivo anterior) y `rutas_de_fotos` (`productos.ver`; omite archivos que ya no existen). `foto` NO se agregó a `_a_dict` para no alterar el contrato del catálogo.
- Pantalla Productos: columna de miniatura y, en el diálogo, vista previa con «Elegir foto…» y «Quitar foto». Al crear, la foto se guarda en la misma transacción que el producto.
- `fotos/` está en `.gitignore`: **respáldala junto con `respaldos/`** (el respaldo de la base no incluye las imágenes).
- Actualizar: `pip install -r requirements.txt` y `python main.py --migrar`.
- Pendiente consciente: la caja aún no muestra fotos.

## Pagos mixtos y devoluciones (Fase 7c)

- Migración `0009`: `ventas_pagos` (venta, método, monto, recibido), `devoluciones` y `devoluciones_detalle`. Parte de `0008` (fotos): hay que unir 7b antes.
- **Pagos:** `registrar_venta(..., pagos=[{"metodo","monto","recibido"}])`; la suma debe ser exactamente el total, sin métodos repetidos ni montos en cero si hay más de uno. `metodo_pago` queda en `mixto` cuando hay varios. Solo el efectivo admite `recibido` (cambio = recibido − monto). Sin `pagos` se usa `metodo_pago` por el total (siempre se guarda una fila de pago). Las ventas anteriores sin filas se muestran con su `metodo_pago`.
- **Devoluciones** (`servicios/devoluciones.py`): permiso nuevo `ventas.devolver` (solo administrador por defecto; se concede por usuario). Solo ventas completadas; quien no ve todas las ventas solo devuelve las suyas. Reembolso por línea = ingreso de la línea (descuentos prorrateados) × unidades / vendidas, redondeo acumulado: al devolver todo se reembolsa exactamente lo cobrado. El stock vuelve a la sucursal de la venta al costo con que salió (movimiento `devolucion`); los servicios no mueven stock. `previsualizar_devolucion` calcula sin guardar. Auditoría: `devolucion_registrada`.
- **Anulación:** una venta con devoluciones ya no se puede anular (se devuelve lo que falta); una anulada no admite devoluciones.
- **Reportes:** las devoluciones restan unidades, ingreso y costo en el día en que se hicieron, con el vendedor y la sucursal de la venta original, y no cuentan como ventas. Con eso también cambian Inicio y resultado del periodo. La repartición del descuento ahora vive en `ventas.repartir_descuento`.
- **Pantalla:** en la caja, «Efectivo recibido» con cambio en vivo y «Dividir pago…» (reparte el total, avisa si falta o sobra y se cancela solo si cambia el total). En el comprobante, «Devolver…» (elige cantidades, calcula el reembolso, pide motivo y forma de reembolso). El comprobante muestra pagos, cambio, devoluciones y neto.
- Pendiente consciente: no hay devoluciones sin venta de origen; el reembolso solo se registra (no hay caja que cuadrar); el CSV de detalle de ventas no incluye aún lo devuelto.

## Instalador de Windows (Fase 7f)

- **Empaquetado:** `instalador/construir.py` (PyInstaller, modo carpeta y sin consola) y `instalador/Inventario.iss` (Inno Setup, instalación por usuario, en español). Flujo manual `.github/workflows/instalador.yml` («Instalador») en `windows-latest`: construye, hace una **prueba de humo** del .exe (`Inventario.exe --autoprueba`: base temporal, migraciones, administrador, login con argon2, salud e importación de todas las pantallas; escribe `autoprueba.txt`), compila el instalador y sube `Instalador-Inventario.exe` y `Inventario-portatil.zip` como artifact `Inventario-Windows`. Si falla, las anotaciones traen el final del registro.
- **Rutas** (`app/config.py`): con `sys.frozen` los recursos de solo lectura (migraciones en `migraciones/`, `alembic.ini`, assets) salen del paquete (`RAIZ_PROYECTO`) y todo lo escribible (base `inventario.db`, `respaldos/`, `fotos/`, `.env`, `assets/logo.png` propio) va a `DIRECTORIO_DATOS` = `%LOCALAPPDATA%\Inventario` (o `INVENTARIO_DATOS`). Sin empaquetar nada cambia. `RUTA_MIGRACIONES` unifica dónde están las migraciones.
- **Arranque** (`main.py`): al abrir la ventana se hace el respaldo diario (si la base ya existe), se aplican las migraciones y se crean los permisos nuevos; así actualizar no requiere comandos. Un fallo al arrancar se guarda en `error.log` y se muestra en una ventana. Sin consola, stdout/stderr se redirigen a `os.devnull`.
- **Primer uso** (`PantallaPrimerUso`): si no hay usuarios, la ventana pide negocio, nombre, correo y contraseña (y opcionalmente datos de ejemplo) y crea el administrador (reemplaza a `seed.py` para el usuario final).
- `__version__` pasó a 0.7.0. `build/`, `dist/`, `salida/`, `autoprueba.txt` y `error.log` quedan fuera de Git.
- **No se pudo construir ni probar el .exe en la sesión** (el entorno no es Windows y PyPI está bloqueado): la primera corrida del flujo «Instalador» puede necesitar ajustes (módulos que PyInstaller no detecte, etc.). El instalador no está firmado: Windows SmartScreen avisará.
- Pendiente consciente: sin icono propio (`--icon`), sin actualización automática ni firma de código.

## Costeo PEPS configurable (Fase 7d)

- **Capas de costo** (`capas_costo`, migración `0010`): cada compra, devolución, anulación o ajuste positivo crea una capa (cantidad inicial/restante, costo unitario, origen). Se mantienen **siempre**, sea cual sea el método, para poder cambiar de método sin perder historia. La migración siembra una capa «inicial» por cada existencia actual al costo promedio vigente.
- **Método** (`configuracion.metodo_costeo`: `promedio` por defecto o `peps`, pantalla Configuración → «Costeo del inventario»). Solo cambia (1) con qué costo sale una venta/merma/ajuste negativo y (2) cómo se valora el inventario. Con PEPS se consumen las capas más antiguas primero; el costo de la línea es el promedio ponderado (redondeado a centavos) de las capas consumidas. Las ventas anteriores conservan su costo congelado.
- `aplicar_movimiento` consume/crea capas; `trasladar` mueve las capas con su costo al destino; anular/devolver regresa las unidades al costo congelado de la venta.
- Tolerancia: si faltan capas (datos manipulados) la salida usa el costo promedio del producto en lugar de bloquear la venta; `verificar_capas` y `python main.py --salud` reportan la diferencia.
- UI: botón «Capas» junto a «Kardex» en Inventario (el cajero no ve costos).
- Pendiente consciente: el costo por línea se redondea a centavos por unidad (la suma de líneas puede diferir centavos del costo exacto de las capas).
- `tests/test_fase7d.py` (17 pruebas). **No se pudo ejecutar en la sesión** (PyPI bloqueado): correr «Pruebas» sobre `fase-7d-peps`.

## Dependencias

SQLAlchemy 2.0.36, alembic 1.14.0, customtkinter 5.2.2, Pillow 11.0.0, python-dotenv 1.0.1, argon2-cffi 23.1.0, pytest 8.3.4.

## Estado de pruebas

- Fases 0 y 1: pasaron en GitHub Actions. Fase 2 unida a `main` (PR #2).
- Fase 3: `tests/test_fase3.py` escrita (unas 35 pruebas); el código compila. **No se pudo ejecutar en la sesión de construcción** (PyPI bloqueado). Correr "Run workflow" en Actions sobre la rama `fase-3-inventario-kardex`.
- Riesgo a vigilar en esa corrida: el cambio de `crear_motor` (BEGIN explícito en SQLite) toca también las migraciones y las pruebas anteriores.
- Fase 4: `tests/test_fase4.py` escrita (unas 40 pruebas con casos); el código compila. **No se pudo ejecutar en la sesión de construcción**. Correr "Run workflow" en Actions sobre la rama `fase-4-ventas`.
- Fase 4: unida a `main` (PR #4), pruebas en verde.
- Fase 5: `tests/test_fase5.py` escrita (unas 25 pruebas); el código compila. **No se pudo ejecutar en la sesión de construcción**. Correr "Run workflow" en Actions sobre la rama `fase-5-reportes`.
- Fase 5: unida a `main` (PR #5), pruebas en verde.
- Fase 5.5 (interfaz): `tests/test_fase55.py` escrita (unas 45 pruebas con casos); el código compila. **No se pudo ejecutar en la sesión de construcción**. Correr "Run workflow" en Actions sobre la rama `fase-5-5-interfaz`.
- Fase 5.5: unida a `main` (PR #6), pruebas en verde.
- Fase 6a (servicios): `tests/test_fase6a.py` escrita (9 pruebas); el código compila. **No se pudo ejecutar en la sesión de construcción**. Correr "Run workflow" en Actions sobre la rama `fase-6a-servicios`.
- Fase 6a: unida a `main` (PR #8), pruebas en verde.
- Fase 6b: unida a `main`, pruebas en verde.
- Fase 6c: prueba nueva en `tests/test_seed.py` (seed sin ejemplos). Correr "Run workflow" sobre la rama `fase-6c-documentacion`.
- Las pantallas de CustomTkinter no tienen pruebas automáticas: hay que probarlas a mano (login, encabezado y reloj, menú, inicio, usuarios, permisos, bitácora, productos, inventario, clientes, proveedores, gastos, caja, historial de ventas y reportes).

## Fases planificadas

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Cimientos | Validada en GitHub Actions |
| 1 | Usuarios, roles, permisos por módulo, login, bitácora | Validada y unida a `main` |
| 2 | Catálogo de productos e historial de precios | Unida a `main` (PR #2) |
| 3 | Inventario, compras, kardex, alertas de stock mínimo, traslados entre sucursales | Unida a `main` (PR #3) |
| 4 | Ventas (POS), anulaciones, comprobante | Unida a `main` (PR #4) |
| 5 | Histórico y reportes | Unida a `main` (PR #5) |
| 5.5 | Interfaz: tema oscuro morado, inicio con indicadores y gráfica, clientes, proveedores y gastos | Unida a `main` (PR #6) |
| 6a | Servicios sin stock (polarizado, instalación, car wash) | Unida a `main` (PR #8) |
| 6b | Costos ocultos al cajero, bloqueo de acceso, respaldos, salud con inventario, paginación | Unida a `main` |
| 6c | Dockerfile, README completo, guía de GitHub, `SEMBRAR_EJEMPLOS` | Unida a `main` |
| 7a–7c, 7f | Configuración, inactividad, fotos, pagos mixtos, devoluciones, instalador | Unidas a `main` |
| 7d | Costeo PEPS configurable | Código en rama `fase-7d-peps` |
| 7e | Respaldos cifrados opcionales | Pendiente |

## Documentación (Fase 6c)

- `README.md` completo (instalación en Windows, roles, flujos, respaldos, actualización, configuración, seguridad, PostgreSQL, Docker, problemas comunes) y `docs/GUIA_GITHUB.md`.
- `SEMBRAR_EJEMPLOS=false` en `.env` hace que `seed.py` no cree productos ni stock de muestra (`sembrar(..., con_ejemplos=False)`).
- `Dockerfile` (python:3.12-bookworm) y `.dockerignore`: solo para pruebas y comandos; la ventana no corre en contenedor. **No probado** en la sesión de construcción.

## Siguiente paso

Probar la fase 7d (Actions «Pruebas» sobre `fase-7d-peps`; luego probar PEPS en Configuración). Después: 7e (respaldos cifrados opcionales). La mejora de interfaz (colores, tamaños, caja con catálogo y fotos, atajos de teclado, modo claro/oscuro) queda pendiente sin fecha.
