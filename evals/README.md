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

Para importar los ocho originales con ACL y versiones verificadas:

```bash
uv run python -m scripts.seed_corpus --demo
```

El flag opcional `--process` completa el pipeline con el proveedor configurado. El valor local
`DOCUMIND_EMBEDDING_PROVIDER=fake` produce índices de demostración, sin calidad semántica.
El importador reutiliza sus IDs/versiones y detecta conflictos de metadata o grants; no corrige
ediciones del operador. Sincroniza roles/membresías de identidades demo y conserva contraseñas
y estados existentes. Nunca ejecutar estos seeds sobre datos de producción.
