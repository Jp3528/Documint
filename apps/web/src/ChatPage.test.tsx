import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { clearSession } from "./api";
import { ChatPage } from "./ChatPage";

const id = "12345678-1234-4234-8234-123456789010";
const answer = {
  id,
  text: "Los gastos se presentan en 7 días.",
  abstained: false,
  model: { name: "fake-corpus-scripted", revision: "1", mode: "FAKE" },
  citations: [
    {
      chunk_id: id,
      document_id: id,
      version_id: id,
      index_revision_id: id,
      version_number: 1,
      title: "Política de viajes",
      filename: "viajes.pdf",
      sha256: "a".repeat(64),
      snippet: "Plazo de 7 días.",
      locators: [{ format: "pdf", page: 1, heading_path: [] }],
      source_url: `/sources/${id}`,
      original_url: `/documents/${id}/versions/${id}/original`,
    },
  ],
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });
beforeEach(() => clearSession());
afterEach(() => vi.unstubAllGlobals());

it("sends a bounded question, shows fake mode and opens its authorized source", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, options?: RequestInit) => {
      if (path === "/api/chat/answers") {
        expect(JSON.parse(String(options?.body)).query).toBe(
          "¿En cuántos días se presentan los gastos del viaje?",
        );
        return json(answer);
      }
      return json({ ...answer.citations[0], text: "Texto de la fuente original." });
    }),
  );
  render(<ChatPage />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Usar pregunta de ejemplo" }));
  await user.click(screen.getByRole("button", { name: "Enviar pregunta" }));
  expect(await screen.findByText(answer.text)).toBeInTheDocument();
  expect(screen.getByText(/respuestas programadas/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Política de viajes · Versión 1" }));
  expect(await screen.findByText("Texto de la fuente original.")).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "Política de viajes", level: 2 })).toHaveFocus();
});

it("displays insufficient evidence without invented citations", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      json({
        ...answer,
        abstained: true,
        text: "No encuentro evidencia suficiente para responder esta pregunta.",
        citations: [],
      }),
    ),
  );
  render(<ChatPage />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Tu pregunta"), "Pregunta desconocida");
  await user.click(screen.getByRole("button", { name: "Enviar pregunta" }));
  expect(await screen.findByText(/No encuentro evidencia suficiente/)).toBeInTheDocument();
  expect(screen.queryByText("Fuentes de esta respuesta")).not.toBeInTheDocument();
});

it("preserves the question for a manual retry after a safe service error", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => json({ detail: "private provider body" }, 503)),
  );
  render(<ChatPage />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Tu pregunta"), "Mi pregunta");
  await user.click(screen.getByRole("button", { name: "Enviar pregunta" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "El servicio no pudo completar la solicitud.",
  );
  expect(screen.getByLabelText("Tu pregunta")).toHaveValue("Mi pregunta");
  expect(screen.queryByText("private provider body")).not.toBeInTheDocument();
});
