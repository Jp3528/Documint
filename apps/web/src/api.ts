import { z } from "zod";

export const roles = ["ADMIN", "KNOWLEDGE_MANAGER", "EMPLOYEE", "AUDITOR"] as const;
export type Role = (typeof roles)[number];
export const roleLabels: Record<Role, string> = {
  ADMIN: "Administración",
  KNOWLEDGE_MANAGER: "Gestión de conocimiento",
  EMPLOYEE: "Colaborador",
  AUDITOR: "Auditoría",
};
export const profileSchema = z.object({
  id: z.uuid(),
  email: z.email(),
  display_name: z.string(),
  status: z.enum(["ACTIVE", "INACTIVE"]),
  roles: z.array(z.enum(roles)),
  departments: z.array(
    z.object({ id: z.uuid(), code: z.string(), name: z.string(), membership_role: z.string() }),
  ),
  capabilities: z.object({
    manage_users: z.boolean(),
    manage_departments: z.boolean(),
    view_audit: z.boolean(),
    manage_knowledge: z.boolean(),
  }),
});
export type Profile = z.infer<typeof profileSchema>;
export const departmentSchema = z.object({
  id: z.uuid(),
  code: z.string(),
  name: z.string(),
  active: z.boolean(),
});
export type Department = z.infer<typeof departmentSchema>;
export function pageSchema<T extends z.ZodType>(item: T) {
  return z.object({
    items: z.array(item),
    total: z.number().int().nonnegative(),
    offset: z.number().int().nonnegative(),
    limit: z.number().int().positive(),
  });
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}
const tokenSchema = z.object({
  access_token: z.string().min(1),
  token_type: z.literal("bearer"),
  expires_in: z.number().positive(),
});
let accessToken: string | null = null;
let generation = 0;
let refreshFlight: Promise<void> | null = null;
const expiredListeners = new Set<() => void>();
const permissionListeners = new Set<() => void>();

export function clearSession() {
  generation++;
  accessToken = null;
}
export function onSessionExpired(listener: () => void) {
  expiredListeners.add(listener);
  return () => {
    expiredListeners.delete(listener);
  };
}
export function onPermissionsChanged(listener: () => void) {
  permissionListeners.add(listener);
  return () => {
    permissionListeners.delete(listener);
  };
}

async function transport(path: string, options: RequestInit = {}): Promise<Response> {
  if (!path.startsWith("/") || path.startsWith("//"))
    throw new ApiError(0, "Ruta de servicio inválida.");
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (typeof options.body === "string") headers.set("Content-Type", "application/json");
  try {
    return await fetch(`/api${path}`, {
      ...options,
      headers,
      credentials: "same-origin",
      signal: options.signal ?? AbortSignal.timeout(10000),
    });
  } catch {
    throw new ApiError(0, "No se pudo conectar con el servicio. Inténtalo de nuevo.");
  }
}

async function failure(response: Response): Promise<ApiError> {
  const messages: Record<number, string> = {
    401: "Tu sesión terminó. Inicia sesión de nuevo.",
    403: "No tienes permiso para esta operación.",
    404: "El recurso no está disponible.",
    409: "El cambio entra en conflicto con el estado actual.",
    422: "Revisa los datos del formulario.",
  };
  let message = messages[response.status] ?? "El servicio no pudo completar la solicitud.";
  if (response.status === 409 || response.status === 401) {
    const data: unknown = await response.json().catch(() => null);
    if (data && typeof data === "object" && "detail" in data && typeof data.detail === "string")
      message = data.detail.slice(0, 240);
  }
  return new ApiError(response.status, message);
}

async function parsed<T>(schema: z.ZodType<T>, response: Response): Promise<T> {
  if (!response.ok) throw await failure(response);
  const result = schema.safeParse(await response.json().catch(() => null));
  if (!result.success) throw new ApiError(502, "El servicio devolvió una respuesta inesperada.");
  return result.data;
}

async function authPost(path: string, body?: string): Promise<Response> {
  const operation = () =>
    transport(`/auth/${path}`, { method: "POST", headers: { "X-DocuMind-CSRF": "1" }, body });
  // Serialize cookie changes across tabs; the in-memory flight also deduplicates within a tab.
  return navigator.locks
    ? await navigator.locks.request("documint-auth-cookie", operation)
    : operation();
}

export async function refreshAccess(): Promise<void> {
  if (refreshFlight) return refreshFlight;
  const epoch = generation;
  refreshFlight = (async () => {
    try {
      const token = await parsed(tokenSchema, await authPost("refresh"));
      if (epoch !== generation) throw new ApiError(401, "La sesión cambió.");
      accessToken = token.access_token;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401 && epoch === generation) {
        clearSession();
        expiredListeners.forEach((listener) => listener());
      }
      throw error;
    } finally {
      refreshFlight = null;
    }
  })();
  return refreshFlight;
}

export async function apiRequest(path: string, options: RequestInit = {}): Promise<unknown> {
  const epoch = generation,
    attemptedToken = accessToken;
  const send = () => {
    const headers = new Headers(options.headers);
    if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
    return transport(path, { ...options, headers });
  };
  let response = await send();
  if (response.status === 401 && epoch === generation) {
    if (attemptedToken === accessToken) await refreshAccess();
    response = await send();
  }
  if (!response.ok) {
    if (response.status === 401 && epoch === generation) {
      clearSession();
      expiredListeners.forEach((listener) => listener());
    }
    if (response.status === 403) permissionListeners.forEach((listener) => listener());
    throw await failure(response);
  }
  if (response.status === 204) return null;
  return response.json();
}

export async function getProfile(): Promise<Profile> {
  const result = profileSchema.safeParse(await apiRequest("/me"));
  if (!result.success) throw new ApiError(502, "No se pudo validar el perfil recibido.");
  return result.data;
}
export async function login(email: string, password: string): Promise<Profile> {
  await refreshFlight?.catch(() => undefined);
  clearSession();
  const token = await parsed(
    tokenSchema,
    await authPost("login", JSON.stringify({ email, password })),
  );
  accessToken = token.access_token;
  return getProfile();
}
export async function logout(): Promise<void> {
  await refreshFlight?.catch(() => undefined);
  const response = await authPost("logout");
  if (!response.ok) throw await failure(response);
  clearSession();
}
export function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : "No se pudo completar la solicitud.";
}
