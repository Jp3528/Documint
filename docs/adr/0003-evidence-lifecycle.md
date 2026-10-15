# ADR 0003 Versiones y evidencia inmutables

Estado: aceptado; implementación en fases 2 a 5.

Cada upload crea una versión con SHA-256, tamaño, MIME detectado y una object key interna.
El filename no decide rutas. Reintentar una versión con el mismo pipeline reutiliza su revisión
de índice; cambiar chunking, parser o modelo crea una revisión nueva.

UPLOADED y QUEUED avanzan por extracción, chunking, embeddings e indexación. READY exige índice
completo y contadores reconciliados. En 2C solo fixtures aislados simulan READY; los jobs reales
quedan pendientes hasta conectar el pipeline, sin gastar reintentos en bucles artificiales.

La versión y revisión activa cambian juntas en una transacción después de completar el índice.
La revisión anterior sigue disponible durante el procesamiento. Los chunks publicados no se
sobrescriben ni se reasignan: las citas guardan su identidad, contenido y locator verificable.
Reindexar y archivar conservan esa evidencia para historial y auditoría autorizados.

Integridad referencial no equivale a respaldo semántico. En 5C se validará por separado que las
citas existen y que cada afirmación está sustentada. Una cita real acompañada de un dato falso
debe fallar el segundo control. Ante soporte insuficiente, contradictorio o incierto, se usa
el fallback sin respuesta factual. Ese control reduce riesgo y tiene limitaciones documentadas.
