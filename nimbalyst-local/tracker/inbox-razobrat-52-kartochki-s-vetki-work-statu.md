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

**Разобрано: 33 из 52.** Осталось 19 — все `inbox-*`/`agent-*`; **вопросов владельца среди них
больше нет** (батч 2 закрыл все 18).
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



### Батч 2 (цикл #355, 23.08) — 18 карточек: ВСЕ оставшиеся вопросы владельца

Отбор — не по имени файла: сначала посчитаны пути, которых на `main` НЕТ ВООБЩЕ
(`git ls-tree` ветки минус `main` = **43**), из них вычтены 6, уже разобранных батчем 1 как
(б)/(в) и оставшихся на ветке. Итог — 37 неразобранных, среди них ровно **18** `own-*`/
`owner-decision-*`. Именно они разобраны здесь (п. 2 приёмки: вопросы владельца — первыми).

**(а) живое, на `main` не было ⇒ ПЕРЕНЕСЕНО — 8.** У каждой в теле раздел «🚚 Перенесено на
`main` циклом #355»: с чем сверялось и **чем премиса перемерена на `main` 4fc822849** (не со слов
карточки):

| карточка | статус | чем ПЕРЕМЕРЕНА на `main` |
|---|---|---|
| `own-2026-08-18-metka-zhivoi-na-konstante-v-allokatore` | ingested | `allocator.py:926-928` ставит `live`, `:937` кладёт литерал — дефект ЖИВ |
| `owner-decision-pravilo-sky-susds-0-otmeneno-tvoim-zhe-r` | ingested | `CLAUDE.md:95` и `.claude/rules/adapters.md:29` объявляют инвариант 10 действующим |
| `own-yakorenie-treka-ne-rabotalo-43-dnya` | ingested | `proofs/ots/ots_anchors.jsonl` = 1 строка; вызывающего у `ots_anchor.py` нет; `com.spa.smoke_flagship` не установлен |
| `owner-decision-doska-kartochek-obeschaet-bolshe-chem-da` | needs-owner | `CLAUDE.md:27` дословно обещает «сам на каждой мутации карточки» |
| `owner-decision-dve-zapisi-o-dengah-prichina-naidena-i-i` | needs-owner | ответ на задачу `inbox-dve-zapisi-o-dengah-rashodyatsya-kazhdyi` (`new`) — причина найдена прогоном |
| `owner-decision-vnutridnevnaya-prosadka-slepota-teper-sl` | needs-owner | 4 вопроса о ПОВЕДЕНИИ риска; ADR-068/104/114 отвечают «что построено», не «как вести себя вслепую» |
| `owner-decision-zakrytie-voprosa-vladeltsa-iz-rabochego` | needs-owner | `.gitignore:47-48` — журнал аудита в git не попадает ⇒ ложная тревога воспроизводится всегда |
| `owner-decision-shest-nahodok-za-den-okazalis-odnoi-bole` | needs-owner | на `main` есть частные случаи класса, карточки о самом классе нет |

**(б) повтор того, что на `main` уже есть ⇒ НЕ перенесено — 7.** Замер с ветки приложен к
карточке `main` разделом «➕ Замер с ветки», иначе он умер бы вместе с веткой:

