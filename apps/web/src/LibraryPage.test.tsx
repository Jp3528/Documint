import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AuthContext } from "./auth-context";
import { clearSession, type Profile } from "./api";
import { LibraryPage } from "./LibraryPage";

const documentId = "12345678-1234-4234-8234-123456789010";
const version = {
  document_id: documentId,
  version_id: "12345678-1234-4234-8234-123456789011",
  version_number: 1,
  owner_id: "12345678-1234-4234-8234-123456789012",
  title: "Guía del equipo",
  visibility: "RESTRICTED",
  filename: "guia.txt",
  media_type: "text/plain",
  size_bytes: 42,
  sha256: "a".repeat(64),
  status: "UPLOADED",
  error_code: null,
  created_at: "2026-10-16T09:00:00Z",
};
const item = {
  id: documentId,
  title: version.title,
  owner_id: version.owner_id,
  department_id: null,
  department_name: null,
  visibility: "RESTRICTED",
  archived: false,
  can_manage: false,
  created_at: version.created_at,
  latest_version: version,
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const page = (items: unknown[]) => ({ items, total: items.length, offset: 0, limit: 10 });
function mount(manager = false) {
  const profile: Profile = {
    id: version.owner_id,
    email: "equipo@documind.example",
    display_name: "Equipo",
    status: "ACTIVE",
    roles: [manager ? "KNOWLEDGE_MANAGER" : "EMPLOYEE"],
    departments: [],
    capabilities: {
      manage_users: false,
      manage_departments: false,
      view_audit: false,
      manage_knowledge: manager,
    },
  };
  return render(
    <AuthContext
      value={{ user: profile, loading: false, restoreError: "", login: vi.fn(), logout: vi.fn() }}
    >
      <LibraryPage />
    </AuthContext>,
  );
}
beforeEach(() => clearSession());
afterEach(() => vi.unstubAllGlobals());

it("shows an authorized empty library without upload controls for a collaborator", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json(page([]))),
  );
  mount();
  expect(await screen.findByText("Tu biblioteca está vacía")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Subir documento" })).not.toBeInTheDocument();
});

it("uploads multipart through the authenticated client and reloads the library", async () => {
  let uploaded = false;
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    if (path === "/api/documents" && options?.method === "POST") {
      expect(options.body).toBeInstanceOf(FormData);
      expect(new Headers(options.headers).has("Content-Type")).toBe(false);
      uploaded = true;
      return json(version, 201);
    }
    return json(page(uploaded ? [item] : []));
  });
  vi.stubGlobal("fetch", fetcher);
  mount(true);
  const user = userEvent.setup();
  await user.upload(
    screen.getByLabelText("Archivo"),
    new File(["guía"], "guia.txt", { type: "text/plain" }),
  );
  expect(screen.getByLabelText<HTMLInputElement>("Archivo").files).toHaveLength(1);
  // userEvent patches FileList, while jsdom's native required check uses its empty internal list.
  // Submit the React form here; native file selection/submission is verified in the real browser.
  fireEvent.submit(screen.getByLabelText("Archivo").closest("form")!);
  expect(await screen.findByText("Biblioteca actualizada.")).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: "Ver Guía del equipo" })).toBeInTheDocument();
});

it("shows read-only version history and reports revoked original access", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      if (path.endsWith("/original")) return json({ detail: "unavailable" }, 404);
      if (path.includes("/versions?")) return json(page([version]));
      if (path === `/api/documents/${documentId}`) return json(item);
      return json(page([item]));
    }),
  );
  mount();
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Ver Guía del equipo" }));
  expect(await screen.findByRole("heading", { name: "Versiones originales" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Guardar cambios" })).not.toBeInTheDocument();
  await user.click(await screen.findByRole("button", { name: "Descargar versión 1" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("El recurso no está disponible.");
});

it("keeps the selected file and displays an upload size rejection", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options?: RequestInit) =>
      path === "/api/documents" && options?.method === "POST" ? json({}, 413) : json(page([])),
    ),
  );
  mount(true);
  const user = userEvent.setup();
  const input = screen.getByLabelText<HTMLInputElement>("Archivo");
  await user.upload(input, new File(["oversize fixture"], "grande.txt", { type: "text/plain" }));
  fireEvent.submit(input.closest("form")!);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "El archivo supera el tamaño permitido.",
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Subir documento" })).toBeEnabled(),
  );
  expect(input.files?.[0]?.name).toBe("grande.txt");
});
