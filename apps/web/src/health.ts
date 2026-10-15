export type ApiHealth = { status: "ok"; service: "documind-api"; version: string };

export async function getApiHealth(signal?: AbortSignal): Promise<ApiHealth> {
  const response = await fetch("/health", { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error("La API no está disponible.");
  const data: unknown = await response.json();
  if (
    typeof data !== "object" ||
    data === null ||
    !("status" in data) ||
    data.status !== "ok" ||
    !("service" in data) ||
    data.service !== "documind-api" ||
    !("version" in data) ||
    typeof data.version !== "string"
  ) {
    throw new Error("La API devolvió un estado no reconocido.");
  }
  return { status: "ok", service: "documind-api", version: data.version };
}
