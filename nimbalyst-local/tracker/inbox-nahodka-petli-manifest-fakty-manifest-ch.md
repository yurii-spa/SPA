---
trackerStatus:
  type: inbox
title: "Находка петли: манифест ↔ факты: manifest --check вернул дрейф (см. build_architectur"
status: done
source: nimbalyst
created: 2026-08-15
finding_key: "B5:drift:manifest --check вернул дрейф (см. build_architecture_manifest.py)"
claimed_by: cycle-264-pid80387
claimed_at: 2026-08-16T18:49:54Z
---

Находка петли ADR-066 (architecture_conformance, WARN, подтверждена 2 прогонами подряд):

манифест ↔ факты: manifest --check вернул дрейф (см. build_architecture_manifest.py)

Сделано = находка исчезает из отчёта источника при следующем прогоне (мост закроет карточку сам).

_finding_key: `B5:drift:manifest --check вернул дрейф (см. build_architecture_manifest.py)` · ADR-066_

---

## Исполнено — цикл #264 (2026-08-16, worktree от `origin/main` a04e175ef)

**Закрыта ФОРМА находки, а не причина дрейфа — это разные утверждения, и ниже сказано, где
живёт причина.**

### Что оказалось не так с самой находкой

Текст находки — это всё, что о ней знает читатель: он и в отчёте, и в заголовке карточки, и в
Телеграме. Здесь он не содержал ни агента, ни поля, ни направления, зато советовал повторить
замер флагом `--check`, **которого у скрипта нет вовсе**:

```
$ python3 scripts/build_architecture_manifest.py --check
build_architecture_manifest.py: error: unrecognized arguments: --check
```

Диагноз при этом был в руках: `_manifest_drift_problems()` звал `gen.main([])`, брал от него
ОДИН код возврата, а три готовые строки `DRIFT:` уходили в чужой stdout и пропадали. Замер 16.08
в проде — ровно три:

```
DRIFT: com.spa.site_freshness: plist_source 'repo:launchd/com.spa.site_freshness.plist' → None
DRIFT: com.spa.site_freshness: schedule 'interval:21600s' → None
DRIFT: com.spa.site_freshness: program 'agent_site_freshness.sh' → None
```

### Как теперь

| | было | стало |
|---|---|---|
| текст | `manifest --check вернул дрейф (см. build_architecture_manifest.py)` | `com.spa.site_freshness: plist_source 'repo:launchd/…' → None; schedule 'interval:21600s' → None; program 'agent_site_freshness.sh' → None` |
| ключ находки | константа на все случаи жизни | `B5:drift:com.spa.site_freshness` — личность агента |
| карточек на одну причину | 1 бессодержательная | 1 содержательная (три поля одного агента НЕ дробятся) |

- `scripts/build_architecture_manifest.py` — замер вынесен наружу: `measure()` / `compute_drift()`
  (без stdout, без записи, без `sys.exit`). Пусто ⇔ CLI без флагов вернул бы 0 — один источник
  вердикта для человека и для сторожа. Вывод CLI сверен байт-в-байт со старой версией на общем
  `REPO_ROOT` и настоящем дрейфе. В докстринге больше не обещан несуществующий `--check`.
- `spa_core/monitoring/architecture_conformance.py` — `group_drift_by_agent()`; прежняя форма
  (просто строка) поддержана и закреплена обратным контролем.

### Причина дрейфа НЕ тронута и не потеряна

Прод-дерево не получает при автосинке каталог `launchd/` (возятся `spa_core/`·`scripts/`·`tests/`),
поэтому plist `com.spa.site_freshness` есть на origin и отсутствует в проде. Это правило доставки,
менять его самовольно нельзя (`.claude/rules/deployment.md`, п. 6 — прод-дерево только с разрешения
владельца). Причина живёт в карточке
**`inbox-prod-storozh-arhitektury-chitaet-fail-ko`** (тот же класс: сторож читает каталог, который
синхронизация не обновляет), включение самого агента — в
**`owner-decision-vklyuchit-novogo-storozha-saita-na-make`**.

**Почему эта карточка закрывается, хотя дрейф жив:** её `finding_key` описывал старый — пустой —
текст, и после доставки такой находки не станет. На её место встанет находка
`B5:drift:com.spa.site_freshness`, называющая причину прямо в отчёте; мост заведёт по ней карточку
сам, если дрейф переживёт два прогона. Закрытие тихим «решено» здесь исключено: строка выше — это
и есть объяснение.

Приёмка: +13 тестов (8 сторож · 5 генератор), контроль на чистом `origin/main` того же sha —
**12 красных / 1 зелёный**, и единственный зелёный (`test_legacy_string_form_still_supported`) —
объявленный обратный контроль. 4 мутации, каждая красит свою цель. Поузловая сверка
`--collect-only`: удалённых узлов **0**, добавленных ровно 13. Ни один существующий тест не
ослаблен и не изменён (инв. #16).
