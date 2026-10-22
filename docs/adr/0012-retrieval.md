# 0012. Recuperación autorizada sobre revisiones activas

Fecha: 2026-10-22. Estado: aceptado.

Los retrievers comparten `SearchRequest`, `Candidate` y `RetrievalResult`. `POST /search` exige
sesión activa, consulta no vacía de hasta 1000 caracteres y top-k de 1 a 50. Los filtros UUID
de documento/departamento y tipo de archivo se aplican con parámetros SQL; no aceptamos vectores
ni expresiones SQL del cliente. No se devuelve un conteo de documentos restringidos.

## FTS y vector

Cada chunk tiene un `tsvector` generado en PostgreSQL con configuración `spanish`, más GIN.
La estrategia actual `spanish-fts-v2` usa términos normalizados por PostgreSQL con OR para
preguntas normales y conserva la sintaxis websearch cuando hay frases, OR o exclusiones
explícitas. El ranking usa `ts_rank_cd` normalizado. Sustituye la consulta AND de v1 tras
comparar el corpus completo en 4R; el baseline anterior se conserva en el reporte.
Se documenta esta configuración porque el stemming/stopwords influye en relevancia; no es
un detector multilingüe. Referencia: [PostgreSQL 17, búsqueda de texto](https://www.postgresql.org/docs/17/textsearch-controls.html).

La estrategia `cosine-exact-v1` usa distancia coseno de pgvector. Solo compara el mismo
modelo, etiqueta de revisión, modo y dimensiones del proveedor de la consulta. No mezcla
vectores incompatibles, incluso con igual dimensión. La similitud `1 - distancia` no es una
probabilidad. El modo FAKE no acredita recuperación semántica. Referencia del adaptador:
[pgvector-python SQLAlchemy](https://github.com/pgvector/pgvector-python#sqlalchemy).

El conjunto autorizado se materializa antes de calcular distancias y ordenar/limitar.
Así la planificación SQL no aplica funciones sensibles a dimensiones sobre vectores
incompatibles. Es una búsqueda exacta, apropiada para el corpus inicial. Una aproximación
HNSW exigiría índices por perfil/dimensión y comprobar de nuevo recall y ACL. El FTS GIN queda
disponible, aunque la barrera materializada puede limitar su aprovechamiento; se medirá en 7B.

## Permisos y ciclo de vida

Ambas consultas exigen READ mediante el predicado SQL de biblioteca, documento no archivado,
revisión activa READY y versión READY. Los filtros no amplían permisos. Cambiar visibilidad,
archivar o revocar grants afecta la siguiente consulta, sin reindexar ni borrar evidencia.
Antes de un embedding externo se comprueba que haya un perfil autorizado; solo se envía la
pregunta del usuario al proveedor. Tras la llamada se recargan usuario, roles y membresías y
se construye otra consulta ACL: una revocación durante la espera excluye esa evidencia.

Empates se resuelven por UUID de chunk para garantizar orden repetible. Se devuelven IDs,
texto, hash y spans de chunks físicos inmutables, nunca claves S3 ni vectores. La construcción
de citas navegables y snippets pertenece a 4C. Los resultados llevan `no-store` y los fallos
del proveedor se convierten en 503 genérico sin mensajes de red o credenciales.

## Fusión de rangos

`weighted-rrf-v1` suma `peso / (constante + rango)` por chunk único y por retriever. El valor
inicial es constante 60, pesos FTS/vector 1/1, pool 50 y un máximo de 3 chunks por documento.
Se publica la configuración completa porque cambiar pesos/diversidad cambia los resultados.
La diversidad se aplica después de ordenar; puede reducir el número final de resultados.
No hay combinación de escalas crudas, reranker externo ni llamadas LLM durante la búsqueda.
Un fallo del proveedor vectorial se devuelve explícitamente, sin esconderlo como éxito híbrido.
Antes de fusionar se comprueban nuevamente ACL y revisión activa sobre ambos conjuntos.

## Fuentes navegables

El límite de snippet es 500 caracteres. La API reconstruye la cita consultando el chunk
publicado, calcula su SHA-256 y usa los locators persistidos; descarta evidencia corrupta.
`GET /sources/{chunk_id}` reautoriza con roles/membresías actuales antes de devolver texto.
Un chunk histórico READY puede consultarse con READ aunque ya no esté activo o esté archivado.
Las revisiones históricas nunca se usan como candidatos nuevos. El original se descarga por
su endpoint privado, que vuelve a comprobar permisos y hash/tamaño de esa versión.
