export type Role = "owner" | "engineer" | "reviewer" | "viewer";
export type Capability = "view" | "download_sources" | "edit" | "approve" | "manage";

export interface OrgRef {
  id: string;
  name: string;
  slug: string;
}

export interface Membership {
  organization: OrgRef;
  roles: Role[];
  capabilities: Capability[];
}

export interface Me {
  id: string;
  email: string;
  full_name: string;
  is_staff: boolean;
  memberships: Membership[];
  signup_mode: "invite_only" | "open";
}

export interface Preferences {
  drawing_units: "in" | "mm";
  projection: "third_angle" | "first_angle";
  tapped_hole_model: "tap_drill" | "tap_drill_with_major_step" | "major_diameter" | "minor_diameter";
  tap_drill_basis: "cut_tap" | "form_tap" | "thread_mill";
  model_tolerance: "nominal" | "mid_tolerance";
  also_export_mid_tolerance: boolean;
  color_faces_by_tolerance: boolean;
  color_faces_by_hole_type: boolean;
  origin: "datum_abc" | "stock_corner" | "stock_top_center" | "part_center";
  include_stock_body: boolean;
  step_units: "drawing" | "in" | "mm";
  step_schema: "AP214" | "AP242";
  dxf_version: "R12" | "R2000";
  filename_pattern: string;
  cam_software: string;
  stock_allowance_in: number;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  allow_external_ai: boolean;
  allowed_ai_providers: string[];
  max_upload_mb: number;
  max_pdf_pages: number;
  max_active_generation_jobs: number;
  retention_days: number | null;
  monthly_ai_budget_usd: string | null;
  preferences: Preferences;
  created_at: string;
  my_roles: Role[];
}

export interface Member {
  id: string;
  user: { id: string; email: string; full_name: string; last_login: string | null };
  roles: Role[];
  created_at: string;
}

export interface Invitation {
  id: string;
  email: string;
  roles: Role[];
  status: "pending" | "accepted" | "revoked" | "expired";
  expires_at: string;
  created_at: string;
  last_sent_at: string | null;
  invited_by_email: string | null;
}

export interface InvitationPreview {
  organization: { name: string };
  email: string;
  roles: Role[];
  status: Invitation["status"];
  expires_at: string;
  invited_by: string | null;
  account_exists: boolean;
}

export interface Paginated<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Customer {
  id: string;
  organization: string;
  name: string;
  code: string;
  notes: string;
  created_at: string;
}

export type ProjectStatus = "active" | "on_hold" | "complete" | "archived";

export interface Project {
  id: string;
  organization: string;
  customer: string | null;
  customer_name: string | null;
  name: string;
  reference: string;
  status: ProjectStatus;
  due_date: string | null;
  external_ai_allowed: boolean;
  notes: string;
  created_at: string;
  updated_at: string;
  part_count: number | null;
}

export type RevisionState =
  | "draft"
  | "needs_input"
  | "ready_for_review"
  | "approved"
  | "released"
  | "superseded";

export interface Part {
  id: string;
  organization: string;
  project: string;
  project_name: string;
  customer_name: string | null;
  part_number: string;
  description: string;
  material: string;
  quantity: number | null;
  created_at: string;
  updated_at: string;
  latest_revision: { id: string; drawing_revision: string; sequence: number; state: RevisionState } | null;
}

export type ExportControl = "none_found" | "not_scanned" | "detected" | "confirmed" | "cleared";

export interface Marking {
  kind: string;
  severity: "block" | "info";
  page: number;
  text: string;
}

export interface IntakeWarning {
  code: string;
  page?: number;
  message: string;
}

export interface IntakeReport {
  version: number;
  page_count: number;
  pages: {
    number: number;
    width_in: number | null;
    height_in: number | null;
    has_vector_text: boolean;
    text_chars: number;
    sharpness: number;
    render_px: [number, number];
  }[];
  warnings: IntakeWarning[];
  export_control: { status: string; markings: Marking[] };
  hints: {
    units: "in" | "mm" | null;
    projection: "third_angle" | "first_angle" | null;
    revision_candidates: string[];
    material_candidates: string[];
    outside_processes: string[];
    thread_callouts: string[];
    general_tolerance_block: boolean;
    unless_otherwise_specified: boolean;
  } | null;
  notes: string[];
}

