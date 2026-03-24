---
stepsCompleted:
  - step-01-validate-prerequisites
  - step-02-design-epics
  - step-03-create-stories
  - step-04-final-validation
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
  - docs/DOCUMENTATION.md
workflowType: epics-and-stories
project_name: rhino_app
user_name: Roy
status: complete
completedAt: '2026-03-23'
---

# rhino_app — Epic Breakdown

## Overview

This document decomposes the PRD and architecture into epics and user stories for **rhino_app** (Rhino Re-ID). The product is **brownfield**: many capabilities already exist; stories are written so **verification/regression** stories can be run first, and **growth** stories capture PRD gaps.

**Inputs:** `prd.md`, `architecture.md`, `docs/DOCUMENTATION.md`.

---

## Requirements Inventory

### Functional Requirements (from PRD)

| ID | Summary |
|----|---------|
| FR-1 | Sign-in; inactive users blocked from protected actions |
| FR-2 | Single or set Re-ID; ranked matches or clear failure |
| FR-3 | Per-part LLM description when LLM configured |
| FR-4 | Confirm prediction; optional add query images to gallery |
| FR-5 | Report wrong prediction with correct identity |
| FR-6 | Prediction history with top-5 and reported flag |
| FR-7 | Browse identities/images with supported filters |
| FR-8 | Upload gallery images; four-part description; confirm image |
| FR-9 | Admin-only identity/list operations enforced |
| FR-10 | Admins exempt from standard-user predict rate limit |
| FR-11 | Persist prediction records (path, scores, top-5 JSON) |
| FR-12 | Machine-readable API documentation (OpenAPI) |

### Non-Functional Requirements (from PRD)

| ID | Summary |
|----|---------|
| NFR-1 | API error `detail` strings in English |
| NFR-2 | UI strings English per language policy |
| NFR-3 | Secrets not committed; rotate defaults before production |
| NFR-4 | Predict abuse resistance (rate limit for non-admin) |
| NFR-5 | Bounded-time Re-ID (subprocess timeout) |
| NFR-6 | Async DB access; growth: optional load targets |

### Additional / UX Requirements

- **UX design artifact:** None in repo. **PRD Growth:** admin-focused filters, unify orphan routes (`Predict.tsx`, `Lists.tsx`, `Dashboard.tsx`).
- **Architecture:** Re-ID subprocess temp file race (`project-context.md`); optional tests.

### FR Coverage Map

| FR / NFR | Epic(s) |
|----------|---------|
| FR-1, FR-9, FR-10 | E1 |
| FR-7, FR-8, SC-3 | E2 |
| FR-2, FR-3, FR-11, NFR-5 | E3 |
| FR-4, FR-5, FR-6 | E4 |
| FR-12, NFR-1, NFR-2 | E5 |
| NFR-3, NFR-4, NFR-6 | E1, E3, E6 |
| Growth (admin queue, orphans, tests) | E6 |

---

## Epic List

| ID | Title | Goal |
|----|-------|------|
| **E1** | Authentication & authorization | Secure access, admin boundaries, predict rate policy |
| **E2** | Gallery & identity management | Curate reference images and identities |
| **E3** | Re-ID inference & descriptions | Run retrieval and optional LLM part text |
| **E4** | Prediction feedback & history | Confirm, report, audit predictions |
| **E5** | API contract & language compliance | Integrators and English-only policy |
| **E6** | Growth & hardening | PRD Growth items, tech debt, tests |

---

## Epic 1: Authentication & authorization

**Goal:** Users authenticate with JWT; admins perform gated actions; non-admins are rate-limited on predict per architecture ADR-5 and ADR-6.

### Story 1.1: User login and protected session

As an **operator**,  
I want to **log in and access protected pages**,  
So that **only authenticated users use the gallery and Re-ID**.

**Acceptance Criteria:**

**Given** a registered active user  
**When** they submit valid credentials  
**Then** they receive a token and can call protected APIs  
**And** invalid credentials are rejected without revealing which field failed (existing behavior).

