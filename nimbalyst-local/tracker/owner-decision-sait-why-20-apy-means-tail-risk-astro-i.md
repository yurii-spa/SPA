---
trackerStatus:
  type: owner-decision
title: "Сайт: why-20-apy-means-tail-risk.astro и ещё 2 — автономная правка задела owner-gated область, нужно решение"
status: needs-owner
source: orchestrator
created: 2026-09-09
approves: landing/src/pages/learn/why-20-apy-means-tail-risk.astro, landing/src/pages/packages.astro, landing/src/pages/system.astro
---

## Что случилось и почему это важно
На сайте в шестнадцати местах руками была вписана строка «~3,3% фактических». Это была ставка
трека где-то в июле; трек с тех пор ушёл вперёд — на 9 сентября он даёт 5,3% (якорь 22 июня,
78 подтверждённых дней). Число, перепечатанное в шестнадцати файлах, не обновляет никто.

Сегодня страницы перестали его печатать: значение приходит из дневного снимка, одна точка правды.
Шестнадцать файлов уже уехали в live (коммит 2da9918e). Три оставшиеся — /system, /packages и
статья «why 20% APY means tail risk» — сторож задержал: он видит, что строка с числом-доказательством
УДАЛЕНА, и по построению не может знать, что на её месте теперь рендер того же смысла, а не пустота.
Сторож прав, что спросил. Правка — та же, что в остальных.

Пока ты не ответишь, эти три страницы показывают 3,3%, а соседние — 5,3%. Именно такое расхождение
ты и заметил вчера на скриншотах.

## Что от тебя нужно
Посмотри изменение и выбери:

1. **Одобрить (рекомендую)** — три страницы догоняют остальной сайт; на всём сайте одна
   цифра, и она берётся из замера, а не из памяти. Это ровно то, что ты выбрал на карточке про
   сайт («Починить всё по замерам»), — машинного одобрения у того ответа просто нет.
2. **Отклонить** — три страницы остаются на 3,3%, остальной сайт на 5,3%. Расхождение сохраняется.
3. **Отложить** — карточка ждёт; сайт остаётся расхождением.

Что именно меняется:
- Файлы: landing/src/pages/system.astro, landing/src/pages/packages.astro, landing/src/pages/learn/why-20-apy-means-tail-risk.astro
- Коммит-сообщение оркестратора: site: последние три страницы с напечатанной ставкой — на общий источник (ADR-292)

Те же правки, что уехали коммитом 2da9918e для остальных шестнадцати файлов: строка
«~3,3% realized» заменена на значение из снимка (landing/src/lib/realized_rate.js).
Гейт владельца пометил их honesty.token.removed — строка с evidence-токеном удаляется,
и он не может знать, что она заменена рендером того же смысла, а не выброшена.

Владелец ответил на карточку про сайт «Починить всё по замерам» (сессия 09.09), но
машинного одобрения (owner-done карточки) у этого ответа нет — поэтому уезжает через вас.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
- Что зафлагано owner-gate линтером:
  - [E] landing/src/pages/learn/why-20-apy-means-tail-risk.astro · honesty.token.removed · a: 'Our live conservative paper track runs at ~3.3% realized with 0.0% drawdown — real, evidenced, checkable. Up-to-20% 
  - [E] landing/src/pages/packages.astro · honesty.token.removed · description="Three yield-package tiers by target APY and drawdown limit. Conservative targets up to 6% (the REAL live pa
  - [E] landing/src/pages/system.astro · honesty.token.removed · { href: '/packages', en: 'Yield packages', ru: 'Доходные пакеты', desc_en: 'Three honest tiers — Conservative (up to 6%,

## Как понять, что готово
Ты нажал кнопку в Телеграме (или написал в карточке «одобряю» / «отклоняю»); при одобрении оркестратор запушит с трейлером `Owner-Approved: <id-карточки>`.

## Что будет после
Одобришь → изменение уезжает в live /dashboard и на сайт. Отклонишь → оркестратор не трогает эту область.

<!-- owner-gate-fingerprint: 6a9e44266a3f -->