export interface SourceFile {
  id: string;
  revision: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  page_count: number;
  selected_pages: number[];
  intake_status: "pending" | "ok" | "warning" | "failed";
  intake_report: IntakeReport | Record<string, never>;
  created_at: string;
  uploaded_by_email: string | null;
  thumbnails: { page: number; thumbnail?: string; page_image?: string }[];
}

export interface Revision {
  id: string;
  organization: string;
  part: string;
  part_number: string;
  drawing_revision: string;
  sequence: number;
  state: RevisionState;
  external_ai_allowed: boolean;
  effective_external_ai: boolean;
  export_control: ExportControl;
  export_control_markings: Marking[];
  notes: string;
  created_at: string;
  updated_at: string;
  source_files: SourceFile[];
}

export type JobState =
  | "queued"
  | "running"
  | "waiting_input"
  | "succeeded"
  | "failed"
  | "unsupported"
  | "canceled";

export interface JobEvent {
  at: string;
  state: JobState;
  stage: string;
  message: string;
}

export interface Job {
  id: string;
  organization: string;
  revision: string | null;
  source_file: string | null;
  source_file_name: string | null;
  kind: "intake_check" | "geometry_benchmark";
  state: JobState;
  stage: string;
  idempotency_key: string;
  result: Record<string, unknown>;
  error_code: string;
  error_message: string;
  attempts: number;
  max_attempts: number;
  deadline_seconds: number;
  cancel_requested: boolean;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  elapsed_seconds: number | null;
  engine_versions: Record<string, string>;
  usage: Record<string, number | null>;
  processing_location: string;
  requested_by_email: string | null;
  created_at: string;
  events?: JobEvent[];
}

export interface Artifact {
  id: string;
  kind: "page_image" | "thumbnail" | "step" | "dxf" | "glb" | "report" | "manifest";
  variant: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  is_draft: boolean;
  released_at: string | null;
  metadata: { part?: string; validation?: Validation; page?: number };
  created_at: string;
  job: string | null;
  revision: string | null;
}

export interface Check {
  check: string;
  label: string;
  feature: string;
  instance: number | null;
  dims: string[];
  expected: unknown;
  measured: unknown;
  units: string;
  status: "pass" | "fail" | "not_applicable";
}

export interface Validation {
  passed: boolean;
  summary: { total: number; passed: number; failed: number; not_applicable?: number; volume?: number; bbox?: number[] };
  checks: Check[];
}

export interface BenchmarkPart {
  part: string;
  variant: "nominal" | "mid_tolerance";
  title: string;
  validation: Validation;
}

export interface BenchmarkData {
  latest: Job | null;
  history: Job[];
  artifacts: Artifact[];
  specs: { part: string; title: string; family: string }[];
}

export interface AuditEvent {
  id: number;
  created_at: string;
  action: string;
  actor_email: string;
  target_type: string;
  target_id: string;
  ip: string | null;
  data: Record<string, unknown>;
}

export interface SearchResults {
  parts: Part[];
  projects: Project[];
  customers: Customer[];
}

export interface UserSession {
  id: number;
  created_at: number;
  ip: string;
  user_agent: string;
  is_current: boolean;
  last_seen_at?: number;
}

export interface Health {
  version: { app: string; git_sha: string };
  database: { ok: boolean; engine?: string; error?: string };
  cache: { ok: boolean; error?: string };
  queues: { available: boolean; depths?: Record<string, number>; error?: string };
  disk: { ok: boolean; total_gb?: number; free_gb?: number; used_percent?: number; alert_percent?: number; error?: string };
  jobs: { last_24h: Record<string, number>; running: number; queued: number; oldest_queued_minutes: number; alert_minutes: number };
  backups: {
    ok: boolean;
    last_backup: { at: string; status: string; size_bytes: number | null; location: string } | null;
    last_backup_age_hours: number | null;
    last_restore_drill: { at: string; status: string } | null;
    alert_hours: number;
  };
  email: { delivery: "smtp" | "outbox" };
  signup_mode: string;
  checked_at: string;
  workers?: { ok: boolean; workers: { name: string; queues: string[] }[]; missing_queues?: string[]; error?: string };
  alerts: { code: string; title: string; message: string }[];
}

export interface AdminUser {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_staff: boolean;
  last_login: string | null;
  date_joined: string;
  organizations: string[];
}
