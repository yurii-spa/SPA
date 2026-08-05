# Первоисточники SPA — founding docs (май 2026)

Архив самой первой документации проекта, в которой была прописана исходная идея
«как всё должно работать». Перенесено в репо 2026-08-05 из внешних папок
(`~/Downloads/spa_v03/` и `~/Project CPA/spa_v045_final/`), где документы жили
вне git и вне бэкап-контура. Содержимое не редактировалось — только перенос.

## Состав

| Папка | Что это | Дата оригинала |
|---|---|---|
| `00_Admin/` | 4 PDF с исходным замыслом (ai_base_architecture, design_foundation, docs_architecture, roadmap_milestones) — старейшие артефакты идеи. В обоих сетах файлы байт-в-байт идентичны, хранятся один раз | 2026-05-02 |
| `v0.3_2026-05-01/01_Docs/` | 16 документов v0.3 DRAFT: 00_Context (идейное ядро), Risk_Policy, Mode_Policy, Whitelist_Policy, Operations_Runbook, Incident_Response, Monitoring_and_Alerts, Data_and_Signals, Agent_Architecture, Execution_Cost_Model, Accounting_and_PnL, Reporting_Weekly, Paper_Trading_Plan, Strategy_Passport ×2, Docs_Index | 2026-05-01 |
| `v0.4.5_2026-05-02/01_Docs/` | Тот же сет в финальной редакции линии v0.x + `Paper_Trading_Week0_Baseline_2026-05-02.md` (первая неделя paper-трека) | 2026-05-02 |
| `v0.4.5_2026-05-02/06_ADR/` | Девять самых первых ADR (ADR-2026-001…009), включая adopt_spa_documentation_v0_3, whitelist_tier1_protocols, launch_paper_trading | 2026-05 |

Журнал ревью v0.2→v0.3 — рядом: `archive/CHANGELOG_v0.3.md` (и `CHANGELOG_v0.4_v0.4.5.md`).

## Зачем хранить

Идейное ядро из `00_Context` дожило до прода почти дословно: «сохранность капитала
важнее доходности», «отсутствие действий допустимо и часто предпочтительно»,
«правила выше возможностей», AI Agent «не владеет капиталом и не принимает
финальных решений» — сегодняшние refusal-first / fail-CLOSED / детерминированный
RiskPolicy-гейт растут отсюда. Расхождения тоже видны и осознанны: исходный
критерий успеха maxDD ≤ 2% заменён двухступенчатым kill-switch −5%/−10%
(ADR-034/048).

Эти документы — историческая справка, **не действующие правила**. Действующее —
`CLAUDE.md`, `.claude/rules/`, `docs/decisions/`.