| карточка ветки | совпала с (на `main`) | что забрано в `main`-карточку |
|---|---|---|
| `own-2026-08-17-morpho-blue-odin-pul-dva-kluycha` | `inbox-morpho-blue-i-morpho-steakhouse-razresha` (new) | **ответ владельца 18.08 — вариант B** + замер одного пула |
| `own-2026-08-17-spark-susds-dublikat` | `agent-spark-susds-identity-split` (backlog) | **ответ владельца 18.08 — вариант B** (переименовать в SparkLend USDS) |
| `owner-decision-proverka-knigi-slabee-proverki-pered-sde` | `agent-enforcer-coverage-gaps` (in-progress) | замер 14 порогов: 3 строги на обеих, 60 % T2 проходит как «здоровый портфель» |
| `owner-decision-vesti-opros-ot-polnogo-reestra-adapterov` | `inbox-orkestrator-vedom-kanonicheskim-reestrom` (new) | таблица 8/10/36 → 8/9/**27** проходных при пределе ALLOC-002 = 8 |
| `owner-decision-spisat-180-fonovyh-modulei-tier-c-ili-ch` | `inbox-tier-c-171-iz-180-modulei-ne-otvechayut` (in-progress) | разложение 162/9/5/4, протокол-чувствительных 0 из 180 |
| `owner-decision-razvedka-krichit-critical-na-nashu-zhe-o` | `own-red-team-nablyudennaya-ugroza-ne-doezzhaet` (перенесена батчем 1) | адреса: `red_team.py:89`, `house_view_gap.py:69` и `:517-539` |
| `owner-decision-storozh-saita-ne-kladet-v-git-dannye-iz` | `owner-decision-chisla-treka-na-saite-ne-podtverzhdayuts` (ingested) | 6 коммитов сторожа = 0 файлов `data/`; 53 дн./29-29 против 13 дн./27-29 в git |

**(в) устарело фактически ⇒ НЕ перенесено — 3.** Починка названа поимённо:

| карточка ветки | чем закрыта на `main` |
|---|---|
| `own-55-vtoroi-chitatel-komand-v-telegram` | вопрос ПЕРЕСПРОШЕН и отвечен: `owner-decision-peresprashivayu-sudba-storozha-telegram` (ingested) + **ADR-113** (`telegram_watcher` разоружён) |
| `owner-decision-sbalansirovannyi-paket-ne-pokupaet-niche` | **ADR-125** (23.08): у Balanced появился шаг выбора — живой ranking, 4 позиции по $25k; премиса «в коде нет самого шага покупки» больше не верна |
| `owner-decision-storozh-saita-krasneet-kazhduyu-noch-na` | **ADR-116** (22.08): стоящее одобрение владельца, класс B (числа доходности) уезжает в live без карточки ⇒ ежедневная тревога на длине трека снята источником |

### Что вскрылось по дороге (сверх приёмки карточки) — батч 2

**Вывод `ADR-099` «потерянных решений нет» верен для КАРТОЧЕК и неверен для СОДЕРЖАНИЯ.**
`ADR-099` считал, сколько карточек ветки уже `ingested` на `main` (8 из 9), и заключил: владельца
переспросили, но ничего не потеряли. Замер батча 2 показывает второй слой: `ADR-095` ветки
(18.08) содержит **четыре** решения владельца, и два из них — пп. 3 и 4, помеченные там же
«работа агента, исполняется сразу», — **на `main` не исполнены и карточек на `main` не имели**:

1. **п. 3** — аллокатор ставит метку «живое» на константу. Перемерено сегодня на `main`
   4fc822849: `spa_core/allocator/allocator.py:926-928` читает живой TVL из `tvl_evidence`,
   ставит `tvl_source="live"` и **выбрасывает число**, а `:937` кладёт в `tvl_usd` литерал
   адаптера. Соседний registry-путь `:1019-1021` написан верно. Прямое нарушение
   `.claude/rules/risk-engine.md` («Never stamp `live` on a constant»); кормит отбор кандидатов,
   `feed_coverage`, дашборд и куратора тиров. Жёсткого гейта не достигает (тот читает снимок
   оркестратора).
2. **п. 4** — инвариант 10 «Sky/sUSDS = 0 %» снять как исполненный (условие выполнено 05.08,
   `ADR-065`). На `main` он по-прежнему объявлен действующим (`CLAUDE.md:95`,
   `.claude/rules/adapters.md:29`) и уже породил ложную «критичную» находку 16.08.

Оба решения теперь лежат на `main` в перенесённых карточках (то есть с закрытием ветки не
исчезнут). Исполнение — вопрос владельцу: `owner-decision-dva-tvoih-resheniya-ot-18-08-ne-ispolnen`.

### Следующий батч

Осталось **19** карточек, все `inbox-*`/`agent-*` (вопросов владельца больше нет). Полный список —
`comm -23 <(git ls-tree -r --name-only <ветка> -- nimbalyst-local/tracker/|sort) <(git ls-tree -r --name-only origin/main -- nimbalyst-local/tracker/|sort)` минус разобранные выше.
Ветку НЕ удалять до конца разбора (п. «Чего делать нельзя»).


---

## 📦 Пачка 3 — 2026-08-24, цикл #372 (все 12 висевших вопросов владельца разобраны)

**Перемерено, а не переписано из шапки.** «52 карточки» — число цикла #322; сегодня на ветке
осталось **35** путей, которых на `main` нет ВООБЩЕ (пачки 1 и 2 уже сняли 17). Из этих 35:
**16 карточек владельца** (12 в статусе `needs-owner` — те самые, что каждый цикл называет
`owner_decision_pending.branch_queue`; 4 уже `ingested` на самой ветке) и **19** карточек
`inbox-*`/`agent-*`.

Эта пачка закрывает **все 12 `needs-owner`**. Каждая отнесена по СОДЕРЖАНИЮ — сверкой с
сегодняшним кодом `main` (`5a9fbb2ba`), а не по заголовку.

### Перенесено на `main` — 9 (замер подтвердил: дефект жив сегодня)

| карточка | чем подтверждено на `main` сегодня |
|---|---|
| `own-2026-08-18-potolok-ne-vidit-obshchego-kuratora` | `grep -c curator spa_core/risk/policy.py` = **0**; на `main` только `agent-morpho-curator-concentration` (`backlog`, карточка агента, не вопрос) |
| `own-2026-08-18-tyuner-ne-znaet-o-setevykh-potolkakh` | дыра ШИРЕ описанной: `allocation_tuner.py:42-47` держит свои литералы (0.35/0.25/0.05), теста `test_unmirrored_gate_rules_are_still_exactly_the_known_gap` на `main` НЕТ, `chain` не упоминается ни в тюнере, ни в аллокаторе |
| `own-2026-08-18-zapas-rebalansera-strozhe-politiki` | `portfolio_rebalancer.py:63` — `t1_min=0.55` на месте; в политике правила «≥55 % в T1» нет |
| `own-fluid-gsm-gate-chuzhoy-parametr` | `fluid_fusdc_adapter.py:11-12,20,178` — гейт 48 ч на месте; `allocator.py:471` называет его намеренным; `fluid_usdc` по-прежнему без гейта |
| `own-ruchnoy-instrument-poiska-istochnikov` | читателя `data/source_discovery.json` нет (только сам скрипт и его тест). Помечена **PARTIAL**: вариант A частично перекрыт ответом владельца 19.08 (вариант 1 в `owner-decision-poisk-novyh-protokolov-ne-idet-programmu`) — это записано В карточке |
| `own-tsena-nashego-limita-20-na-odno-imya-izme` | самого замера (852 дня, потолок 20/25/30 %) на `main` нет нигде; это ОТВЕТ на запрос владельца 08.08 (`own-rnd-duty-is-concentration-adr055`, вариант A) |
| `owner-decision-proverka-knigi-slabee-proverki-pered-sde` | интроспекция `RiskPolicy.check_portfolio_health` (`policy.py:511`): `t2_allocation_pct` / `chain_allocation` / `l2_allocation` / `apy` / `max_protocols` — **ни одного** в исходнике проверки книги |
| `owner-decision-spisat-180-fonovyh-modulei-tier-c-ili-ch` | находка на `main` есть (`inbox-tier-c-171-…`, `inbox-tier-c-pyat-…`), но обе типа `inbox`; ВОПРОСА владельцу нет ни одного. `_tier_c_key_coverage.py` на `main` не существует |
| `owner-decision-vesti-opros-ot-polnogo-reestra-adapterov` | `POLLED_ADAPTERS` = **8** (`adapter_orchestrator.py:73`), `len(ADAPTER_REGISTRY)` = **36**, `max_protocols = 8` (`policy.py:75`) — «ровно у края» воспроизводится |

### Перенесено ЧАСТЬЮ — 1 (половина устарела по-хорошему, половина жива)

* `owner-decision-sbalansirovannyi-paket-ne-pokupaet-niche` → новая карточка
  **`own-2026-08-24-pustaya-kniga-prohodit-chek-list-go-live`**.
  Главное утверждение оригинала («в коде пакета нет шага выбора протоколов») на `main` НЕВЕРНО:
  `hy_cycle.py:271-287` и `lp_cycle.py:257-274` зовут `sleeve_book` и пишут позиции (ADR-125,
  23.08); перемерено — Balanced держит 4 позиции, Aggressive 2. Нести это владельцу значило бы
  спросить об отвеченном (ADR-084). Жива вторая половина: `golive_checker_lp.py:341-355` —
  CHECK-LP-006 на нуле позиций отвечает «требование выполнено», у CHECK-HY-001…006 проверки
  наполнения книги нет вовсе. Перенесена ровно она, с честной рамкой «сегодня книги не пусты».

### НЕ перенесено — 2 (повтор и решённое; названо, с чем совпало)

* `owner-decision-razvedka-krichit-critical-na-nashu-zhe-o` — **дубль по объекту и по вариантам**
  карточки `own-red-team-nablyudennaya-ugroza-ne-doezzhaet` (`main`, статус `blocked`, 18.08):
  тот же `red_team.py` + `house_view_gap.py`, та же перевёрнутая чувствительность
  (`THREATS_PRESENT` не доезжает, эхо стоп-крана доезжает), те же три варианта. Заголовки
  разные — содержание одно. Второй раз владельца об этом не спрашиваем.
* `owner-decision-storozh-saita-krasneet-kazhduyu-noch-na` — **решено более широким решением.**
  `real_track_days` уже входит в `_TS_NUMBER_FIELDS` (класс B, `scripts/check_owner_gate.py:107-108`)
  и пересчитывается из канона (`:455`), а класс B c **ADR-116** (22.08) стоит в
  `_STANDING_APPROVED_KLASSES` — числа уезжают в live без карточки владельцу. Ровно вариант A
  этой карточки, только принятый шире. Ежедневной красноты по этому полю больше нет.

### Осталось на ветке после пачки 3

**26 путей** = 4 карточки владельца, уже `ingested` **на самой ветке**
(`own-2026-08-17-morpho-blue-odin-pul-dva-kluycha`, `own-2026-08-17-spark-susds-dublikat`,
`own-55-vtoroi-chitatel-komand-v-telegram`, `owner-decision-storozh-saita-ne-kladet-v-git-dannye-iz`)
+ **19** карточек `inbox-*`/`agent-*`
+ 3 разобранные сегодня, но намеренно оставленные на ветке (2 повтора/решённых и оригинал
разделённой карточки). **Вопросов владельца в статусе `needs-owner` на ветке НЕ ОСТАЛОСЬ.**

**Чего я про эти 4 НЕ мерил, чтобы не выдать чужое измерение за своё:** доехал ли ОТВЕТ
каждой из них на `main`. Карточка владельца `owner-decision-na-vetke-lezhat-52-tvoi-kartochki-a-ne-t`
утверждает это про решения ветки в целом («их ты потом ответил ещё раз через Мак»), и это замер
цикла #322, а не мой. Спот-проверка сегодня: у трёх на `main` лежит родственник по объекту
(`agent-spark-susds-identity-split`, `inbox-morpho-blue-i-morpho-steakhouse-razresha`,
`owner-decision-storozh-saita-odnoi-komandy-ne-hvatilo-r`), у `own-55-vtoroi-chitatel-komand-v-telegram`
родственника по имени я не нашёл. Это НЕ находка (совпадение ищется содержанием, а имён я и не
сверял по содержанию) — это честная граница пачки 3: они `ingested`, вопросов не держат, и их
разбор идёт следующей пачкой вместе с `inbox-*`/`agent-*`.

Ветку НЕ удаляю: решение владельца — удалять ПОСЛЕ разбора, а 19 карточек `inbox-*`/`agent-*`
ещё не разобраны. Следующая пачка — они.

**Владельцу пачкой не отправлялось** (ADR-084) — `notify` ни по одной карточке не запускался.
Код и тесты ветки не переносились.
