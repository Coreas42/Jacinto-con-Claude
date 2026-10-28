# Sistema de inventario y ventas

Aplicación de escritorio (Python + CustomTkinter + SQLite) para controlar inventario, compras, ventas, servicios y gastos en una o varias sucursales. Incluye kardex, histórico de precios, trazabilidad de quién vendió, roles con permisos, reportes con ganancia y respaldos.

Pensada para negocios como accesorios de auto, instalación, polarizado y lavado: vende productos con stock y servicios sin stock en la misma caja.

> **Estado:** Fase 6c (documentación). El avance detallado está en [`PROGRESO.md`](PROGRESO.md).

## Qué incluye

- **Inicio:** ventas y ganancia del día, productos vendidos, inventario, aviso de stock bajo, últimas ventas, más vendidos y gráfica de 7 días.
- **Caja (ventas):** lector de código de barras, búsqueda, descuentos, cliente, forma de pago, comprobante imprimible, anulación con motivo.
- **Productos y servicios:** SKU, código de barras, categoría, foto, precio, costo, stock mínimo e historial de cambios.
- **Inventario:** compras a proveedores, mermas, ajustes, traslados entre sucursales, kardex y alertas de stock mínimo (costo promedio ponderado).
- **Clientes, proveedores y gastos.**
- **Reportes:** ventas por día, vendedor, producto, categoría o sucursal; inventario valorizado; resultado del periodo (ganancia bruta − gastos); exportación a CSV.
- **Usuarios y permisos** por módulo, y **bitácora** de acciones sensibles.
- **Respaldos** automáticos y restauración.

## Requisitos

- Python 3.11 o superior.
- En Linux, `python3-tk` para la ventana: `sudo apt install python3-tk`.
- Los iconos del menú son emoji; en Linux hace falta una fuente de emoji instalada.

## Instalador de Windows (recomendado)

No necesitas instalar Python ni usar la terminal.

1. En GitHub: **Actions → Instalador → Run workflow**. Espera unos minutos y abre la corrida terminada.
2. En **Artifacts** descarga `Inventario-Windows` (un .zip que contiene `Instalador-Inventario.exe` y `Inventario-portatil.zip`).
3. Ejecuta `Instalador-Inventario.exe`. Se instala por usuario, sin permisos de administrador, y crea el acceso en el menú Inicio (y en el escritorio si lo eliges).
4. Abre **Inventario**. La primera vez aparece una pantalla de bienvenida: escribe el nombre del negocio y crea tu usuario administrador (el correo es tu usuario). No hace falta `seed.py`.

- **Windows puede advertir** («Windows protegió su PC») porque el instalador no tiene firma digital de pago. Pulsa *Más información → Ejecutar de todas formas*.
- **Tus datos** (base de datos, respaldos, fotos, `.env` y tu logo en `assets\logo.png`) viven en `%LOCALAPPDATA%\\Inventario`; en el menú Inicio hay un acceso a esa carpeta. Desinstalar o actualizar el programa no los borra.
- **Actualizar:** construye un instalador nuevo y ejecútalo encima. Al abrir, el programa aplica solo las migraciones y los permisos nuevos y antes hace un respaldo del día.
- **Versión portátil:** descomprime `Inventario-portatil.zip` en cualquier carpeta y ejecuta `Inventario.exe`.
- Si el programa no abre, revisa `error.log` en la carpeta de datos.
- Comandos de mantenimiento con el programa instalado: desde una terminal, `Inventario.exe --salud` o `--respaldo` (sin ventana de consola no muestran texto; el resultado queda en el respaldo o en la bitácora).

## Instalación manual en Windows (con Python)

