import { useState } from "react";
import { getApiHealth } from "./health";

export function HealthCard() {
  const [status, setStatus] = useState("Pendiente de comprobar.");
  const [busy, setBusy] = useState(false);
  async function check() {
    setBusy(true);
    try {
      const health = await getApiHealth(AbortSignal.timeout(5000));
      setStatus(`API conectada · versión ${health.version}`);
    } catch {
      setStatus(
        "No se pudo conectar con la API. Comprueba que esté iniciada e inténtalo de nuevo.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel" aria-labelledby="service-title">
      <p className="eyebrow">SERVICIO</p>
      <h2 id="service-title">Estado de conexión</h2>
      <p role="status" aria-live="polite">
        {busy ? "Comprobando conexión…" : status}
      </p>
      <button className="button secondary" type="button" onClick={check} disabled={busy}>
        {busy ? "Comprobando…" : "Comprobar conexión"}
      </button>
    </section>
  );
}
