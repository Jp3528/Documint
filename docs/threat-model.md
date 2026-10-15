# Modelo de amenazas inicial

Estado de fase 0: servicios y contratos disponibles; los controles funcionales indicados abajo
se incorporan y prueban antes de habilitar cada feature. Esta tabla no declara seguridad ya
implementada en endpoints que todavía no existen.

Activos: binarios, permisos, chunks, respuestas/citas históricas, sesiones, claves del proveedor
y evidencia de auditoría. Actores: usuario autorizado, usuario de otro departamento, auditor,
usuario inactivo, atacante anónimo y autor de un documento malicioso.

Fronteras: navegador → API; API → DB/storage/Redis; worker → parser/provider; evidencia → LLM;
historial persistido → nueva respuesta. PostgreSQL es fuente de verdad de identidad y alcance.

| Riesgo                                                        | Control previsto o actual                                                    | Evidencia y sesión                                       |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------- | -------------------------------------------------------- |
| Servicio local expuesto o credenciales en readiness           | Loopback y estados sanitizados                                               | 0B: integración negativa por dependencia y contrato HTTP |
| Dependencias sin mantenimiento                                | Versiones fijadas, registrar archivado de MinIO y revisar antes de desplegar | 0B y gate 8B                                             |
| Robo/reutilización de refresh                                 | Hash, rotación, revocación por familia, expiración                           | 1A/1R: replay y usuario inactivo                         |
| IDOR o escalamiento de rol                                    | Policies centralizadas y denegación de IDs inaccesibles                      | 1B/1R y 2R: matriz rol × endpoint                        |
| Archivo con extensión falsa, tamaño excesivo o ruta maliciosa | Allowlist real, límites, hash y object key interna                           | 2A/2R: negativos de upload                               |
| Retry duplicado o activación incompleta                       | Idempotencia persistida, transición atómica, READY real                      | 2C/3R: retry y fallos por etapa                          |
| Fuga en retrieval/caché                                       | ACL antes de candidatos y caché ligada a permisos vigentes                   | 4R/7C: personas restringidas                             |
| Prompt injection en pregunta/documento                        | Separar evidencia, no herramientas autónomas, no instrucciones desde fuentes | 5A/5R: caso adversarial del corpus                       |
| Cita válida con respuesta inventada                           | Integridad y soporte por afirmación separados; fallback                      | 5C/5R: contradicción y cita existente                    |
| Historial tras revocar acceso                                 | Ocultar respuesta dependiente completa y excluirla del contexto              | 5C/5R: revocación y conversación posterior               |
| Pérdida de citas al reindexar                                 | Chunks publicados inmutables y revisión activa atómica                       | 3B/5C: historial después de reindexar                    |
| Logs con secretos, abuso o costos sin control                 | Sanitizar errores, límites, timeout/retry y métricas de consumo              | 1R/5B/7B/7C                                              |

Riesgos residuales: un control semántico puede fallar; el corpus pequeño no cubre todas las
formulaciones. Un administrador autorizado puede leer contenido global. La instalación local
usa HTTP y credenciales públicas de demo. MinIO comunitario está archivado. Estas condiciones
se revisan antes del gate de release; no se anuncian garantías absolutas de ausencia de alucinación.
