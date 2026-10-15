# DocuMind AI

Plataforma de conocimiento empresarial con ingestión documental, permisos y RAG con evidencia.
El repositorio se llama **Documint**; el nombre del producto es **DocuMind AI**.

El desarrollo sigue el plan 1.1 en nueve fases y 36 sesiones. La primera entrega prepara API,
worker, interfaz de estado y comprobaciones automáticas. El seguimiento está en
[docs/progress.md](docs/progress.md).

## Requisitos

- Python **3.12** y [uv](https://docs.astral.sh/uv/).
- Node.js **22.12 o superior**; CI utiliza Node 22.
- npm **11.6.2** para resolver las dependencias de workspaces de forma reproducible.
- Redis será necesario para ejecutar un worker con broker real desde la sesión 0B.

## Instalación

Desde la raíz del repositorio:

```sh
uv sync --locked --dev
npx --yes npm@11.6.2 ci
```

Las dependencias se fijan en `uv.lock` y `package-lock.json`. No se necesitan claves de IA.

## Desarrollo

En una terminal, inicia la API:

```sh
uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

En otra terminal, inicia la web:

```sh
npm run dev
```

Abre `http://127.0.0.1:5173` y pulsa **Comprobar conexión**. Vite reenvía `/health` a la API;
no requiere configurar CORS para este flujo local. El contrato HTTP está en
`http://127.0.0.1:8000/docs`.

`GET /health` comprueba que el proceso de la API responde. No afirma que PostgreSQL, Redis o
storage estén disponibles; el endpoint separado de readiness se incorpora en 0B.

## Worker

Con Redis disponible, inicia un worker en otra terminal:

```sh
uv run celery -A apps.worker.celery_app:celery_app worker --pool=solo --loglevel=INFO
```

Despacha y verifica una tarea por el broker:

```sh
uv run python -m scripts.worker_smoke
```

El pool `solo` permite el smoke local en Windows. El despliegue del worker será Linux/Docker.
Las variables de broker están documentadas en `.env.example`. Celery las lee del entorno del
proceso; el archivo `.env` todavía no se carga automáticamente.

## Comprobaciones

```sh
uv run python -m scripts.check
```

Ese comando ejecuta lint y formato Python, mypy, pytest, lint/tipos/pruebas web, build y formato
del repositorio. También se pueden ejecutar individualmente:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
npm run lint
npm run typecheck
npm test
npm run build
npm run format:check
```

La prueba de worker inicia un worker real en el proceso con transporte de memoria. Comprueba
registro, serialización y ejecución; no equivale a verificar Redis. Todos los checks automáticos
son independientes de un proveedor de IA.

## Estructura

```text
apps/api/          FastAPI y operaciones HTTP
apps/worker/       Celery y tareas asíncronas
apps/web/          React, TypeScript y Vite
packages/rag/      Recuperación y evidencia, desde la fase 4
packages/providers/  Contratos y fakes, desde 0C
packages/parsers/  Extracción documental, desde 3A
migrations/       Migraciones, desde 0B
tests/            Pruebas Python por nivel
evals/            Evaluaciones y preguntas esperadas, desde 0C
demo_corpus/      Documentos sintéticos, desde 0C
docs/             Decisiones, avances y evidencia
infra/            Servicios y despliegue, desde 0B
```

## Integración continua

[CI](https://github.com/Jp3528/Documint/actions/workflows/ci.yml) ejecuta los mismos checks en cada
push y pull request, con permisos de lectura. Se ampliará conforme existan migraciones,
infraestructura y reglas de seguridad. El empaquetado de producción corresponde a la fase 8.
