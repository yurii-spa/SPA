---
trackerStatus:
  type: inbox
title: "Работа двух PR не доехала до main: 50 и 42 дня, среди потерянного — восемь ADR решений владельца"
status: new
source: agent
created: 2026-09-25
priority: high
acceptance_probe: pr_work_arrived_on_main
---

## Что измерено (цикл #699, 2026-09-25, прибор `scripts/pr_delivery_census.py`, ADR-477)

Три открытых PR держат в себе работу, которой на `main` НЕТ ВООБЩЕ. Мерено не глазами:
прибор спрашивает у API список добавляемых файлов и у git — лежат ли эти пути на
`origin/main`.

| PR | открыт | добавляет | нет на `main` |
|---|---|---|---|
| #9 `novel-edge-daily` | **49,6 дн** | 2 | 2 |
| #10 `claude/work-status-check-xfnbew` | **41,6 дн** | 17 | **17** |
| #50 `claude/chat-search-saagql` | 27,9 дн | 2 | 1 → **0, перенесено циклом #699** |

Содержимое PR #50 перенесено на `main` этим же циклом (§6–52 приказа владельца в якорную
карточку + `docs/research/RS-portfolio-cio-audit-2026-08-29.md`), и перепись после пуша
перемерила его: **`arrived`**. Сам PR остаётся открытым черновиком — закрыть его агент физически не может (PAT fine-grained, только `contents`; API отвечает `403` и на комментарий, и на закрытие), это действие владельца: карточка `owner-decision-zakryt-tri-chernovyh-pr-u-moego-klyucha`. Остаются #9 и #10.

## Что именно потеряно

**PR #9** (2 файла): `scripts/edge_tail_portfolio_frontier.py` и его тест
`scripts/tests/test_edge_tail_portfolio_frontier.py` — находка novel-edge #94
(вырожденная концентрация на `points_farm` у обеих целевых функций).

**PR #10** (17 файлов), и это серьёзнее: **восемь ADR**, записывающих решения владельца
от 15–18 августа, —
`ADR-088-portfolio-cio-advisory-layer`, `ADR-089-portfolio-cio-followups-2026-08-15`,
`ADR-090-owner-decisions-2026-08-15-vtoroi-paket`, `ADR-091-panel-fix-code-and-feeds`,
`ADR-092-points-farm-dohodnost-nol`, `ADR-093-owner-decisions-2026-08-17`,
`ADR-094-owner-decisions-2026-08-15`, `ADR-095-owner-decisions-2026-08-18`;
плюс `docs/PORTFOLIO_CIO_DIAGNOSIS.md`, `docs/PORTFOLIO_CIO_PLAN.md`,
`docs/AGGRESSIVE_PANEL_FEEDS.md`, `docs/APY_DIVERGENCE_MEASUREMENT.md`,
`docs/BACKLOG_TRIAGE_2026-08-16.md`, `.github/workflows/perf-budget.yml`,
`landing/src/data/changelog_status.json`, `launchd/com.spa.smoke_flagship.plist`,
`nimbalyst-local/tracker/agent-t2-total-cap-ne-proveryaetsya-na-portfele.md`.

## Почему PR #10 нельзя просто смержить — и почему он сгнил молча

Два препятствия, оба названы замером, а не предположением:

1. **Номера ADR-088 и ADR-089 на `main` УЖЕ ЗАНЯТЫ другими решениями**
   (`ADR-088-autonomy-mandate-not-renewed`, `ADR-089-owner-decisions-batch-2026-08-19`).
   Содержимое обязано лечь под ДРУГИМИ номерами — `python3 scripts/adr_number.py next`.
2. PR несёт ещё и **десятки файлов `data/`** сорокадневной давности. Мёрж как есть
   откатил бы живое состояние — ровно авария 24.08 (`.claude/rules/deployment.md`, п. 4).

Поэтому верный исход — **перенос содержимого дописыванием** (docs/ADR — под новыми
номерами, `data/` НЕ трогать вовсе), а затем закрытие PR. Не мёрж.

## Как понять, что готово (машинный критерий, объявлен ДО работы)

`acceptance_probe: pr_work_arrived_on_main` — проба зелёная, когда ни один открытый PR
старше порога не держит добавляемых путей, отсутствующих на `main`. Критерий выполняется
ДВУМЯ законными путями (содержимое перенесено ЛИБО PR закрыт) намеренно: требуй он
появления ИМЕННО этих путей — карточка стала бы незакрываемой там, где верный исход иной
(см. столкновение номеров выше). Контроль пробы в обе стороны —
`spa_core/tests/test_pr_delivery_probe.py`.

## Почему этого не видел никто 50 дней

Сторож `pr-ci-liveness` (ADR-145) спрашивает «а прогон-то БЫЛ?». По PR #50 он был ЗЕЛЁН и
был ПРАВ: прогонов у head'а три. Нужный вопрос — «а работа-то ДОЕХАЛА?» — не задавал
никто. Зелёный ответ сторожа на СВОЙ вопрос никогда не есть ответ на нужный
(`.claude/rules/deployment.md`, «четыре вопроса — четыре разных сторожа»).
