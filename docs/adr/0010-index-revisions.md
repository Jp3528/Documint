# ADR 0010 Revisiones y evidencia inmutables

Estado: aceptado; implementado en 3B, conectado al worker completo en 3C.

El chunking agrupa bloques consecutivos de la misma página/heading y aplica ventanas de
caracteres con overlap explícito. No confunde caracteres con tokens de un proveedor. Cada
fragmento conserva spans hacia bloques normalizados, offsets y locators. El fingerprint incluye
hash del original, extracción/parser, estrategia y perfil de embeddings, con modo FAKE/REAL,
modelo, revisión y dimensión. Cambiar esos parámetros crea otra revisión e IDs de chunks.

La reserva bajo lock de versión asigna generación creciente. Retry del mismo fingerprint
reutiliza revisión y chunks. UUID deterministas y unicidad en PostgreSQL refuerzan idempotencia.
Los triggers impiden actualizar o borrar chunks/vectores y añadir filas a un índice publicado.
Los guards se instalan en el esquema correcto también en fixtures, sin tocar tablas públicas.

READY exige conteos físicos reconciliados de chunks y vectores, dimensiones correctas y vectores
no nulos. El guard PostgreSQL rechaza incluso modificar contadores para simular completitud.
La activación bloquea documento/revisión y cambia un único puntero a una revisión READY del
mismo documento: esa referencia determina versión y revisión juntas. Una generación o versión
antigua que termina tarde no reemplaza una más reciente. Las revisiones anteriores conservan
IDs, texto y locators para citas históricas; archivar sigue siendo lógico.

La tabla pgvector prepara el contrato del índice; generación por providers y runner se conectan
en 3C. `scripts.chunk_job <uuid>` solo prepara CHUNKED, reserva perfil FAKE y deja el job
pendiente/version EMBEDDING, sin generar vectores ni activar READY. Los vectores usados para
probar activación son fake explícitos en esquemas aislados y no evalúan calidad semántica.
