import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import { useOrganization } from "../api/hooks";
import type { Organization, Preferences } from "../api/types";
import { useWorkspace } from "../auth/workspace";
import { useToast } from "../components/toast";
import { Alert, Button, Card, ErrorText, Field, PageLoading } from "../components/ui";

type Choice<T extends string> = [T, string, string?];

const TAPPED: Choice<Preferences["tapped_hole_model"]>[] = [
  ["tap_drill", "Tap-drill diameter", "Hole recognition sees a drill-size bore"],
  ["tap_drill_with_major_step", "Tap drill + major-diameter step to thread depth", "Shows thread depth in the solid"],
  ["major_diameter", "Major (nominal) diameter", "Common for thread milling"],
  ["minor_diameter", "Minor diameter", ""],
];
const BASIS: Choice<Preferences["tap_drill_basis"]>[] = [
  ["cut_tap", "Cut tap"],
  ["form_tap", "Form (roll) tap"],
  ["thread_mill", "Thread mill"],
];
const ORIGIN: Choice<Preferences["origin"]>[] = [
  ["datum_abc", "Datum A/B/C intersection"],
  ["stock_corner", "Stock corner"],
  ["stock_top_center", "Stock top centre"],
  ["part_center", "Part centre"],
];

function Select<T extends string>({ label, help, value, options, disabled, onChange }: {
  label: string;
  help?: string;
  value: T;
  options: Choice<T>[];
  disabled: boolean;
  onChange: (value: T) => void;
}) {
  const current = options.find((o) => o[0] === value);
  return (
    <Field label={label} help={current?.[2] || help}>
      {(id) => (
        <select id={id} className="select" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value as T)}>
          {options.map(([v, text]) => <option key={v} value={v}>{text}</option>)}
        </select>
      )}
    </Field>
  );
}

function Toggle({ label, help, checked, disabled, onChange }: { label: string; help?: string; checked: boolean; disabled: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="checkbox">
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}{help && <span className="help subtle">{help}</span>}</span>
    </label>
  );
}

/** Mirrors the CAD worker's naming: units are always stamped into the name. */
export function filenamePreview(pattern: string, units: string): string {
  const kind = `NOMINAL-${units.toUpperCase()}`;
  let name = pattern
    .replace("{part}", "BP-1001")
    .replace("{rev}", "C")
    .replace("{kind}", kind)
    .replace("{customer}", "Acme")
    .replace("{seq}", "2");
  if (!name.includes(kind)) name = `${name}_${kind}`;
  return `${name.replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[._-]+|[._-]+$/g, "")}.step`;
}

