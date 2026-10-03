---
trackerStatus:
  type: owner-decision
title: Три бумажных портфеля работают — осталось одобрить формулировки на сайте одним пакетом (метки «отказан для live», FAQ, комиссии, первая фраза главной)
status: owner-done
source: nimbalyst
created: 2026-10-03
priority: high
package: docs/owner_packages/2026-10-02-three-portfolios-closeout.md
approves: [landing/src/pages/index.astro, landing/src/pages/packages.astro, landing/src/pages/faq.astro, landing/src/pages/fees.astro, landing/src/pages/snapshot.astro, landing/src/pages/system.astro, landing/src/pages/strategies/index.astro, landing/src/pages/strategies/aggressive.astro, landing/src/pages/strategies/balanced.astro, landing/src/pages/strategies/conservative.astro, landing/src/lib/tier_bands.json, landing/src/lib/package_card.js, landing/src/data/strategy_config.json, landing/src/components/StrategyCard.astro]
owner_choice: "все 10 пунктов одобрены с уточнениями; 6 — вариант 6а; 8 — вариант 8б; 9 — оставить"
owner_answer_via: "интерактивная сессия Claude Code, 2026-10-03"
status_trail:
  - "2026-10-03T11:52:20.156947+00:00 needs-owner -> owner-done · queue.set_status/closed_by:agent on the owner's explicit decision of 2026-10-03 (interactive session: «Одобряю consolidated package … Закрыть owner card как owner-done»)/evidence:all 10 items applied as approved (with the owner's clarifications) in one commit; check_owner_gate passes with Owner-Approved: owner-decision-tri-bumazhnyh-portfelya-rabotayut-ostalo; landing build 12"
---

## Что случилось и почему это важно

Три бумажных портфеля работают, и сайт с Director показывают их по одному правилу (ADR-537). Осталось то, что агенту менять нельзя. Это строки с метками честности («refused for live», уровни L0–L6), формулировки фонда, комиссий и минимальной суммы, а также опубликованные цели доходности.

Из-за этих строк:
- на главной у Aggressive висит смешанная надпись «PAPER-ТЕСТ · ОТКАЗАН ДЛЯ LIVE»;
- в нескольких местах описан старый Aggressive Lab с его ~50 % хвостом;
- FAQ говорит про «SPA Family Fund» и «минимальную сумму инвестиций».

Всё собрано здесь одним пакетом. Каждый пункт можно одобрить или отклонить отдельно.

## Что от тебя нужно

Ответь «да на всё», «да, кроме №…» или «нет». Рекомендация агента — **да на пункты 1–5, вариант 6а, 7 — да, 8 — вариант 8б, 9 — оставить, 10 — да**.

**1. Допуск к реальному капиталу у Aggressive (метки честности, класс E). Смысл отказа сохраняется, меняется только формулировка.**

| Где | Сейчас | Предлагаю |
|---|---|---|
| Главная, карточка Aggressive, значок | EN «Paper-tested · refused for live»<br>RU «Paper-тест · отказан для live» | тот же значок, что у двух других карточек:<br>EN «Real capital: refused»<br>RU «Реальный капитал: не допускается» |
| Главная, строка под значком | «paper-tested in Aggressive Lab · refused for live capital»<br>RU «paper-тест в Aggressive Lab · отказан для live-капитала» | «simulated leverage, research paper portfolio — refused for live capital»<br>RU «симулированное плечо, исследовательский бумажный портфель — реальный капитал не допускается» |
| Главная, полоса сравнения | «paper · tail shown · refused for live»<br>RU «бумага · хвост показан · для live отклонён» | «paper · simulated loop · refused for live capital»<br>RU «бумага · симулированная петля · реальный капитал не допускается» |
| /packages, ярлык Aggressive | «RESEARCH · paper track running · refused for live (by design)»<br>RU «ИССЛЕДОВАНИЕ · идёт paper-трек · отказан для live (осознанно)» | «RESEARCH · simulated loop experiment · refused for live (by design)»<br>RU «ИССЛЕДОВАНИЕ · эксперимент с симулированной петлёй · реальный капитал не допускается (осознанно)» |
| /strategies/aggressive, баннер | «TARGET PROFILE — RESEARCH/PAPER, REFUSED FOR LIVE» + абзац про 12–20 % Aggressive Lab и ~50 % на обвале ETH | «PAPER EXPERIMENT — REFUSED FOR LIVE CAPITAL» + абзац о текущей механике: симулированная петля, своя история накапливается. Хвост старой книги Aggressive Lab — одной ссылкой «предыдущее исследование» |
| /strategies/aggressive, строки 266, 279, 430 · /strategies/balanced, строка 43 · /strategies, строка 73 · /system: описание пакетов · /snapshot: шаг «рост» · `strategy_config`: ярлык, первый пункт «не делает» и заметка о цели Aggressive | те же метки, привязанные к старой книге Aggressive Lab | те же метки, привязанные к текущей механике |
| `tier_bands`, уровень доказательности Aggressive | «L2 · backtest · refused for live» — это бэктест старой книги Aggressive Lab | уровень текущей механики по шкале `docs/37`: бумажный эксперимент, версия набирает 30 дней · refused for live. Число уровня агент проставит по шкале и покажет в коммите |

