# ADR 0007 Originales privados y reservas recuperables

Estado: aceptado; implementado en 2A.

Solo ADMIN y KNOWLEDGE_MANAGER pueden cargar. `POST /documents` recibe un archivo multipart,
sin campos adicionales, después de autenticar y autorizar. Por defecto cada documento empieza
RESTRICTED y pertenece al actor. El nombre se normaliza para presentación; la object key solo
contiene UUID internos. La API devuelve metadata y SHA-256, nunca una URL pública o credenciales.

El tamaño de archivo se limita a 20 MiB por defecto (`DOCUMIND_UPLOAD_MAX_BYTES`). El middleware
también limita los bytes recibidos del multipart, aun sin Content-Length, con 64 KiB de margen
para el sobre. El parser acepta un archivo y ningún campo; sus temporales se cierran al terminar
o rechazar. La lectura del archivo se limita a máximo más un byte para detectar exceso.

PDF requiere firma y estructura de catálogo válidas y no admite cifrado. DOCX requiere un ZIP
Word ordinario, XML sin entidades, sin macros VBA, rutas relativas seguras, sin entradas
duplicadas y un máximo de 1000 entradas/50 MiB expandidos. TXT/MD requieren UTF-8 y excluyen
controles binarios. El Content-Type del cliente no decide aceptación. Estos controles no
equivalen a antivirus; los originales son datos no confiables y no se ejecutan ni sirven inline.

PostgreSQL y S3 no comparten transacción. Antes de PUT se confirma una reserva UPLOADING con
hash, tamaño y key; así un objeto escrito durante un corte conserva una referencia durable.
Después de PUT se confirma UPLOADED. Si falla S3, se intenta borrar la key y se registra
UPLOAD_FAILED/STORAGE_WRITE_FAILED. Un fallo de limpieza conserva esa referencia y un evento
sanitizado con version_id. Un fallo al confirmar tras PUT deja UPLOADING para reconciliación.

`scripts.reconcile_uploads` procesa hasta 100 reservas de al menos cinco minutos. Comprueba
tamaño/hash antes de restaurar UPLOADED, distingue ausencia de error transitorio y limpia las
escrituras fallidas pendientes. Nunca borra versiones publicadas ni modifica READY. Los cambios
se bloquean por fila; fallos transitorios se difieren. Se ejecuta explícitamente en operación.

UPLOADED significa original almacenado, sin extracción ni índice. La cola y el pipeline llegan
en 2C/3; READY sigue reservado al índice completo. La publicación de una revisión no sobrescribe
originales o citas anteriores.

Referencias: [archivos y UploadFile de FastAPI](https://fastapi.tiangolo.com/tutorial/request-files/),
[parser multipart de Starlette](https://github.com/Kludex/starlette/blob/main/starlette/formparsers.py).
El uso de temporales no reemplaza los límites explícitos de este producto.