1. **Instala Python** desde <https://www.python.org/downloads/>. En el instalador marca **«Add python.exe to PATH»**.
2. **Descarga el proyecto:** en GitHub pulsa *Code → Download ZIP* y descomprímelo (por ejemplo en `C:\inventario`), o clónalo con `git clone`.
3. Abre **PowerShell** dentro de la carpeta y ejecuta:

   ```powershell
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   copy .env.example .env
   ```

   Si PowerShell bloquea `activate`, ejecuta una vez `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` o usa el Símbolo del sistema (cmd).
4. **Edita `.env`** con el Bloc de notas: pon el nombre de tu negocio (`NOMBRE_EMPRESA`), tu correo (`ADMIN_CORREO`) y, para un negocio real, `SEMBRAR_EJEMPLOS=false`.
5. **Prepara la base de datos y el primer administrador:**

   ```powershell
   python main.py --migrar
   python seed.py
   ```

6. **Abre la aplicación:** `python main.py`. Desde la fase 7f, al abrir se aplican solas las migraciones pendientes; si no hay usuarios, la ventana ofrece crear el administrador (equivale a `seed.py`).

En Linux y macOS es igual, pero se activa el entorno con `source venv/bin/activate` y se copia con `cp .env.example .env`.

## Primer ingreso

`python seed.py` crea los roles (administrador, bodeguero, vendedor, contador), la sucursal «Principal» y el primer administrador con `ADMIN_CORREO` y `ADMIN_CONTRASENA` del `.env`. Si no defines la contraseña, la pide por consola o genera una aleatoria y **la muestra una sola vez**: anótala y cámbiala después de entrar.

- Con `SEMBRAR_EJEMPLOS=true` (valor por defecto) también carga 9 productos y stock de muestra, útiles para probar. En un negocio real pon `false` antes de ejecutar `seed.py`. Si ya se cargaron, desactívalos desde *Productos*.
- `seed.py` se puede ejecutar de nuevo sin riesgo: no duplica nada ni cambia contraseñas.

## Uso por rol

| Módulo | Administrador | Contador | Bodeguero | Vendedor |
|---|---|---|---|---|
| Productos | todo | ver | ver y editar (sin precios) | ver |
| Inventario | todo | ver | todo (compras, mermas, ajustes, traslados, CSV) | ver |
| Ventas | todo, ver todas, anular, devolver | ver todas | — | ver las propias y vender |
| Reportes | ver y exportar | ver y exportar | ver (solo inventario) | ver (solo lo propio) |
| Gastos | todo | ver, crear, anular | — | — |
| Bitácora | ver | ver | — | — |
| Usuarios y permisos | todo | — | — | — |

- El **vendedor no ve costos ni ganancia**: esas columnas aparecen vacías. Ven costos el administrador, el contador y el bodeguero.
- El administrador puede conceder o quitar permisos puntuales a un usuario desde *Usuarios*.
- Nadie puede cambiar su propio rol, desactivarse ni editar sus propios permisos.

## Flujos del día a día

**Vender.** Menú *Ventas*: escanea el código o busca por nombre/SKU, ajusta cantidades, elige cliente y forma de pago, aplica descuento si hace falta y cobra. Se genera un número (`V-000001`) y un comprobante que se imprime con *Imprimir*. Los servicios se venden igual pero no descuentan stock.

**Cobrar con varias formas de pago.** En la caja, «Dividir pago…» reparte el total entre efectivo, tarjeta, transferencia u otro (debe sumar exacto). Con efectivo, escribe «Efectivo recibido» y verás el cambio; el comprobante lo muestra.

**Anular una venta.** *Ventas → Historial*, elegir la venta y anular con un motivo (permiso `ventas.anular`). El stock vuelve al kardex. Las ventas nunca se borran. Una venta que ya tiene devoluciones no se anula.

**Devolver parte de una venta.** *Ventas → Historial → Ver → Devolver…* (permiso `ventas.devolver`, solo el administrador por defecto): elige cuántas unidades regresan de cada línea, escribe el motivo y la forma de reembolso. El stock vuelve a la sucursal y los reportes restan lo devuelto en el día de la devolución. Se puede devolver varias veces hasta agotar las unidades.

