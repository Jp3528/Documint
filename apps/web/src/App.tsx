import { useEffect, useState } from "react";
import {
  BrowserRouter,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { AuthProvider } from "./AuthProvider";
import { DepartmentsPage, UsersPage } from "./AdminPages";
import { HealthCard } from "./HealthCard";
import { LoginPage } from "./LoginPage";
import { LibraryPage } from "./LibraryPage";
import { SearchPage } from "./SearchPage";
import { errorMessage, roleLabels, type Profile } from "./api";
import { useAuth } from "./auth-context";

function RequireSession() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading)
    return (
      <div className="splash" role="status">
        Recuperando sesión…
      </div>
    );
  return user ? <Outlet /> : <Navigate to="/login" replace state={{ from: location.pathname }} />;
}
function RequireCapability({ capability }: { capability: keyof Profile["capabilities"] }) {
  const { user } = useAuth();
  return user?.capabilities[capability] ? (
    <Outlet />
  ) : (
    <Navigate to="/" replace state={{ denied: true }} />
  );
}
function Shell() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    document.getElementById("page-title")?.focus();
  }, [location.pathname]);
  if (!user) return null;
  async function close() {
    setBusy(true);
    setError("");
    try {
      await logout();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="workspace">
      <a className="skip-link" href="#content">
        Ir al contenido
      </a>
      <aside className="sidebar">
        <NavLink className="brand" to="/">
          <span className="brand-mark" aria-hidden="true">
            D
          </span>
          Documint
        </NavLink>
        <p className="sidebar-label">ESPACIO DE TRABAJO</p>
        <nav className="main-nav" aria-label="Principal">
          <NavLink to="/" end>
            <span aria-hidden="true">⌂</span>Inicio
          </NavLink>
          <NavLink to="/library">
            <span aria-hidden="true">▧</span>Biblioteca
          </NavLink>
          <NavLink to="/search">
            <span aria-hidden="true">⌕</span>Buscar
          </NavLink>
          {user.capabilities.manage_users && (
            <NavLink to="/admin/users">
              <span aria-hidden="true">◫</span>Usuarios
            </NavLink>
          )}
          {user.capabilities.manage_departments && (
            <NavLink to="/admin/departments">
              <span aria-hidden="true">▤</span>Departamentos
            </NavLink>
          )}
        </nav>
        <div className="sidebar-footer">
          <span className="small-dot" aria-hidden="true" />
          Sesión activa
        </div>
      </aside>
      <div className="workspace-body">
        <header className="workspace-header">
          <span className="header-label">Tu organización</span>
          <div className="account">
            <span className="avatar" aria-hidden="true">
              {user.display_name.slice(0, 1)}
            </span>
            <span>{user.display_name}</span>
            <button className="text-button" onClick={() => void close()} disabled={busy}>
              {busy ? "Cerrando…" : "Cerrar sesión"}
            </button>
          </div>
        </header>
        <main id="content" className="workspace-main">
          {error && (
            <p role="alert" className="error-box">
              {error}
            </p>
          )}
          <Outlet />
        </main>
        <footer className="workspace-footer">Documint · Espacio de conocimiento</footer>
      </div>
    </div>
  );
}
function HomePage() {
  const { user } = useAuth();
  const location = useLocation();
  if (!user) return null;
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">TU ESPACIO</p>
          <h1 id="page-title" tabIndex={-1}>
            Hola, {user.display_name}.
          </h1>
          <p className="muted">Este es tu punto de partida en Documint.</p>
        </div>
        <span className="workspace-badge">Acceso personal</span>
      </div>
      {(location.state as { denied?: boolean } | null)?.denied && (
        <p className="error-box" role="alert">
          No tienes acceso a esa sección.
        </p>
      )}
      <section className="welcome-panel">
        <div className="document-symbol" aria-hidden="true">
          D
        </div>
        <div>
          <p className="eyebrow">BIENVENIDO A DOCUMINT</p>
          <h2>Un equipo. Un espacio compartido.</h2>
          <p>
            Consulta tu perfil y los departamentos a los que perteneces.
            {user.capabilities.manage_users
              ? " Desde Administración puedes gestionar las personas y sus accesos."
              : " Tu administrador gestiona los permisos de tu cuenta."}
          </p>
        </div>
      </section>
      <div className="dashboard-grid">
        <section className="panel" aria-labelledby="profile-title">
          <p className="eyebrow">IDENTIDAD</p>
          <h2 id="profile-title">Tu perfil</h2>
          <dl className="profile-details">
            <div>
              <dt>Correo</dt>
              <dd>{user.email}</dd>
            </div>
            <div>
              <dt>Responsabilidades</dt>
              <dd>
                {user.roles.map((role) => (
                  <span className="tag" key={role}>
                    {roleLabels[role]}
                  </span>
                ))}
              </dd>
            </div>
          </dl>
        </section>
        <section className="panel" aria-labelledby="teams-title">
          <p className="eyebrow">ORGANIZACIÓN</p>
          <h2 id="teams-title">Tus departamentos</h2>
          {user.departments.length ? (
            <ul className="department-list">
              {user.departments.map((department) => (
                <li key={department.id}>
                  <span className="department-icon" aria-hidden="true">
                    ▤
                  </span>
                  <div>
                    <strong>{department.name}</strong>
                    <span>{department.code}</span>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">Tu cuenta no tiene departamentos asignados.</p>
          )}
        </section>
        <HealthCard />
      </div>
    </>
  );
}
function MissingPage() {
  return (
    <section className="panel">
      <h1 id="page-title" tabIndex={-1}>
        Página no encontrada
      </h1>
      <p>La dirección no corresponde a una sección disponible.</p>
      <NavLink to="/">Volver al inicio</NavLink>
    </section>
  );
}

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireSession />}>
        <Route element={<Shell />}>
          <Route index element={<HomePage />} />
          <Route path="/library" element={<LibraryPage />} />
          <Route path="/search" element={<SearchPage />} />
          <Route element={<RequireCapability capability="manage_users" />}>
            <Route path="/admin/users" element={<UsersPage />} />
          </Route>
          <Route element={<RequireCapability capability="manage_departments" />}>
            <Route path="/admin/departments" element={<DepartmentsPage />} />
          </Route>
          <Route path="*" element={<MissingPage />} />
        </Route>
      </Route>
    </Routes>
  );
}
export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}
