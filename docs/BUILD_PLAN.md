# Blueprint to CAD: Phased Build Plan, Version 2

Prepared for Frankie Gonzalez and 8 West Ventures · October 22, 2026 · Revises Version 1 (October 21, 2026)

A machine shop uploads a customer part drawing, reviews what the system read, and downloads a **checked** solid model (STEP), cut-ready DXF and a check report that ties every modeled feature to a drawing callout. The application and geometry engine run on the shop's own Linux VM in Docker. Customers sign in with an emailed one-time code.

Version 1's architecture, phase gates and safety rules are kept. Version 2 adds the features machinists asked for in our research (Section 2), makes verification the product's centre, tightens export-control handling, and reorders the phases so the first release produces what CAM programmers and inspectors use every day.

---

## What changed in Version 2

| Area | Version 1 | Version 2 | Why |
|---|---|---|---|
| Core promise | Traceable model + dimension report | **Callout-by-callout check report**: every dimension, note and hole shows print value, tolerance, value measured on the solid and pass / fail / not modeled | Machinists distrust models that disagree with the print; no competing 2D→3D tool documents this check (Section 2) |
| Geometry options | Nominal model only | Nominal **and** mid-tolerance STEP; per-shop tapped-hole representation; faces coloured by hole type; origin on datums A/B/C | Programmers model to mid-tolerance by hand and cannot tell tapped from drilled holes after STEP import |
| Hole data | In report | **Hole & thread schedule** (CSV/PDF): XYZ from datum, type, thread and class, depths, counterbore/countersink | Thread data does not survive STEP; Mastercam hole recognition needs it |
| Units | Normalise to mm | Build in mm internally, **export in the drawing's units by default**, units stamped in every filename and STEP header | "Silent unit conversion" is a top complaint |
| Drawing reading | Extract dimensions | Adds title-block/notes checklist with sign-off, **tolerance engine with provenance** (title block, ISO 2768, ISO 286 fits), projection gate, and a drafted **customer question list** | Shops ask questions at quote time; software must never invent datums, tolerances or threads |
| Inspection outputs | Out of scope | Ballooned PDF and **AS9102 Form 3 draft** / CSV / XLSX from the same extraction (Phase 4); QIF later | One extraction feeds STEP, DXF, balloons and FAI; manual FAI setup takes 8–12 h |
| DXF | Selected views | **Cut-ready DXF** option: closed loops, true arcs, R12, cut/etch layers, no annotations | OMAX/laser/waterjet requirements |
| Export control | Hold restricted drawings | **Controlled until cleared**: automatic marking detection (ITAR, EAR/ECCN, CUI + dissemination controls, Distribution B–F, classification blocks) at intake; external AI requires an owner's recorded clearance | An unmarked drawing is not proof it is uncontrolled; ITAR/EAR encryption carve-outs do not cover AI inference |
| Revisions | Revision record | Customer revision letter is first-class; intake warns when title block and selected revision disagree; **revision compare** gets its own phase | Wrong-revision work is a classic, expensive error |
| Phase 0 | Manual benchmark | Automated geometry benchmark ships inside Phase 1 (three reference parts, nominal + mid-tolerance, independent checks); humans still verify imports in Fusion and Mastercam | Faster evidence, repeatable on every release |
| Phases | 0–7 | 0–8 (new Phase 4 inspection outputs and Phase 5 revision compare; native CAD adapters move to 6–7) | Delivers the highest-value shop outputs before vendor-dependent adapters |

---

## 1. Product goal and boundary

**Goal.** Cut the time a machinist spends reconstructing customer drawings, without lowering confidence that the part is right. The strongest feature is still traceability: every modeled feature points to a drawing dimension, a recorded rule (for example, the title-block tolerance) or an explicit answer from a person. A good-looking model is not evidence that the part is correct.

**Boundary (unchanged).** A drawing can be incomplete or contradictory; the system asks and stops rather than guessing. An approved model is a geometry deliverable. Tool selection, workholding, toolpaths, post-processing and machine operation remain CAM work. The drawing always governs: every exported file is labelled reference geometry with drawing number, revision, variant (nominal or mid-tolerance) and units.

