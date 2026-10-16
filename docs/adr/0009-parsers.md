# ADR 0009 Bloques normalizados y procedencia verificable

Estado: aceptado; implementado en 3A.

El registro acepta PDF/DOCX/TXT/MD y vuelve a validar los bytes originales y sus presupuestos.
Cada bloque conserva índice, texto, tipo y locator tipado. PDF usa páginas reales desde 1.
DOCX recorre párrafos/tablas en orden, conserva headings estándar y localiza párrafo, tabla,
fila y columna; las celdas combinadas se extraen una vez. No inventa páginas de Word. TXT y
Markdown conservan rangos de líneas; Markdown añade jerarquía de encabezados y bloques de código.

Se normalizan Unicode/saltos/espacios de prosa y se conserva indentación de código. HTML y
instrucciones dentro del contenido siguen siendo datos: no se renderizan ni ejecutan. El parser
no llama a proveedores, red externa o herramientas solicitadas por un documento.

La revisión identifica algoritmo y versión de biblioteca. La extracción guarda SHA-256 del
original y del JSON canónico normalizado, bloques y contadores. Unicidad `(version_id,
parser_revision)` y ON CONFLICT permiten reutilización sin duplicados. Una extracción cacheada
comprueba source hash, locators, índices, contadores y digest antes de reutilizarse.

El presupuesto predeterminado es 2 millones de caracteres, 10000 bloques y 1000 páginas PDF,
además de los límites de upload y ZIP. No se devuelve salida parcial al excederlo. Estos límites
de salida no sustituyen aislamiento y límites de memoria/tiempo del worker de producción.
No hay OCR, lectura de imágenes, encabezados/pies de Word, text boxes ni notas al pie en v1.

La etapa explícita `scripts.extract_job <uuid>` valida almacenamiento y persiste EXTRACTED,
dejando WAITING_PIPELINE/CHUNKING. Repetirla no consume otro intento. Fallos generan FAILED con
código sanitizado: sin texto extraíble, límite, documento inválido o integridad/lectura de S3.
La interfaz explica esos errores y respeta el máximo de intentos. El worker completo se conecta
en 3C; esta etapa no crea chunks, vectores ni READY y rechaza modificar una versión ya READY.

Referencias de implementación: [python-docx y orden del documento](https://python-docx.readthedocs.io/en/latest/api/document.html),
[tokens de markdown-it-py](https://markdown-it-py.readthedocs.io/en/latest/using.html),
[extracción y límites de PDF](https://pypdf.readthedocs.io/en/stable/user/extract-text.html).
