# ADR 0002 Autorización centralizada antes de recuperar contenido

Estado: aceptado; implementación en fases 1, 2 y 4.

Un usuario inactivo se deniega siempre. ADMIN puede administrar y leer todos los documentos.
El owner y los grants READ/MANAGE conceden lectura explícita. COMPANY concede lectura a usuarios
activos con rol funcional; DEPARTMENT exige membership vigente; RESTRICTED exige owner,
ADMIN o grant explícito. MANAGE incluye READ. KNOWLEDGE_MANAGER no obtiene un bypass global.

AUDITOR por sí solo accede a metadata autorizada y eventos sanitizados; necesita permiso
explícito para contenido, incluso COMPANY. Esta regla conservadora resuelve la ambigüedad
entre “cualquier usuario activo” y la restricción específica del auditor en la matriz del plan.
Si una persona tiene además EMPLOYEE/KM, ese rol funcional aplica su alcance normal. Un grant
de rol no concede más que el permiso explícitamente indicado para ese documento.

Los IDs documentales inaccesibles responden 404 para no revelar existencia. Una operación
administrativa conocida para la que falta un rol responde 403. Las queries lexical y vectorial
incluyen ACL antes de ordenar o limitar candidatos; filtrar resultados después no es válido.

Cada consulta de binarios, citas e historial reautoriza con estado actual. Si una respuesta
histórica usa una fuente ya no autorizada, se oculta completa y se devuelve un marcador neutro
sin texto, títulos, snippets ni citas. Tampoco entra en prompts posteriores. La auditoría
conserva evidencia con permisos separados. Archivar excluye nuevas búsquedas pero no revoca
automáticamente lectura histórica.

`evals.schema.reference_can_read` solo valida el diseño de fixtures; no es el motor de
autorización de la API ni una prueba de que el producto ya impida fugas.