**First users and parts.** Invite-only pilot (Ralls Precision proposed). Flat plates, prismatic blocks and brackets, stepped shafts and bushings. Inputs: PDF, PNG, JPEG; clean vector PDFs first.

---

## 2. What machinists told us

Three research passes (shop forums and trade press; the competitive landscape; quality, compliance and drafting standards) are summarised in [`docs/research/machinist-needs.md`](research/machinist-needs.md) with sources. The findings that changed this plan:

1. **Verification earns trust.** Programmers check supplied models dimension by dimension; parts have failed first-article inspection because a customer's model disagreed with the print. Auto-balloon tools miss callouts written as notes. Every 2D→3D product we found leaves checking to a human.
2. **Never guess silently.** Shops want missing or conflicting requirements listed and drafted as customer questions; software that invents datums, tolerances or thread specs is a reason to reject it.
3. **CAM-ready geometry.** Programmers program to the middle of the tolerance band (Creo, NX, CAMWorks and SolidWorks macros support it, but only with a native toleranced model, which PDF-only jobs do not have). Holes need a representation CAM can recognise; STEP drops thread data, so a hole table is still needed. The tap-drill choice belongs to the shop.
4. **Units, projection, revision.** Mirror-image scrap from first-angle prints, unit-conversion errors and wrong-revision work recur in every source.
5. **Cut-ready DXF.** Waterjet and laser shops need closed contours, true arcs, R12, explicit units and no title-block clutter.
6. **One extraction, several outputs.** The same characteristic list should feed STEP, DXF, balloons and AS9102/PPAP drafts. Inspection tools do not make solids; 2D→3D tools do not make inspection documents.
7. **Controlled data.** Defense and aerospace shops cannot send ITAR/EAR/CUI drawings to commercial AI APIs. A genuinely self-hosted, local-by-default path that reacts to markings is a differentiator.
8. **Do not overclaim.** No "ITAR compliant", "CMMC certified" or "AS9102-compliant FAI" claims; no accuracy percentages without a published test method.

---

## 3. Recommended feature set

Release column: **P1** = Phase 1 (built now), **MVP** = Phases 2–4, **Later** = Phases 5–8.

### A. Trust and verification
| Feature | Problem it solves | Release |
|---|---|---|
| Check report: per callout print value, tolerance, measured value on the B-rep, pass/fail/not modeled, source crop | Models that disagree with the print | Engine and benchmark P1; full report MVP (Phase 3) |
| Independent validation (closed-form volume, extents, per-hole diameter, position and depth, STEP reopen) | "A plausible model cannot pass" | P1 |
| Assumption log and drafted customer questions | Silent guessing | MVP (Phase 2) |
| Source overlay: every value links to the region of the drawing it came from | Traceability | MVP (Phase 2) |

### B. CAM-ready geometry
| Feature | Problem it solves | Release |
|---|---|---|
| Nominal + mid-tolerance STEP, per-feature override | Manual "machine to the mean" | Engine P1; per-feature override MVP |
| Tapped-hole representation preference (tap drill, tap drill + major-diameter step, major, minor) and tap-drill basis (cut tap, form tap, thread mill) | CAM hole recognition; shop owns the tap-drill choice | Preference P1; used in generation MVP |
| Faces coloured by hole type (tapped, reamed, bored, clearance, drilled, counterbore); optional tolerance-class colouring | Tapped and drilled holes look identical after import | P1 (benchmark), MVP |
| Origin on datum A/B/C (or stock corner / top centre), Z out of the first-operation face, optional stock body | Rotating every imported model | P1 preference, MVP |
| Hole & thread schedule (CSV/PDF), DRO coordinate table, bolt circles | Thread data lost in STEP; manual mills | MVP (Phase 3) |
| Cut-ready DXF (R12, closed loops, true arcs, layers) | Waterjet/laser rejects | MVP (Phase 3) |
| Stock size and weight (bounding envelope + allowance → standard bar/plate; finished and stock weight) | Quoting and material ordering | MVP (Phase 3) |

