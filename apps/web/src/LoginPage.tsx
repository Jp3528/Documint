import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { errorMessage } from "./api";
import { useAuth } from "./auth-context";

export function LoginPage() {
  const auth = useAuth();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const state = location.state as { from?: unknown } | null;
  const destination =
    typeof state?.from === "string" && /^\/(?!\/)/.test(state.from) ? state.from : "/";
  if (auth.loading)
    return (
      <div className="splash" role="status">
        Recuperando sesión…
      </div>
    );
  if (auth.user) return <Navigate to={destination} replace />;
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await auth.login(email, password);
      setPassword("");
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-layout">
      <section className="login-story" aria-label="Documint">
        <a className="brand" href="/">
          <span className="brand-mark" aria-hidden="true">
            D
          </span>
          Documint
        </a>
        <div>
          <p className="eyebrow">EL ESPACIO DE TU EQUIPO</p>
          <h1>
            La información empieza
            <br />
            con las personas.
          </h1>
          <p>Un espacio de trabajo para tu equipo, con acceso según sus responsabilidades.</p>
        </div>
        <span className="story-note">Documint · Conocimiento empresarial</span>
      </section>
      <section className="login-form-area" aria-labelledby="login-title">
        <form className="login-form" onSubmit={submit}>
          <p className="eyebrow">BIENVENIDO</p>
          <h2 id="login-title">Inicia sesión</h2>
          <p className="muted">Accede con el correo de tu organización.</p>
          {auth.restoreError && (
            <p className="notice" role="status">
              {auth.restoreError}
            </p>
          )}
          {error && (
            <p className="error-box" role="alert">
              {error}
            </p>
          )}
          <label htmlFor="email">Correo electrónico</label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={busy}
          />
          <label htmlFor="current-password">Contraseña</label>
          <input
            id="current-password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            maxLength={128}
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={busy}
          />
          <button className="button" type="submit" disabled={busy}>
            {busy ? "Entrando…" : "Entrar"}
            <span aria-hidden="true">↗</span>
          </button>
          <p className="login-help">Si necesitas acceso, contacta al administrador de tu equipo.</p>
          {import.meta.env.DEV && (
            <details className="demo-details">
              <summary>Acceso a la demo local</summary>
              <p>
                <strong>admin@documind.example</strong>
                <br />
                Contraseña: <code>DocumindDemo2026!</code>
              </p>
            </details>
          )}
        </form>
      </section>
    </main>
  );
}
