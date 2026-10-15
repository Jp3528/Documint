# Infraestructura local

`compose.yaml` de la raíz crea tres servicios con red y volúmenes propios del proyecto
`documind`. No utiliza el PostgreSQL del host ni los contenedores de otros proyectos.

| Servicio              | Versión fijada                                    | Puerto host   | Datos             |
| --------------------- | ------------------------------------------------- | ------------- | ----------------- |
| PostgreSQL + pgvector | `0.8.7-pg17-bookworm`                             | 55432         | `postgres_data`   |
| Redis                 | `7.4.7-alpine`                                    | 56379         | `redis_data`, AOF |
| MinIO                 | commit `7aac2a2c5b7c882e68c1ce017d8256be2feea27f` | 59000 / 59001 | `minio_data`      |

Los healthchecks de Compose comprueban los procesos. `/ready` comprueba además la migración
vigente, pgvector y acceso autenticado al bucket configurado. Un bucket ausente no se crea
como efecto de consultar readiness: `python -m scripts.init_storage` lo inicializa explícitamente.
No se aplica ninguna política pública al bucket. La aplicación futura autorizará cada lectura.

## MinIO comunitario

El [repositorio oficial](https://github.com/minio/minio) está archivado y su distribución
comunitaria es solo código fuente. La imagen local compila el commit final oficial con Go
1.26.9 y conserva sus dependencias Go fijadas por upstream. No depende de una imagen antigua
de Docker Hub. El servicio ejecuta como UID 10001 y publica sus puertos solo en loopback.

Esta decisión conserva el stack del plan para desarrollo. El archivado limita la disponibilidad
de futuras correcciones; antes de publicar una demo en la fase 8 debe revisarse mantenimiento
y vulnerabilidades, y elegir una implementación S3 mantenida si es necesario. La interfaz
`ObjectStorage` permite hacerlo sin acoplar el dominio a MinIO. Este entorno no es un despliegue
de producción: usa credenciales de ejemplo, HTTP local y un único usuario administrativo S3.

## Operación

Consulta los comandos de arranque, migración y pruebas en el README de la raíz. Ejecutarlos
desde esa raíz permite compartir `.env` entre Compose y Python. Si cambias un puerto o contraseña,
ajusta también la URL del cliente correspondiente. Cambiar `POSTGRES_PASSWORD` no cambia una
contraseña ya almacenada en un volumen existente.

`docker compose down` conserva los datos; `docker compose up -d --wait` los recupera.
No borres volúmenes si contienen evidencia que debas conservar. Una actualización de versión
mayor de PostgreSQL requiere migración de datos, no reemplazar solamente la etiqueta.
