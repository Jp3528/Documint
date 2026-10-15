# Matriz de acceso de identidad

Implementación de fase 1B. La API consulta roles y memberships actuales en cada request.
Las capabilities de `/me` sirven para navegación; ocultar un botón no autoriza una operación.

| Acción                                   | ADMIN | KNOWLEDGE_MANAGER                 | EMPLOYEE                 | AUDITOR                  |
| ---------------------------------------- | ----- | --------------------------------- | ------------------------ | ------------------------ |
| Perfil propio                            | Sí    | Sí                                | Sí                       | Sí                       |
| Listar/crear/editar usuarios             | Sí    | 403                               | 403                      | 403                      |
| Leer/asignar roles                       | Sí    | 403                               | 403                      | 403                      |
| Crear/editar departamentos y memberships | Sí    | 403                               | 403                      | 403                      |
| Listar departamentos                     | Todos | Solo memberships activos          | Solo memberships activos | Solo memberships activos |
| Leer departamento ajeno por ID           | Sí    | 404                               | 404                      | 404                      |
| Capability de gestión de conocimiento    | Sí    | Sí, dentro del alcance documental | No                       | No                       |
| Capability de auditoría                  | Sí    | No                                | No                       | Sí, metadata sanitizada  |

Un usuario INACTIVE recibe 401, también con access emitido previamente. Se mantiene al menos
un ADMIN activo: quitar su rol o desactivarlo devuelve 409 si es el último. Los cambios de
estado/rol administrativo se serializan sobre la fila del rol ADMIN para evitar carreras.

404 usa el mismo mensaje para recurso inexistente y departamento fuera de alcance. 403 indica
que falta una capacidad administrativa conocida, sin revelar el objeto solicitado. Duplicados
de email, código o membership devuelven 409 sin errores SQL; paginación se limita a 100 filas.

La lectura documental tiene un contrato puro en `packages/identity/policies.py`, contrastado con
company/departamento/restringido, owner y grants. AUDITOR sin otro rol funcional requiere permiso
explícito. La persistencia de documentos/grants y el filtro SQL se incorporan en 2B/4A; esta fase
no afirma haber protegido un retrieval o historial que todavía no existe.

Cuando exista historial, ser propietario de la conversación no bastará: cada fuente se volverá
a autorizar. Perder READ sobre una de ellas ocultará toda la respuesta y sus citas y la excluirá
del contexto posterior. La evidencia se preservará para auditoría autorizada conforme a ADR 0002.
