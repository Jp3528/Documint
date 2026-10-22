# 0012. Recuperación autorizada sobre revisiones activas

Fecha: 2026-10-22. Estado: aceptado.

Los retrievers comparten `SearchRequest`, `Candidate` y `RetrievalResult`. `POST /search` exige
sesión activa, consulta no vacía de hasta 1000 caracteres y top-k de 1 a 50. Los filtros UUID
de documento/departamento y tipo de archivo se aplican con parámetros SQL; no aceptamos vectores
ni expresiones SQL del cliente. No se devuelve un conteo de documentos restringidos.

## FTS y vector

Cada chunk tiene un `tsvector` generado en PostgreSQL con configuración `spanish`, más GIN.
La estrategia `spanish-fts-v1` utiliza `websearch_to_tsquery` y `ts_rank_cd` normalizado.
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