### C. Drawing understanding
| Feature | Problem it solves | Release |
|---|---|---|
| Intake check: page previews, vector-text vs scan, sharpness and resolution warnings | Bad scans discovered late | P1 |
| Drawing hints: units, projection, revision, material, thread callouts, outside processes (anodize, heat treat, plating…) | Notes buried in the print | P1 (unverified hints); verified extraction MVP |
| Revision mismatch warning (title block vs selected revision) | Working to the wrong revision | P1 |
| Title-block and notes checklist with reviewer sign-off | Missed notes | MVP (Phase 2) |
| Tolerance engine with provenance: explicit, title-block decimal places (inch), ISO 2768-1 classes, ISO 286 fits, basic and reference dimensions, limit dimensions, nX/TYP | Untoleranced dimensions misread | MVP (Phase 2) |
| Thread, fit and surface-finish parsers (ASME B1.1, ISO 965, NPT; Ra) | Callout decoding | MVP (Phase 2) |
| Projection-method gate: confirm first/third angle before any 3D build | Mirror-image parts | MVP (Phase 2) |
| Edition-aware rules (Y14.5-2018 vs -2009; ISO 8015 independency) | Inspection planning | Later |
| Scanned and legacy prints (fractions, hand lettering) with explicit uncertainty | Old faxes and TIFFs | Clean scans MVP; hand-drawn later |

### D. Quality and inspection outputs
| Feature | Problem it solves | Release |
|---|---|---|
| Ballooned PDF (one balloon = one characteristic; notes ballooned; basic dimensions not; sheet/zone from the border grid) | Manual ballooning | MVP (Phase 4) |
| AS9102 Rev C Form 3 draft + Form 1 header pre-fill; CSV/XLSX; per-customer ballooning profile | 8–12 h FAI setup | MVP (Phase 4) |
| Shop-floor packet: printed ballooned print, hole chart and QR link to the released revision viewer | Paper on the floor, tablets get oily | MVP (Phase 4) |
| PPAP dimensional results, QIF 3.0 export / CMM results import, AP242 semantic PMI (validated subset) | Automotive and CMM workflows | Later (Phase 8) |

### E. Compliance and data handling
| Feature | Problem it solves | Release |
|---|---|---|
| Export-control marking detection at intake; owner review (confirm / clear with reason, audited) | ITAR/EAR/CUI handling | P1 |
| Controlled until cleared: external AI only after an owner records clearance, and only if workspace and project allow it | Unmarked ≠ uncontrolled | P1 |
| Local-only by default; no telemetry; AI endpoint allow-list (GovCloud / Azure Government class endpoints for CUI if ever enabled); every outbound call logged | Self-hosting claims must be true | P1 policy; allow-list MVP |
| Append-only audit trail with CSV export; role-separated approve/verify | AS9100/ISO 9001 records | Audit P1; e-signatures MVP |
| US-person attribute and controlled-document access lists | Deemed exports | MVP (Phase 2) |
| SSO/MFA via the shop's identity provider (OIDC/SAML), admin MFA | NIST 800-171 alignment | Admin MFA before broad access; SSO later |
| NIST SP 800-171 responsibility matrix and FIPS-mode guide | Shop's security plan | Later |
| Configurable retention; deletion removes files (backups expire on their own schedule) | Customer IP and NDAs | P1 (project delete), retention MVP |

### F. Shop workflow and integrations
| Feature | Problem it solves | Release |
|---|---|---|
| Customers, projects (PO/RFQ), parts, revisions; repeat-part search | "Have we made this before?" | P1 |
| Revision compare: diff prints and specs, list changed characteristics for a partial FAI | Unclouded revision changes | Later (Phase 5) |
| Check a customer-supplied STEP against the print | Model/print conflicts | Later (Phase 5) |
| Watch folder, batch jobs, saved templates, usage dashboard | Volume | Later (Phase 8) |
| Integrations: Paperless Parts API, ERP (ProShop, Fulcrum, JobBOSS²/E2, Global Shop) via CSV/watch folder first | Double entry | Later (Phase 8) |

---

## 4. Phases and exit gates

Planning allowances are estimates for a constrained part scope, not delivery promises; re-estimate after Phase 0 and again after the pilot.

