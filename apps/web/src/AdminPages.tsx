import { useEffect, useState, type FormEvent } from "react";
import {
  apiRequest,
  departmentSchema,
  errorMessage,
  pageSchema,
  profileSchema,
  roleLabels,
  roles,
  type Profile,
  type Role,
} from "./api";
import { useResource } from "./useResource";

const usersPage = pageSchema(profileSchema);
const departmentsPage = pageSchema(departmentSchema);
const pageSize = 10;

function Pager({
  offset,
  total,
  onChange,
}: {
  offset: number;
  total: number;
  onChange: (offset: number) => void;
}) {
  return (
    <nav className="pagination" aria-label="Paginación">
      <span>
        {total === 0
          ? "Sin resultados"
          : `${offset + 1}–${Math.min(offset + pageSize, total)} de ${total}`}
      </span>
      <div>
        <button
          className="button secondary"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - pageSize))}
        >
          Anterior
        </button>
        <button
          className="button secondary"
          disabled={offset + pageSize >= total}
          onClick={() => onChange(offset + pageSize)}
        >
          Siguiente
        </button>
      </div>
    </nav>
  );
}

export function UsersPage() {
  const [offset, setOffset] = useState(0),
    [revision, setRevision] = useState(0);
  const resource = useResource(
    `/admin/users?offset=${offset}&limit=${pageSize}`,
    usersPage,
    revision,
  );
  const [email, setEmail] = useState(""),
    [name, setName] = useState(""),
    [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("EMPLOYEE"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const [editing, setEditing] = useState<Profile | null>(null),
    [selected, setSelected] = useState<Role[]>([]);
  useEffect(() => {
    if (editing) document.getElementById("roles-title")?.focus();
  }, [editing]);
  async function action(operation: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await operation();
      setMessage(success);
      setRevision((value) => value + 1);
      return true;
    } catch (cause) {
      setError(errorMessage(cause));
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    if (
      await action(
        () =>
          apiRequest("/admin/users", {
            method: "POST",
            body: JSON.stringify({ email, display_name: name, password, roles: [role] }),
          }),
        "Usuario creado.",
      )
    ) {
      setEmail("");
      setName("");
      setPassword("");
    }
  }
  async function saveRoles(event: FormEvent) {
    event.preventDefault();
    if (!editing) return;
    if (
      await action(
        () =>
          apiRequest(`/admin/users/${editing.id}/roles`, {
            method: "PUT",
            body: JSON.stringify({ roles: selected }),
          }),
        "Roles actualizados.",
      )
    )
      setEditing(null);
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">ADMINISTRACIÓN</p>
          <h1 id="page-title" tabIndex={-1}>
            Usuarios
          </h1>
          <p className="muted">Gestiona el acceso y las responsabilidades de tu equipo.</p>
        </div>
      </div>
      {error && (
        <p className="error-box" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      <section className="panel" aria-labelledby="new-user-title">
        <h2 id="new-user-title">Nuevo usuario</h2>
        <form className="form-grid" onSubmit={create}>
          <label>
            Nombre
            <input
              required
              maxLength={120}
              autoComplete="name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            Correo electrónico
            <input
              required
              type="email"
              autoComplete="off"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            Contraseña inicial
            <input
              required
              type="password"
              minLength={12}
              maxLength={128}
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            Rol inicial
            <select
              value={role}
              onChange={(event) => setRole(event.target.value as Role)}
              disabled={busy}
            >
              {roles.map((value) => (
                <option key={value} value={value}>
                  {roleLabels[value]}
                </option>
              ))}
            </select>
          </label>
          <div>
            <button className="button" disabled={busy} type="submit">
              Crear usuario
            </button>
          </div>
        </form>
      </section>
      {editing && (
        <section className="panel" aria-labelledby="roles-title">
          <h2 id="roles-title" tabIndex={-1}>
            Roles de {editing.display_name}
          </h2>
          <form onSubmit={saveRoles}>
            <fieldset disabled={busy}>
              <legend>Selecciona al menos un rol</legend>
              <div className="role-options">
                {roles.map((value) => (
                  <label key={value}>
                    <input
                      type="checkbox"
                      checked={selected.includes(value)}
                      onChange={(event) =>
                        setSelected((current) =>
                          event.target.checked
                            ? [...current, value]
                            : current.filter((item) => item !== value),
                        )
                      }
                    />
                    {roleLabels[value]}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="actions">
              <button className="button" disabled={busy || selected.length === 0}>
                Guardar roles
              </button>
              <button className="button secondary" type="button" onClick={() => setEditing(null)}>
                Cancelar
              </button>
            </div>
          </form>
        </section>
      )}
      <section className="panel list-panel" aria-label="Lista de usuarios">
        {resource.loading && (
          <p role="status" className="loading">
            Cargando usuarios…
          </p>
        )}
        {resource.error && (
          <div className="empty">
            <p role="alert">{resource.error}</p>
            <button className="button secondary" onClick={() => setRevision((value) => value + 1)}>
              Reintentar
            </button>
          </div>
        )}
        {resource.data && (
          <>
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Tabla con desplazamiento horizontal"
            >
              <table>
                <caption className="sr-only">Usuarios registrados y permisos</caption>
                <thead>
                  <tr>
                    <th scope="col">Persona</th>
                    <th scope="col">Roles</th>
                    <th scope="col">Estado</th>
                    <th scope="col">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {resource.data.items.map((user) => (
                    <tr key={user.id}>
                      <td>
                        <strong>{user.display_name}</strong>
                        <span className="cell-detail">{user.email}</span>
                      </td>
                      <td>
                        {user.roles.map((value) => (
                          <span className="tag" key={value}>
                            {roleLabels[value]}
                          </span>
                        ))}
                      </td>
                      <td>
                        <span
                          className={`badge ${user.status === "ACTIVE" ? "active" : "inactive"}`}
                        >
                          {user.status === "ACTIVE" ? "Activo" : "Inactivo"}
                        </span>
                      </td>
                      <td>
                        <div className="row-actions">
                          <button
                            className="text-button"
                            disabled={busy}
                            onClick={() => {
                              setEditing(user);
                              setSelected(user.roles);
                            }}
                            aria-label={`Editar roles de ${user.display_name}`}
                          >
                            Roles
                          </button>
                          <button
                            className="text-button"
                            disabled={busy}
                            onClick={() =>
                              void action(
                                () =>
                                  apiRequest(`/admin/users/${user.id}`, {
                                    method: "PATCH",
                                    body: JSON.stringify({
                                      status: user.status === "ACTIVE" ? "INACTIVE" : "ACTIVE",
                                    }),
                                  }),
                                "Estado actualizado.",
                              )
                            }
                            aria-label={`${user.status === "ACTIVE" ? "Desactivar" : "Activar"} ${user.display_name}`}
                          >
                            {user.status === "ACTIVE" ? "Desactivar" : "Activar"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {resource.data.items.length === 0 && (
                <p className="empty">No hay usuarios para mostrar.</p>
              )}
            </div>
            <Pager offset={offset} total={resource.data.total} onChange={setOffset} />
          </>
        )}
      </section>
    </>
  );
}

export function DepartmentsPage() {
  const [offset, setOffset] = useState(0),
    [revision, setRevision] = useState(0);
  const resource = useResource(
    `/departments?offset=${offset}&limit=${pageSize}`,
    departmentsPage,
    revision,
  );
  const [code, setCode] = useState(""),
    [name, setName] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  async function change(operation: () => Promise<unknown>, success: string) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await operation();
      setMessage(success);
      setRevision((value) => value + 1);
      return true;
    } catch (cause) {
      setError(errorMessage(cause));
      return false;
    } finally {
      setBusy(false);
    }
  }
  async function create(event: FormEvent) {
    event.preventDefault();
    if (
      await change(
        () => apiRequest("/departments", { method: "POST", body: JSON.stringify({ code, name }) }),
        "Departamento creado.",
      )
    ) {
      setCode("");
      setName("");
    }
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">ADMINISTRACIÓN</p>
          <h1 id="page-title" tabIndex={-1}>
            Departamentos
          </h1>
          <p className="muted">Organiza los espacios y el alcance de cada equipo.</p>
        </div>
      </div>
      {error && (
        <p className="error-box" role="alert">
          {error}
        </p>
      )}
      {message && (
        <p className="notice" role="status">
          {message}
        </p>
      )}
      <section className="panel" aria-labelledby="new-department-title">
        <h2 id="new-department-title">Nuevo departamento</h2>
        <form className="form-grid" onSubmit={create}>
          <label>
            Código
            <input
              required
              maxLength={32}
              pattern="[A-Za-z][A-Za-z0-9_]{0,31}"
              value={code}
              onChange={(event) => setCode(event.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            Nombre
            <input
              required
              maxLength={120}
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={busy}
            />
          </label>
          <div className="form-end">
            <button className="button" disabled={busy}>
              Crear departamento
            </button>
          </div>
        </form>
      </section>
      <section className="panel list-panel" aria-label="Lista de departamentos">
        {resource.loading && (
          <p role="status" className="loading">
            Cargando departamentos…
          </p>
        )}
        {resource.error && (
          <div className="empty">
            <p role="alert">{resource.error}</p>
            <button className="button secondary" onClick={() => setRevision((value) => value + 1)}>
              Reintentar
            </button>
          </div>
        )}
        {resource.data && (
          <>
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="Tabla con desplazamiento horizontal"
            >
              <table>
                <caption className="sr-only">Departamentos de la organización</caption>
                <thead>
                  <tr>
                    <th scope="col">Código</th>
                    <th scope="col">Departamento</th>
                    <th scope="col">Estado</th>
                    <th scope="col">Acciones</th>
                  </tr>
                </thead>
                <tbody>
                  {resource.data.items.map((department) => (
                    <tr key={department.id}>
                      <td>
                        <code>{department.code}</code>
                      </td>
                      <td>
                        <strong>{department.name}</strong>
                      </td>
                      <td>
                        <span className={`badge ${department.active ? "active" : "inactive"}`}>
                          {department.active ? "Activo" : "Inactivo"}
                        </span>
                      </td>
                      <td>
                        <button
                          className="text-button"
                          disabled={busy}
                          onClick={() =>
                            void change(
                              () =>
                                apiRequest(`/departments/${department.id}`, {
                                  method: "PATCH",
                                  body: JSON.stringify({ active: !department.active }),
                                }),
                              "Departamento actualizado.",
                            )
                          }
                          aria-label={`${department.active ? "Desactivar" : "Activar"} ${department.name}`}
                        >
                          {department.active ? "Desactivar" : "Activar"}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {resource.data.items.length === 0 && (
                <p className="empty">No hay departamentos para mostrar.</p>
              )}
            </div>
            <Pager offset={offset} total={resource.data.total} onChange={setOffset} />
          </>
        )}
      </section>
    </>
  );
}
