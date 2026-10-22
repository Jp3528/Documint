# 0014. Servicio de respuestas, proveedores y trazabilidad

Fecha: 2026-10-22. Estado: aceptado.

`POST /chat/answers` coordina retrieval, contexto limitado, proveedor, validación de estructura
y citas actuales. No envía herramientas al modelo. El proveedor FAKE de la demo solo reconoce
preguntas del corpus sintético y extrae líneas presentes en la evidencia recibida; las demás
se abstienen. La UI lo identifica como respuesta programada. No es un modelo generativo ni
una evaluación de calidad. Producción rechaza proveedores FAKE.

El adaptador real usa [Responses con Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses),
mensajes system/user separados, `store=false`, esquema estricto y límite de salida explícito.
No se selecciona un modelo real por defecto: el operador configura un ID compatible y una
etiqueta de despliegue. Se comprueba el modelo recibido, estado completo, contenido esperado,
esquema y consumo; se rechazan herramientas, rechazos del modelo y JSON incompleto/inválido.
Esas comprobaciones no certifican respaldo semántico. Un alias que devuelva otro ID debe
configurarse con su ID/snapshot exacto para conservar la comprobación de modelo.

El transporte comparte origen HTTPS fijo, no sigue redirecciones, limita respuesta a 8 MiB,
usa timeout 30 s para embeddings y 45 s para LLM, y no hace retries automáticos. Una respuesta
perdida puede haber sido cobrada: consumo/costo no conocidos quedan null. El navegador permite
90 s para la consulta completa y deja el texto disponible para retry manual si falla.

Se reconstruyen citas desde chunks reales y se reautorizan todos los chunks enviados al modelo,
no solo los que este cita, antes de publicar una respuesta factual. La metadata persistida
incluye actor, hash de pregunta, modelo, versión de prompt, configuración de retrieval, consumo
y todas las fuentes de contexto mediante FK, marcando cuáles fueron citadas. Se conservan
fallos con códigos seguros; no se guardan prompts completos en estos recibos.

El soporte por afirmación y el historial persistente son el cierre de 5C. En 5B el campo de
soporte se identifica como NOT_EVALUATED, separado de integridad referencial. No se presenta
como una validación semántica ni como un despliegue de producción.
