# 0013. Contexto limitado y evidencia separada de instrucciones

Fecha: 2026-10-22. Estado: aceptado.

El contrato `evidence-claims-v1` separa instrucciones del sistema y datos de usuario/documentos.
La pregunta y la evidencia se serializan como valores JSON en el mensaje de usuario. Un texto
que parezca cerrar un delimitador o crear otro rol sigue siendo una cadena, no una instrucción
de sistema. El modelo no recibe herramientas, credenciales, rutas S3 ni documentos no autorizados.
La delimitación reduce ambigüedad; no demuestra inmunidad a prompt injection. El control de
citas y respaldo por afirmación de 5C sigue siendo necesario.

El builder vuelve a consultar chunks READY con READ actual, revisión activa y documento sin
archivar. Deduplica por UUID y hash de texto. Admite un máximo de chunks y por documento;
la vecindad está desactivada inicialmente y puede ampliarse a un chunk a cada lado, siempre
de la misma revisión activa autorizada. Se priorizan candidatos antes que vecinos. El orden
y los IDs son reproducibles. No se recorta el texto de un chunk ni se inventa una fuente.

El presupuesto de entrada configurable inicial es 6000. El contador
`utf8-byte-upper-bound-v1` cuenta bytes UTF-8 del sistema, JSON de usuario y esquema de salida,
más una reserva de 256 tokens para el envelope. Es un límite conservador para tokenizadores
byte-BPE, no un conteo real ni una garantía universal para cualquier proveedor futuro.
Se omiten chunks que no caben; si pregunta/contrato solos exceden el presupuesto se rechaza.
El límite de salida se configura por separado en el proveedor. Los tokens reales observados
se registrarán con la respuesta y no se confunden con esta cota de entrada.

El paquete identifica versión de prompt, contador, presupuesto, evidencia exacta y source IDs
canónicos UUID. El proveedor debe devolver texto y afirmaciones con source_ids; no basta con
que el JSON sea válido para demostrar que una afirmación tiene respaldo.
