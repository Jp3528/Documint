import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ProcessingPanel } from "./ProcessingPanel";

const documentId = "12345678-1234-4234-8234-123456789010",
  versionId = "12345678-1234-4234-8234-123456789011";
const job = {
  id: "12345678-1234-4234-8234-123456789012",
  status: "WAITING_PIPELINE",
  stage: "WAITING_PIPELINE",
  attempts: 0,
  max_attempts: 3,
  error_code: null,
};
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200 });
const page = (status: string) => ({ items: [{ ...job, status }], total: 1, offset: 0, limit: 1 });
afterEach(() => vi.unstubAllGlobals());

it("shows pending processing without claiming search readiness or offering a retry loop", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(page("WAITING_PIPELINE"))),
  );
  render(<ProcessingPanel documentId={documentId} versionId={versionId} canManage />);
  expect(await screen.findByText("Procesamiento pendiente")).toBeInTheDocument();
  expect(screen.getByText(/Todavía no está disponible para búsqueda/)).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("retries a failed job through the same authorized job id", async () => {
  let retried = false;
  const fetcher = vi.fn(async (path: string, options?: RequestInit) => {
    if (options?.method === "POST") {
      expect(path).toBe(`/api/documents/${documentId}/jobs/${job.id}/retry`);
      retried = true;
      return response(job);
    }
    return response(page(retried ? "PENDING" : "DISPATCH_FAILED"));
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ProcessingPanel documentId={documentId} versionId={versionId} canManage />);
  await userEvent
    .setup()
    .click(await screen.findByRole("button", { name: "Reintentar procesamiento" }));
  expect(await screen.findByText("Pendiente de iniciar")).toBeInTheDocument();
});

it("does not offer retry controls to a read-only user", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => response(page("DISPATCH_FAILED"))),
  );
  render(<ProcessingPanel documentId={documentId} versionId={versionId} canManage={false} />);
  expect(await screen.findByText("No se pudo iniciar")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
