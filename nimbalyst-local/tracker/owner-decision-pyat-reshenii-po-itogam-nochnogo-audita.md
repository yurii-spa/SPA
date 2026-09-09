---
trackerStatus:
  type: owner-decision
title: "Указатель: все решения по итогам ночного аудита разложены по отдельным карточкам"
status: ingested
source: agent
created: 2026-09-09
tags: [index, night-audit, owner-decisions]
owner_choice: 2
owner_answered_at: 2026-09-09T06:12:54.808480+00:00
owner_answer_via: telegram
owner_answered_by: 258651137
status_trail:
  - "2026-09-09T18:35:28.309428+00:00 needs-owner -> ingested · queue.set_status · cycle-80789"
---

## Что случилось и почему это важно

Эта карточка сначала собирала пять решений в одну. По твоей просьбе («всё, что на мне, разложи
карточками с вариантами ответов») каждое решение вынесено в свою карточку — с вариантами и
рекомендацией агента, чтобы отвечать можно было нажатием, а не письмом.

Полный отчёт, из которого всё это вышло: `docs/OWNER_RECOMMENDATIONS_2026-09-09.md`
(10 рекомендаций + аудит всех 82 твоих правил, каждое число перемерено по живым данным).

## Что от тебя нужно

Ответить в карточках ниже. Порядок — по цене вопроса, а не по срочности.

1. **Go-live** — `owner-decision-go-live-geit-proiden-29-iz-29-reshenie-tvoe`.
   Гейт прошёл 29 из 29, дальше по инварианту №14 решаешь только ты.
2. **Честные числа** — карточка уже висит с 5 сентября:
   `owner-decision-dve-treti-kapitala-stoyat-na-chislah-kot`. Новой не завожу, чтобы не дублировать.
3. **Кнопка «Пауза»** — висит с 7 сентября: `owner-decision-knopka-pauza-ne-stavit-na-pauzu-ona-prod`.
4. **Замкнутый круг советника** — висит с 5 сентября:
   `owner-decision-sovetnik-po-perekladke-deneg-ne-smozhet`.
5. **Реинвестировать заработанное** — `owner-decision-reinvestirovat-nachislennoe-ili-derzhat-100k`.
6. **Граница «решай сам» / «спроси меня»** — `owner-decision-gde-granitsa-reshai-sam-i-sprosi-menya`.
   Эта карточка снимает очередь: при варианте 1 из 26 ожидающих остаётся 4–6.
7. **Токен в папке проекта** — `owner-decision-udalit-ostavshiisya-fail-s-tokenom` (одна команда).
8. **Obsidian на зеркало** — `owner-decision-obsidian-chitaet-sostoyanie-nedelnoi-davnosti` (одна минута).
9. **Цена одного цикла** — `owner-decision-skolko-stoit-odin-tsikl-agenta` (одно число).
10. **earn-defi: репозиторий на GitHub** — `owner-decision-earn-defi-sozdat-repozitorii-na-github`.
11. **earn-defi: Telegram-канал** — `owner-decision-earn-defi-kanal-telegram-dlya-publikatsii`.
12. **earn-defi: белый список** — `owner-decision-earn-defi-belyi-spisok-nichego-ne-odobreno`.
13. **earn-defi: таблица режимов** — `owner-decision-earn-defi-tablitsa-rezhimov-ne-bet-buy-and-hold`.
14. **earn-defi: лицензия на данные** — `owner-decision-earn-defi-litsenziya-na-dannye-do-deneg`.
15. **Стейбл-нога BTC в пол SPA** — `owner-decision-steibl-noga-btc-dvizhka-v-pol-spa`.

Самая дешёвая по времени и самая полезная по эффекту — пункт 6: она разгружает всё остальное.

## Как понять, что готово

Ты ответил в отдельных карточках. Эту можно закрыть в любой момент — она только указатель.

## Что будет после

Агент разбирает ответы по одному, на каждое решение оформляет ADR и делает работу с приёмкой.
Шесть рекомендаций из отчёта, которые твоего ответа не требуют, агент уже делает сам.
