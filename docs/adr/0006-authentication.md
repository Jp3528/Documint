# ADR 0006 Sesiones cortas y refresh de un solo uso

Estado: implementado en 1A.

Las contraseñas usan Argon2id mediante pwdlib. El email se normaliza y valida, con unicidad y
constraint de normalización en PostgreSQL. Un login incorrecto, inexistente o inactivo devuelve
la misma respuesta; también se realiza verificación de hash para usuarios desconocidos.

El access JWT dura cinco minutos por defecto y exige firma HS256, issuer, audience, subject,
session ID, jti, tipo access y tiempos válidos. Roles y departamentos se consultarán en DB,
no se confiará en copias antiguas dentro del JWT. Cada request comprueba además que el usuario
y su familia de sesión sigan activos; logout tiene efecto inmediato sobre access ya emitidos.

Refresh es un valor aleatorio de 256 bits. Solo su SHA-256 se almacena en DB. Viaja en cookie
HttpOnly, SameSite Strict y path `/auth`, con Secure configurable para HTTPS. No se devuelve
en JSON. La familia expira de forma absoluta a siete días, sin prolongarse al rotar.

La rotación bloquea la fila del refresh y la familia con `FOR UPDATE`, consume el token y crea
otro en la misma transacción. Un refresh ya consumido revoca toda su familia, incluso la nueva
credencial emitida. La revocación se confirma antes del 401. Dos refresh simultáneos tienen un
solo ganador y el replay revoca esa familia; el frontend debe coordinar un único refresh en vuelo.

Los POST de `/auth` requieren `X-DocuMind-CSRF: 1`; si hay Origin debe coincidir exactamente con
los orígenes configurados. Esto impide envíos por formularios y peticiones de otros orígenes
sin preflight autorizado. La cookie Strict añade protección. Los errores de validación no
repiten entradas privadas y las respuestas de auth/perfil usan `Cache-Control: no-store`.

No existe una clave de firma pública por defecto. El comando `scripts.init_env` genera una
clave local privada y preserva una ya configurada. Auth responde 503 sin una clave válida.
La producción usará secretos de plataforma y cookies Secure conforme al gate de fase 8.

Seeds requieren un comando explícito `--demo`, se rechazan en production y preservan cuentas
existentes. La contraseña publicada solo pertenece a identidades sintéticas de demo; no es una
credencial de producción. Rate limiting y otros controles contra abuso se añaden en 7B antes
de habilitar exposición pública.
