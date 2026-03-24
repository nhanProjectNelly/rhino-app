---
stepsCompleted:
  - step-01-init
  - step-02-discovery
  - step-03-success
  - step-04-journeys
  - step-05-domain
  - step-06-innovation
  - step-07-project-type
  - step-08-scoping
  - step-09-functional
  - step-10-nonfunctional
  - step-11-polish
  - step-12-complete
inputDocuments:
  - docs/DOCUMENTATION.md
  - docs/LANGUAGE_POLICY.md
  - _bmad-output/project-context.md
workflowType: prd
productOrDomain: Rhino Re-ID
classification:
  domain: wildlife-conservation-research-tooling
  projectType: web-application-with-ml-inference
lastEdited: '2026-03-23'
editSource: prd-validation-report.md (bmad-edit-prd)
---

# Product Requirements Document — rhino_app (Rhino Re-ID)

**Author:** Roy  
**Date:** 2026-03-23  
**Status:** Draft — revised after PRD validation (behavior-first requirements)  
**BMad module:** BMM (planning artifact → UX / Architecture / Epics)

---

## Executive Summary

**Vision:** Deliver a web application that **re-identifies individual rhinos** from new field photos against a **reference gallery**, supports **structured visual descriptions** (body, head, ears), and keeps a **human-in-the-loop** path so operators can **confirm, correct, or report** model outputs—giving **admins** the data they need to **govern the gallery** and **review prediction quality**.

**Differentiator:** End-to-end loop from **query upload → embedding Re-ID (IndivAID-style checkpoint) → top-k results → optional LLM part descriptions → user confirmation or “wrong prediction” report** with persisted history—not a one-shot demo script.

**Primary users:** Field or lab **operators** (run Re-ID, review uploads) and **administrators** (manage identities/lists, seed gallery, oversee reported outcomes). Secondary: ML engineers syncing checkpoints and datasets.

**Constraints (brownfield):** FastAPI + async SQLAlchemy + React (Vite); English-only UI and docs per `docs/LANGUAGE_POLICY.md`. ML stack depends on external IndivAID checkout, weights, and optional OpenAI for descriptions.

---

## Success Criteria (SMART)

| ID | Criterion | Measure |
|----|-----------|---------|
| SC-1 | Operators complete a **set-based Re-ID run** and see **top-5** plus **finalized identity** when the model and gallery are configured | **Pass/fail:** Follow the setup steps in `docs/DOCUMENTATION.md` (DB, weights, gallery layout). In one session after login, user runs set Re-ID and receives a non-empty top-ranked list and finalized identity **or** a clear error explaining misconfiguration (no response without explanation). |
| SC-2 | Users can **record a wrong prediction** with a **correct identity** | After submit, the system stores **reported** state and **corrected identity** on the prediction record; user can see the update in prediction history. |
| SC-3 | Gallery stewards can **mark images confirmed** or **deactivate** them | Confirmation/deactivation persists; reloading the gallery view shows the updated state. |
| SC-4 | **Admins** can create or update identities/lists where the product enforces admin-only actions | A signed-in **non-admin** receives **forbidden** when invoking an admin-only action; **admin** succeeds. |
| SC-5 | **Prediction history** is inspectable and shows whether a row was **reported** | History list includes a per-row **reported** indicator (and related correction fields as designed). |
| SC-6 | No production deployment with default **admin/admin** or default **SECRET_KEY** | Release checklist blocks go-live until credentials rotated |

---

## Product Scope

### MVP (current product intent — largely implemented)

- JWT auth; roles `admin` | `user`.
- **Re-ID home:** build image set → optional per-image describe → **upload-set** prediction → display top-k, per-image breakdown, weak-match demo folder when scores fall below threshold.
- **Prediction history** with query URL, top-5 payload, confirmed/report flags.
- **Report:** user submits correct identity for a stored prediction.
- **Gallery / lists:** browse identities and images; upload with optional four-part description; capture detail with part crops and description versions (per `DOCUMENTATION.md`).
- **Crop assist:** server bbox suggestions (YOLO) for UI cropping flows.
- **Rate limit:** non-admin predict calls capped per hour; admin exempt (`auth.py`).

### Growth (near-term)

