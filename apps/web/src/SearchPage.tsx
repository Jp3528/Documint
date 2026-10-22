import { useEffect, useRef, useState, type FormEvent } from "react";
import { apiRequest, apiResponse, errorMessage } from "./api";
import { useAuth } from "./auth-context";
import {
  locatorLabel,
  searchSchema,
  sourceSchema,
  type SearchHit,
  type SearchResults,
  type Source,
} from "./search";

export function SearchPage() {
  const { user } = useAuth();
  const [query, setQuery] = useState(""),
    [method, setMethod] = useState("hybrid"),
    [fileType, setFileType] = useState(""),
    [department, setDepartment] = useState("");
  const [results, setResults] = useState<SearchResults | null>(null),
    [source, setSource] = useState<Source | null>(null),
    [lastQuery, setLastQuery] = useState(""),
    [busy, setBusy] = useState(false),
    [sourceBusy, setSourceBusy] = useState(false),
    [error, setError] = useState("");
  const searchController = useRef<AbortController | null>(null),
    sourceController = useRef<AbortController | null>(null),
    sourceHeading = useRef<HTMLHeadingElement>(null),
    opener = useRef<HTMLButtonElement | null>(null);
  useEffect(
    () => () => {
      searchController.current?.abort();
      sourceController.current?.abort();
    },
    [],
  );
  useEffect(() => {
    sourceHeading.current?.focus();
  }, [source]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    searchController.current?.abort();
    sourceController.current?.abort();
    const controller = new AbortController();
    searchController.current = controller;
    setBusy(true);
    setSourceBusy(false);
    setError("");
    setResults(null);
    setSource(null);
    setLastQuery(query.trim());
    try {
      const response = await apiRequest("/search", {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({
          query: query.trim(),
          method,
          limit: 10,
          file_type: fileType || null,
          department_id: department || null,
        }),
      });
      if (!controller.signal.aborted) setResults(searchSchema.parse(response));
    } catch (cause) {
      if (!controller.signal.aborted) setError(errorMessage(cause));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  async function openSource(hit: SearchHit, button: HTMLButtonElement) {
    sourceController.current?.abort();
    const controller = new AbortController();
    sourceController.current = controller;
    opener.current = button;
    setSource(null);
    setSourceBusy(true);
    setError("");
    try {
      const response = await apiRequest(`/sources/${hit.chunk_id}`, { signal: controller.signal });
      const parsed = sourceSchema.parse(response);
      if (parsed.chunk_id !== hit.chunk_id) throw new Error("Invalid source");
      if (!controller.signal.aborted) setSource(parsed);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(errorMessage(cause));
        setResults(null);
      }
    } finally {
      if (!controller.signal.aborted) setSourceBusy(false);
    }
  }
  async function downloadOriginal() {
    if (!source) return;
    try {
      const response = await apiResponse(
        `/documents/${source.document_id}/versions/${source.version_id}/original`,
      );
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = source.filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setSource(null);
      setResults(null);
      setError(errorMessage(cause));
    }
  }
  return (
    <>
      <div className="page-heading search-heading">
        <p className="eyebrow">CONOCIMIENTO</p>
        <h1 id="page-title" tabIndex={-1}>
          Buscar documentos
        </h1>
        <p>Encuentra información y consulta la fuente que la respalda.</p>
      </div>
      <section className="panel search-panel" aria-label="Buscar en la biblioteca">
        <form onSubmit={(event) => void submit(event)} className="search-form">
          <label htmlFor="search-query">¿Qué estás buscando?</label>
          <div className="search-query-row">
            <input
              id="search-query"
              name="query"
              type="search"
              required
              maxLength={1000}
              value={query}
              autoComplete="off"
              autoCapitalize="off"
              spellCheck={false}
              enterKeyHint="search"
              aria-describedby="search-help"
              onChange={(event) => setQuery(event.target.value)}
            />
            <button className="button" type="submit" disabled={busy || !query.trim()}>
              {busy ? "Buscando…" : "Buscar"}
            </button>
          </div>
          <p id="search-help" className="muted">
            Los resultados respetan tu acceso actual a los documentos.
          </p>
          <fieldset className="search-methods">
            <legend>Método de búsqueda</legend>
            {[
              ["hybrid", "Combinada"],
              ["lexical", "Palabras"],
              ["vector", "Semántica"],
            ].map(([value, label]) => (
              <label className="checkbox-label" key={value}>
                <input
                  type="radio"
                  name="method"
                  value={value}
                  checked={method === value}
                  onChange={() => setMethod(value)}
                />
                {label}
              </label>
            ))}
          </fieldset>
          <div className="form-grid search-filters">
            <label>
              Tipo de archivo
              <select
                name="file_type"
                value={fileType}
                onChange={(e) => setFileType(e.target.value)}
              >
                <option value="">Todos los tipos</option>
                {[
                  ["pdf", "PDF"],
                  ["docx", "Word"],
                  ["txt", "Texto"],
                  ["md", "Markdown"],
                ].map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {!!user?.departments.length && (
              <label>
                Departamento
                <select
                  name="department_id"
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                >
                  <option value="">Todos los departamentos</option>
                  {user.departments.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>
        </form>
      </section>
      {error && (
        <p role="alert" className="error-box">
          {error}
        </p>
      )}
      {busy && <p role="status">Consultando documentos…</p>}
      {results && (
        <section className="search-results" aria-labelledby="results-title">
          <h2 id="results-title">Resultados para «{lastQuery}»</h2>
          <p role="status" className="muted">
            {results.candidates.length}{" "}
            {results.candidates.length === 1 ? "resultado" : "resultados"} en esta búsqueda.
          </p>
          {results.embedding_mode === "FAKE" && (
            <p className="demo-note">
              Modo de demostración: el orden semántico utiliza un proveedor de prueba.
            </p>
          )}
          {!results.candidates.length && (
            <div className="panel empty-state">
              <h3>No hay coincidencias disponibles</h3>
              <p>Prueba otras palabras o ajusta los filtros.</p>
            </div>
          )}
          <ol className="search-list">
            {results.candidates.map((hit) => (
              <li className="panel search-hit" key={hit.chunk_id}>
                <div className="detail-heading">
                  <h3>{hit.title}</h3>
                  <span className="tag">Versión {hit.version_number}</span>
                </div>
                <p className="muted">
                  {hit.filename} · {hit.locators.map(locatorLabel).join(" / ")}
                </p>
                <p className="search-snippet">{hit.snippet}</p>
                <button
                  type="button"
                  className="button secondary"
                  onClick={(event) => void openSource(hit, event.currentTarget)}
                >
                  Ver fuente de {hit.title}
                </button>
              </li>
            ))}
          </ol>
        </section>
      )}
      {sourceBusy && <p role="status">Comprobando acceso a la fuente…</p>}
      {source && (
        <section className="panel source-panel" aria-labelledby="source-title">
          <div className="detail-heading">
            <h2 id="source-title" ref={sourceHeading} tabIndex={-1}>
              {source.title}
            </h2>
            <button
              type="button"
              className="text-button"
              onClick={() => {
                setSource(null);
                opener.current?.focus();
              }}
            >
              Cerrar fuente
            </button>
          </div>
          <p className="muted">
            {source.filename} · Versión {source.version_number} ·{" "}
            {source.locators.map(locatorLabel).join(" / ")}
          </p>
          <blockquote className="source-text">{source.text}</blockquote>
          <button
            type="button"
            className="button secondary"
            onClick={() => void downloadOriginal()}
          >
            Descargar original de esta versión
          </button>
        </section>
      )}
    </>
  );
}
