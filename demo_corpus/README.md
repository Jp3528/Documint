# Corpus de demostración

Ocho documentos ficticios de Lumen Demo: dos PDF, dos DOCX, dos TXT y dos Markdown. No contienen
información de empresas o personas reales. Los hechos y permisos se editan en `source.json`.
`manifest.json` conserva visibilidad, owner, grants, versión, tamaño y SHA-256 del archivo final.
Los binarios están en `files/`; no se deben reformatear después de generar el manifiesto.

Los documentos incluyen políticas COMPANY, procedimientos DEPARTMENT y dos fuentes RESTRICTED.
El informe Atlas contiene una instrucción adversarial explícitamente marcada como dato no confiable.
Las personas se definen en `evals/personas.json`; son escenarios de prueba, no usuarios desplegados.

Para regenerar los archivos tras editar los hechos:

```sh
uv sync --locked --dev --group corpus
uv run python -m scripts.build_demo_corpus
uv run pytest tests/eval
```

Revisar visualmente los PDF y DOCX antes de versionar sus hashes nuevos. La tipografía/renderizado
puede variar entre sistemas; el manifiesto identifica los bytes publicados. El generador no es
el pipeline productivo de ingestión, que se implementa en fase 3.
