# ADR 0005 Límites de confianza y entradas no confiables

Estado: aceptado; controles de upload en fase 2 y de contexto en fase 5.

El navegador no es una frontera de autorización. La API valida identidad, rol y alcance de
cada objeto. El worker no acepta rutas del usuario ni instrucciones ejecutables dentro del
archivo. PDF/DOCX/TXT/MD se procesan como datos, sin macros, OCR obligatorio o acceso de red
dictado por el contenido. Tamaño, formato detectado y límites del parser se validan en servidor.

El system prompt define reglas; los fragmentos se envían como evidencia delimitada con IDs.
Instrucciones dentro de fuentes o preguntas no cambian permisos ni pueden ordenar recuperar
contenido restringido. El LLM no recibe credenciales, herramientas para ejecutar acciones ni
chunks fuera del alcance. El corpus contiene una muestra adversarial expresamente etiquetada.

Las descargas y aperturas de fuentes pasan por autorización vigente. Las URLs públicas
permanentes o la confianza en IDs enviados por el frontend no son aceptables. Logs y eventos
excluyen contraseñas, tokens, binarios, prompts completos privados y errores externos crudos.
La auditoría registra actor, acción, entidad, resultado y correlación con datos mínimos.
