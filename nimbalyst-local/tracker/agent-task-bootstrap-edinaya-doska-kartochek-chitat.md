---
trackerStatus:
  type: agent-task
title: "Bootstrap: единая доска карточек + читать историю решений при старте"
status: done
source: session-2026-07-16
created: 2026-07-16
---

Owner-директива (при 98% контекста): по умолчанию читать историю решений + все карточки в ОДНОМ месте,
чтобы новое окно не было «новым сотрудником».

## Сделано 2026-07-16
- `scripts/build_tracker_board.py` → `nimbalyst-local/tracker/_BOARD.md`: обзор всех 56 карточек по
  типу+статусу, вверху «🔴 ЖДЁТ ВЛАДЕЛЬЦА». Авто-регенерится на мутациях (orchestrator_queue create/
  set-status/ingest-notes) + по требованию.
- Указатели на `_BOARD.md` в CLAUDE.md §1 и memory `session-bootstrap-read-first`.
- Ядро уже было: CLAUDE.md §1 (SYSTEM_MAP + trackers + OWNER_BACKLOG + agent-arch docs + STATE +
  decisions/INDEX) + memory `session-bootstrap-read-first` / `decide-dont-ask-continue`.
Всё на origin.