**2. Мета-описания** страниц /packages, /strategies/balanced и /strategies/aggressive. Сейчас: «Three yield-package tiers by target APY and drawdown limit… up to 12 %… up to 20 %». Предлагаю: «Three paper portfolios with different mechanics… status and results of the current version… research targets are not results».

**3. FAQ (класс A, формулировки фонда).**
- Вопрос «What is the minimum investment amount? / Какова минимальная сумма инвестиций?» заменить на «Can I invest today? / Можно ли инвестировать сейчас?». Ответ уже честный («минимальной суммы нет, это не оферта») и не меняется.
- Шапку «Everything you need to know before becoming a member of the SPA Family Fund / …участником SPA Family Fund» заменить на «Everything about the SPA research paper track / Всё об исследовательском бумажном треке SPA».

**4. Комиссии (класс D / legal).**
- Сейчас: блоки на /strategies/conservative, /strategies/balanced и /strategies/aggressive («Fee structure is discussed individually at onboarding; high-water mark…») и страница /fees. Это действующие условия для продукта, который ничего не предлагает.
- Предлагаю одну строку: «No fees: this is a paper stage and nothing is offered; commercial terms only after go-live and a legal review» / «Комиссий нет: это бумажная стадия, ничего не предлагается; коммерческие условия — только после go-live и юридической проверки».
- /fees — тот же текст или скрыть страницу из меню. Рекомендую текст.

**5. Блок раннего доступа на главной.**
- Сейчас: «Aggressive targets go live only after they're proven» и подписка с меткой `tier:aggressive`. Это обещание, что Aggressive выйдет в live.
- Предлагаю: «Want the validation report of a paper portfolio when its current version reaches 30 valid days? No offer, no promise of yield».

**6. Опубликованные цели доходности (предмет №2).**
- Сейчас цели (до 6 / 12 / 20 %) показаны второстепенной строкой «исследовательская цель — не результат и не прогноз».
- В `tier_bands` к ним приклеены бюджеты просадки «≤3 % / ≤10 % / ≤25 %». Это не пороги с действием: реальные стопы −5/−10 %, −8 % и −25 %.
- Вариант 6а (рекомендую): цели оставить исследовательскими, бюджеты просадки из строк диапазонов убрать. Публикуется только правило остановки с его действием.
- Вариант 6б: оставить как есть.
- В обоих вариантах удаляется неиспользуемое `strategy_config.target_apy` (6/5/15, расходилось с 6/12/20).

**7. Стоп рукавов от пика старой версии (денежный путь, найдено ревью).**
- Стопы Balanced (−8 %) и Aggressive (−25 %) считаются от пика, который записала прежняя версия (100 496 и 100 607), а не от пика текущей механики.
- Рекомендую мерить от пика текущего эксперимента. Это правка правила остановки, поэтому только с твоего «да».

