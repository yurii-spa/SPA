---
trackerStatus:
  type: inbox
title: Разобрать 52 карточки с ветки work-status-check, потом удалить ветку (решение владельца 20.08, вариант 1)
status: new
source: nimbalyst
created: 2026-08-20
claimed_by: cycle-72588
claimed_at: 2026-08-20T23:44:32Z
---

## Что случилось

Владелец 20.08 в 19:12:45Z выбрал **вариант 1**: сначала разобрать карточки с ветки
`origin/claude/work-status-check-xfnbew`, потом удалить ветку
(`owner-decision-na-vetke-lezhat-52-tvoi-kartochki-a-ne-t`, ADR-100).

Замер цикла #322: на ветке **178 путей, которых на `main` нет ВООБЩЕ** — 8 решений, **52 карточки**
(≈20 из них — вопросы владельцу), 110 файлов кода. Совпадение заголовков с карточками `main`:
**0 из 52** — значит по заголовку дубли не ищутся, сверять надо СОДЕРЖАНИЕМ (прецедент #321:
«возврат после HARD_KILL» на ветке 15.08 и `ADR-097` 20.08 — одно и то же решение под разными
заголовками).

## Что сделать

1. Пройти **52 карточки** ветки, разложив на три кучи, и КАЖДУЮ отнести по содержанию, а не по
   имени файла: (а) живое и на `main` отсутствует ⇒ перенести; (б) повтор того, что на `main` уже
   есть (в любом статусе, включая `done`/`ingested`) ⇒ НЕ переносить, назвать, с чем совпало;
   (в) устарело фактически (дефект починен после 19.08) ⇒ не переносить, назвать починку.
2. Начать с ~20 карточек `own-*` / `owner-decision-*`: это вопросы ВЛАДЕЛЬЦУ, и их потеря стоит
   дороже всего. Перенесённый вопрос НЕ отправлять владельцу автоматически пачкой — сначала
   измерить, жив ли он ещё (ADR-084: штатное и решённое не звонит владельцу).
3. Код и тесты ветки **НЕ переносить** — так записано в карточке владельца: `main` ушёл на 147
   коммитов вперёд, трёхдневный слепок даст конфликты без выгоды. Отдельные находки из кода
   ветки, если они всплывут при разборе карточек, заводить как НОВЫЕ карточки со ссылкой на
   коммит ветки.
4. После разбора — удалить ветку (`scripts/github_delete.py` умеет только файлы; удаление ветки
   через GitHub API `DELETE /repos/{repo}/git/refs/heads/{branch}` с PAT из Keychain) и записать
   в журнал, что именно ушло.
5. Разбор можно вести пачками по 10–15 карточек за цикл (одна безопасная задача за цикл, ADR-088):
   промежуточное состояние держать в теле ЭТОЙ карточки — какие имена уже разобраны.

## Как понять, что готово

Все 52 карточки отнесены к одной из трёх куч и это записано в теле карточки; перенесённые лежат на
`origin/main`; ветки `origin/claude/work-status-check-xfnbew` нет; журнал называет числа
(перенесено / повтор / устарело).

## Чего делать НЕЛЬЗЯ

