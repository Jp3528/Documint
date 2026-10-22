import { useEffect, useRef, useState, type FormEvent } from "react";
import { z } from "zod";
import { apiRequest, apiResponse, errorMessage } from "./api";
import { citationSchema, locatorLabel, sourceSchema, type Source } from "./search";

const answerSchema = z.object({
  id: z.uuid(),
  text: z.string(),
  abstained: z.boolean(),
  model: z.object({ name: z.string(), revision: z.string(), mode: z.enum(["FAKE", "REAL"]) }),
  citations: z.array(citationSchema),
});
type Message = { question: string; answer: z.infer<typeof answerSchema> };

export function ChatPage() {
  const [question, setQuestion] = useState(""),
    [messages, setMessages] = useState<Message[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [source, setSource] = useState<Source | null>(null),
    [sourceBusy, setSourceBusy] = useState(false);
  const request = useRef<AbortController | null>(null),
    sourceRequest = useRef<AbortController | null>(null),
    opener = useRef<HTMLButtonElement | null>(null),
    heading = useRef<HTMLHeadingElement>(null);
  useEffect(
    () => () => {
      request.current?.abort();
      sourceRequest.current?.abort();
    },
    [],
  );
  useEffect(() => {
    heading.current?.focus();
  }, [source]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || busy) return;
    const controller = new AbortController();
    request.current = controller;
    const text = question.trim();
    setBusy(true);
    setError("");
    setSource(null);
    sourceRequest.current?.abort();
    setSourceBusy(false);
    try {
      const response = await apiRequest("/chat/answers", {
        method: "POST",
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(90000)]),
        body: JSON.stringify({ query: text, method: "hybrid", limit: 8 }),
      });
      const answer = answerSchema.parse(response);
      if (!controller.signal.aborted) {
        setMessages((previous) => [...previous, { question: text, answer }]);
        setQuestion("");
      }
    } catch (cause) {
      if (!controller.signal.aborted) setError(errorMessage(cause));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }
  async function openSource(id: string, button: HTMLButtonElement) {
    sourceRequest.current?.abort();
    const controller = new AbortController();
    sourceRequest.current = controller;
    opener.current = button;
    setSource(null);
    setSourceBusy(true);
    setError("");
    try {
      const response = sourceSchema.parse(
        await apiRequest(`/sources/${id}`, { signal: controller.signal }),
      );
      if (response.chunk_id !== id) throw new Error("Invalid source");
      if (!controller.signal.aborted) setSource(response);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setMessages([]);
        setError(errorMessage(cause));
      }
    } finally {
      if (!controller.signal.aborted) setSourceBusy(false);
    }
  }
  async function download() {
    if (!source) return;
    try {
      const response = await apiResponse(
        `/documents/${source.document_id}/versions/${source.version_id}/original`,
      );
      const url = URL.createObjectURL(await response.blob()),
        link = document.createElement("a");
      link.href = url;
      link.download = source.filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setSource(null);
      setMessages([]);
      setError(errorMessage(cause));
    }
  }
  return (
    <>
      <div className="page-heading search-heading">
        <p className="eyebrow">CONSULTAS</p>
        <h1 id="page-title" tabIndex={-1}>
          Preguntar a tus documentos
        </h1>
        <p>Consulta la información y revisa las fuentes de cada respuesta.</p>
      </div>
      <section className="chat-messages" role="log" aria-label="Consultas y respuestas">
        {!messages.length && (
          <div className="panel empty-state">
            <h2>Empieza con una pregunta</h2>
            <p>Haz una consulta concreta sobre la información de tu biblioteca.</p>
            <button
              type="button"
              className="button secondary"
              onClick={() => setQuestion("¿En cuántos días se presentan los gastos del viaje?")}
            >
              Usar pregunta de ejemplo
            </button>
          </div>
        )}
        {messages.map(({ question: text, answer }) => (
          <article className="panel chat-turn" key={answer.id}>
            <p className="eyebrow">TU PREGUNTA</p>
            <h2>{text}</h2>
            {answer.model.mode === "FAKE" && (
              <p className="demo-note">
                Modo de demostración: respuestas programadas para el corpus de ejemplo.
              </p>
            )}
            <p className="chat-answer">{answer.text}</p>
            {!!answer.citations.length && (
              <div>
                <h3>Fuentes de esta respuesta</h3>
                <ul className="chat-citations">
                  {answer.citations.map((citation) => (
                    <li key={citation.chunk_id}>
                      <button
                        type="button"
                        className="text-button"
                        onClick={(event) => void openSource(citation.chunk_id, event.currentTarget)}
                      >
                        {citation.title} · Versión {citation.version_number}
                      </button>
                      <span className="muted">
                        {citation.locators.map(locatorLabel).join(" / ")}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </article>
        ))}
      </section>
      <form className="panel chat-composer" onSubmit={(event) => void submit(event)}>
        <label htmlFor="question">Tu pregunta</label>
        <textarea
          id="question"
          name="query"
          rows={3}
          required
          maxLength={1000}
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          disabled={busy}
          aria-describedby="question-help"
        />
        <p id="question-help" className="muted">
          Si las fuentes no son suficientes, la respuesta lo indicará.
        </p>
        <button type="submit" className="button" disabled={busy || !question.trim()}>
          {busy ? "Consultando…" : "Enviar pregunta"}
        </button>
      </form>
      {busy && <p role="status">Preparando una respuesta con las fuentes disponibles…</p>}
      {error && (
        <p role="alert" className="error-box">
          {error}
        </p>
      )}
      {sourceBusy && <p role="status">Comprobando acceso a la fuente…</p>}
      {source && (
        <section className="panel source-panel" aria-labelledby="chat-source-title">
          <div className="detail-heading">
            <h2 id="chat-source-title" ref={heading} tabIndex={-1}>
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
          <button type="button" className="button secondary" onClick={() => void download()}>
            Descargar original de esta versión
          </button>
        </section>
      )}
    </>
  );
}
