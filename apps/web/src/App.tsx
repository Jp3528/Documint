import { useState } from "react";
import { getApiHealth } from "./health";

type Connection =
  | { state: "idle" }
  | { state: "loading" }
  | { state: "connected"; version: string }
  | { state: "error"; message: string };

export function App() {
  const [connection, setConnection] = useState<Connection>({ state: "idle" });

  async function checkConnection() {
    setConnection({ state: "loading" });
    try {
      const health = await getApiHealth(AbortSignal.timeout(5000));
      setConnection({ state: "connected", version: health.version });
    } catch {
      setConnection({
        state: "error",
        message:
          "No se pudo conectar con la API. Comprueba que esté iniciada e inténtalo de nuevo.",
      });
    }
  }

  return (
    <>
      <a className="skip-link" href="#content">
        Ir al contenido
      </a>
      <header className="topbar">
        <a className="brand" href="/" aria-label="Documint, inicio">
          <span className="brand-mark" aria-hidden="true">
            D
          </span>
          <span>Documint</span>
        </a>
        <span className="environment">Desarrollo local</span>
      </header>
      <main id="content">
        <p className="eyebrow">CONOCIMIENTO EMPRESARIAL</p>
        <h1>
          Una base para conectar
          <br />
          conocimiento y evidencia.
        </h1>
        <p className="intro">
          Este entorno verifica el arranque de Documint. El proyecto avanzará hacia una biblioteca
          documental y respuestas con fuentes verificables.
        </p>

        <section className="connection" aria-labelledby="connection-title">
          <div className="connection-header">
            <div>
              <p className="eyebrow">ESTADO DEL ENTORNO</p>
              <h2 id="connection-title">Conexión con la API</h2>
            </div>
            <span className={`status-indicator ${connection.state}`} aria-hidden="true" />
          </div>
          <div className="status-message" role="status" aria-live="polite" aria-atomic="true">
            {connection.state === "idle" && <p>Pendiente de comprobar.</p>}
            {connection.state === "loading" && <p>Comprobando conexión…</p>}
            {connection.state === "connected" && (
              <p className="success">API conectada · versión {connection.version}</p>
            )}
            {connection.state === "error" && <p className="error">{connection.message}</p>}
          </div>
          <button type="button" onClick={checkConnection} disabled={connection.state === "loading"}>
            {connection.state === "loading" ? "Comprobando…" : "Comprobar conexión"}
            <span aria-hidden="true">↗</span>
          </button>
          <p className="hint">
            La comprobación confirma que el proceso de la API responde. El estado de sus
            dependencias se consulta por separado en el endpoint /ready.
          </p>
        </section>

        <footer className="footer">
          <span>Documint</span>
          <span>Entorno de desarrollo</span>
        </footer>
      </main>
    </>
  );
}
