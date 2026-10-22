# 0011. Pipeline completo y embeddings explícitos

Fecha: 2026-10-22. Estado: aceptado.

El worker ejecuta extracción, chunking determinista, embeddings por lotes y activación.
La configuración forma parte de la huella inmutable de cada revisión: parser, chunking,
proveedor/modelo, etiqueta de revisión, modo y dimensiones. Repetir la misma entrada reutiliza
chunks y vectores. Cambiar configuración produce otra revisión y conserva las anteriores.

## Proveedores y consumo

`fake` es el valor local de demostración/CI; genera vectores físicos SHA-256 sin significado
semántico. La UI muestra ese modo y producción lo rechaza. `openai` requiere una clave privada
explícita y nunca recurre silenciosamente al fake. `DOCUMIND_EMBEDDING_REVISION` identifica
el despliegue del operador; no demuestra que el proveedor haya fijado una versión interna de
un alias. Cambiar de despliegue exige cambiar esta etiqueta y usar otra clave de pipeline
para reindexar un trabajo ya completado.

El adaptador llama a [Create embeddings de OpenAI](https://developers.openai.com/api/reference/python/resources/embeddings/methods/create)
con `encoding_format=float` y dimensiones explícitas. Reordena por `index` y rechaza índices
repetidos/ausentes, modelo o dimensión diferentes, NaN/infinito, vectores nulos y consumo
inválido. Un límite conservador de 8192 bytes UTF-8 por texto y 32 textos por lote acota tokens
por entrada y por petición. No equivale a un tokenizer; algunos textos válidos se rechazan.
Un chunk demasiado grande requiere reducir el presupuesto de caracteres y reindexar.

Cada lote aceptado registra tokens informados y costo observado, cuando existe. OpenAI no
devuelve precio en esta respuesta: el costo queda NULL, no cero. Estos recibos no reconstruyen
peticiones cobradas cuya respuesta se perdió ni un crash anterior al commit; no son facturación.
Las evaluaciones reales de recuperación se realizarán en 4R con configuración y costo separado.
Las pruebas HTTP de este adaptador son stubs y no se presentan como llamadas reales.

## Consistencia y recuperación

Cada ejecución adquiere un token y un lease de cinco minutos; renueva el lease entre etapas y
lotes. Las operaciones de red no conservan locks SQL. Una entrega duplicada durante un lease
vigente retorna RUNNING. Antes de persistir vectores o publicar se comprueba bajo lock que el
token sigue vigente. Un worker sustituido no puede guardar ese resultado ni cambiar el estado.
El dispatcher vuelve a publicar trabajos con lease vencido y los WAITING_PIPELINE heredados.
Los intentos de ejecución y de publicación mantienen sus límites independientes.

Los lotes ya confirmados son inmutables y un reintento pide solo los vectores ausentes.
La base valida también que las dimensiones correspondan al perfil padre. La activación vuelve
a contar chunks y vectores y verifica el perfil; READY, el puntero activo y SUCCEEDED se
confirman en una transacción. Una revisión anterior no reemplaza otra versión/generación más
nueva. Una reindexación fallida conserva el índice activo y las evidencias previas.

Las extracciones y chunks reproducibles pueden quedar preparados por una ejecución sustituida;
son caches verificadas y no hacen que el documento sea READY. El fencing protege los resultados
vectoriales y la publicación. Un lease vencido puede repetir una llamada externa ya cobrada.
El parsing pesado aún requiere aislamiento y límites de proceso en las fases 7/8.