**Given** an inactive user  
**When** they present a token  
**Then** protected actions are denied.

**Maps to:** FR-1 · **Verify** `Login.tsx`, `AuthContext`, `/auth/login`.

---

### Story 1.2: Admin-only gallery operations

As an **administrator**,  
I want **identity and list operations that change the reference gallery to be restricted to my role**,  
So that **standard users cannot corrupt the gallery**.

**Acceptance Criteria:**

**Given** a signed-in user with role `user`  
**When** they call an admin-only gallery/list endpoint  
**Then** the API returns forbidden  
**Given** a signed-in `admin`  
**When** they perform the same operation  
**Then** the operation succeeds when valid.

**Maps to:** FR-9 · **Verify** routes using `require_admin` per `architecture.md`.

---

### Story 1.3: Predict rate limit for standard users only

As a **product owner**,  
I want **predict endpoints throttled for standard users but not admins**,  
So that **abuse is limited without blocking operators with admin duties**.

**Acceptance Criteria:**

**Given** a non-admin user  
**When** they exceed the configured hourly predict budget  
**Then** further predict calls are rejected until the window resets  
**Given** an admin user  
**When** they invoke predict repeatedly  
**Then** they are not subject to the same throttle.

**Maps to:** FR-10, NFR-4 · **Verify** `check_predict_rate_limit` in `auth.py`.

---

## Epic 2: Gallery & identity management

**Goal:** Maintain lists, identities, and images with confirmation and deactivation (PRD SC-3).

### Story 2.1: Browse identities and filtered images

As an **operator**,  
I want to **browse rhino lists, identities, and images with filters the product supports**,  
So that **I can find captures to review or describe**.

**Acceptance Criteria:**

**Given** an authenticated user  
**When** they open the gallery / list views  
**Then** identities and images load from the API  
**And** confirmation filters apply as documented (e.g. confirmed vs unconfirmed where implemented).

**Maps to:** FR-7 · **Verify** `Gallery.tsx` + `GET /gallery/identities`, `GET /gallery/images`.

---

### Story 2.2: Upload gallery image with description and confirmation

As a **steward**,  
I want to **upload images to an identity with optional four-part descriptions and mark images confirmed**,  
So that **the reference gallery stays curated**.

**Acceptance Criteria:**

**Given** a valid image and identity  
**When** the user uploads with optional description data  
**Then** the image row persists with paths and JSON fields  
**When** the user confirms or deactivates an image  
**Then** state persists after reload.

**Maps to:** FR-8, SC-3 · **Verify** gallery upload and `PATCH` confirm/deactivate flows.

---

## Epic 3: Re-ID inference & descriptions

**Goal:** Run single/set Re-ID against on-disk gallery; optional per-part LLM description; persist structured prediction (FR-2, FR-3, FR-11).

### Story 3.1: Set-based Re-ID with explicit failure modes

As an **operator**,  
I want to **run Re-ID on a set of query images**,  
So that **I get a ranked identity or a clear error if weights or gallery are misconfigured**.

**Acceptance Criteria:**

**Given** gallery and weights configured per `docs/DOCUMENTATION.md`  
**When** the user runs set predict from the Re-ID UI  
**Then** the response includes top matches or finalized identity summary  
**Given** missing weight or gallery layout  
**When** the user runs predict  
**Then** the response contains a structured error (no empty success).

**Maps to:** FR-2, SC-1 · **Verify** `upload-set` + `Gallery.tsx` predict flow.

---

### Story 3.2: Per-part LLM description on predict path

As an **operator**,  
I want to **generate four-part text for a query image when the deployment has an LLM key**,  
So that **Re-ID can use part-aligned prompts when available**.

**Acceptance Criteria:**

**Given** `OPENAI_API_KEY` configured  
**When** the user runs describe-file / per-part flow from predict  
**Then** four-part text and schema payload return  
**Given** no key  
**Then** the API returns a controlled failure (503 or equivalent).

**Maps to:** FR-3 · **Verify** `POST /predict/describe-file` and describe service.

---

### Story 3.3: Persist prediction record with top-5 payload

