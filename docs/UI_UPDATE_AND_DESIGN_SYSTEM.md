# UI update and design system (implementation guide)

> **Audience:** architects, frontend developers, and AI assistants planning a **visual refresh** without breaking behavior.  
> **Companion docs:** [FRONTEND_UX_AND_BACKEND_LOGIC.md](FRONTEND_UX_AND_BACKEND_LOGIC.md) (behavior), [LANGUAGE_POLICY.md](LANGUAGE_POLICY.md) (English-only), [DOCUMENTATION.md](DOCUMENTATION.md) (index).

---

## 1. Purpose

This document is the **single planning reference** for:

- Establishing a **coherent visual language** (colors, type, spacing, components).
- **Scoping** UI work in phases so Gallery-heavy flows stay usable.
- Keeping **API contracts and routing** stable unless a feature explicitly requires change.

It does **not** replace the PRD; it operationalizes **NFR-2** (English UI) and **UX growth** items from planning artifacts when they concern presentation.

---

## 2. Hard constraints

| Constraint | Rule |
|------------|------|
| **Language** | All user-visible strings remain **English**. See [LANGUAGE_POLICY.md](LANGUAGE_POLICY.md). No Vietnamese or other languages in `frontend/`, `docs/`, or API `detail` messages. |
| **Behavior first** | Re-ID batch flow, gallery modes, auth, and admin gates **must not regress**. Style changes should not remove loading states, error feedback, or keyboard paths without replacement. |
| **API stability** | A UI refresh **does not** change REST shapes unless coordinated with `backend/` and `api.ts`. |
| **Assets** | Prefer **system or licensed** fonts and icons; document font URLs and licenses if adding webfonts. |

---

## 3. Current frontend architecture

| Area | Implementation |
|------|----------------|
| **Build** | Vite 7, React 19, TypeScript |
| **Routing** | `react-router-dom` — see [FRONTEND_UX_AND_BACKEND_LOGIC.md](FRONTEND_UX_AND_BACKEND_LOGIC.md) (section 3) |
| **HTTP** | Axios wrapper in `frontend/src/api.ts` |
| **Global styles** | **`frontend/src/index.css`** — large flat CSS (layout, gallery, login, dashboard, cropper-related rules). This is the **primary** styling surface today. |
| **Entry** | `frontend/src/main.tsx` imports `./index.css` only (not `App.css`). |
| **Design libraries** | **None** in `package.json` (no Tailwind, MUI, Chakra). Visual work is **hand-rolled CSS + class names** in TSX. |

**Implication:** A “beautiful UI” project should either (a) **introduce design tokens + refactored CSS** in place, or (b) **add a CSS framework** and migrate incrementally. Section 9 compares options.

---

## 4. UI surface inventory

Use this checklist when estimating work and avoiding orphan styles.

| Priority | File | Role |
|----------|------|------|
| P0 (shell) | `pages/Layout.tsx` | Header, nav, `Outlet` — affects every authenticated route. |
| P0 | `pages/Login.tsx` | First impression; form layout. |
| P0 | `pages/Gallery.tsx` | Largest surface: Re-ID vs list mode, batch UI, history, modals. |
| P1 | `pages/RhinoImageDetail.tsx` | Capture detail, part rows, LLM actions. |
| P1 | `pages/Dashboard.tsx` | Hub cards and links. |
| P1 | `pages/Lists.tsx` | List CRUD and migration. |
| P1 | `pages/Predict.tsx` | Single-image predict path. |
| P2 | `components/ImageCropper.tsx` | Crop UX; keep touch targets usable. |
| — | `App.tsx` | Routes only; minimal markup. |
| — | `contexts/AuthContext.tsx` | Logic only; no visual requirement beyond patterns used by consumers. |

**CSS:** Most classes are defined in `index.css`. Search for `.gallery-`, `.image-card`, `.header`, `.login-`, `.dashboard` when refactoring.

---

## 5. Design direction (product)

Before writing CSS, capture **decisions** (even as a short subsection in the PRD or a ticket):

1. **Primary persona** — Operator (speed, density) vs occasional admin (clarity, guidance).
2. **Density** — Default spacing for Gallery lists and cards (compact vs comfortable).
3. **Brand** — Neutral tooling vs branded (logo, accent color, dark mode intent).
4. **Motion** — Level of animation; respect `prefers-reduced-motion`.

These drive token choices and whether to invest in **dark mode** in v1 of the refresh.

---

## 6. Design tokens (recommended baseline)

Define **CSS custom properties** on `:root` (and optionally `[data-theme="dark"]` later). Example **structure** (values are placeholders — replace as a team):

