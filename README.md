# Documint

Plataforma de conocimiento empresarial con ingestión documental, permisos y RAG con evidencia.
El nombre del producto y del repositorio es **Documint**.

El desarrollo sigue el plan 1.1 en nueve fases y 36 sesiones. La base incluye API,
worker, interfaz autenticada y administrativa, servicios locales, corpus y proveedores fake. El seguimiento está en
[docs/progress.md](docs/progress.md).

Las [decisiones de arquitectura](docs/adr/0001-architecture.md), el
[modelo de amenazas](docs/threat-model.md) y el [dataset sintético](evals/README.md) fijan los
contratos de permisos y evidencia antes de habilitar búsqueda o generación.

## Requisitos

- Python **3.12** y [uv](https://docs.astral.sh/uv/).
- Node.js **22.12 o superior**; CI utiliza Node 22.
- npm **11.6.2** para resolver las dependencias de workspaces de forma reproducible.
- Docker Engine con Compose v2 o posterior (Docker Desktop en Windows, contenedores Linux).

## Instalación

Desde la raíz del repositorio:

```sh
uv sync --locked --dev
npx --yes npm@11.6.2 ci
uv run python -m scripts.init_env
```

Las dependencias se fijan en `uv.lock` y `package-lock.json`. No se necesitan claves de IA.
El último comando crea `.env` con una clave de firma aleatoria y privada; una clave existente
se conserva. Nunca publiques ese archivo.

## Servicios locales

Copia `.env.example` a `.env` si necesitas personalizar la configuración. API, worker y Alembic
cargan ese archivo desde la raíz; las variables del proceso tienen prioridad. Los valores de
ejemplo solo sirven para desarrollo. Los puertos se publican exclusivamente en `127.0.0.1`.

```sh
docker compose up -d --build --wait --wait-timeout 120
uv run alembic upgrade head
uv run python -m scripts.init_storage
```

La primera compilación de MinIO puede tardar varios minutos y necesita Internet. Se compila
desde un commit oficial fijado porque la distribución comunitaria pasó a ser código fuente.
Ver [infra/README.md](infra/README.md) para versiones, mantenimiento y limitaciones.

| Servicio                 | Acceso desde el host     |
| ------------------------ | ------------------------ |
| PostgreSQL 17 / pgvector | `127.0.0.1:55432`        |
| Redis / Celery           | `127.0.0.1:56379`        |
| MinIO S3                 | `http://127.0.0.1:59000` |
| Consola MinIO            | `http://127.0.0.1:59001` |

`docker compose down` detiene los servicios conservando volúmenes. Evita `down -v` salvo que
quieras borrar todos los datos de este entorno. Otros proyectos usan redes y volúmenes separados.

## Desarrollo

En una terminal, inicia la API:

```sh
uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8000
```

En otra terminal, inicia la web:

```sh
npm run dev
```

Abre `http://localhost:5173` e inicia sesión con una cuenta local o demo. En **Inicio** puedes
comprobar la conexión con la API. Vite reenvía `/api/*` a la API quitando ese prefijo y reescribe
el path de la cookie a `/api/auth`; las rutas de React pueden recargarse directamente.
No requiere configurar CORS para este flujo local. El contrato HTTP está en
`http://127.0.0.1:8000/docs`.

`GET /health` comprueba que el proceso de la API responde. `GET /ready` comprueba base de datos
con migración y extensión vector, Redis y acceso al bucket privado. Devuelve 200 con todos
disponibles o 503 con el estado de cada dependencia, sin detalles de conexión ni credenciales.

## Identidad y sesiones

Después de migrar, crea las cuentas sintéticas solo si necesitas una demo local:

```sh
uv run python -m scripts.seed_demo --demo
```

Contraseña pública de todas las cuentas demo: **`DocumindDemo2026!`**. Los emails se encuentran
en `evals/personas.json`; por ejemplo `admin@documind.example` e `ingenieria@documind.example`.
El seed conserva contraseñas/estados existentes y sincroniza roles y memberships del manifiesto.
Rechaza `DOCUMIND_ENVIRONMENT=production`. `inactivo@documind.example` está desactivado.

Para una cuenta local propia, usa entrada oculta de contraseña:

```sh
uv run python -m scripts.create_user --email usuario@documind.example --name "Usuario local"
```

| Endpoint             | Uso                                                                      |
| -------------------- | ------------------------------------------------------------------------ |
| `POST /auth/login`   | JSON `email` y `password`; devuelve access JWT y cookie refresh HttpOnly |
| `POST /auth/refresh` | Rota el refresh de la cookie; un replay revoca su familia                |
| `POST /auth/logout`  | Revoca la familia y elimina la cookie                                    |
| `GET /me`            | Perfil con `Authorization: Bearer <access>`                              |

Los POST requieren `X-DocuMind-CSRF: 1`. Si se envía Origin debe estar entre `DOCUMIND_WEB_ORIGINS`
(lista JSON; por defecto ambos orígenes locales de Vite). El access dura cinco minutos; el
refresh expira a siete días desde el login. Logout y desactivación bloquean el access vigente.
Sin clave configurada, auth responde 503. Consulta [ADR 0006](docs/adr/0006-authentication.md).
La web recupera la sesión desde la cookie al recargar y conserva el access token solo en memoria.
Un único refresh atiende solicitudes concurrentes dentro de una pestaña. En navegadores con
Web Locks, las operaciones de cookie también se coordinan entre pestañas. Logout solo vuelve
al login cuando el servidor confirma la revocación; un fallo de conexión se muestra al usuario.

La navegación muestra administración según las capabilities vigentes. ADMIN puede listar y
crear usuarios, editar roles y estados, y listar/crear/activar departamentos. El servidor vuelve
a comprobar permisos en cada operación. Los formularios tienen etiquetas, estados de error y
foco visible; la interfaz se comprobó en escritorio y móvil. Evidencia en
[sesión 1C](docs/sessions/1C.md).

`/me` incluye roles, departamentos activos y capabilities. ADMIN gestiona usuarios y roles en
`/admin/users`, `/admin/roles` y `/admin/users/{id}/roles`; departamentos y memberships en
`/departments` y `/departments/{id}/memberships`. Listas aceptan `offset` y `limit` (máximo 100).
Consulta los contratos completos en `/docs` y la [matriz de acceso](docs/access-matrix.md).
Para provisionar un administrador propio desde la terminal de confianza, añade `--role ADMIN`
al comando `scripts.create_user`. Nunca se expone ese privilegio como registro público.

## Carga de documentos

`POST /documents` recibe multipart con un único campo archivo `file` y bearer ADMIN/KM.
Acepta PDF, DOCX, TXT y MD validados por contenido; el límite predeterminado es 20 MiB.
`DOCUMIND_UPLOAD_MAX_BYTES` y `DOCUMIND_DOCX_MAX_EXPANDED_BYTES` ajustan los presupuestos.
La respuesta incluye IDs, SHA-256, tamaño, MIME detectado y estado UPLOADED. El original queda
en el bucket privado, con una key generada por el servidor y visibilidad RESTRICTED.

`GET /documents` ofrece biblioteca paginada con ACL antes del conteo y de `offset`/`limit`.
`GET /documents/{document_id}` devuelve detalle; PATCH cambia metadata, visibilidad y archivo.
COMPANY requiere rol funcional, DEPARTMENT membership vigente y RESTRICTED permiso explícito,
owner o ADMIN. AUDITOR solo no obtiene acceso implícito al contenido.

`GET /documents/{document_id}/versions` lista versiones autorizadas; POST añade una nueva
recibiendo el mismo multipart. GET de `/{version_id}` devuelve metadata y de
`/{version_id}/original` descarga el original autorizado, sin sobrescribir versiones anteriores.
`/documents/{document_id}/grants` lista/crea permisos READ/MANAGE para un usuario o rol;
DELETE de `/{grant_id}` revoca. Las listas aceptan offset/limit con máximo 100.

La sección **Biblioteca** de la web permite cargar, gestionar visibilidad, archivar, consultar
versiones y descargar según los permisos actuales. El editor visual de grants se incorpora en
la fase de administración; por ahora están disponibles por API. Consultar [ADR 0002](docs/adr/0002-access.md).

UPLOADED aún no implica procesamiento ni búsqueda. Las reservas interrumpidas se recuperan con:

```sh
uv run python -m scripts.reconcile_uploads
```

El comando solo procesa reservas de al menos cinco minutos y conserva metadata ante fallos;
no elimina versiones publicadas. Ver [ADR 0007](docs/adr/0007-upload-originals.md) y
[evidencia 2A](docs/sessions/2A.md).

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
Las variables de broker están documentadas en `.env.example`; Celery utiliza la configuración
compartida y carga `.env` desde la raíz.

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

Con los servicios inicializados, ejecuta además la integración real:

```sh
# Bash
DOCUMIND_TEST_INFRA=1 uv run pytest -m infrastructure
# PowerShell (en dos comandos)
$env:DOCUMIND_TEST_INFRA='1'
uv run pytest -m infrastructure
```

Esta suite comprueba distancia pgvector, ida/vuelta binaria y borrado en MinIO, `/ready` y
una tarea ejecutada por un worker a través de Redis. Se omite de forma explícita sin la variable;
el job CI de infraestructura la ejecuta con los tres servicios reales desde una base vacía.

Con Docker disponible, revisa también el historial confirmado antes de publicar:

```sh
uv run python -m scripts.secret_scan
```

El escaneo usa Gitleaks fijado, montaje de solo lectura y salida redactada; también corre en CI.
Complementa la revisión humana de fixtures y documentación. Las estimaciones y condiciones de
avance se conservan en [docs/planning.md](docs/planning.md).

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