As a **system**,  
I want to **store query path, scores, and serialized top-5 for each prediction run**,  
So that **history and auditing remain consistent**.

**Acceptance Criteria:**

**Given** a successful predict  
**When** the response returns to the client  
**Then** a `PredictionRecord` exists with `top5_json` and links as designed  
**Given** a follow-up read  
**Then** fields are stable for history UI.

**Maps to:** FR-11 · **Verify** `_persist_reid_prediction` and DB row.

---

## Epic 4: Prediction feedback & history

**Goal:** Confirm into gallery, report errors, inspect history (FR-4–FR-6, SC-2, SC-5).

### Story 4.1: Confirm prediction into gallery

As an **operator**,  
I want to **confirm a prediction and optionally add query images under the chosen identity**,  
So that **good matches enrich the gallery**.

**Acceptance Criteria:**

**Given** a stored prediction  
**When** the user confirms with a target identity  
**Then** the prediction record updates and optional gallery rows exist for added images.

**Maps to:** FR-4 · **Verify** predict confirm endpoint and UI.

---

### Story 4.2: Report wrong prediction with correct identity

As an **operator**,  
I want to **report an incorrect top prediction and record the correct identity**,  
So that **admins can track quality issues**.

**Acceptance Criteria:**

**Given** a stored prediction  
**When** the user submits a report with correct identity  
**Then** the record shows reported state and corrected identity  
**And** history reflects the update.

**Maps to:** FR-5, SC-2 · **Verify** `POST /predict/report` and UI modal.

---

### Story 4.3: Prediction history for audit

As an **operator or admin**,  
I want to **list recent predictions with top-5 detail and a reported flag**,  
So that **I can review past runs**.

**Acceptance Criteria:**

**Given** existing prediction rows  
**When** the user opens prediction history  
**Then** each row includes reported status and enough detail for audit  
**When** optional `confirmed` filter is used  
**Then** results respect the filter.

**Maps to:** FR-6, SC-5 · **Verify** `GET /predict/history`.

---

## Epic 5: API contract & language compliance

**Goal:** OpenAPI for integrators; English-only API and UI (FR-12, NFR-1, NFR-2).

### Story 5.1: OpenAPI documentation available

As an **integrator**,  
I want **interactive HTTP documentation when the backend runs**,  
So that **I can integrate without reading source first**.

**Acceptance Criteria:**

**Given** the API process is running  
**When** a client opens `/docs`  
**Then** OpenAPI lists auth, gallery, predict, and crop routes.

**Maps to:** FR-12 · **Verify** FastAPI `/docs`.

---

### Story 5.2: English-only API and UI surfaces

As a **maintainer**,  
I want **API `detail` messages and user-visible UI strings in English**,  
So that **the repo meets `LANGUAGE_POLICY.md`**.

**Acceptance Criteria:**

**Given** a sample of error paths and main pages  
**When** reviewed or linted per team practice  
**Then** no non-English user-facing strings are introduced in `rhino_app/`.

**Maps to:** NFR-1, NFR-2 · **Ongoing / verify** — spot-check + future CI rule if added.

---

## Epic 6: Growth & hardening

**Goal:** PRD Growth items, architecture risks, and release hygiene (NFR-3, NFR-6 growth, technical debt).

### Story 6.1: Admin visibility for reported predictions

As an **administrator**,  
I want **to filter or view reported predictions distinctly**,  
So that **I can manage quality without scanning full history**.

**Acceptance Criteria:**

**Given** reported and non-reported predictions exist  
**When** the admin uses the new filter or view (API and/or UI per implementation)  
**Then** only reported rows appear when filtered  
**Maps to:** PRD Growth · **Implement** — extend `GET /predict/history` query params and/or admin UI.

---

### Story 6.2: Unify or remove orphan frontend routes

As a **maintainer**,  
I want **`Predict`, `Lists`, and `Dashboard` either routed or removed**,  
So that **users and agents do not follow dead code paths**.

**Acceptance Criteria:**

