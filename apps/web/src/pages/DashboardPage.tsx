import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { api } from "../api/client";
import { useCustomers, useJobs, useOrganization, useProjects } from "../api/hooks";
import type { Customer, Project, ProjectStatus } from "../api/types";
import { useWorkspace } from "../auth/workspace";
import { Icon } from "../components/icons";
import { AiBadge } from "../components/status";
import { useToast } from "../components/toast";
import { Badge, Button, Card, Empty, ErrorText, Field, Modal, Spinner } from "../components/ui";
import { formatDate, relativeTime } from "../lib/format";

const STATUS_LABEL: Record<ProjectStatus, string> = {
  active: "Active",
  on_hold: "On hold",
  complete: "Complete",
  archived: "Archived",
};

export function StatusTag({ status }: { status: ProjectStatus }) {
  const tone = status === "active" ? "info" : status === "on_hold" ? "warn" : "neutral";
  return <Badge tone={tone}>{STATUS_LABEL[status]}</Badge>;
}

export function NewProjectModal({ onClose }: { onClose: () => void }) {
  const { orgId } = useWorkspace();
  const org = useOrganization(orgId);
  const customers = useCustomers(orgId);
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState("");
  const [reference, setReference] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [newCustomer, setNewCustomer] = useState("");
  const [dueDate, setDueDate] = useState("");
  const [externalAi, setExternalAi] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let customer: string | null = customerId || null;
      if (customerId === "__new" && newCustomer.trim()) {
        const created = await api.post<Customer>("/api/v1/customers/", { organization: orgId, name: newCustomer.trim() });
        customer = created.id;
        await queryClient.invalidateQueries({ queryKey: ["customers", orgId] });
      } else if (customerId === "__new") {
        customer = null;
      }
      const project = await api.post<Project>("/api/v1/projects/", {
        organization: orgId,
        name: name.trim(),
        reference: reference.trim(),
        customer,
        due_date: dueDate || null,
        external_ai_allowed: externalAi,
      });
      await queryClient.invalidateQueries({ queryKey: ["projects", orgId] });
      toast(`Project "${project.name}" created`);
      navigate(`/w/${orgId}/projects/${project.id}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const aiAllowedByWorkspace = org.data?.allow_external_ai ?? false;
  return (
    <Modal
      title="New project"
      subtitle="A customer job, RFQ or purchase order. Add parts and drawings next."
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" busy={busy} onClick={submit} disabled={name.trim().length < 2}>
            Create project
          </Button>
        </>
      }
    >
      <form className="stack" onSubmit={submit}>
        <Field label="Project name">
          {(id) => <input id={id} className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Acme brackets, PO 4471" required />}
        </Field>
        <div className="form-grid">
          <Field label="Customer">
            {(id) => (
              <select id={id} className="select" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                <option value="">No customer</option>
                {customers.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                <option value="__new">+ New customer…</option>
              </select>
            )}
          </Field>
          <Field label="PO / RFQ / job number">
            {(id) => <input id={id} className="input" value={reference} onChange={(e) => setReference(e.target.value)} />}
          </Field>
        </div>
        {customerId === "__new" && (
          <Field label="New customer name">
            {(id) => <input id={id} className="input" value={newCustomer} onChange={(e) => setNewCustomer(e.target.value)} />}
          </Field>
        )}
        <Field label="Due date">
          {(id) => <input id={id} className="input" type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />}
        </Field>
        <label className="checkbox">
          <input type="checkbox" checked={externalAi} disabled={!aiAllowedByWorkspace} onChange={(e) => setExternalAi(e.target.checked)} />
          <span>
            Allow external AI processing for this project
            <span className="help subtle">
              {aiAllowedByWorkspace
                ? "Drawings are still processed locally until an owner clears each revision as not export controlled."
                : "Off for this workspace. Drawings are processed only on your server. An owner can change this in Settings."}
            </span>
          </span>
        </label>
        <ErrorText error={error} />
      </form>
    </Modal>
  );
}

export function DashboardPage() {
  const { orgId, can, membership } = useWorkspace();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const status = params.get("status") ?? "active";
  const customer = params.get("customer") ?? "";
  const [creating, setCreating] = useState(false);
  const filters: Record<string, string> = {};
  if (status !== "all") filters.status = status;
  if (customer) filters.customer = customer;
  if (params.get("q")) filters.q = params.get("q") ?? "";
  const projects = useProjects(orgId, filters);
  const activeJobs = useJobs({ organization: orgId, state: "running" });
  const queuedJobs = useJobs({ organization: orgId, state: "queued" });
  const customers = useCustomers(orgId);
  const customerName = customers.data?.find((c) => c.id === customer)?.name;

  function applySearch(event: FormEvent) {
    event.preventDefault();
    const next = new URLSearchParams(params);
    if (q.trim()) next.set("q", q.trim());
    else next.delete("q");
    setParams(next);
  }

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Projects</h1>
          <p>{membership.organization.name} · customer jobs, parts and drawings</p>
        </div>
        {can("edit") && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Icon.Plus width={16} height={16} /> New project
          </Button>
        )}
      </div>

      <div className="grid-4">
        <div className="card stat">
          <div className="label">Projects shown</div>
          <div className="value">{projects.data?.count ?? "—"}</div>
          <div className="hint">{status === "all" ? "All statuses" : STATUS_LABEL[status as ProjectStatus] ?? status}</div>
        </div>
        <div className="card stat">
          <div className="label">Jobs running</div>
          <div className="value">{activeJobs.data?.count ?? "—"}</div>
          <div className="hint"><Link to={`/w/${orgId}/jobs`}>View jobs</Link></div>
        </div>
        <div className="card stat">
          <div className="label">Jobs queued</div>
          <div className="value">{queuedJobs.data?.count ?? "—"}</div>
          <div className="hint">One geometry job at a time</div>
        </div>
        <div className="card stat">
          <div className="label">Customers</div>
          <div className="value">{customers.data?.length ?? "—"}</div>
          <div className="hint">{customerName ? `Filtered: ${customerName}` : "All customers"}</div>
        </div>
      </div>

      <Card
        flush
        title="Project list"
        actions={
          <form className="row" onSubmit={applySearch}>
            <input className="input" style={{ width: 240 }} placeholder="Name, PO/RFQ, part number…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filter projects" />
            <select
              className="select"
              style={{ width: 150 }}
              value={status}
              aria-label="Status"
              onChange={(e) => {
                const next = new URLSearchParams(params);
                next.set("status", e.target.value);
                setParams(next);
              }}
            >
              <option value="active">Active</option>
              <option value="on_hold">On hold</option>
              <option value="complete">Complete</option>
              <option value="archived">Archived</option>
              <option value="all">All</option>
            </select>
            {customer && (
              <Button size="sm" variant="ghost" onClick={() => { const n = new URLSearchParams(params); n.delete("customer"); setParams(n); }}>
                Clear customer
              </Button>
            )}
          </form>
        }
      >
        {projects.isLoading ? (
          <div className="card-body"><Spinner label="Loading projects…" /></div>
        ) : projects.error ? (
          <div className="card-body"><ErrorText error={projects.error} /></div>
        ) : !projects.data?.results.length ? (
          <Empty
            title={params.get("q") ? "No projects match" : "No projects yet"}
            action={can("edit") && !params.get("q") ? <Button variant="primary" onClick={() => setCreating(true)}>Create the first project</Button> : undefined}
          >
            {params.get("q")
              ? "Try a part number, PO number or customer name."
              : "Create a project for a customer job, add the part, then upload its drawing for an intake check."}
          </Empty>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Project</th>
                  <th>Customer</th>
                  <th>PO / RFQ</th>
                  <th className="right">Parts</th>
                  <th>Status</th>
                  <th>Processing</th>
                  <th>Due</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {projects.data.results.map((p) => (
                  <tr key={p.id}>
                    <td><Link to={`/w/${orgId}/projects/${p.id}`}><strong>{p.name}</strong></Link></td>
                    <td>{p.customer_name ?? <span className="subtle">—</span>}</td>
                    <td className="num">{p.reference || "—"}</td>
                    <td className="right num">{p.part_count ?? 0}</td>
                    <td><StatusTag status={p.status} /></td>
                    <td><AiBadge allowed={p.external_ai_allowed} /></td>
                    <td className="nowrap">{formatDate(p.due_date)}</td>
                    <td className="subtle nowrap">{relativeTime(p.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {creating && <NewProjectModal onClose={() => setCreating(false)} />}
    </div>
  );
}
