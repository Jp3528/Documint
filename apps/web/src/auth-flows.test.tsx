import { StrictMode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppRoutes } from "./App";
import { AuthProvider } from "./AuthProvider";
import { clearSession } from "./api";

const employee = {
  id: "12345678-1234-4234-8234-123456789012",
  email: "elena@documind.example",
  display_name: "Elena",
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
const admin = {
  ...employee,
  roles: ["ADMIN"],
  capabilities: {
    manage_users: true,
    manage_departments: true,
    manage_knowledge: true,
    view_audit: true,
  },
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
const token = () => json({ access_token: "fake-access", token_type: "bearer", expires_in: 300 });
function mount(path = "/") {
  return render(
    <StrictMode>
      <MemoryRouter initialEntries={[path]}>
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>
    </StrictMode>,
  );
}

beforeEach(() => clearSession());
afterEach(() => vi.unstubAllGlobals());

it("redirects a protected route to login, submits credentials and denies an employee's admin route", async () => {
  let authenticated = false;
  const fetcher = vi.fn((path: string) => {
    if (path === "/api/auth/refresh") return Promise.resolve(json({}, 401));
    if (path === "/api/auth/login") {
      authenticated = true;
      return Promise.resolve(token());
    }
    if (path === "/api/me" && authenticated) return Promise.resolve(json(employee));
    throw new Error(`Unexpected path ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  mount("/admin/users");
  await screen.findByRole("heading", { name: "Inicia sesión" });
  await userEvent.type(screen.getByLabelText("Correo electrónico"), employee.email);
  await userEvent.type(screen.getByLabelText("Contraseña"), "test-password");
  await userEvent.click(screen.getByRole("button", { name: /Entrar/ }));
  expect(await screen.findByRole("heading", { name: "Hola, Elena." })).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("No tienes acceso");
  expect(screen.queryByRole("link", { name: "Usuarios" })).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([path]) => path === "/api/auth/refresh")).toHaveLength(1);
});

it("shows invalid credentials without losing the email or leaving submit disabled", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      Promise.resolve(
        json(
          { detail: path.endsWith("login") ? "Credenciales inválidas" : "Sesión no válida" },
          401,
        ),
      ),
    ),
  );
  mount("/login");
  await screen.findByRole("heading", { name: "Inicia sesión" });
  await userEvent.type(screen.getByLabelText("Correo electrónico"), employee.email);
  await userEvent.type(screen.getByLabelText("Contraseña"), "wrong-password");
  await userEvent.click(screen.getByRole("button", { name: /Entrar/ }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Credenciales inválidas");
  expect(screen.getByLabelText("Correo electrónico")).toHaveValue(employee.email);
  expect(screen.getByRole("button", { name: /Entrar/ })).toBeEnabled();
});

it("restores an admin session once in StrictMode and lists actual API results", async () => {
  const fetcher = vi.fn((path: string) =>
    Promise.resolve(
      path === "/api/auth/refresh"
        ? token()
        : path === "/api/me"
          ? json(admin)
          : path.startsWith("/api/admin/users?")
            ? json({ items: [admin], total: 1, offset: 0, limit: 10 })
            : json({}, 404),
    ),
  );
  vi.stubGlobal("fetch", fetcher);
  mount("/admin/users");
  expect(await screen.findByRole("heading", { name: "Usuarios" })).toBeVisible();
  expect(await screen.findByRole("cell", { name: /Elena/ })).toBeVisible();
  expect(fetcher.mock.calls.filter(([path]) => path === "/api/auth/refresh")).toHaveLength(1);
});

it("handles a failed logout honestly and returns to login after the server confirms it", async () => {
  let fail = true;
  vi.stubGlobal(
    "fetch",
    vi.fn((path: string) =>
      Promise.resolve(
        path === "/api/auth/refresh"
          ? token()
          : path === "/api/me"
            ? json(employee)
            : path === "/api/auth/logout"
              ? fail
                ? json({}, 503)
                : new Response(null, { status: 204 })
              : json({}, 404),
      ),
    ),
  );
  mount();
  await screen.findByRole("heading", { name: "Hola, Elena." });
  await userEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("no pudo completar");
  expect(screen.getByRole("heading", { name: "Hola, Elena." })).toBeVisible();
  fail = false;
  await userEvent.click(screen.getByRole("button", { name: "Cerrar sesión" }));
  await waitFor(() => expect(screen.getByRole("heading", { name: "Inicia sesión" })).toBeVisible());
  expect(screen.queryByText(employee.email)).not.toBeInTheDocument();
});
