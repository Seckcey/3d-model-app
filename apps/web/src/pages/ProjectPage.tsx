import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { api } from "../api/client";
import { useParts, useProject } from "../api/hooks";
import type { Part, Project, ProjectStatus, Revision } from "../api/types";
import { useWorkspace } from "../auth/workspace";
import { Icon } from "../components/icons";
import { AiBadge, RevisionStateBadge } from "../components/status";
import { useToast } from "../components/toast";
import { Button, Card, Empty, ErrorText, Field, Modal, PageLoading, Spinner } from "../components/ui";
import { formatDate, relativeTime } from "../lib/format";
import { StatusTag } from "./DashboardPage";

function NewPartModal({ projectId, onClose }: { projectId: string; onClose: () => void }) {
  const { orgId } = useWorkspace();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [partNumber, setPartNumber] = useState("");
  const [description, setDescription] = useState("");
  const [material, setMaterial] = useState("");
  const [quantity, setQuantity] = useState("");
  const [revision, setRevision] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const part = await api.post<Part>("/api/v1/parts/", {
        project: projectId,
        part_number: partNumber.trim(),
        description: description.trim(),
        material: material.trim(),
        quantity: quantity ? Number(quantity) : null,
      });
      await api.post<Revision>(`/api/v1/parts/${part.id}/revisions/`, { drawing_revision: revision.trim() });
      await queryClient.invalidateQueries({ queryKey: ["parts", projectId] });
      navigate(`/w/${orgId}/parts/${part.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title="Add part"
      subtitle="Use the customer's part number and the drawing revision you received."
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={busy} onClick={submit} disabled={!partNumber.trim()}>Add part</Button>
        </>
      }
    >
      <form className="stack" onSubmit={submit}>
        <div className="form-grid">
          <Field label="Part number">
            {(id) => <input id={id} className="input" value={partNumber} onChange={(e) => setPartNumber(e.target.value)} required />}
          </Field>
          <Field label="Drawing revision" help="The letter or number in the customer's title block">
            {(id) => <input id={id} className="input" value={revision} maxLength={20} onChange={(e) => setRevision(e.target.value.toUpperCase())} placeholder="e.g. C" />}
          </Field>
        </div>
        <Field label="Description">
          {(id) => <input id={id} className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Mounting bracket" />}
        </Field>
        <div className="form-grid">
          <Field label="Material (if known)">
            {(id) => <input id={id} className="input" value={material} onChange={(e) => setMaterial(e.target.value)} placeholder="e.g. 6061-T6" />}
          </Field>
          <Field label="Quantity">
            {(id) => <input id={id} className="input" type="number" min={1} value={quantity} onChange={(e) => setQuantity(e.target.value)} />}
          </Field>
        </div>
        <ErrorText error={error} />
      </form>
    </Modal>
  );
}

function EditProjectModal({ project, onClose }: { project: Project; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(project.name);
  const [reference, setReference] = useState(project.reference);
  const [status, setStatus] = useState<ProjectStatus>(project.status);
  const [dueDate, setDueDate] = useState(project.due_date ?? "");
  const [notes, setNotes] = useState(project.notes);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/api/v1/projects/${project.id}/`, { name, reference, status, due_date: dueDate || null, notes });
      await queryClient.invalidateQueries({ queryKey: ["project", project.id] });
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      onClose();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal title="Edit project" onClose={onClose} footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" busy={busy} onClick={submit}>Save</Button></>}>
      <div className="stack">
        <Field label="Name">{(id) => <input id={id} className="input" value={name} onChange={(e) => setName(e.target.value)} />}</Field>
        <div className="form-grid">
          <Field label="PO / RFQ / job number">{(id) => <input id={id} className="input" value={reference} onChange={(e) => setReference(e.target.value)} />}</Field>
          <Field label="Status">
            {(id) => (
              <select id={id} className="select" value={status} onChange={(e) => setStatus(e.target.value as ProjectStatus)}>
                <option value="active">Active</option>
                <option value="on_hold">On hold</option>
                <option value="complete">Complete</option>
                <option value="archived">Archived</option>
              </select>
            )}
          </Field>
          <Field label="Due date">{(id) => <input id={id} className="input" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />}</Field>
        </div>
        <Field label="Notes">{(id) => <textarea id={id} className="textarea" value={notes} onChange={(e) => setNotes(e.target.value)} />}</Field>
        <ErrorText error={error} />
      </div>
    </Modal>
  );
}

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const { orgId, can } = useWorkspace();
  const project = useProject(projectId);
  const parts = useParts(projectId);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState(false);
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();

  if (project.isLoading) return <PageLoading />;
  if (project.error || !project.data) return <ErrorText error={project.error ?? new Error("Project not found.")} />;
  const p = project.data;

  async function remove() {
    const typed = window.prompt(
      `Delete "${p.name}" and every drawing and file in it? This cannot be undone (backups expire on their own schedule).\n\nType the project name to confirm:`,
    );
    if (typed !== p.name) return;
    try {
      await api.del(`/api/v1/projects/${p.id}/`);
      await queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
      toast("Project deleted");
      navigate(`/w/${orgId}`);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Delete failed", "error");
    }
  }

  return (
    <div className="stack">
      <div>
        <div className="crumbs"><Link to={`/w/${orgId}`}>Projects</Link> / <span>{p.name}</span></div>
        <div className="page-header">
          <div>
            <h1>{p.name}</h1>
            <div className="row" style={{ marginTop: 8 }}>
              <StatusTag status={p.status} />
              <AiBadge allowed={p.external_ai_allowed} />
              {p.customer_name && <span className="muted">Customer: <strong>{p.customer_name}</strong></span>}
              {p.reference && <span className="muted">PO/RFQ: <span className="mono">{p.reference}</span></span>}
              {p.due_date && <span className="muted">Due {formatDate(p.due_date)}</span>}
            </div>
          </div>
          <div className="row">
            {can("edit") && <Button onClick={() => setEditing(true)}>Edit</Button>}
            {can("manage") && <Button variant="danger" onClick={remove}>Delete</Button>}
            {can("edit") && (
              <Button variant="primary" onClick={() => setAdding(true)}>
                <Icon.Plus width={16} height={16} /> Add part
              </Button>
            )}
          </div>
        </div>
        {p.notes && <p className="muted">{p.notes}</p>}
      </div>

      <Card flush title="Parts">
        {parts.isLoading ? (
          <div className="card-body"><Spinner /></div>
        ) : !parts.data?.results.length ? (
          <Empty
            title="No parts yet"
            action={can("edit") ? <Button variant="primary" onClick={() => setAdding(true)}>Add the first part</Button> : undefined}
          >
            Add the customer's part number and drawing revision, then upload the drawing.
          </Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Part number</th><th>Description</th><th>Material</th><th className="right">Qty</th><th>Latest revision</th><th>Updated</th></tr>
              </thead>
              <tbody>
                {parts.data.results.map((part) => (
                  <tr key={part.id} className="clickable" onClick={() => navigate(`/w/${orgId}/parts/${part.id}`)}>
                    <td><Link to={`/w/${orgId}/parts/${part.id}`}><strong>{part.part_number}</strong></Link></td>
                    <td>{part.description || <span className="subtle">—</span>}</td>
                    <td>{part.material || <span className="subtle">—</span>}</td>
                    <td className="right num">{part.quantity ?? "—"}</td>
                    <td>
                      {part.latest_revision ? (
                        <span className="row">
                          <span className="mono">Rev {part.latest_revision.drawing_revision || "?"} · #{part.latest_revision.sequence}</span>
                          <RevisionStateBadge state={part.latest_revision.state} />
                        </span>
                      ) : "—"}
                    </td>
                    <td className="subtle nowrap">{relativeTime(part.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {adding && <NewPartModal projectId={p.id} onClose={() => setAdding(false)} />}
      {editing && <EditProjectModal project={p} onClose={() => setEditing(false)} />}
    </div>
  );
}
