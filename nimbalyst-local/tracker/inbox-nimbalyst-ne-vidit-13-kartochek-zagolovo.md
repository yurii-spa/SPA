---
trackerStatus:
  type: inbox
title: Nimbalyst не видит 13 карточек — заголовок с двоеточием без кавычек ломает разбор frontmatter
status: new
source: nimbalyst
created: 2026-09-17
---

## Задание

Nimbalyst не разбирает frontmatter 13 карточек — `YAML parsing error: bad indentation of a mapping
entry`: заголовок с двоеточием записан без кавычек. Такие карточки на доске владельца не видны вовсе.
Замер 17.09 по `~/Library/Application Support/@nimbalyst/electron/logs/main.log` (строки
`Parse errors for nimbalyst-local/tracker/…`), примеры: `agent-analytics-lab.md`, `agent-owner-gate.md`,
`agent-site-numbers.md`. Наш парсер (`owner_queue/queue.py`) ручной и их читает — поэтому расхождение
никто не видел.

Нужно: взять заголовки в кавычки у всех таких карточек и закрыть класс у производителя
(`orchestrator_queue.py create` и прочие писатели frontmatter); сторож — каждый frontmatter трекера
разбирается строгим YAML.

## Приёмка

Пробу объявляет берущая сессия. Исход: строгий разбор frontmatter всех карточек трекера — ноль ошибок;
контроль — карточка с `title: a: b` без кавычек краснит сторожа.
