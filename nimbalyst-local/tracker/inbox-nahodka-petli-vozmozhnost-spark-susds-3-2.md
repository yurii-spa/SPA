---
trackerStatus:
  type: inbox
title: "Находка петли: возможность spark_susds 3.8367% (evidence L4) доступна книге, не держи"
status: done
source: nimbalyst
created: 2026-08-27
finding_key: "gap:opportunity_unnamed:spark_susds"
claimed_by: pid14899
claimed_at: 2026-08-27T10:42:11Z
status_trail:
  - "2026-08-27T10:42:11.813292+00:00 new -> done · queue.set_status · cycle-14899"
---

Находка петли ADR-066 (house_view_gap, WARN, подтверждена 2 прогонами подряд):

возможность spark_susds 3.8367% (evidence L4) доступна книге, не держится и отказ НЕ назван — безымянный простой (дух ADR-055) [постура 0.0 ч назад · книга 0.1 ч назад]

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `gap:opportunity_unnamed:spark_susds` · ADR-066_

---

**Разобрано циклом #394 (2026-08-27). Находка оказалась ЛОЖНОЙ — и это измерено, а не заявлено.**

Отказ по `spark_susds` был НАЗВАН, просто не в том регистре, куда смотрела сверка.
Замер по живому `data/allocation_rationale.json` (цикл 27.08):
`cash.policy_refusals` → `{"protocol": "spark_susds", "reason": "tvl_unverified_policy_gate",
"usd_removed_from_target": 37894.74}`. А `house_view_gap` спрашивал «назван ли отказ?» только у
ДВУХ регистров — `below_median_cap` и `decision_shadow.warnings` — и третьего, который пишет тот
же цикл в тот же файл, не читал вовсе.

Тот же класс, ради которого сторожей и разделяют: честный ответ на свой вопрос, прочитанный как
ответ на нужный. Цена не гипотетическая — WARN дошёл до моста и стал карточкой владельцу.

Сделано: `spa_core/monitoring/house_view_gap.py` читает третий регистр; ключ находки НЕ тронут
(`gap:opportunity_explained:<proto>`, INFO), а в текст теперь входит САМА причина и снятая с цели
сумма, чтобы читатель не ходил в файл. Проверка после: та же возможность выдаётся
`INFO gap:opportunity_explained:spark_susds — отказ НАЗВАН в rationale: tvl_unverified_policy_gate,
снято с цели $37 895`; WARN по протоколу больше нет, значит мост карточку не заведёт.

Тесты: `spa_core/tests/test_house_view_gap_reads_policy_refusals.py` (+14), контроли в ОБЕ стороны —
молчащий rationale, отказ про соседний протокол и запись БЕЗ причины по-прежнему дают WARN
«безымянный простой». На непочиненном модуле 5 из 14 краснеют.

**Настоящий простой капитала этим НЕ закрыт и молчанием не объявлен:** в том же цикле
`cash.unexplained_deployable` = 5 % ($5 000, forgone ≈ 25.4 bps/год), и причина названа самим
аллокатором — «$18 947 цели снято после аллокатора по `fluid_fusdc:tvl_unverified_policy_gate`,
освобождённый бюджет никто не перезаполнил». Это money-path и он уже ведётся отдельно:
`inbox-svesti-dve-realizatsii-perezapolneniya-b`, `inbox-prostoi-kapitala-snova-ne-obyasnen-10-pr`.
Второй карточки об этом не завожу (ADR-084).
