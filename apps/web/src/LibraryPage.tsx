import { useEffect, useState, type FormEvent } from "react";
import { apiRequest, apiResponse, departmentSchema, errorMessage, pageSchema } from "./api";
import { useAuth } from "./auth-context";
import {
  documentSchema,
  fileSize,
  statusLabel,
  versionSchema,
  visibilityLabels,
  type LibraryDocument,
} from "./documents";
import { useResource } from "./useResource";

const documentsPage = pageSchema(documentSchema),
  versionsPage = pageSchema(versionSchema),
  departmentsPage = pageSchema(departmentSchema);
const acceptedFiles = ".pdf,.docx,.txt,.md";

function UploadForm({ documentId, onUploaded }: { documentId?: string; onUploaded: () => void }) {
  const [file, setFile] = useState<File | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const body = new FormData();
      body.set("file", file);
      const result = await apiRequest(
        documentId ? `/documents/${documentId}/versions` : "/documents",
        { method: "POST", body, signal: AbortSignal.timeout(60000) },
      );
      versionSchema.parse(result);
      setFile(null);
      setRevision((value) => value + 1);
      onUploaded();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form onSubmit={submit} className="upload-form">
      <label>
        {documentId ? "Archivo de la nueva versión" : "Archivo"}
        <input
          key={revision}
          type="file"
          accept={acceptedFiles}
          required
          disabled={busy}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
      </label>
      <p className="muted">
        PDF, DOCX, TXT o Markdown.{!documentId && " El documento empieza con acceso restringido."}
      </p>
      <button className="button" disabled={busy || !file}>
        {busy ? "Subiendo…" : documentId ? "Subir nueva versión" : "Subir documento"}
      </button>
      {error && (
        <p role="alert" className="error-box">
          {error}
        </p>
      )}
    </form>
  );
}

