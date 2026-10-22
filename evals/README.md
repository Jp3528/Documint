# Evaluaciones

`golden.json` versión 1.1 contiene 24 preguntas: 12 con respuesta (4 requieren dos fuentes),
6 sin evidencia en el corpus y 6 con evidencia que la persona no está autorizada a consultar.
Cada caso identifica persona, fuentes esperadas/prohibidas y fragmentos de referencia cuando
corresponde. Las respuestas restringidas deben abstenerse sin revelar existencia, títulos o datos.

`personas.json` cubre ADMIN, KNOWLEDGE_MANAGER, EMPLOYEE, AUDITOR, departamentos, usuario inactivo
y auditor con grant explícito. No incluye contraseñas. `schema.py` valida estructura y una matriz
de acceso de referencia exclusivamente para los fixtures; no autoriza requests de la aplicación.

`uv run pytest tests/eval` comprueba hashes, formatos, texto real, categorías, referencias y
permisos de los casos. Aprobar estos checks no significa haber medido retrieval o generación.
CI usa fakes sin llamadas de IA. Las evaluaciones reales se ejecutan explícitamente en 4R/5R
y sus resultados se separarán de las pruebas técnicas conforme a ADR 0004. La administración
del dataset se implementa en 6B.

Decisión del usuario del 22 de octubre de 2026: dejar pendientes las evaluaciones con
proveedores reales de 4R y 5R. Se implementan sus herramientas y las pruebas FAKE/ACL;
no se ejecutan llamadas pagadas ni se declara aprobado el componente REAL de esas sesiones.

Para importar los ocho originales con ACL y versiones verificadas:

```bash
uv run python -m scripts.seed_corpus --demo
```

El flag opcional `--process` completa el pipeline con el proveedor configurado. El valor local
`DOCUMIND_EMBEDDING_PROVIDER=fake` produce índices de demostración, sin calidad semántica.
El importador reutiliza sus IDs/versiones y detecta conflictos de metadata o grants; no corrige
ediciones del operador. Sincroniza roles/membresías de identidades demo y conserva contraseñas
y estados existentes. Nunca ejecutar estos seeds sobre datos de producción.

La comparación de retrieval se ejecuta por separado:

```bash
uv run python -m scripts.evaluate_retrieval --mode FAKE --top-k 5
```

El reporte en `evals/reports/retrieval_fake.json` identifica modo y alcance técnico. `--mode REAL`
rechaza el proveedor fake y exige las ocho revisiones activas con el perfil real configurado.
No prepara índices ni cambia de proveedor automáticamente. Los errores se conservan por caso;
el CLI devuelve fallo si hay errores de proveedor o evidencia no autorizada. Consulta
[4R](../docs/sessions/4R.md) para definiciones de métricas, configuración y límites de costos.
Los JSON generados pueden formatearse con `npm run format` antes de incluirlos en un commit.
