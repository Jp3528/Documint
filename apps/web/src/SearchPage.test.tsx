import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { clearSession, type Profile } from "./api";
import { AuthContext } from "./auth-context";
import { SearchPage } from "./SearchPage";

const id = "12345678-1234-4234-8234-123456789010";
const hit = {
  chunk_id: id,
  document_id: id,
  version_id: id,
  index_revision_id: id,
  version_number: 2,
  title: "Política de viajes",
  filename: "viajes.pdf",
  sha256: "a".repeat(64),
  snippet: "El plazo es de siete días.",
  locators: [{ format: "pdf", page: 1, heading_path: [] }],
  source_url: `/sources/${id}`,
  original_url: `/documents/${id}/versions/${id}/original`,
  score: 0.1,
  rank: 1,
};
const result = {
  method: "hybrid",
  strategy_version: "weighted-rrf-v1",
  embedding_mode: "FAKE",
  candidates: [hit],
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
function mount() {
  const profile: Profile = {
    id,
    email: "equipo@synthetic.example",
    display_name: "Equipo",
    status: "ACTIVE",
    roles: ["EMPLOYEE"],
    departments: [{ id, name: "Ingeniería", code: "ENG", membership_role: "MEMBER" }],
    capabilities: {
      manage_users: false,
      manage_departments: false,
      view_audit: false,
      manage_knowledge: false,
    },
  };
  return render(
    <AuthContext
      value={{ user: profile, loading: false, restoreError: "", login: vi.fn(), logout: vi.fn() }}
    >
      <SearchPage />
    </AuthContext>,
  );
}
beforeEach(() => clearSession());
afterEach(() => vi.unstubAllGlobals());
async function search() {
  const user = userEvent.setup();
  await user.type(screen.getByRole("searchbox"), "viajes");
  await user.click(screen.getByRole("button", { name: "Buscar" }));
  return user;
}

it("submits labeled filters and clearly identifies fake semantic results", async () => {
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    expect(path).toBe("/api/search");
    expect(options?.method).toBe("POST");
    return json(result);
  });
  vi.stubGlobal("fetch", fetcher);
  mount();
  expect(screen.getByRole("button", { name: "Buscar" })).toBeDisabled();
  const user = userEvent.setup();
  await user.selectOptions(screen.getByLabelText("Tipo de archivo"), "pdf");
  await user.selectOptions(screen.getByLabelText("Departamento"), id);
  await search();
  expect(await screen.findByText(hit.snippet)).toBeInTheDocument();
  expect(screen.getByText(/Modo de demostración/)).toBeInTheDocument();
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toEqual({
    query: "viajes",
    method: "hybrid",
    limit: 10,
    file_type: "pdf",
    department_id: id,
  });
  expect(fetcher.mock.calls[0][0]).toBe("/api/search");
});

it("opens a fresh authorized historical source and returns keyboard focus on close", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) =>
      json(
        path.includes("/sources/") ? { ...hit, text: "<script>never execute</script>" } : result,
      ),
    ),
  );
  mount();
  const user = await search();
  const open = await screen.findByRole("button", { name: `Ver fuente de ${hit.title}` });
  await user.click(open);
  const heading = await screen.findByRole("heading", { name: hit.title, level: 2 });
  expect(heading).toHaveFocus();
  expect(screen.getByText("<script>never execute</script>")).toBeInTheDocument();
  expect(document.querySelector("blockquote script")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Cerrar fuente" }));
  expect(open).toHaveFocus();
});

it("clears old evidence if access to a source is no longer available", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) =>
      path.includes("/sources/") ? json({ detail: "Recurso no disponible" }, 404) : json(result),
    ),
  );
  mount();
  const user = await search();
  await user.click(await screen.findByRole("button", { name: `Ver fuente de ${hit.title}` }));
  expect(await screen.findByRole("alert")).toHaveTextContent("El recurso no está disponible.");
  expect(screen.queryByText(hit.snippet)).not.toBeInTheDocument();
});

it("displays a neutral empty state without revealing unavailable documents", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json({ ...result, candidates: [] })),
  );
  mount();
  await search();
  expect(await screen.findByText("No hay coincidencias disponibles")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /Ver fuente/ })).not.toBeInTheDocument();
});

it("removes earlier results when a later search fails", async () => {
  let calls = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      ++calls === 1 ? json(result) : json({ detail: "Búsqueda no disponible" }, 503),
    ),
  );
  mount();
  const user = await search();
  await screen.findByText(hit.snippet);
  await user.click(screen.getByRole("button", { name: "Buscar" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "El servicio no pudo completar la solicitud.",
  );
  expect(screen.queryByText(hit.snippet)).not.toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole("button", { name: "Buscar" })).toBeEnabled());
});