Ставить `owner-done` перенесённым карточкам (инв. #14) · тащить карточку по заголовку, не сверив
содержание (заголовки дрейфуют, #321) · удалять ветку ДО разбора · переносить код.

## Резерв

`~/SPA_backups/branch_archive/claude-work-status-check-xfnbew-20260820.bundle` (28 МБ, `git bundle
verify` пройден) — полная копия ветки на случай, если после удаления понадобится что-то поднять.

---

## 📦 Ход разбора (промежуточное состояние — обновлять каждым циклом)

**Разобрано: 15 из 52.** Осталось 37 (в т.ч. 18 живых вопросов владельца).
Замер состава: из 52 карточек ветки `own-*`/`owner-decision-*` не ~20, а **33** —
26 `needs-owner`, 6 `ingested`, 1 `blocked`. Начал с них, как велит п.2.

### Батч 1 (цикл #324, 21.08) — 15 карточек

**(а) живое, на `main` не было ⇒ ПЕРЕНЕСЕНО — 9.** У каждой в теле дописан раздел
«🚚 Перенесено на `main` циклом #324» с провенансом, с чем сверялось и почему не дубль:

| карточка | статус | с чем сверялась на `main` |
|---|---|---|
| `own-2026-08-18-avariinaya-kniga-idet-mimo-geitov-svezhesti` | needs-owner | `agent-safe-fallback-bypasses-adapter-gates` — тот же объект, следующий слой |
| `own-2026-08-18-dozapisat-li-knigu-za-12-proshlyh-dnei` | needs-owner | `inbox-knigi-za-proshlyi-den-net-v-arhive-dozap` — там механизм, тут вопрос про прошлое |
| `own-2026-08-18-dva-proizvoditelya-apy-opoznayut-pul-po-raznomu` | needs-owner | D6 в `agent-tuner-constraints-drift-and-feed-divergence` — там следствие, тут причина |
| `own-2026-08-18-prosadka-v-otchete-eto-shov-dvuh-simulyatsii` | needs-owner | `inbox-dve-zapisi-o-dengah-rashodyatsya-kazhdyi` — это её ОТВЕТ, а она ещё `new` |
| `own-2026-08-19-sudba-voronki-chekapa-i-kanal-zayavok` | needs-owner | `agent-checkup-waitlist-fail-open-ok-true`, `inbox-ves-poddomen-checkup-earn-defi-com-otdae` — там части, тут судьба продукта |
| `own-56-avtopochinshchik-ostalsya-bez-vyzyvayushchih` | needs-owner | совпадений НЕТ (искал `auto_fixer`, «автопочин») |
| `own-red-team-nablyudennaya-ugroza-ne-doezzhaet` | blocked | `inbox-red-team-critical-eto-eho-ostanovki-a-ne-nahodka` — она `done` и покрывала лишь половину |
| `owner-decision-avariinaya-ostanovka-teryaetsya-pri-vosst` | needs-owner | `inbox-snyataya-ostanovka-zhivet-v-git-vosstano` — её премису этот замер ОПРОВЕРГАЕТ |
| `owner-decision-dnevnoy-limit-ubytka-schitaet-neizvestn` | needs-owner | `inbox-stroka-risk-gate-dnevnogo-limita-ubytka` — тот же сторож, другой вопрос |

**(б) повтор того, что на `main` уже есть ⇒ НЕ перенесено — 5.** Совпадение названо в каждой; замер
с ветки приложен к карточке `main` разделом «➕ Замер с ветки», иначе он умер бы вместе с веткой:

| карточка ветки | совпала с (на `main`) |
|---|---|
| `own-2026-08-18-potolok-ne-vidit-obshchego-kuratora` | `agent-morpho-curator-concentration` (backlog, 05.08) |
| `own-2026-08-18-tyuner-ne-znaet-o-setevykh-potolkakh` | `agent-allocator-slep-k-limitu-seti` (backlog, 08.08) |
| `own-2026-08-18-zapas-rebalansera-strozhe-politiki` | `agent-tuner-constraints-drift-and-feed-divergence`, п. D5 |
| `own-fluid-gsm-gate-chuzhoy-parametr` | `agent-fluid-timelock-source` (backlog, 05.08) |
| `own-ruchnoy-instrument-poiska-istochnikov` | `inbox-sem-skriptov-vskrytyh-strogim-skanerom-r` (new) — родительская задача про все 7 |

**(в) устарело фактически ⇒ НЕ перенесено — 1.**
`own-tsena-nashego-limita-20-na-odno-imya-izme` — замер уже сделан и его ВЫВОД записан в
`docs/STATE.md` (R&D #46: «лимит 20 % = максимум Calmar ⇒ ADR не нужен»); задача на `main`
(`inbox-zamer-obmena-dohodnost-kontsentratsiya-n`) при этом всё ещё `new`. Её статус я НЕ трогал:
сверить её критерии приёмки с замером #46 — отдельная работа, а закрыть «на глаз» значило бы
объявить сделанным то, что не проверено.

### Что вскрылось по дороге (сверх приёмки карточки)

Три карточки ветки говорят «я это починил», и **ни одна из починок на `main` не доставлена** —
код ветки не переносится по решению владельца, значит вместе с веткой уйдёт и он. Проверено
поимённо на `main` (`8aa6df1ec`), а не со слов карточек:

1. **Дозапись книги в архив исходов.** `spa_core/monitoring/outcomes_archive.py` (строки 96–102)
   по-прежнему берёт книгу из `data/current_positions.json`. Механизм НЕ починен.
2. **Списание `telegram_watcher`.** И `spa_core/monitoring/telegram_watcher.py`, и
   `spa_core/devtools/auto_fixer.py` (26 КБ) на `main` на месте. Петля не закрыта вовсе.
3. **Сведение порогов тюнера к RiskPolicy** (D5). На `main` не доставлено.

Это НЕ повод переносить код (запрет владельца в силе), но и молчать об этом нельзя: после удаления
ветки три готовых решения придётся находить заново. Названо здесь и в журнале W34.

### Следующий батч

Начинать с оставшихся живых вопросов владельца (18 шт.), затем 6 `ingested` и 19 `inbox-*`/`agent-*`.
Ветку НЕ удалять до конца разбора (п. «Чего делать нельзя»).