### Phase 0 — Prove the geometry path (3–5 days; partly automated)
- **Automated (delivered in Phase 1):** FeatureSpec v1 schema; three reference parts (plate with counterbored, tapped, reamed and bored holes; L-bracket with step, inside fillet, pocket, slot and blind tapped holes; stepped shaft with grooves, chamfers, cross hole and tapped centre hole); nominal and mid-tolerance variants; independent checks (closed-form volume, extents, per-hole diameter/position/depth, STEP reopen and units).
- **Human:** select 20–30 customer-authorised drawings (10+ untouched for acceptance); have a machinist record reference dimensions and manual reconstruction time; **import the benchmark STEP files into the shop's actual Fusion and Mastercam versions** and confirm units, size, hole colours and hole recognition; inventory VM and CAD versions; confirm automation licensing.
- **Exit gate:** three checked STEP models import correctly in the named CAD versions; at least one incomplete drawing is correctly blocked; geometry epsilon per family is recorded.

### Phase 1 — Foundation, access and intake (1–2 weeks) — **built in this repository**
- Repository, Compose stack (proxy, api, postgres, redis, extract-worker, cad-worker, scheduler), migrations, CI, production configuration.
- Email-code sign-in (six digits, ten-minute expiry, three attempts, sixty-second resend, per-address and per-IP limits, enumeration-neutral), invitation-gated signup, workspaces, roles (owner, engineer, reviewer, viewer; several per person), session list and revocation, immediate logout.
- Customers, projects (PO/RFQ reference), parts, revisions (customer letter + internal sequence), repeat-part search.
- Private storage (content-type sniffing, size and page limits, SHA-256, read-only originals), authenticated downloads (nginx X-Accel), append-only audit log with CSV export.
- Durable jobs: idempotency keys, leases and heartbeats, fenced completion, reconciler, bounded retries, cancellation, explicit unsupported state.
- **New:** intake check (previews, vector-text detection, sharpness and resolution warnings, export-control markings, drawing hints, revision-mismatch warning); controlled-until-cleared policy with owner review; shop modelling preferences; geometry benchmark in an isolated CAD worker (no database, no outbound network, read-only filesystem); system health, alerts and admin user controls; encrypted backup and isolated restore drill.
- **Exit gate:** two test shops cannot access each other's files or jobs (automated, every endpoint); login expiry and replay checks pass (automated); restarting the stack preserves uploads and job history; a backup restores into an isolated environment and verifies every file hash.

### Phase 2 — Drawing understanding and clarification (2–3 weeks)
- PDF/image preparation, local OCR and a replaceable vision-model adapter with per-workspace provider allow-list; no external call unless the revision is cleared.
- Extract source-linked dimensions, tolerances, notes, title block, materials, threads, finishes and view relationships into FeatureSpec v2.
- Tolerance engine with provenance; thread/fit/finish parsers; projection-method gate; units and dual-dimension detection.
- Review screen: source overlay, editable dimension table, title-block and notes checklist with sign-off, clarification queue with drafted customer questions; detected / inferred / confirmed states.
- US-person attribute and access lists for controlled drawings; per-job AI cost limit.
- **Exit gate:** critical missing or contradictory values stay unresolved until a person answers; every critical dimension traces to a source region, a recorded rule or an answer; projection and units are confirmed before modelling.

### Phase 3 — CAM-ready solid generation and check report (3–4 weeks)
- Allowlisted feature interpreter for plates, blocks, brackets and turned parts (extends the Phase 1 engine): countersinks, patterns, bolt circles, more fillet/chamfer cases.
- Nominal and mid-tolerance STEP; shop tapped-hole representation; hole-type colours; datum origin; optional stock body.
- Check report (HTML/PDF/JSON) callout by callout; hole and thread schedule; DRO coordinate table; cut-ready DXF; stock size and weight.
- Side-by-side drawing/model viewer with section cuts; measurements from the B-rep, never the mesh; parameter edits create a new revision and invalidate approvals.
- **Exit gate:** supported reference parts pass independent dimension checks and target-CAD import; a plausible but incomplete model cannot pass; changing a parameter rebuilds and invalidates prior approval.