```css
:root {
  /* Color */
  --color-bg: #ffffff;
  --color-bg-muted: #f6f8fa;
  --color-surface: #ffffff;
  --color-border: #d0d7de;
  --color-text: #1a1a1a;
  --color-text-muted: #57606a;
  --color-accent: #0969da;
  --color-accent-hover: #0550ae;
  --color-danger: #cf222e;
  --color-success: #1a7f37;

  /* Typography */
  --font-sans: system-ui, -apple-system, sans-serif;
  --font-display: var(--font-sans);
  --text-base: 1rem;
  --text-sm: 0.875rem;
  --leading-tight: 1.25;
  --leading-normal: 1.5;

  /* Spacing & layout */
  --space-1: 0.25rem;
  --space-2: 0.5rem;
  --space-3: 0.75rem;
  --space-4: 1rem;
  --space-6: 1.5rem;
  --space-8: 2rem;
  --radius-sm: 6px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --shadow-sm: 0 1px 3px rgba(0, 0, 0, 0.06);

  /* Focus ring (accessibility) */
  --focus-ring: 2px solid var(--color-accent);
  --focus-offset: 2px;
}
```

**Migration rule:** Replace hard-coded hex/rgb in `index.css` with `var(--token)` **incrementally** by section (e.g. shell first, then login, then gallery).

---

## 7. Component patterns

Standardize these **once** and reuse:

| Pattern | Notes |
|---------|--------|
| **Primary button** | High contrast; used for main actions (Predict, Save, Confirm). |
| **Secondary button** | Neutral border; Cancel, secondary actions. |
| **Destructive** | Distinct from primary; delete, irreversible actions. |
| **Form fields** | Label + input alignment; consistent error text below field (`.error` exists). |
| **Cards** | Image cards, dashboard cards — shared radius, border, hover. |
| **Navigation** | Active route clearly indicated (`.header nav a.active` today). |
| **Modals / overlays** | Z-index stacking; focus trap if adding a dialog library later. |

Avoid duplicating one-off shadows and border colors; bind them to tokens.

---

## 8. Typography and `index.html`

- Set `<html lang="en">` (already set).
- **Title:** Replace generic `frontend` in `frontend/index.html` with the product name in English (e.g. “Rhino Re-ID”).
- **Fonts:** If loading Google Fonts or similar, add `<link>` in `index.html` and map `--font-sans` / `--font-display` in `:root`. Verify **font-display: swap** and fallbacks for slow networks.

---

## 9. Technical options (stack)

| Approach | Pros | Cons |
|----------|------|------|
| **A. Tokens + refactor `index.css`** | No new deps; full control; matches current codebase. | Manual discipline; larger CSS file. |
| **B. Tailwind CSS** | Utility speed; design system via config theme. | Build setup; learning curve; migration effort. |
| **C. Component library (e.g. MUI, Radix + styling)** | Accessible primitives; fast dashboards. | Bundle size; theming alignment; may fight existing markup. |

**Pragmatic recommendation:** Start with **(A)** through tokens and shared classes; re-evaluate **(B)** if velocity stalls on layout-heavy screens.

---

## 10. Phased rollout (suggested)

| Phase | Scope | Exit criteria |
|-------|--------|----------------|
| **0** | Document decisions (this file + tokens table agreed). | Tokens in `:root`; 1–2 reference screens approved visually. |
| **1** | Shell + Login + Dashboard | Header, nav, login card, dashboard cards use tokens; focus visible. |
| **2** | Gallery list + cards + drop zone | Grid, badges, filters readable; no layout breakage on narrow viewports. |
| **3** | Modals and multi-step crop/describe flows | Step indicators clear; buttons consistent. |
| **4** | RhinoImageDetail, Lists, Predict, ImageCropper | Remaining pages; cropper remains usable on small screens. |
| **5** | Polish | Empty states, skeletons if desired; optional dark mode behind `data-theme`. |

---

## 11. Accessibility (non-negotiable)

- **Contrast:** WCAG AA for body text on backgrounds; test primary buttons and links.
- **Focus:** Visible `:focus-visible` outline using `--focus-ring`; do not `outline: none` without replacement.
- **Motion:** Respect `prefers-reduced-motion` for large transitions.
- **Semantics:** Prefer semantic HTML (`button` vs `div` for actions); keep form labels associated with inputs when refactoring.

---

## 12. Testing and verification

| Check | How |
|-------|-----|
| **Lint** | `npm run lint` in `frontend/` |
| **Build** | `npm run build` |
| **Smoke** | Login, `/`, `/lists`, `/dashboard`, one predict path, capture detail — manual or scripted E2E later |
| **Responsive** | Narrow viewport for Gallery and cropper |
| **English** | Grep for non-ASCII user strings in `frontend/src` (should be empty for UI copy) |

---

## 13. Alignment with planning artifacts

- **PRD NFR-2:** UI strings English — unchanged by styling.
- **Architecture:** Frontend remains static SPA; no requirement to change deployment for CSS-only updates.
- **Epics:** A major UI program may warrant a **new epic or story** in `_bmad-output/` for tracking; keep `sprint-status.yaml` in sync if your process requires it.

---

## 14. Related files (quick reference)

| Path | Purpose |
|------|---------|
| `frontend/src/index.css` | Global styles |
| `frontend/index.html` | Document title, future font links |
| `frontend/src/App.tsx` | Route table |
| `_bmad-output/planning-artifacts/prd.md` | Product requirements |
| `_bmad-output/planning-artifacts/architecture.md` | Technical context |

---

_Document version: 1.0 — prepared as the full reference for UI update work. Revise tokens and phases when brand or scope changes._
