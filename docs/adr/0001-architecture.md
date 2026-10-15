# ADR 0001 Arquitectura modular y persistencia

Estado: aceptado para v1.0. Referencia: plan 1.1, fase 0.

La aplicación usa FastAPI, SQLAlchemy 2 y Alembic, con React/TypeScript/Vite en el navegador.
Celery procesa documentos fuera del request HTTP. PostgreSQL es la fuente de verdad para
identidad, ACL, versiones, chunks, vectores, historial y auditoría; pgvector comparte la misma
transacción y filtros de autorización. Redis transporta tareas, no decide permisos. MinIO/S3
almacena binarios privados mediante `ObjectStorage`.

Se evita una base vectorial adicional para mantener consistencia entre permisos y retrieval.
Los routers coordinarán servicios; las policies serán funciones comprobables fuera de HTTP.
Los workers reciben IDs internos y vuelven a cargar estado persistido. Los cambios de esquema
se realizan con migraciones explícitas, nunca al iniciar una petición.

La infraestructura local se ejecuta ahora en Docker; las imágenes de aplicación y el despliegue
se preparan en fase 8. El archivado de MinIO exige revisar una alternativa S3 mantenida antes
de una exposición pública, conservando el contrato del dominio.

Consecuencia: PostgreSQL concentra carga operacional y de búsqueda. Se medirán índices y
latencia antes de añadir servicios. OCR, agentes, fine-tuning, conectores y multitenancy SaaS
quedan fuera de v1.0.