**Given** the current `App.tsx` route table  
**When** the change ships  
**Then** every shipped page is reachable from nav or documented test URL  
**And** unused files are deleted or wired.

**Maps to:** PRD Growth · **Implement**.

---

### Story 6.3: Safe subprocess Re-ID output file

As a **maintainer**,  
I want **subprocess Re-ID to write results to a unique temp file per request**,  
So that **concurrent predictions cannot overwrite each other’s output**.

**Acceptance Criteria:**

**Given** two concurrent predict calls using subprocess fallback  
**When** both complete  
**Then** each receives its own result payload without cross-talk.

**Maps to:** `architecture.md` / `project-context.md` · **Implement** in `predict.py` / subprocess caller.

---

### Story 6.4: Automated API smoke tests

As a **maintainer**,  
I want **automated tests for auth, predict persist, report, and gallery confirm**,  
So that **regressions are caught in CI**.

**Acceptance Criteria:**

**Given** a CI job running against a test DB  
**When** the test suite runs  
**Then** core flows above execute with pass/fail  
**Maps to:** PRD Growth · **Implement** — choose pytest + httpx/ASGI test client.

---

### Story 6.5: Production secrets checklist

As a **deployer**,  
I want **a short checklist to rotate default admin password and `SECRET_KEY`**,  
So that **SC-6 is satisfied before go-live**.

**Acceptance Criteria:**

**Given** a release candidate  
**When** the checklist is applied  
**Then** no default `admin/admin` or dev `SECRET_KEY` remains in production config.

**Maps to:** NFR-3, SC-6 · **Document / verify** — may live in `README` or ops doc only.

---

## Epic 7: Single-upload triage and admin review queue

**Goal:** Ensure every single-image predict upload is persisted for admin review, remove ambiguous `undefined` bucket behavior, and enforce explicit lifecycle states (`draft`, `pending_review`, `junk`, `confirmed`).

### Story 7.1: Persist single-upload source image with explicit review status

As an **operator**,  
I want **every single upload to be stored regardless of prediction outcome**,  
So that **admins can triage edge cases later**.

**Acceptance Criteria:**

**Given** a single-image predict upload  
**When** prediction returns a candidate identity  
**Then** source image is created under that identity with review status `draft`.

**Given** a single-image predict upload  
**When** prediction has no match or fails  
**Then** source image is still stored with status `junk` and reason (`no_match` or `predict_error`).

### Story 7.2: Reporting routes images to pending review

As an **operator**,  
I want **reported wrong predictions to enter a clear pending-review state**,  
So that **admin correction is deterministic**.

**Acceptance Criteria:**

**Given** a prediction is reported wrong  
**When** report is submitted  
**Then** related source image and prediction move to `pending_review` with reason `report_wrong_id`.

**And** no records use ambiguous `undefined` buckets.

### Story 7.3: Admin review actions

As an **admin**,  
I want **review actions for queued items**,  
So that **I can assign or discard uncertain data**.

**Acceptance Criteria:**

- Admin can assign to existing identity → status `confirmed`.
- Admin can create new identity and assign → status `confirmed`.
- Admin can mark item as junk → status `junk`.
- Review queue endpoint supports filtering by `draft`, `pending_review`, `junk`.

### Story 7.4: Non-rhino handling and audit log

As a **steward**,  
I want **non-rhino/invalid outcomes and transitions to be auditable**,  
So that **quality governance is measurable**.

**Acceptance Criteria:**

- Predict no-match/failure maps to junk with reason.
- LLM non-rhino classification maps to junk with reason `llm_non_rhino` (when surfaced by describe flow).
- Transition log stores actor, action, from_status, to_status, note, timestamp.

---

## Final validation notes

- **Dependency order suggested:** E1 → E2 → E3 → E4 (natural user flow); E5 parallel; E6 anytime after baseline verification.
- **Brownfield:** Stories 1.1–5.2 are primarily **verification** unless regressions found; E6 items are **new implementation**.
- **Next BMad step:** `bmad-bmm-check-implementation-readiness` then `bmad-bmm-sprint-planning`.