- **Admin-focused views:** filter history by `reported=true`, date range, or user; optional export for audit.
- **Unify or remove orphan pages** (`Predict.tsx`, `Lists.tsx`, `Dashboard.tsx` not in `App.tsx`) so all flows route from one navigation model.
- **Automated tests** for critical API paths (predict persist, report, gallery confirm).

### Vision (longer-term)

- Multi-tenant or project-scoped galleries; stronger audit log; batch ingestion from camera traps; evaluation metrics dashboard (rank-k, mAP) against held-out queries.

---

## User Journeys

### Journey A — Operator runs Re-ID on a new capture set

1. Log in → **Re-ID** tab (`/`).
2. Upload one or more images; use crop/describe popup as needed.
3. **Predict** runs **set** inference once; UI shows finalized ID, scores, gallery thumbnails.
4. Operator **confirms** into gallery, picks another identity, or **reports** wrong ID with correct identity.
5. Operator reviews **prediction history** for recent runs.

**Implementation map (brownfield):** primary UI `Gallery.tsx`; predict flows `upload-set`, `describe-file`, `confirm`, `report`, `history` (see Appendix A).

### Journey B — Admin maintains reference gallery

1. Admin logs in; uses **Rhino list** (`/lists`) and gallery APIs.
2. Creates lists/identities (admin-gated where applicable); uploads images; marks **confirmed** when quality is approved.
3. Runs or scripts **sync** from ATRW/split (`sync_reid_test_data.py`, migrations per docs).

**Implementation map (brownfield):** lists + gallery routers; admin-gated routes as implemented.

### Journey C — Reviewer audits a bad prediction

1. User **reports** a prediction with correct identity.
2. Admin opens **prediction history** (same endpoint today; growth: filter reported only).
3. Admin corrects gallery or identity records as needed; optional process outside app (spreadsheet, issue tracker).

**Implementation map (brownfield):** prediction record fields **reported**, **corrected_identity_id**; operational follow-up outside app optional.

---

## Domain Requirements

**Domain:** Wildlife conservation / research tooling—not regulated healthcare or fintech. **No HIPAA/PCI** by default.

**Data handling:** Images may be sensitive (location, rare species); PRD assumes **deployer** controls access (network, credentials, backups). Future: explicit **audit log** and **PII/geo** policy if images gain metadata.

**Accessibility:** Not yet specified; Growth: WCAG 2.1 AA for operator UI if publicly funded.

---

## Innovation Analysis

- **Prompt-injected ViT Re-ID** with optional **textual part descriptions** aligns gallery and query when both have four-part text; **visual-only** mode when text missing (`REID_INFER_VISUAL_ONLY`).
- **Set-based query** with aggregation (finalize) reduces single-frame noise for field photography.

---

## Project-Type Requirements (Web app + ML service)

- **Browser client** talks to API via **`/api` proxy** in dev; production must serve same-origin or CORS as configured.
- **Large artifacts:** checkpoints and `uploads/` on disk; backup and disk quota are operational NFRs.
- **Optional GPU** for in-process Torch; subprocess fallback to IndivAID script if `ai_core` unavailable.

---

## Functional Requirements

Requirements state **what** the product must do. **Acceptance / verification** is user-observable or record-level unless noted. Brownfield API/module mapping is **Appendix A** (informative).

| ID | Requirement | Acceptance / verification |
|----|-------------|---------------------------|
| FR-1 | Users can **sign in**; inactive accounts cannot use protected features | Invalid credentials rejected; inactive user cannot complete protected actions |
| FR-2 | Users can run **single** or **set** Re-ID on uploaded query images against the configured gallery | Response includes ranked matches **or** a clear, structured failure (e.g. missing weights/gallery) — not silent failure |
| FR-3 | Users can request **per-part LLM description** of an uploaded image when the deployment provides LLM credentials | Returns four-part text + schema payload when configured; otherwise controlled failure |
| FR-4 | Users can **confirm** a prediction and optionally **add query images** to the gallery under a chosen identity | Prediction record and gallery rows reflect confirmation and optional new images |
| FR-5 | Users can **report** a wrong prediction and supply **correct identity** | Stored record shows **reported** and **corrected identity** |
| FR-6 | Users can **list prediction history** including top-5 payload and **reported** flag | History entries expose reported status and match detail needed for audit |
| FR-7 | Users can **browse identities and images**, with filters where the product supports them | Lists respect filters (e.g. confirmation state) as documented |
| FR-8 | Users can **upload gallery images** with optional four-part description and **confirm** an image | Image state and descriptions persist as intended |
| FR-9 | **Admins** can perform **identity/list operations** reserved for administrators | Non-admin cannot complete admin-only actions |
| FR-10 | **Admins** are **not subject** to the same predict **rate limit** as standard users | Observed behavior: admin predict path not throttled like standard user |
| FR-11 | System **persists prediction records** with query path, scores, and serialized top-5 | Record retrievable after creation with consistent fields |
| FR-12 | System exposes **machine-readable API documentation** for integrators | Interactive API docs available when backend is running |

