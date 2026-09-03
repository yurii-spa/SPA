---
trackerStatus:
  type: owner-decision
title: "Критичная находка петли: com.spa.weekly_backup: intent=active, но НЕ загружен во флоте"
status: needs-owner
source: nimbalyst
created: 2026-09-02
finding_key: "B1:dead:com.spa.weekly_backup"
owner_choice: ack
owner_answered_at: 2026-09-03T10:10:47.176119+00:00
owner_answer_via: telegram
owner_answered_by: 258651137
---

## Что случилось и почему это важно
Сторож петли (architecture_conformance) нашёл КРИТИЧНОЕ расхождение с архитектурой:
com.spa.weekly_backup: intent=active, но НЕ загружен во флоте

## Что от тебя нужно
Посмотреть находку и решить: чиним / принимаем осознанно (тогда фиксируем решение в манифесте или ADR). Рекомендация агента — чинить: критичные находки этого класса уже стоили нам молчаливых отказов.

## Как понять, что готово
Находка исчезает из data/architecture_conformance.json при следующем прогоне.

## Что будет после
Мост сам закроет эту карточку, когда находка исчезнет; сторож продолжит следить, чтобы она не вернулась.

_finding_key: `B1:dead:com.spa.weekly_backup` · источник: architecture_conformance · ADR-066_

---

## ЗАМЕР цикла #466 (2026-09-03, читать перед ответом — карточку писал мост, замера в ней не было)

Обязательный шаг 0-офис третьи сутки печатает эту находку как `CRITICAL`. Сессия #466 померила
её сама, чтобы вопрос стоял на фактах, а не на строке сторожа:

| вопрос | замер |
|---|---|
| что говорит манифест | `intent: active`; примечание — «развёрнут 2026-08-08 по решению владельца „четыре — ставить“ (`own-31`); гейт `check_agent_before_deploy` пройден, last exit=0» |
| есть ли plist на диске | **да**, `~/Library/LaunchAgents/`, файлы от 2026-08-08 |
| загружен ли во флоте | **нет** — `launchctl list` не знает ни одного из трёх |
| когда работал в последний раз | **2026-08-29 10:02** — `~/Documents/SPA_Backups/SPA_Claude_backup_2026-08-29.tar.gz`, 2.99 ГБ |
| когда сработал бы в следующий раз | суббота **2026-09-05 10:00** (расписание `wd6·10:00`) — **ближайший срок из трёх** |

**Что это меняет для решения.** Расхождение не «архитектурное» — это **уже принятое тобой решение
от 08.08 (`own-31`), которое перестало действовать молча**: файл на месте, гейт когда-то пройден,
агент просто не загружен. Потерянного пока НЕТ (последний запуск прошёл штатно), и первая
настоящая потеря наступает в названный выше срок.

**Чинится одной командой владельца** (агент сам не имеет права — инвариант #12 и
`.claude/rules/deployment.md`, п. 6):

```bash
python3 -m spa_core.monitoring.deployment_acceptance      # ДО
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.spa.weekly_backup.plist
python3 -m spa_core.monitoring.deployment_acceptance      # ПОСЛЕ
```

Второй вариант — если агент больше не нужен: сказать это, и тогда правится **манифест**
(`intent: retired`), а находка исчезает честно, а не замалчивается.

---

## Исполнено (интерактивная сессия, 2026-09-03T13:41Z)

Владелец ответил в чате (не Telegram): «Да, перезагрузить все три сейчас». Выполнено:
```
python3 -m spa_core.monitoring.deployment_acceptance      # ДО  -> OK
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.spa.weekly_backup.plist
python3 -m spa_core.monitoring.deployment_acceptance      # ПОСЛЕ -> OK
```
Все три подтверждены `launchctl list` (0 = не запущен ни разу, ждёт расписания — штатно для только что
загруженного calendar-агента). Находка должна исчезнуть из `data/architecture_conformance.json`
при следующем прогоне сторожа петли.
