# ADR 0004 Proveedores y evaluación separada

Estado: aceptado; contratos y fakes implementados en 0C.

`LLMProvider` y `EmbeddingProvider` intercambian estructuras tipadas e inmutables. Cada resultado
identifica nombre, revisión y modo FAKE/REAL; embeddings añaden dimensión. El consumo y costo
observado se conservan cuando están disponibles. Ausencia de información se registra como null,
nunca como cero. Los fakes sí cuestan cero porque no realizan llamadas; no inventan tokens.

FakeEmbeddingProvider produce vectores normalizados mediante SHA-256, estables entre procesos.
No representan similitud semántica. FakeLLMProvider usa respuestas programadas por pregunta,
exige los source IDs declarados y se abstiene en casos desconocidos. Puede configurarse con
afirmaciones falsas para probar controles. Ninguno certifica que las citas o afirmaciones sean
válidas: esa responsabilidad pertenece a los servicios de evidencia.

CI se ejecuta offline respecto a proveedores de IA. Las evaluaciones reales de 4R usan embeddings
reales y las de 5R añaden un LLM real mediante ejecución explícita. No se disparan en cada push.
Cada reporte incluirá run_id, commit, corpus/dataset, personas, modelos/revisiones, pipeline e
índice, configuración de retrieval, fallos por caso, latencia, consumo y costo observado.

Se separan Recall@k/MRR, integridad de citas, soporte por afirmación, abstención y fugas ACL.
El corpus de ocho documentos y 24 casos es una base de regresión pequeña, no una validación
representativa de conocimiento empresarial. 6B añade administración/versionado del dataset.
