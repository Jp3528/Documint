# ADR 0008 Jobs durables y entrega al menos una vez

Estado: aceptado; implementado en 2C.

El commit que confirma UPLOADED también crea el job PENDING. Su identidad lógica es
`(version_id, pipeline_key)` con unicidad PostgreSQL. La API no depende de que Redis esté
disponible al cargar. `scripts.dispatch_jobs` publica UUID, sin nombres, contenido ni secretos,
a la cola `documind.processing`. El dispatcher puede ejecutarse una vez o con `--watch`.

Las filas se bloquean con SKIP LOCKED. Una publicación perdida o duplicada no crea otro job.
QUEUED sin entrega confirmada se puede publicar otra vez después de cinco minutos. El worker
usa ack tardío; un duplicado observa el mismo estado. Intentos de publicación y de procesamiento
son contadores separados. Un fallo de broker aplica backoff y se detiene tras cinco intentos
de publicación; los códigos son sanitizados. Un gestor puede reintentar el mismo job lógico.

El máximo de procesamiento se persiste (tres, acotado entre uno y cinco). Retry no lo aumenta
ni reinicia sus intentos consumidos. Un job en ejecución no se vuelve a poner en cola mediante
retry. Al no existir todavía pipeline productivo, el worker pasa a WAITING_PIPELINE, mantiene
la versión QUEUED y conserva cero intentos de procesamiento. No hay bucles ni flag de simulación
en CLI, task o API. READY solo aparece como dato de fixtures en esquemas aislados de prueba.

GET de jobs exige READ; creación/retry exigen MANAGE sobre el documento y comprueban que versión
y job pertenecen a ese documento. Los tres endpoints devuelven metadata sanitizada y no-store.
La web muestra pendiente, cola, ejecución o fallo y ofrece retry solo al gestor. WAITING_PIPELINE
no se presenta como disponibilidad para búsqueda y deja de consultar periódicamente.

La fase 3 conectará extracción, chunks e índice y recuperará los trabajos pendientes. READY
requerirá el índice completo; una nueva configuración/revisión no sobrescribirá evidencia ya
publicada. La recuperación de ejecuciones largas se cerrará con el runner y sus leases.
