# Sistema de inventario y ventas

Aplicación de escritorio (Python + CustomTkinter + SQLite) para controlar inventario, compras y ventas en varias sucursales, con kardex, histórico de precios y trazabilidad de quién vendió.

> **Estado:** Fase 0 (cimientos). Aún no hay módulos de negocio; el avance está en `PROGRESO.md`.

## Requisitos

- Python 3.11 o superior
- En Linux, `python3-tk` para la ventana (`sudo apt install python3-tk`)

## Instalación

```bash
python -m venv venv
source venv/bin/activate        # En Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # En Windows: copy .env.example .env
```

## Uso

```bash
python main.py --migrar   # crea o actualiza la base de datos
python main.py --salud    # verifica la base de datos y las migraciones
python main.py            # abre la aplicación
```

## Pruebas

```bash
pytest
```

## Estructura

```text
app/
  config.py        configuración por variables de entorno
  db.py            motor, sesiones y transacciones
  modelos/         tablas de la base de datos
  servicios/       reglas de negocio (sin depender de la interfaz)
  ui/              ventanas de CustomTkinter
alembic/           migraciones de la base de datos
tests/             pruebas automatizadas
PROGRESO.md        estado del proyecto entre fases
```

## Subir a GitHub

```bash
git init
git add .
git commit -m "Fase 0: cimientos del sistema de inventario"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPOSITORIO.git
git push -u origin main
```

El archivo `.gitignore` ya excluye la base de datos (`*.db`) y el archivo `.env`.