export function SettingsPage() {
  const { orgId, can } = useWorkspace();
  const org = useOrganization(orgId);
  const queryClient = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<Organization | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const editable = can("manage");

  useEffect(() => {
    if (org.data) setDraft(org.data);
  }, [org.data]);

  if (org.isLoading || !draft) return <PageLoading />;
  const prefs = draft.preferences;
  const setPref = <K extends keyof Preferences>(key: K, value: Preferences[K]) =>
    setDraft({ ...draft, preferences: { ...prefs, [key]: value } });

  async function save() {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const saved = await api.patch<Organization>(`/api/v1/organizations/${orgId}/`, {
        name: draft.name,
        allow_external_ai: draft.allow_external_ai,
        max_upload_mb: draft.max_upload_mb,
        max_pdf_pages: draft.max_pdf_pages,
        max_active_generation_jobs: draft.max_active_generation_jobs,
        retention_days: draft.retention_days,
        preferences: draft.preferences,
      });
      queryClient.setQueryData(["org", orgId], saved);
      await queryClient.invalidateQueries({ queryKey: ["me"] });
      toast("Settings saved");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  const units = prefs.step_units === "drawing" ? prefs.drawing_units : prefs.step_units;
  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Settings</h1>
          <p>How this shop wants models built and drawings handled. {editable ? "" : "Only owners can change these."}</p>
        </div>
        {editable && <Button variant="primary" busy={busy} onClick={save}>Save changes</Button>}
      </div>
      <ErrorText error={error} />

      <Card title="Shop modelling preferences" subtitle="Applied to every model this workspace generates. Each one answers a common CAM-programmer complaint.">
        <div className="form-grid">
          <Select label="Tapped holes are modelled as" value={prefs.tapped_hole_model} options={TAPPED} disabled={!editable} onChange={(v) => setPref("tapped_hole_model", v)} />
          <Select label="Tap-drill size basis" value={prefs.tap_drill_basis} options={BASIS} disabled={!editable} onChange={(v) => setPref("tap_drill_basis", v)} help="Form taps need a larger drill" />
          <Select label="Default model" value={prefs.model_tolerance} options={[["nominal", "Nominal dimensions"], ["mid_tolerance", "Mid-tolerance (middle of each band)"]]} disabled={!editable} onChange={(v) => setPref("model_tolerance", v)} />
          <Select label="Model origin" value={prefs.origin} options={ORIGIN} disabled={!editable} onChange={(v) => setPref("origin", v)} help="Z points out of the first-operation face" />
          <Select label="STEP units" value={prefs.step_units} options={[["drawing", "Same as the drawing (no conversion)"], ["in", "Inches"], ["mm", "Millimetres"]]} disabled={!editable} onChange={(v) => setPref("step_units", v)} />
          <Select label="Typical drawing units" value={prefs.drawing_units} options={[["in", "Inches"], ["mm", "Millimetres"]]} disabled={!editable} onChange={(v) => setPref("drawing_units", v)} />
          <Select label="Projection your customers use" value={prefs.projection} options={[["third_angle", "Third angle (US)"], ["first_angle", "First angle (ISO)"]]} disabled={!editable} onChange={(v) => setPref("projection", v)} help="Still confirmed per drawing before modelling" />
          <Select label="STEP schema" value={prefs.step_schema} options={[["AP214", "AP214 (colours, widest support)"], ["AP242", "AP242"]]} disabled={!editable} onChange={(v) => setPref("step_schema", v)} />
          <Select label="DXF version" value={prefs.dxf_version} options={[["R12", "R12 (waterjet/laser safe)"], ["R2000", "R2000"]]} disabled={!editable} onChange={(v) => setPref("dxf_version", v)} />
          <Field label="Stock allowance per side (in)" help="Used for stock-size suggestions">
            {(id) => <input id={id} className="input" type="number" step="0.005" min={0} max={2} value={prefs.stock_allowance_in} disabled={!editable} onChange={(e) => setPref("stock_allowance_in", Number(e.target.value))} />}
          </Field>
          <Field label="CAM software and version" help="For the record and Phase 0 import checks">
            {(id) => <input id={id} className="input" value={prefs.cam_software} disabled={!editable} placeholder="e.g. Mastercam 2026, Fusion" onChange={(e) => setPref("cam_software", e.target.value)} />}
          </Field>
          <Field label="File name pattern" help={`Preview: ${filenamePreview(prefs.filename_pattern, units)} · tokens {part} {rev} {kind} {customer} {seq}`}>
            {(id) => <input id={id} className="input mono" value={prefs.filename_pattern} disabled={!editable} onChange={(e) => setPref("filename_pattern", e.target.value)} />}
          </Field>
        </div>
        <div className="stack-sm" style={{ marginTop: 16 }}>
          <Toggle label="Also export a mid-tolerance STEP" help="Asymmetric tolerances move to the middle of the band; the file name says MIDTOL" checked={prefs.also_export_mid_tolerance} disabled={!editable} onChange={(v) => setPref("also_export_mid_tolerance", v)} />
          <Toggle label="Colour hole faces by type" help="Tapped, reamed, bored, clearance, drilled and counterbore faces get distinct colours in STEP and the viewer" checked={prefs.color_faces_by_hole_type} disabled={!editable} onChange={(v) => setPref("color_faces_by_hole_type", v)} />
          <Toggle label="Colour faces by tightest tolerance" help="Planned for generated parts (Phase 3)" checked={prefs.color_faces_by_tolerance} disabled={!editable} onChange={(v) => setPref("color_faces_by_tolerance", v)} />
          <Toggle label="Include a stock body" help="Adds the suggested stock as a second body (Phase 3)" checked={prefs.include_stock_body} disabled={!editable} onChange={(v) => setPref("include_stock_body", v)} />
        </div>
      </Card>

      <div className="grid-2">
        <Card title="Workspace">
          <div className="stack">
            <Field label="Workspace name">{(id) => <input id={id} className="input" value={draft.name} disabled={!editable} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />}</Field>
            <div className="form-grid">
              <Field label="Max upload (MB)">{(id) => <input id={id} className="input" type="number" min={1} max={200} value={draft.max_upload_mb} disabled={!editable} onChange={(e) => setDraft({ ...draft, max_upload_mb: Number(e.target.value) })} />}</Field>
              <Field label="Max PDF pages">{(id) => <input id={id} className="input" type="number" min={1} max={200} value={draft.max_pdf_pages} disabled={!editable} onChange={(e) => setDraft({ ...draft, max_pdf_pages: Number(e.target.value) })} />}</Field>
              <Field label="Geometry jobs at once">{(id) => <input id={id} className="input" type="number" min={1} max={10} value={draft.max_active_generation_jobs} disabled={!editable} onChange={(e) => setDraft({ ...draft, max_active_generation_jobs: Number(e.target.value) })} />}</Field>
              <Field label="Keep projects (days)" help="Empty = keep until deleted">
                {(id) => <input id={id} className="input" type="number" min={1} value={draft.retention_days ?? ""} disabled={!editable} onChange={(e) => setDraft({ ...draft, retention_days: e.target.value ? Number(e.target.value) : null })} />}
              </Field>
            </div>
          </div>
        </Card>
        <Card title="Drawing processing policy">
          <div className="stack">
            <Toggle
              label="Allow external AI processing"
              help="Off means every drawing is processed only on this server. Even when on, a project must opt in and an owner must clear each revision as not export controlled."
              checked={draft.allow_external_ai}
              disabled={!editable}
              onChange={(v) => setDraft({ ...draft, allow_external_ai: v })}
            />
            {draft.allow_external_ai ? (
              <Alert tone="warn" title="Before you turn this on">
                Do not send ITAR, EAR or CUI drawings to a commercial AI service. Encryption exemptions cover storage and
                transmission, not processing. Ask export counsel if unsure.
              </Alert>
            ) : (
              <Alert tone="ok">Local-only processing. No drawing leaves this server.</Alert>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