**Comprar mercadería.** *Inventario → Compra*: elige proveedor, productos, cantidades y costo. Recalcula el costo promedio y suma el stock.

**Corregir existencias.** *Ajuste* (conteo físico, con motivo), *Merma* (pérdida o daño, con motivo) o *Traslado* entre sucursales. No hay anulación de compras: se corrige con un ajuste.

**Servicios (polarizado, instalación, lavado).** En *Productos* activa «Es un servicio» al crearlo (no se puede cambiar después). No maneja stock; el campo «Costo» es lo que te cuestan los materiales o la comisión, para calcular la ganancia.

**Gastos.** *Gastos → Nuevo*: fecha, categoría, descripción y monto. No se editan; se anulan con motivo.

**Reportes.** Elige periodo y sucursal. «Resultado del periodo» = ganancia bruta − gastos. Los CSV se pueden abrir en Excel y cada exportación queda en la bitácora.

**Clientes y proveedores.** Se crean y editan desde sus pantallas; un cliente desactivado no se puede usar en ventas nuevas.

## Respaldos y restauración

Con SQLite el sistema crea **un respaldo por día** al abrir la aplicación en la carpeta `respaldos/` y conserva los 14 más recientes.

```bash
python main.py --respaldo                       # respaldo manual ahora
python main.py --restaurar respaldos/ARCHIVO.db # restaurar (con la aplicación cerrada)
python main.py --salud                          # revisa la base y que el stock cuadre con el kardex
```

- Al restaurar, la base actual se guarda como `antes_de_restaurar_*.db`.
- Las **fotos** de producto viven en la carpeta `fotos/` y no van dentro del respaldo de la base: cópiala junto con `respaldos/`.
- Los respaldos **no van cifrados**. **Copia la carpeta `respaldos/` a una memoria USB o a la nube con regularidad**: si falla el disco se pierden la base y sus respaldos.
- Con PostgreSQL los respaldos se hacen con `pg_dump`.

## Actualizar a una versión nueva

1. Haz un respaldo: `python main.py --respaldo`.
2. Cierra la aplicación.
3. Descarga los cambios: `git pull` (o reemplaza los archivos del ZIP; tu `.env` y tu base `.db` no se tocan).
4. Con el entorno activado:

   ```powershell
   pip install -r requirements.txt
   python main.py --migrar
   python seed.py
   ```

   `--migrar` actualiza las tablas y `seed.py` agrega permisos nuevos sin quitar los que personalizaste.
5. Comprueba con `python main.py --salud` y abre la aplicación.

## Configuración (`.env`)

| Variable | Para qué sirve | Por defecto |
|---|---|---|
| `DATABASE_URL` | Base de datos | `sqlite:///inventario.db` |
| `NOMBRE_EMPRESA` | Nombre en la ventana y comprobantes | `Mi Empresa` |
| `ESLOGAN_EMPRESA` | Línea bajo el nombre (opcional) | vacío |
| `SQL_DEBUG` | Muestra el SQL en consola | `false` |
| `ADMIN_NOMBRE`, `ADMIN_CORREO`, `ADMIN_CONTRASENA` | Primer administrador (`seed.py`) | `Administrador`, `admin@ejemplo.com`, se pide o se genera |
| `SEMBRAR_EJEMPLOS` | Productos y stock de muestra en `seed.py` | `true` |
| `RESPALDO_AUTOMATICO` | Respaldo diario al abrir | `true` |
| `CARPETA_RESPALDOS` | Dónde se guardan los respaldos | `respaldos` |
| `CARPETA_FOTOS` | Dónde se guardan las fotos de producto | `fotos` |
| `INVENTARIO_DATOS` | Solo con el programa instalado: carpeta de datos | `%LOCALAPPDATA%\\Inventario` |

Para mostrar tu logo guarda el archivo como `assets/logo.png` (alto recomendado: 120 px o más); si no existe solo se muestra el nombre.

