# Documint | Document Knowledge Platform

[Español](#espanol) · [English](#english)

<a id="espanol"></a>

## Español

### Descripción

Plataforma de conocimiento documental en desarrollo, orientada a gestionar fuentes con permisos y construir respuestas respaldadas por evidencia. La implementación actual cubre identidad, biblioteca versionada, almacenamiento privado y un pipeline completo de extracción, fragmentación e indexación vectorial.

### Funcionalidades

- Autenticación con access tokens, rotación de refresh y administración de usuarios y departamentos.
- Biblioteca con permisos, versiones inmutables y originales en almacenamiento S3 privado.
- Carga validada de PDF, DOCX, TXT y Markdown.
- Pipeline con Redis/Celery, parsers con procedencia, fragmentación e índices pgvector versionados.
- Corpus sintético, proveedores fake deterministas y evidencia de avance por sesión.

### Tecnologías

Python 3.12 · FastAPI · PostgreSQL/pgvector · Redis · Celery · MinIO/S3 · React · TypeScript · Vite · Docker

### Ejecutar localmente

**Requisitos:** Python 3.12, uv, Node.js 22.12 o superior, npm 11.6.2 y Docker con Compose v2 y contenedores Linux.

```bash
git clone https://github.com/Jp3528/Documint.git
cd Documint
```

```bash
uv sync --locked --dev
npx --yes npm@11.6.2 ci
uv run python -m scripts.init_env
```

**Configuración.** `scripts.init_env` crea `.env` con una clave privada aleatoria y conserva una existente. Consulta [`.env.example`](.env.example) para personalizar puertos y servicios. El entorno base no necesita claves de IA.

```bash
docker compose up -d --build --wait --wait-timeout 120
uv run alembic upgrade head
uv run python -m scripts.init_storage
```

Inicia la API y la web en terminales separadas:

```bash
uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
npm run dev
```

Web: `http://localhost:5173`. Contrato OpenAPI: `http://127.0.0.1:8000/docs`. Para crear una cuenta local, consulta `uv run python -m scripts.create_user --help`.

Para procesar trabajos, ejecuta en otras terminales:

```bash
uv run celery -A apps.worker.celery_app:celery_app worker --pool=solo --queues=celery,documind.processing --loglevel=INFO
```

```bash
uv run python -m scripts.dispatch_jobs --watch
```

### Comprobaciones

```bash
uv run python -m scripts.check
npm run format:check
```

El check reúne lint, formato, tipos, pruebas y build. Las pruebas con infraestructura real requieren servicios activos y `DOCUMIND_TEST_INFRA=1`; los proveedores fake no acreditan calidad semántica ni integración con un proveedor real. Revisa `docs/progress.md` y las evidencias antes de interpretar resultados históricos.

### Estructura

| Ruta                           | Contenido                                                     |
| ------------------------------ | ------------------------------------------------------------- |
| [`apps/api/`](apps/api/)       | API y controles de acceso.                                    |
| [`apps/worker/`](apps/worker/) | Trabajos asíncronos.                                          |
| [`apps/web/`](apps/web/)       | Interfaz React y TypeScript.                                  |
| [`packages/`](packages/)       | Parsers, contratos de proveedores y componentes del pipeline. |
| [`migrations/`](migrations/)   | Migraciones Alembic.                                          |
| [`tests/`](tests/)             | Pruebas unitarias y de integración.                           |
| [`docs/`](docs/)               | Decisiones, avance y evidencia.                               |

### Alcance

El [seguimiento actual](docs/progress.md) sitúa el proyecto en la fase 3: el pipeline conecta extracción, fragmentación, embeddings y activación atómica. Recuperación, citas y chat RAG corresponden a fases posteriores. READY exige un índice completo; el modo local FAKE no acredita calidad semántica. El [adaptador real y su configuración](docs/adr/0011-embedding-pipeline.md) están separados de las evaluaciones reales pendientes en 4R. No incluye OCR ni conectores externos. Los nombres internos `DOCUMIND_*` se conservan por compatibilidad; el producto se llama Documint.

### Documentación

- [Estado y evidencia por sesión](docs/progress.md)
- [Arquitectura](docs/adr/0001-architecture.md)
- [Matriz de acceso](docs/access-matrix.md)
- [Modelo de amenazas](docs/threat-model.md)
- [Servicios locales y mantenimiento](infra/README.md)
- [Corpus y evaluación](evals/README.md)

---

<a id="english"></a>

## English

### Overview

A document knowledge platform under development, designed to manage permission-controlled sources and build evidence-backed answers. The current implementation covers identity, a versioned library, private storage and a complete extraction, chunking and vector-indexing pipeline.

### Features

- Authentication with access tokens, refresh rotation, and user and department administration.
- A permission-controlled library with immutable versions and originals in private S3 storage.
- Validated PDF, DOCX, TXT and Markdown uploads.
- Redis/Celery pipeline, provenance-aware parsers, chunking and versioned pgvector indexes.
- Synthetic corpus, deterministic fake providers and session-by-session progress evidence.

### Technology

Python 3.12 · FastAPI · PostgreSQL/pgvector · Redis · Celery · MinIO/S3 · React · TypeScript · Vite · Docker

### Run locally

**Requirements:** Python 3.12, uv, Node.js 22.12 or later, npm 11.6.2 and Docker with Compose v2 and Linux containers.

```bash
git clone https://github.com/Jp3528/Documint.git
cd Documint
```

```bash
uv sync --locked --dev
npx --yes npm@11.6.2 ci
uv run python -m scripts.init_env
```

**Configuration.** `scripts.init_env` creates `.env` with a random private key and preserves an existing one. See [`.env.example`](.env.example) to customize ports and services. The baseline environment needs no AI keys.

```bash
docker compose up -d --build --wait --wait-timeout 120
uv run alembic upgrade head
uv run python -m scripts.init_storage
```

Start the API and web app in separate terminals:

```bash
uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

```bash
npm run dev
```

Web: `http://localhost:5173`. OpenAPI contract: `http://127.0.0.1:8000/docs`. To create a local account, see `uv run python -m scripts.create_user --help`.

To dispatch processing jobs, run these in additional terminals:

```bash
uv run celery -A apps.worker.celery_app:celery_app worker --pool=solo --queues=celery,documind.processing --loglevel=INFO
```

```bash
uv run python -m scripts.dispatch_jobs --watch
```

### Checks

```bash
uv run python -m scripts.check
npm run format:check
```

The check combines lint, formatting, types, tests and build. Real infrastructure tests require running services and `DOCUMIND_TEST_INFRA=1`; fake providers do not establish semantic quality or real-provider integration. Consult `docs/progress.md` and session evidence before interpreting historical results.

### Structure

| Path                           | Contents                                             |
| ------------------------------ | ---------------------------------------------------- |
| [`apps/api/`](apps/api/)       | API and access controls.                             |
| [`apps/worker/`](apps/worker/) | Asynchronous jobs.                                   |
| [`apps/web/`](apps/web/)       | React and TypeScript interface.                      |
| [`packages/`](packages/)       | Parsers, provider contracts and pipeline components. |
| [`migrations/`](migrations/)   | Alembic migrations.                                  |
| [`tests/`](tests/)             | Unit and integration tests.                          |
| [`docs/`](docs/)               | Decisions, progress and evidence.                    |

### Scope

The [current progress log](docs/progress.md) places the project in phase 3: extraction, chunking, embeddings and atomic activation now form a complete pipeline. Retrieval, citations and RAG chat belong to later phases. READY requires a complete physical index; local FAKE mode does not establish semantic quality. The [real adapter and its configuration](docs/adr/0011-embedding-pipeline.md) are separate from the real evaluations pending in 4R. OCR and external connectors are outside scope. Internal `DOCUMIND_*` names are retained for compatibility; the product is named Documint.

### Documentation

- [Status and session evidence](docs/progress.md)
- [Architecture](docs/adr/0001-architecture.md)
- [Access matrix](docs/access-matrix.md)
- [Threat model](docs/threat-model.md)
- [Local services and maintenance](infra/README.md)
- [Corpus and evaluation](evals/README.md)
