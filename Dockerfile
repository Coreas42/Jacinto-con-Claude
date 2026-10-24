# Imagen para ejecutar las pruebas y los comandos de mantenimiento (migrar, seed, salud, respaldo).
# La ventana de escritorio (CustomTkinter) necesita una pantalla: instala la aplicación en tu
# computadora para usarla (ver README.md). La imagen completa de Python incluye tkinter.
FROM python:3.12-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////app/datos/inventario.db \
    CARPETA_RESPALDOS=/app/respaldos

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# La base de datos y los respaldos viven en volúmenes para que sobrevivan al contenedor.
RUN mkdir -p /app/datos /app/respaldos
VOLUME ["/app/datos", "/app/respaldos"]

# Por defecto corre las pruebas. Otros comandos:
#   docker run --rm -v inventario_datos:/app/datos inventario python main.py --migrar
#   docker run --rm -v inventario_datos:/app/datos -e ADMIN_CORREO=yo@correo.com inventario python seed.py
#   docker run --rm -v inventario_datos:/app/datos inventario python main.py --salud
CMD ["pytest", "-q"]
