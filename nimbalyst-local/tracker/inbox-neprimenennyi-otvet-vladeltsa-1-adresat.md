---
trackerStatus:
  type: inbox
title: Неприменённый ответ владельца «1» — адресат не назван
status: new
source: telegram
created: 2026-09-10
---

## Неприменённый ответ владельца — это НЕ задание

Владелец прислал в чат: «1». Это ОТВЕТ на вопрос, а не поручение — применить его было не к чему: открытых вопросов несколько, и угадывать адресата запрещено (ADR-075).

**Что сделал бот:** переспросил ОДНИМ сообщением с кнопками — какому вопросу предназначен ответ. Нажатие запишет решение обычным owner-путём.

### Открытые вопросы на момент ответа

- `owner-decision-otkuda-schitat-trek-dvuh-knig` — Публичное число двух книг: считать трек с 22 июня (там были литералы) или с 10 сентября (там начались наблюдения)? (предлагает этот вариант)
- `owner-decision-avtotorgovlya-potolok-summy-odnoi-sdelki` — Автоторговля, вопрос 1 из 3: ставить ли потолок на СУММУ одной сделки? (предлагает этот вариант)
- `owner-decision-avtotorgovlya-neznakomyi-protokol-i-tir` — Автоторговля, вопрос 3 из 3: что делать с незнакомым протоколом и незнакомым тиром? (предлагает этот вариант)
- `owner-decision-avtotorgovlya-dnevnoi-limit-oborota` — Автоторговля, вопрос 2 из 3: нужен ли ДНЕВНОЙ лимит оборота вдобавок к недельному? (предлагает этот вариант)
- `owner-decision-sait-why-20-apy-means-tail-risk-astro-i` — Сайт: why-20-apy-means-tail-risk.astro и ещё 2 — автономная правка задела owner-gated область, нужно решение (предлагает этот вариант)
- `owner-decision-razorvat-zamknutyi-krug-avtovzvoda-sovet` — Разорвать замкнутый круг автовзвода: советник ребаланса заблокирован 34 дня из 34 (предлагает этот вариант)
- `owner-decision-udalit-ostavshiisya-fail-s-tokenom` — Удалить оставшийся файл с токеном из папки проекта (одна команда) (этого варианта НЕ предлагает)
- `owner-decision-reinvestirovat-nachislennoe-ili-derzhat-100k` — Реинвестировать заработанное или держать базу ровно 100 тысяч (этого варианта НЕ предлагает)
- `owner-decision-obsidian-chitaet-sostoyanie-nedelnoi-davnosti` — Твой Obsidian показывает состояние проекта недельной давности — одна минута на починку (предлагает этот вариант)
- `owner-decision-earn-defi-sozdat-repozitorii-na-github` — earn-defi: создать репозиторий на GitHub — у агента нет прав, работа лежит локально (этого варианта НЕ предлагает)
- `owner-decision-earn-defi-kanal-telegram-dlya-publikatsii` — earn-defi: нужен Telegram-канал — иначе доказательства сигналов копятся, но не публикуются (предлагает этот вариант)
- `owner-decision-earn-defi-belyi-spisok-nichego-ne-odobreno` — earn-defi: в белом списке пусто — движок не может профинансировать ничего (предлагает этот вариант)
- `owner-decision-devyat-tysyach-dollarov-dostayutsya-prot` — Девять тысяч долларов достаются протоколу по алфавиту — чинить ли ступеньку в расчёте раскладки (этого варианта НЕ предлагает)
- `owner-decision-sait-ustarevshie-i-spornye-utverzhdeniya` — Сайт: устаревшие и спорные утверждения — что менять (предлагает этот вариант)
- `owner-decision-kto-planiruet-razvitie-proekta-sudba-arh` — Кто планирует развитие проекта: судьба «Архитектора» и живой план (предлагает этот вариант)
- `owner-decision-shest-modulei-vydumyvayut-ostatok-na-kos` — Шесть модулей выдумывают остаток на кошельке вместо отказа — чинить сейчас или записать условием go-live? (предлагает этот вариант)
- `owner-decision-dva-paketa-iz-treh-zhivut-bez-potolka-ri` — Два пакета из трёх живут без потолка риска — и сегодня стоят вдвое и втрое выше нашего же лимита (предлагает этот вариант)
- `owner-decision-avtotorgovlya-iz-12-tvoih-ogranichitelei` — Автоторговля: из 12 твоих ограничителей работают 4 — нужны три решения (потолок суммы, дневной оборот, незнакомый протокол) (этого варианта НЕ предлагает)
- `owner-decision-knopka-pauza-ne-stavit-na-pauzu-ona-prod` — Кнопка «Пауза» не ставит на паузу — она продаёт всю книгу; настоящей паузы у тебя нет (предлагает этот вариант)
- `owner-decision-tsena-gaza-v-reshenii-o-perekladke-vzyat` — Цена газа в решении о перекладке взята константой — живые показания сети в 316 раз дешевле (этого варианта НЕ предлагает)
- `owner-decision-sorok-protsentov-knigi-stoyat-na-rynke-k` — Сорок процентов книги стоят на рынке, который система выбирает заново каждое утро (этого варианта НЕ предлагает)
- `owner-decision-dve-treti-kapitala-stoyat-na-chislah-kot` — Две трети капитала стоят на числах, которых никто не наблюдал (этого варианта НЕ предлагает)
- `owner-decision-pendle-sam-naznachaet-sebe-uroven-riska` — Pendle сам назначает себе уровень риска по размеру пула — а в справочнике написано другое (этого варианта НЕ предлагает)
- `owner-decision-sovetnik-po-perekladke-deneg-ne-smozhet` — Советник по перекладке денег не сможет включиться НИКОГДА — 30 дней он молчал не потому, что рынок тихий (этого варианта НЕ предлагает)
- `owner-decision-dva-imeni-odin-kontrakt-20-deneg-stoyat` — Запрет на fluid_usdc объявлен и НЕ исполняется: там стоит 20 % книги (этого варианта НЕ предлагает)
- `owner-decision-edinstvennaya-chestnaya-vnevyborochnaya` — Единственная честная вневыборочная таблица реестра посчитана способом, который льстит сторожу — что делать с опубликованными числами (предлагает этот вариант)
- `owner-decision-broshennye-progony-testov-vosmoi-raz-sed` — Брошенные прогоны тестов восьмой раз съедают процессор — разрешить поставить сторожа по расписанию? (предлагает этот вариант)
- `owner-decision-karta-agentov-v-prode-ustarevaet-navsegd` — Карта агентов в проде устаревает навсегда: её некому пересобирать (этого варианта НЕ предлагает)
- `owner-decision-chastota-80-agentov-flota-2-nahodki-po-t` — Частота 80 агентов флота: 2 находки по токенам/CPU, остальное — оставить (этого варианта НЕ предлагает)
- `owner-decision-utochnenie-po-zametke-adr-070-13-trevogu-2` — Уточнение по заметке: ADR-070.13: тревогу core-agent-down гасит agent_health (этого варианта НЕ предлагает)
- `owner-decision-utochnenie-po-zametke-1` — Уточнение по заметке: 1 (этого варианта НЕ предлагает)
- `own-chto-dolzhen-pokazyvat-lokalnyi-server` — Cloudflare проверять не нужно — я измерил сам; остался один вопрос про локальный сервер (предлагает этот вариант)
- `owner-decision-knigu-perekladyvayut-22-raza-za-nedelyu-2026-08-29` — Книгу перекладывают 22 раза за неделю. По нашей же модели издержек это съело бы доходность в 15 раз (этого варианта НЕ предлагает)

### Что делать оркестратору

Задачей это НЕ исполнять. Владелец нажал кнопку ⇒ решение уже записано в свою карточку, здесь останется только закрыть этот след (`done`) со ссылкой. Не нажал ⇒ переспросить по протоколу (`notify` / `resend`), не угадывая, к чему относился номер.

---
_Карточку создал бот (`inbox_intake.save_unapplied_owner_answer`) — см. класс `inbox-golyi-otvet-vladeltsa-1-2-pri-voprose-be`._
