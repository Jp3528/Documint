# Migraciones

Desde la raíz: `uv run alembic upgrade head`. La revisión `0001` habilita pgvector y Alembic
registra el esquema vigente. Repetir upgrade es seguro. Las futuras tablas se crean mediante
revisiones sucesivas; no se usa `metadata.create_all()` al iniciar la API.

`uv run alembic current` informa la revisión instalada y `uv run alembic heads` la esperada.
Readiness falla si no coinciden. Para generar revisiones: `uv run alembic revision -m "cambio"`;
revisar su SQL y probarlas sobre una base vacía antes de subirlas.

El downgrade de `0001` conserva la extensión deliberadamente: eliminarla podría destruir
vectores compartidos. No se ejecuta `DROP EXTENSION ... CASCADE` ni se borra evidencia histórica.
