import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "./App";

afterEach(() => vi.unstubAllGlobals());

it("does not report a successful connection before checking the API", () => {
  render(<App />);
  expect(screen.getByRole("status")).toHaveTextContent("Pendiente de comprobar");
  expect(screen.queryByText(/API conectada/)).not.toBeInTheDocument();
});

it("shows a validated API response after the user requests a check", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "ok",
          service: "documind-api",
          version: "0.1.0",
        }),
        { status: 200 },
      ),
    ),
  );
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: /Comprobar conexión/ }));
  expect(await screen.findByText("API conectada · versión 0.1.0")).toBeVisible();
});

it("shows a recoverable error when the API is unreachable", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network unavailable")));
  render(<App />);
  const button = screen.getByRole("button", { name: /Comprobar conexión/ });
  await userEvent.click(button);
  expect(await screen.findByText(/No se pudo conectar con la API/)).toBeVisible();
  expect(button).toBeEnabled();
});

it("rejects an unexpected successful HTTP payload", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: "ok" }))));
  render(<App />);
  await userEvent.click(screen.getByRole("button", { name: /Comprobar conexión/ }));
  expect(await screen.findByText(/No se pudo conectar con la API/)).toBeVisible();
  expect(screen.queryByText(/API conectada/)).not.toBeInTheDocument();
});
