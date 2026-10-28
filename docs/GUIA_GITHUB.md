# Guía de GitHub paso a paso

Para quien no ha usado Git. Todo se puede hacer con la terminal o con **GitHub Desktop** (<https://desktop.github.com/>), que es más amigable.

## 1. Crear el repositorio

1. Entra a <https://github.com> e inicia sesión.
2. *New repository* → ponle un nombre (por ejemplo `inventario`).
3. Elige **Private** (recomendado: es el sistema de tu negocio).
4. No marques «Add a README»: el proyecto ya trae uno.

## 2. Subir el proyecto por primera vez

Con la terminal, dentro de la carpeta del proyecto:

```bash
git init
git add .
git commit -m "Primera versión"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/TU_REPOSITORIO.git
git push -u origin main
```

Con GitHub Desktop: *File → Add local repository*, elige la carpeta, *Publish repository*.

`.gitignore` ya excluye `.env`, las bases `*.db` y la carpeta `respaldos/`. Antes de subir revisa con `git status` que no aparezcan; **tus datos y contraseñas no deben subirse**.

## 3. Trabajar con ramas y Pull Requests

Cada cambio se hace en una rama, no directamente en `main`:

```bash
git checkout -b mi-cambio
# ... editar archivos ...
git add .
git commit -m "Describe el cambio"
git push -u origin mi-cambio
```

En GitHub aparece el botón **Compare & pull request**. Créalo, revisa los cambios y espera a que las pruebas pasen antes de unirlo.

## 4. Correr las pruebas (Actions)

El flujo **Pruebas** es manual:

1. Pestaña **Actions** → **Pruebas** (a la izquierda).
2. **Run workflow** → elige la rama → **Run workflow**.
3. Espera uno o dos minutos y actualiza la página. Verde = todo bien; rojo = hay un fallo.

Corre en Python 3.11 y 3.12: ejecuta `pytest`, luego `python main.py --migrar` y `--salud`.

## 5. Si una prueba falla

Abre la corrida fallida y entra al trabajo (*job*). Los fallos aparecen como **anotaciones** (cuadros rojos) arriba del resumen, con el nombre de la prueba y el motivo. Copia ese texto o toma una captura y compártelo para corregirlo.

## 6. Unir los cambios (merge)

Con las pruebas en verde, en el Pull Request pulsa **Merge pull request → Confirm merge**. Después, en tu computadora:

```bash
git checkout main
git pull
```

Si el cambio trae migraciones, sigue con «Actualizar a una versión nueva» del README (`--migrar` y `seed.py`).

## 7. Buenas prácticas

- Haz un respaldo (`python main.py --respaldo`) antes de actualizar.
- Mantén el repositorio privado si tiene datos del negocio.
- No subas `.env`, `*.db` ni respaldos. Si lo hiciste por error, cambia las contraseñas y avisa: borrar el archivo después no lo quita del historial.
