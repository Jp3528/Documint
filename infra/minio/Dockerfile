# Community MinIO is source-only. Pin the final official source commit, not a stale binary.
FROM golang:1.26.9-bookworm AS build
ENV CGO_ENABLED=0 GOBIN=/out
RUN go install -trimpath github.com/minio/minio@7aac2a2c5b7c882e68c1ce017d8256be2feea27f

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir /data && chown 10001:10001 /data
COPY --from=build /out/minio /usr/local/bin/minio
USER 10001:10001
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
