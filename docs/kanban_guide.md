# SPA Kanban Board — Guide

**URL (after GitHub Pages is enabled):**
`https://yurii-spa.github.io/SPA/kanban.html`

---

## Overview

The SPA Kanban board is a live project tracking system consisting of two files that work together:

- `KANBAN.json` — the canonical source of truth: all work items, their status, metadata, and history
- `kanban.html` — a read-only dashboard that fetches and renders `KANBAN.json` in the browser

The board has **6 columns** representing the full lifecycle of every work item.

---

## Column Definitions

| Column | Color | What belongs here |
|--------|-------|-------------------|
| **In Progress** | 🟠 Orange (pulsing) | Tasks actively being worked on right now |
| **Review** | 🟡 Yellow | Work completed locally, pending push to GitHub or peer review |
| **Backlog** | ⚫ Gray | Planned tasks not yet started; includes user action items |
| **Features** | 🔵 Blue | Large epics and phase-level features (multi-sprint scope) |
| **Ideas** | 🟣 Purple | Unvalidated ideas to discuss before committing |
| **Done** | 🟢 Green | Completed and merged/deployed work |

---

## How to Update the Board

### Option 1 — Edit KANBAN.json directly

Open `KANBAN.json` and edit the relevant column array. Each card follows this schema:

```json
{
  "id": "SPA-044",
  "title": "Short descriptive title",
  "description": "What was done or what needs to be done.",
  "priority": "HIGH",
  "estimate": "3h",
  "tags": ["backend", "frontend", "infra", "testing", "docs"],
  "sprint": "v1.7",
  "added": "2026-05-22"
}
```

To move a card between columns, cut the object from one array and paste it into the target column array. Update `last_updated` and `updated_by` at the top of the file.

### Option 2 — Ask the Architect Agent

Type `/architect` in the SPA dashboard chat. The Architect agent (implemented in `spa_core/dev_agents/architect.py`) reads `KANBAN.json`, analyses the current project state against the DEV_STRATEGY roadmap, and proposes card moves and new items. Review the diff before saving.

---

## Tags and Priority

Tags drive badge colors on cards:

| Tag | Color | Use for |
|-----|-------|---------|
| `backend` | Blue | Python modules, APIs, data pipeline |
| `frontend` | Teal | HTML, CSS, JS, dashboard changes |
| `infra` | Red | CI/CD, GitHub Actions, server config |
| `testing` | Amber | pytest suites, fixtures, E2E tests |
| `docs` | Gray | Markdown docs, ADRs, guides |

Priority levels: `HIGH` (🔴), `MEDIUM` (🟡), `LOW` (⚪).

---

## Searching

The search bar in the dashboard header filters cards across all columns in real time by title or tag name. The column badges update to show how many cards are visible in each column during a search.

---

## Keeping the Board Current

After each sprint, move completed items from **In Progress** → **Done** and update `last_updated`. When files are ready to push but not yet on GitHub, move them to **Review**. Once pushed, move to **Done**.

The Architect agent is designed to automate this process in future sprints.