function DocumentEditor({ item, onChanged }: { item: LibraryDocument; onChanged: () => void }) {
  const departments = useResource("/departments?limit=100", departmentsPage);
  const [title, setTitle] = useState(item.title),
    [visibility, setVisibility] = useState(item.visibility),
    [department, setDepartment] = useState(item.department_id ?? "");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/documents/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({ title, visibility, department_id: department || null }),
      });
      onChanged();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="form-grid document-editor" onSubmit={save}>
      <label>
        Título
        <input
          required
          maxLength={180}
          value={title}
          disabled={busy}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>
      <label>
        Visibilidad
        <select
          value={visibility}
          disabled={busy}
          onChange={(event) => setVisibility(event.target.value as LibraryDocument["visibility"])}
        >
          {Object.entries(visibilityLabels).map(([value, label]) => (
            <option value={value} key={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        Departamento
        <select
          required={visibility === "DEPARTMENT"}
          value={department}
          disabled={busy || departments.loading}
          onChange={(event) => setDepartment(event.target.value)}
        >
          <option value="">Sin departamento</option>
          {item.department_id &&
            !departments.data?.items.some((d) => d.id === item.department_id) && (
              <option value={item.department_id}>{item.department_name}</option>
            )}
          {departments.data?.items
            .filter((d) => d.active)
            .map((d) => (
              <option value={d.id} key={d.id}>
                {d.name}
              </option>
            ))}
        </select>
      </label>
      {departments.error && <p role="alert">{departments.error}</p>}
      <div className="form-end">
        <button className="button" disabled={busy}>
          Guardar cambios
        </button>
      </div>
      {error && (
        <p role="alert" className="error-box">
          {error}
        </p>
      )}
    </form>
  );
}

function DocumentDetails({
  id,
  revision,
  onChanged,
  onClose,
}: {
  id: string;
  revision: number;
  onChanged: () => void;
  onClose: () => void;
}) {
  const resource = useResource(`/documents/${id}`, documentSchema, revision);
  const [offset, setOffset] = useState(0),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const versions = useResource(
    `/documents/${id}/versions?limit=10&offset=${offset}`,
    versionsPage,
    revision,
  );
  useEffect(() => {
    document.getElementById("document-detail-title")?.focus();
  }, [id, resource.loading]);
  async function archive() {
    if (!resource.data) return;
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/documents/${id}`, {
        method: "PATCH",
        body: JSON.stringify({ archived: !resource.data.archived }),
      });
      onChanged();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  async function download(versionId: string, filename: string) {
    setBusy(true);
    setError("");
    try {
      const response = await apiResponse(`/documents/${id}/versions/${versionId}/original`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  }
  const item = resource.data;
  return (
    <section className="panel document-detail" aria-labelledby="document-detail-title">
      <div className="detail-heading">
        <h2 id="document-detail-title" tabIndex={-1}>
          {item?.title ?? "Documento"}
        </h2>
        <button className="text-button" onClick={onClose}>
          Cerrar detalle
        </button>
      </div>
      {resource.loading && <p role="status">Cargando documento…</p>}
      {resource.error && (
        <p role="alert" className="error-box">
          {resource.error}
        </p>
      )}
      {error && (
        <p role="alert" className="error-box">
          {error}
        </p>
      )}
      {item && (
        <>
          <p className="muted">
            {visibilityLabels[item.visibility]} · {item.department_name ?? "Sin departamento"}
            {item.archived && " · Archivado"}
          </p>
          {item.can_manage && (
            <>
              <DocumentEditor
                key={`${item.id}:${item.title}:${item.visibility}:${item.department_id}`}
                item={item}
                onChanged={onChanged}
              />
              <details className="version-upload">
                <summary>Añadir una versión</summary>
                <UploadForm documentId={id} onUploaded={onChanged} />
              </details>
              <button className="text-button" disabled={busy} onClick={() => void archive()}>
                {item.archived ? "Restaurar documento" : "Archivar documento"}
              </button>
            </>
          )}
          <h3>Versiones originales</h3>
          <p className="muted">
            Cada carga conserva el archivo anterior. La búsqueda estará disponible cuando termine el
            procesamiento.
          </p>
          {versions.loading && <p role="status">Cargando versiones…</p>}
          {versions.error && <p role="alert">{versions.error}</p>}
          {versions.data && (
            <>
              <ul className="versions-list">
                {versions.data.items.map((version) => (
                  <li key={version.version_id}>
                    <div>
                      <strong>
                        Versión {version.version_number} · {version.filename}
                      </strong>
                      <span className="cell-detail">
                        {fileSize(version.size_bytes)} · {statusLabel(version.status)}
                      </span>
                    </div>
                    <button
                      className="button secondary"
                      disabled={busy || ["UPLOADING", "UPLOAD_FAILED"].includes(version.status)}
                      onClick={() => void download(version.version_id, version.filename)}
                      aria-label={`Descargar versión ${version.version_number}`}
                    >
                      Descargar
                    </button>
                  </li>
                ))}
              </ul>
              <nav className="pagination" aria-label="Paginación de versiones">
                <span>{versions.data.total} versiones</span>
                <div>
                  <button
                    className="button secondary"
                    disabled={offset === 0}
                    onClick={() => setOffset(Math.max(0, offset - 10))}
                  >
                    Anteriores
                  </button>
                  <button
                    className="button secondary"
                    disabled={offset + 10 >= versions.data.total}
                    onClick={() => setOffset(offset + 10)}
                  >
                    Más versiones
                  </button>
                </div>
              </nav>
            </>
          )}
        </>
      )}
    </section>
  );
}

export function LibraryPage() {
  const { user } = useAuth();
  const [offset, setOffset] = useState(0),
    [archived, setArchived] = useState(false),
    [revision, setRevision] = useState(0),
    [selected, setSelected] = useState<string | null>(null),
    [message, setMessage] = useState("");
  const resource = useResource(
    `/documents?offset=${offset}&limit=10&include_archived=${archived}`,
    documentsPage,
    revision,
  );
  function changed() {
    setRevision((value) => value + 1);
    setMessage("Biblioteca actualizada.");
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">CONOCIMIENTO COMPARTIDO</p>
          <h1 id="page-title" tabIndex={-1}>
            Biblioteca
          </h1>
          <p className="muted">Los documentos de tu equipo, con acceso según tus permisos.</p>
        </div>
      </div>
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {user?.capabilities.manage_knowledge && (
        <section className="panel" aria-labelledby="upload-title">
          <h2 id="upload-title">Nuevo documento</h2>
          <UploadForm onUploaded={changed} />
        </section>
      )}
      <section className="panel list-panel" aria-label="Documentos autorizados">
        <div className="library-toolbar">
          <h2>Documentos</h2>
          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={archived}
              onChange={(event) => {
                setArchived(event.target.checked);
                setOffset(0);
              }}
            />
            Incluir archivados
          </label>
        </div>
        {resource.loading && (
          <p className="loading" role="status">
            Cargando biblioteca…
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
            {resource.data.items.length ? (
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="Tabla de documentos con desplazamiento horizontal"
              >
                <table>
                  <caption className="sr-only">Documentos a los que tienes acceso</caption>
                  <thead>
                    <tr>
                      <th scope="col">Documento</th>
                      <th scope="col">Acceso</th>
                      <th scope="col">Última carga</th>
                      <th scope="col">Acciones</th>
                    </tr>
                  </thead>
                  <tbody>
                    {resource.data.items.map((item) => (
                      <tr key={item.id}>
                        <td>
                          <strong>{item.title}</strong>
                          <span className="cell-detail">
                            {item.department_name ?? "Sin departamento"}
                            {item.archived && " · Archivado"}
                          </span>
                        </td>
                        <td>
                          <span className="tag">{visibilityLabels[item.visibility]}</span>
                        </td>
                        <td>
                          {item.latest_version ? (
                            <>
                              <span>v{item.latest_version.version_number}</span>
                              <span className="cell-detail">
                                {statusLabel(item.latest_version.status)}
                              </span>
                            </>
                          ) : (
                            "Sin original"
                          )}
                        </td>
                        <td>
                          <button
                            className="text-button"
                            onClick={() => setSelected(item.id)}
                            aria-label={`Ver ${item.title}`}
                          >
                            Ver documento
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty">
                <strong>Tu biblioteca está vacía</strong>
                <p>No hay documentos disponibles con tus permisos actuales.</p>
              </div>
            )}
            <nav className="pagination" aria-label="Paginación de documentos">
              <span>{resource.data.total} documentos</span>
              <div>
                <button
                  className="button secondary"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 10))}
                >
                  Anterior
                </button>
                <button
                  className="button secondary"
                  disabled={offset + 10 >= resource.data.total}
                  onClick={() => setOffset(offset + 10)}
                >
                  Siguiente
                </button>
              </div>
            </nav>
          </>
        )}
      </section>
      {selected && (
        <DocumentDetails
          key={selected}
          id={selected}
          revision={revision}
          onChanged={changed}
          onClose={() => setSelected(null)}
        />
      )}
    </>
  );
}
