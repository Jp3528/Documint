import { useEffect, useState } from "react";
import { z } from "zod";
import { apiRequest, errorMessage, pageSchema } from "./api";
import { useResource } from "./useResource";

const jobsPage = pageSchema(
  z.object({
    id: z.uuid(),
    status: z.string(),
    stage: z.string(),
    attempts: z.number().int().nonnegative(),
    max_attempts: z.number().int().positive(),
    error_code: z.string().nullable(),
  }),
);
const labels: Record<string, string> = {
  PENDING: "Pendiente de iniciar",
  QUEUED: "En cola",
  RUNNING: "Procesando",
  WAITING_PIPELINE: "Procesamiento pendiente",
  SUCCEEDED: "Procesamiento completado",
  FAILED: "Procesamiento fallido",
  DISPATCH_FAILED: "No se pudo iniciar",
};

export function ProcessingPanel({
  documentId,
  versionId,
  canManage,
}: {
  documentId: string;
  versionId: string;
  canManage: boolean;
}) {
  const [revision, setRevision] = useState(0),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const base = `/documents/${documentId}`;
  const resource = useResource(`${base}/versions/${versionId}/jobs?limit=1`, jobsPage, revision);
  const job = resource.data?.items[0];
  useEffect(() => {
    if (!job || !["PENDING", "QUEUED", "RUNNING"].includes(job.status)) return;
    const timer = window.setTimeout(() => setRevision((value) => value + 1), 5000);
    return () => window.clearTimeout(timer);
  }, [job, revision]);
  async function request() {
    setBusy(true);
    setError("");
    try {
      await apiRequest(
        job ? `${base}/jobs/${job.id}/retry` : `${base}/versions/${versionId}/jobs`,
        { method: "POST" },
      );
      setRevision((value) => value + 1);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="processing-panel" aria-labelledby="processing-title">
      <h3 id="processing-title">Estado de la última carga</h3>
      {resource.loading && <p role="status">Consultando procesamiento…</p>}
      {resource.error && <p role="alert">{resource.error}</p>}
      {error && (
        <p role="alert" className="error-box">
          {error}
        </p>
      )}
      {resource.data && (
        <>
          <p role="status">
            <strong>
              {job ? (labels[job.status] ?? "Pendiente") : "Sin solicitud de procesamiento"}
            </strong>
          </p>
          {job?.status !== "SUCCEEDED" && (
            <p className="muted">
              Tu original está guardado. Todavía no está disponible para búsqueda.
            </p>
          )}
          {!!job?.attempts && (
            <p className="muted">
              Intentos de procesamiento: {job.attempts} de {job.max_attempts}.
            </p>
          )}
          {job?.error_code && (
            <p role="alert" className="error-box">
              {job.error_code === "NO_EXTRACTABLE_TEXT"
                ? "Este archivo no contiene texto extraíble. Sube una versión con texto."
                : job.error_code === "EXTRACTION_LIMIT"
                  ? "El contenido supera los límites de procesamiento. Prueba un archivo más pequeño."
                  : job.error_code.includes("INTEGRITY")
                    ? "No se pudo verificar el contenido guardado. Contacta al administrador."
                    : "No se pudo completar el procesamiento. Tu original permanece guardado."}
            </p>
          )}
          {canManage &&
            (!job ||
              (["FAILED", "DISPATCH_FAILED"].includes(job.status) &&
                job.attempts < job.max_attempts)) && (
              <button className="button secondary" disabled={busy} onClick={() => void request()}>
                {busy
                  ? "Solicitando…"
                  : job
                    ? "Reintentar procesamiento"
                    : "Solicitar procesamiento"}
              </button>
            )}
        </>
      )}
    </section>
  );
}