### Phase 4 — Inspection outputs and shop pilot (MVP complete; 2–3 weeks)
- Reviewer approval with role separation; released downloads; job-ready email; usage tracking; actionable failure messages.
- Ballooned PDF; AS9102 Form 3 draft and Form 1 header; CSV/XLSX; per-customer ballooning profile; shop-floor packet with QR link.
- Run the untouched drawing set and a live pilot; measure end-to-end time including corrections and review.
- Failure drills: worker crash, duplicate jobs, timeouts, malformed uploads, expired sessions, cross-shop access, full restore.
- **Exit gate:** release measurements in Section 7.

### Phase 5 — Revision compare and customer-model check (2–3 weeks)
- Diff old and new prints and specs; flag unclouded changes; list changed characteristics for a partial FAI and for program edits; regenerate outputs for the new revision.
- Check a customer-supplied STEP against the print and report conflicts.
- **Exit gate:** on a set of real revision pairs, every changed critical dimension is reported, and no unchanged characteristic is reported as changed.

### Phase 6 — Native Fusion designs (2–4 weeks; was Phase 5)
Unchanged from v1: desktop add-in first, Automation API as an option; validate a real editable timeline. Exit gate: ten representative native files reopen, expose parameters, regenerate after an allowed edit and agree with the approved geometry.

### Phase 7 — AutoCAD and Mastercam adapters (3–6 weeks; was Phase 6)
Unchanged from v1, plus: Mastercam adapter maps hole colours/types to levels and carries the hole table. Initial MCAM files contain geometry only.

