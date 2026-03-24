# Rhino Re-ID — Business Logic

> Purpose: define the product-level decision rules for authentication, prediction, review, gallery curation, and operational states.

---

## 1. Product actors

- **Standard user (`user`)**: runs prediction and submits correction/report signals.
- **Administrator (`admin`)**: validates drafts, manages lists/identities, and resolves uncertain or junk data.

Role checks are enforced server-side; UI visibility is convenience only.

---

## 2. Core domain objects

- **RhinoList**: container/group for identities.
- **RhinoIdentity**: one individual rhino.
- **RhinoImage**: image rows that can be draft/confirmed and may include description parts.
- **PredictionRecord**: audit record of a predict run (`top5`, selected identity, report status, corrected identity).

---

## 3. Primary journeys

### 3.1 Predict (Re-ID)

1. User uploads one or more query images.
2. System runs Re-ID and returns ranked candidates (`top-k`) and finalized identity when available.
3. System persists prediction metadata for audit/history.
4. User can accept, correct, or report the outcome.

### 3.2 Rhino list curation (admin)

1. Admin reviews draft/unconfirmed images.
2. Admin can assign to existing identity, create new identity, confirm quality, or mark junk.
3. Admin actions are persisted and reflected in gallery/history.

---

## 4. Business decision rules

### 4.1 Visibility and permissions

- **Predict** is available to authenticated users.
- **Rhino list** and identity-management operations are admin-only.
- Non-admin users must not be able to execute admin mutations even if they discover endpoint URLs.

### 4.2 Single-image ingestion outcomes

When a single uploaded image enters the system:

- **Case A: Predict returns a candidate identity**
  - Image is attached to that identity in **`draft`** status.
  - Admin later validates: keep identity, move to another identity, create new identity, or mark as junk.

- **Case B: Prediction is reported as wrong**
  - Image enters **admin review queue** (recommended status: `pending_review`).
  - Admin resolves by assigning correct identity, creating new identity, or junk.
  - Do not use ambiguous buckets such as `undefined`.

- **Case C: Predict finds no valid rhino match**
  - Image is classified as **`junk`**.

- **Case D: Description/LLM indicates non-rhino or invalid image**
  - Image is classified as **`junk`**.

### 4.3 Recommended status model

Use explicit states (or equivalent booleans with the same meaning):

- `draft`: candidate identity exists but not admin-validated.
- `pending_review`: reported/uncertain and requires admin decision.
- `confirmed`: validated and accepted into curated gallery.
- `junk`: invalid, non-rhino, or unusable data.

### 4.4 Auditability requirements

For each status transition, keep:

- actor (`user_id`),
- timestamp,
- reason (`report_wrong_id`, `no_match`, `llm_non_rhino`, `admin_mark_junk`, etc.),
- previous and new state.

This supports governance and model-quality review.

---

## 5. Quality and safety rules

- No silent failures: user receives clear error when Re-ID/LLM/config is unavailable.
- Default credentials and secrets must be rotated before production.
- Prediction abuse controls apply to standard users; admins can be exempt by policy.
- All user-facing copy and API `detail` messages remain English-only.

---

## 6. Operational policies

- Treat `junk` as recoverable by admin review only if product policy allows.
- Keep reported cases queryable in prediction history for audits.
- Prefer deterministic storage states over folder-name conventions.

---

## 7. Alignment references

- Requirements: `_bmad-output/planning-artifacts/prd.md`
- Architecture: `_bmad-output/planning-artifacts/architecture.md`
- Routes/FE-BE map: `docs/FRONTEND_UX_AND_BACKEND_LOGIC.md`
- Production hardening: `docs/PRODUCTION_CHECKLIST.md`