**Stakeholder alignment (this PRD):** “Predict rhino,” “manage images,” “admin and users verify uploads,” “see prediction results,” “report on Re-ID so admins can support management” → covered by FR-2–FR-10 and journeys A–C.

**Gaps for Growth (not FR-complete today):** Dedicated **admin-only queue UI** for reported items only; **per-user** history scoping; **bulk export** of reports—capture as follow-up epics.

---

## Non-Functional Requirements

| ID | Requirement | Measure |
|----|-------------|---------|
| NFR-1 | API errors return **English** `detail` strings | Manual/API review |
| NFR-2 | UI strings remain **English** per language policy | Lint/review `frontend/src` |
| NFR-3 | Secrets not committed: `.env` excluded; `SECRET_KEY` and default passwords changed before production | Release checklist |
| NFR-4 | Predict endpoint resists abuse for non-admin users | Rate limit enforced for standard users (see config) |
| NFR-5 | Re-ID invocation completes or fails within bounded time | Subprocess path uses bounded timeout; monitor logs |
| NFR-6 | Data access uses **async** patterns suitable for concurrent web traffic | **MVP:** no formal load-test SLA; implementation uses async DB sessions for router operations. **Growth:** define target RPS/concurrency when load testing is introduced |

---

## Traceability Matrix (summary)

| Stakeholder ask | FRs |
|-----------------|-----|
| Re-ID prediction | FR-2, FR-11 |
| Image / gallery management | FR-7, FR-8 |
| Admin vs user responsibilities | FR-9, FR-10 |
| View prediction outcomes | FR-6 |
| Report wrong prediction | FR-5 |
| Verify / confirm uploads | FR-8, SC-3 |

---

## Out of Scope (this PRD version)

- Mobile native apps.
- Real-time collaboration on the same capture.
- Automatic species detection (only individual re-ID within rhino gallery).
- Legal compliance packaging (export control, CITES) unless provided by deployer.

---

## References

- `docs/DOCUMENTATION.md` — setup, API summary, frontend behavior.
- `docs/CHECKPOINTS_AND_DESCRIPTION_PARTS.md` — four-part JSON.
- `_bmad-output/project-context.md` — agent implementation rules.
- `_bmad-output/planning-artifacts/prd-validation-report.md` — last validation run.

---

## Appendix A — Brownfield verification hooks (informative)

_Useful for developers and testers; not normative for product behavior._

| FR / area | Typical surface (current build) |
|-----------|----------------------------------|
| FR-1 | Auth router: login, token, `/auth/me` |
| FR-2 | Predict: single upload, set upload |
| FR-3 | Predict describe-file; gallery describe endpoints |
| FR-4 | Predict confirm |
| FR-5 | Predict report |
| FR-6 | Predict history |
| FR-7–FR-8 | Gallery router: identities, images, description patches |
| FR-9 | Routes using `require_admin` |
| FR-10 | `check_predict_rate_limit` vs admin role |
| FR-11 | `PredictionRecord` persistence |
| FR-12 | FastAPI `/docs` OpenAPI |

---

## Next BMad Steps

1. **`bmad-bmm-create-architecture`** — technical decisions and diagrams.  
2. **`bmad-bmm-create-epics-and-stories`** — decompose FRs into implementable stories.  
3. **`bmad-bmm-check-implementation-readiness`** — alignment gate before sprint planning.  
4. Optional: **`bmad-bmm-validate-prd`** re-run after major edits.