**8. Первая фраза главной (hero) — твоё решение J3 от 12.07.**
- Сейчас (восстановлено дословно после того, как я 02.10 заменил её без твоего согласия): «Target up to ~20%/yr in our research strategies — paper, always shown with the tail — built on a live desk that already proves 4.9% realized at 0.0% drawdown…». Это твоё июльское «брать максимум».
- Твоё указание 02.10 разводит цели и результаты. Варианты:
  - 8а: оставить J3;
  - 8б (рекомендую): «Three paper portfolios with different mechanics: unlevered lending, a Pendle PT fixed rate and a simulated loop on Morpho Blue. The Conservative book’s realized paper result is 4.9% annualised (measured …; observed drawdown …). Balanced and Aggressive are accumulating the statistics of their current versions. No real capital.» / RU аналогично.

**9. Сценарий в калькуляторе (функция M3, восстановлена в исправленном виде).**
- Сейчас отдельный блок «Сценарий, а не результат: если бы исследовательская цель Aggressive (до 20% годовых) была достигнута — до $10 000 в год».
- Рядом названы допущения (вся сумма, до реальных издержек, у текущей версии 1 из 30 дней) и хвост исследования из `tier_bands`.
- Ставка сценария берётся из `tier_bands`, вшитого 0,20 больше нет.
- Подтверди («оставить») или «убрать».

**10. Метки тира у фактических позиций.**
- Строка «тиры протоколов в книге» показывает метки реестра по замеру: Balanced сейчас держит `susde` с меткой **T3**, а прежняя надпись «T1 + T2» была неверна.
- Сама метка `susde` T3 против `ethena_susde` T2 — тот же вопрос пакета A ADR-532.
- Плюс: в `tier_bands` русская строка хвоста Aggressive содержит транслит «directional-книга». Предлагаю «нехеджированная направленная книга». Это поле с числом, поэтому через тебя.

**Отдельно и без изменений**, чтобы не потерялось: ярлыки тиров (пакет A ADR-532), бюджет Conservative 3 % (B) и RTMR (C) ждут своего решения.

## Как понять, что готово

`scripts/check_owner_gate.py` пропускает пакет с твоим `Owner-Approved:`, а на earn-defi.com после JS (375/390/430/1280, EN/RU) нет ни одной смешанной RU-метки и ни одного упоминания Aggressive Lab как текущей механики.

## Что будет после

Агент применит одобренные пункты одним коммитом через `safe_site_push.py` с этой карточкой, перепроверит все страницы в браузере, закроет карточку и допишет журнал. Неодобренные пункты останутся как есть.

## Ответ владельца (2026-10-03, интерактивная сессия)

Одобрен весь пакет с уточнениями; текст ответа дословно — в журнале `docs/journal/2026-W40.md`, запись 03.10.

1. Aggressive — да: текущая механика (кредитование + симулированная петля sUSDe/PYUSD), только бумага, реальный капитал не допускается; Aggressive Lab — историческое исследование. Не писать «результата ещё нет» — писать «отчётного результата пока нет». Уровень доказательности — только по шкале `docs/37`, не повышать ради интерфейса.
2. Мета-описания — да. 3. FAQ — да: убрать фонд, минимальную сумму и впечатление действующего продукта.
4. Комиссии — да: один текст на трёх страницах стратегий и /fees, будущую модель комиссий не создавать.
5. Ранний доступ — да, формулировка «30-дневный отчёт paper-теста»; 30 дней не «валидируют» и не ведут в live.
6. Вариант 6а: 6/12/20 % — только подписанные исследовательские цели; «≤3/≤10/≤25 %» убрать; настоящие стопы показывать отдельно с их действием; `strategy_config.target_apy` удалить, если не является authority.
7. Да: стопы −8 % / −25 % меряются от пика текущего эксперимента; пороги не меняются; старый пик и история не переписываются; граница версии записана; опора воспроизводима; только бумага.
8. Вариант 8б. 9. Калькулятор — оставить (сценарий отделён, ставка из канона, без 0,20).
10. Да: тиры фактических позиций — только из канонического реестра; спорная идентичность ⇒ «не определён»; русский хвост — «нехеджированная направленная книга»; исторический хвост ~50 % отделён от текущей петли и от стопа.