## Seguridad

- Contraseñas con argon2 (mínimo 8 caracteres). Los permisos se comprueban en los servicios, no solo en la interfaz.
- **Bloqueo de acceso:** 5 intentos fallidos con el mismo correo en 15 minutos bloquean el inicio de sesión hasta que pasen.
- Ventas y gastos no se borran: se anulan con motivo y quedan en la bitácora.
- Los CSV neutralizan textos que Excel interpretaría como fórmulas.
- `.env` y `*.db` están fuera de Git: **nunca los subas a GitHub**.
- Pendientes conocidos: no hay cierre de sesión por inactividad y los respaldos no están cifrados.

## PostgreSQL (opcional)

SQLite basta para una caja o pocas. Si varias cajas escriben a la vez conviene PostgreSQL: instala el controlador con `pip install "psycopg[binary]"` y define `DATABASE_URL=postgresql+psycopg://usuario:clave@servidor:5432/inventario`. No está incluido en `requirements.txt` ni probado en las pruebas automáticas.

## Docker (solo pruebas y mantenimiento)

La ventana de escritorio **no corre en un contenedor** (necesita pantalla). La imagen sirve para ejecutar las pruebas y los comandos de mantenimiento:

```bash
docker build -t inventario .
docker run --rm inventario                                              # corre pytest
docker run --rm -v inventario_datos:/app/datos inventario python main.py --migrar
docker run --rm -v inventario_datos:/app/datos inventario python main.py --salud
```

> El `Dockerfile` no se ha probado en la sesión de construcción (no hay red hacia Docker Hub allí). Si falla, abre un aviso con el mensaje de error.

## Pruebas

```bash
pip install -r requirements.txt
pytest
```

En GitHub, el flujo **Pruebas** se lanza a mano: *Actions → Pruebas → Run workflow*. Las pantallas de CustomTkinter no tienen pruebas automáticas; se revisan a mano. Ver [`docs/GUIA_GITHUB.md`](docs/GUIA_GITHUB.md).

## Solución de problemas

| Problema | Qué hacer |
|---|---|
| `python` no se reconoce | Reinstala Python marcando «Add to PATH» o usa `py` en lugar de `python`. |
| `No module named '_tkinter'` / `tkinter` | En Linux: `sudo apt install python3-tk`. |
| Los iconos del menú salen como cuadros | Instala una fuente de emoji (en Linux, `fonts-noto-color-emoji`). |
| «database is locked» | Hay otra caja o proceso usando el mismo archivo `.db`. Cierra los otros o pasa a PostgreSQL. |
| Cuenta bloqueada al iniciar sesión | Espera 15 minutos sin intentar de nuevo. |
| Olvidé la contraseña del administrador | Otro usuario con permiso de usuarios puede restablecerla. Si no hay otro, crea la base de nuevo desde un respaldo o pide ayuda con el `.db` a mano. |
| `--salud` dice que no cuadra el stock | No uses el sistema hasta revisarlo. Restaura el último respaldo bueno y avisa del caso. |
| Falta una opción de menú tras actualizar | Ejecuta `python main.py --migrar` y `python seed.py`. |

## Estructura

```text
app/
  config.py        configuración por variables de entorno
  db.py            motor, sesiones y transacciones
  respaldo.py      respaldos y restauración (SQLite)
  salud.py         verificación de la base
  modelos/         tablas de la base de datos
  servicios/       reglas de negocio (sin depender de la interfaz)
  ui/              ventanas de CustomTkinter
alembic/           migraciones de la base de datos
tests/             pruebas automatizadas
docs/              guías (GitHub)
Dockerfile         imagen para pruebas y mantenimiento
main.py            arranque y comandos (--migrar --salud --respaldo --restaurar)
seed.py            roles, permisos, administrador y datos de ejemplo
PROGRESO.md        estado del proyecto entre fases
```
