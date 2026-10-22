import { z } from "zod";

export const locatorSchema = z.object({
  format: z.enum(["pdf", "docx", "txt", "md"]),
  page: z.number().int().positive().nullable().optional(),
  paragraph: z.number().int().positive().nullable().optional(),
  heading_path: z.array(z.string()),
  line_start: z.number().int().positive().nullable().optional(),
  line_end: z.number().int().positive().nullable().optional(),
  table_path: z.array(z.number().int()).optional(),
  row: z.number().int().positive().nullable().optional(),
  column: z.number().int().positive().nullable().optional(),
});
export type Locator = z.infer<typeof locatorSchema>;
const citationShape = {
  chunk_id: z.uuid(),
  document_id: z.uuid(),
  version_id: z.uuid(),
  index_revision_id: z.uuid(),
  version_number: z.number().int().positive(),
  title: z.string(),
  filename: z.string(),
  sha256: z.string().regex(/^[a-f0-9]{64}$/),
  snippet: z.string().max(500),
  locators: z.array(locatorSchema).min(1),
  source_url: z.string(),
  original_url: z.string(),
};
export const sourceSchema = z.object({ ...citationShape, text: z.string() });
export type Source = z.infer<typeof sourceSchema>;
export const searchSchema = z.object({
  method: z.enum(["lexical", "vector", "hybrid"]),
  strategy_version: z.string(),
  embedding_mode: z.enum(["FAKE", "REAL"]).nullable(),
  candidates: z.array(
    z.object({ ...citationShape, score: z.number().finite(), rank: z.number().int().positive() }),
  ),
});
export type SearchResults = z.infer<typeof searchSchema>;
export type SearchHit = SearchResults["candidates"][number];
export function locatorLabel(locator: Locator): string {
  const heading = locator.heading_path.join(" › ");
  if (locator.format === "pdf") return `Página ${locator.page}`;
  if (locator.format === "docx")
    return [
      heading,
      `Párrafo ${locator.paragraph}`,
      locator.row ? `Tabla, fila ${locator.row}, columna ${locator.column}` : "",
    ]
      .filter(Boolean)
      .join(" · ");
  return [heading, `Líneas ${locator.line_start}–${locator.line_end}`].filter(Boolean).join(" · ");
}
