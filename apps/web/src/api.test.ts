import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  ApiError,
  apiRequest,
  clearSession,
  login,
  logout,
  onSessionExpired,
  refreshAccess,
} from "./api";

const profile = {
  id: "12345678-1234-4234-8234-123456789012",
  email: "test@documind.example",
  display_name: "Test",
  status: "ACTIVE",
  roles: ["EMPLOYEE"],
  departments: [],
  capabilities: {
    manage_users: false,
    manage_departments: false,
    manage_knowledge: false,
    view_audit: false,
  },
};
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
const token = (value: string) =>
  json({ access_token: value, token_type: "bearer", expires_in: 300 });

beforeEach(() => clearSession());
afterEach(() => vi.unstubAllGlobals());

it("coordinates simultaneous 401s into one refresh and retries with the new token", async () => {
  let refreshes = 0;
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/auth/login") return token("original");
    if (path === "/api/me") return json(profile);
    if (path === "/api/auth/refresh") {
      refreshes++;
      await Promise.resolve();
      return token("replacement");
    }
    const bearer = new Headers(options?.headers).get("Authorization");
    return bearer === "Bearer replacement" ? json({ ok: true }) : json({ detail: "expired" }, 401);
  });
  vi.stubGlobal("fetch", fetcher);
  await login(profile.email, "test-only");
  const results = await Promise.all([apiRequest("/first"), apiRequest("/second")]);
  expect(results).toEqual([{ ok: true }, { ok: true }]);
  expect(refreshes).toBe(1);
  const refresh = fetcher.mock.calls.find(([path]) => path === "/api/auth/refresh");
  expect(refresh?.[1]?.credentials).toBe("same-origin");
  expect(new Headers(refresh?.[1]?.headers).get("X-DocuMind-CSRF")).toBe("1");
});

it("clears a revoked session and stops after one failed refresh", async () => {
  const expired = vi.fn();
  const unsubscribe = onSessionExpired(expired);
  const fetcher = vi.fn((path: string) =>
    Promise.resolve(
      path === "/api/auth/login"
        ? token("old")
        : path === "/api/me"
          ? json(profile)
          : json({ detail: "Sesión no válida" }, 401),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  try {
    await login(profile.email, "test-only");
    await expect(apiRequest("/private")).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledTimes(1);
    expect(fetcher.mock.calls.filter(([path]) => path === "/api/auth/refresh")).toHaveLength(1);
  } finally {
    unsubscribe();
  }
});

it("preserves local access when logout fails and rejects external request paths", async () => {
  const fetcher = vi.fn((path: string) =>
    Promise.resolve(
      path === "/api/auth/login"
        ? token("active")
        : path === "/api/auth/logout"
          ? json({}, 503)
          : json(profile),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  await login(profile.email, "test-only");
  await expect(logout()).rejects.toBeInstanceOf(ApiError);
  await expect(apiRequest("https://external.example")).rejects.toMatchObject({ status: 0 });
  expect(fetcher).not.toHaveBeenCalledWith("https://external.example", expect.anything());
});

it("rejects malformed profile payloads and does not persist tokens in browser storage", async () => {
  const local = vi.spyOn(Storage.prototype, "setItem");
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      Promise.resolve(path === "/api/auth/login" ? token("fake-access") : json({ status: "ok" })),
    ),
  );
  await expect(login(profile.email, "test-only")).rejects.toMatchObject({ status: 502 });
  expect(local).not.toHaveBeenCalled();
  local.mockRestore();
});

it("coordinates login, refresh and logout cookie changes across tabs when Web Locks is available", async () => {
  const request = vi.fn(async (_name: string, work: () => Promise<Response>) => work());
  vi.stubGlobal("navigator", { locks: { request } });
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      Promise.resolve(
        path === "/api/me"
          ? json(profile)
          : path === "/api/auth/logout"
            ? new Response(null, { status: 204 })
            : token("coordinated"),
      ),
    ),
  );
  await login(profile.email, "test-only");
  await refreshAccess();
  await logout();
  expect(request).toHaveBeenCalledTimes(3);
  expect(request.mock.calls.every(([name]) => name === "documint-auth-cookie")).toBe(true);
});
