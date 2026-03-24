# Language policy — Rhino App (`rhino_app/`)

**Mandatory for this repository subtree:** all **source code**, **comments**, **user-facing strings**, **commit messages in app-owned files**, and **documentation** under `rhino_app/` MUST be written in **English only**.

## Scope

| Area | Rule |
|------|------|
| Python (`backend/app/`, scripts) | English identifiers, docstrings, logs, API `detail` messages |
| TypeScript/React (`frontend/src/`) | English UI copy, labels, placeholders, errors |
| Markdown in `rhino_app/` | English (`README.md`, `LOCALHOST.md`, `docs/*.md`) |
| `.env.example` comments | English |

## Do **not**

- Add Vietnamese, or other non-English UI or docs in `rhino_app/` (avoids mixed-language maintenance and wrong LLM output).
- Create parallel `*_VI.md` or locale-specific docs here; use English technical docs only.

## For AI assistants and codegen

Before editing or generating content for `rhino_app/`:

1. Read this file: **`docs/LANGUAGE_POLICY.md`**.
2. Output **only English** for code, comments, and documentation in this tree.
3. If the user asks in another language, **translate requirements into English** in the artifact you produce (code strings, docs), unless they explicitly request an exception *outside* `rhino_app/` (not recommended).

## Rationale

Single language keeps the app, API errors, and docs consistent for international collaborators and prevents assistants from reintroducing non-English strings by habit.