### Phase 8 — Shop automation and integrations (selected features; was Phase 7)
Watch folder with quarantine; batch jobs; saved templates; usage dashboard; Paperless Parts and ERP connectors; QIF 3.0 export and CMM results import; AP242 semantic PMI for a validated subset (checked with NIST's STEP File Analyzer); local vision model after a hardware and accuracy benchmark; setup-sheet drafts; OMAX DXF hand-off.

**Effort.** MVP (Phases 0–4): roughly 10–14 focused engineering weeks with regular machinist review (v1 said 8–12; the inspection outputs add about two weeks). Phases 5–8: 9–16 weeks, dominated by licensing, vendor APIs and workstation testing.

---

## 5. Architecture (changes from v1)

The v1 stack stands: React/TypeScript/Vite, Django + DRF, django-allauth headless (email codes), PostgreSQL as the record of truth, Celery + Redis for scheduling only, CadQuery/Open CASCADE geometry, Three.js preview, nginx in front.

- **Isolation of geometry.** The CAD worker has no database credentials and sits on an internal Docker network with no outbound route; it runs as a non-root user on a read-only filesystem with a tmpfs scratch area and only the staging directory mounted. It returns file hashes; the API verifies and publishes atomically.
- **Extraction worker** (same image as the API) runs intake now and OCR/vision in Phase 2; it is the only service that will ever be given an outbound route to an allow-listed AI endpoint.
- **Ingress.** nginx listens on host port 9999 and is reached through a Cloudflare Tunnel at `https://3d.8westit.com`. Client IPs come from `CF-Connecting-IP`; TLS terminates at Cloudflare. Django admin uses the same email-code session (no admin passwords); protect `/admin/` additionally with a Cloudflare Access policy.
- **Storage.** Originals, artifacts, outbox, database and backups live under one host directory (default `/opt/blueprint-cad/data`), so backup and restore are simple and visible.
- **Email.** Any authenticated SMTP relay. Until one is configured, messages go to a private outbox readable only from the server (`bpcad outbox`).

## 6. FeatureSpec

FeatureSpec v1 (in `packages/feature-spec`) is live for the benchmark: units, datums, a dimension table with signed deviations and tolerance source, and an allowlist of features (block, turned profile, step, hole with counterbore/thread, cross hole, pocket, slot, chamfer, end chamfer, edge fillet, groove). Any value may reference a dimension, which resolves at nominal or mid-tolerance.

v2 additions for Phase 2–3: source regions (page, bounding box, raw text) per dimension and note; dimension types (basic, reference, limit, nX/TYP instance counts, characteristic designators); thread class and tolerance class; surface finish; GD&T frames as text with datum references; edition of the governing standard; per-feature model-variant override; countersinks, patterns and bolt circles; uncertainty and question records.

## 7. Release measurements (Phase 4 gate)

| Measure | Gate or target |
|---|---|
| Critical geometry | Every released critical dimension matches the approved specification; no unresolved geometry-affecting questions |
| Check-report coverage | 100% of ballooned characteristics on pilot parts are either verified on the solid, marked "not modeled" with a reason, or answered by a person |
| Known bad inputs | Every deliberately incomplete, conflicting, unsupported or wrong-projection case stops or routes to review |
| Target import | Every accepted export opens with correct units, body count, dimensions and hole colours in the named CAD versions |
| Export control | Every marked acceptance drawing is detected; no external AI call occurs for an uncleared revision (verified from the outbound-call log) |
| Time saved | At least 50% lower median total preparation time on supported pilot parts, including review |
| Operating behaviour | Access tests and restore drill pass; duplicate delivery never releases two conflicting results |

These are release goals, not accuracy claims. Publish the supported scope and sample size with the pilot results.

## 8. Positioning guardrails

We will **not** claim the software is "ITAR compliant" or "CMMC certified" (organisations are assessed, not tools); call a deployment "self-hosted" while it sends controlled drawings to a commercial AI API; publish accuracy percentages without a test method; call the output an "AS9102-compliant FAI" (we draft the characteristic list; measurement and customer acceptance complete the FAI); or pitch the product as replacing programmers or inspectors. Customer drawings are never used for training and are retained only as configured.

## 9. Compliance notes (not legal advice)

- Under ITAR and EAR, release of technical data to a foreign person is an export, and the encryption carve-outs (22 CFR 120.54(a)(5), 15 CFR 734.18(a)(5)) cover transmission and storage only; an AI API must decrypt a drawing to read it. Treat any AI processing of controlled drawings as requiring US-only, US-person-access infrastructure or an authorisation, and have export counsel confirm.
- DFARS 252.204-7012 requires NIST SP 800-171 and FedRAMP Moderate-equivalent security for external cloud services handling covered defense information.
- CMMC status is in flux: the phase-in of third-party Level 2 assessments was scheduled for November 10, 2026, but our research found a July 2026 suspension of Phase 2 pending a reform review. Verify the current status before making commitments to defense customers.
- ISO 9001:2026 was published in September 2026 and AS9100's successor (IA9100) is expected soon; keep clause numbers out of the data model.

## 10. Deployment for the pilot

- One Linux VM, Docker Engine + Compose v2. Minimum 4 vCPU / 16 GB / 150 GB SSD (one geometry job at a time); preferred 8 vCPU / 32 GB / 250 GB.
- `infra/install.sh` installs or updates the stack under `/opt/blueprint-cad`, generates secrets, creates the first owner, installs nightly encrypted backups and runs a restore drill.
- The proxy listens on **port 9999**. In the Cloudflare Tunnel, map public hostname `3d.8westit.com` to `http://localhost:9999` (or `http://<vm-ip>:9999` if `cloudflared` runs elsewhere). Users browse to **`https://3d.8westit.com`**; Cloudflare does not proxy port 9999 publicly, so `:9999` is the origin port, not part of the public URL.
- Backups: encrypted with a passphrase stored separately; copy them off the VM (a VM snapshot or a second directory on the same disk is not a recovery copy). Pilot goals: ≤ 1 hour of committed work lost, service restored within 8 hours.

## 11. Decisions to close

| Decision | Working assumption |
|---|---|
| Pilot scope | One shop, three part families |
| Mail delivery | Authenticated relay (Microsoft 365, Google Workspace, SES, Postmark) with a verified sending domain; test Outlook and Gmail |
| Default model variant | Nominal by default with mid-tolerance also exported; confirm with the pilot programmer |
| Tapped-hole default | Tap drill (cut tap); confirm with the pilot programmer |
| Model provider (Phase 2) | Local OCR first; choose a vision model by accuracy, data terms, latency and measured cost on approved drawings; GovCloud-class endpoint only for cleared, controlled work |
| Native Fusion path | Desktop add-in first |
| Brand and address | `3d.8westit.com` for the pilot |

## 12. Sources

Primary sources from Version 1 remain valid (Autodesk Fusion and AutoCAD automation, Mastercam SDK and translators, CadQuery, django-allauth). Version 2 research sources are listed in [`docs/research/machinist-needs.md`](research/machinist-needs.md).
