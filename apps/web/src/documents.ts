import { z } from "zod";

export const versionSchema = z.object({
  document_id: z.uuid(),
  version_id: z.uuid(),
  version_number: z.number().int().positive(),
  owner_id: z.uuid(),
  title: z.string(),
  visibility: z.string(),
  filename: z.string(),
  media_type: z.string(),
  size_bytes: z.number().int().positive(),
  sha256: z.string().regex(/^[a-f0-9]{64}$/),
  status: z.string(),
  error_code: z.string().nullable(),
  created_at: z.string(),
});
export const documentSchema = z.object({
  id: z.uuid(),
  title: z.string(),
  owner_id: z.uuid(),
  department_id: z.uuid().nullable(),
  department_name: z.string().nullable(),
  visibility: z.enum(["COMPANY", "DEPARTMENT", "RESTRICTED"]),
  archived: z.boolean(),
  can_manage: z.boolean(),
  created_at: z.string(),
  latest_version: versionSchema.nullable(),
});
export type LibraryDocument = z.infer<typeof documentSchema>;
export const visibilityLabels = {
  COMPANY: "Organización",
  DEPARTMENT: "Departamento",
  RESTRICTED: "Restringido",
};
export function statusLabel(status: string) {
  const labels: Record<string, string> = {
    UPLOADING: "Guardando",
    UPLOAD_FAILED: "Carga fallida",
    UPLOADED: "Original almacenado",
    QUEUED: "En cola",
    EXTRACTING: "Extrayendo",
    CHUNKING: "Preparando fragmentos",
    EMBEDDING: "Preparando búsqueda",
    INDEXING: "Indexando",
    READY: "Disponible para búsqueda",
    FAILED: "Procesamiento fallido",
  };
  return labels[status] ?? "Pendiente";
}
export function fileSize(bytes: number) {
  return bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    : `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
}
