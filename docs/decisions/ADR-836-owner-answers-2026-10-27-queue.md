# ADR-836 · Ответы владельца 27.10 в сессии Claude Code — шестнадцать вопросов очереди

- **Статус:** Accepted
- **Дата:** 2026-10-27
- **Решения:** владелец, ответы на вопросы с вариантами в сессии Claude Code 27.10. Записал: Claude Code. Карточки закрываются агентом по этой записи (ADR-834).

**Поправка ADR-839 (ARB 27.10): фраза ниже для всего пакета НЕВЕРНА — N = 3 дня, свежесть 60/15 с, TTL решения 10 мин и выравнивание тиров МЕНЯЮТ поведение; без изменений только 20 % Base и 5 % кэша. Таблица «до → после → ответ → проверка» — в поставке денежного пути через pre_cutover_gate.**

Ни один ответ не меняет пороги RiskPolicy, ставки, лимиты или реальный капитал: денежные пункты задают ПРЕДМЕТ сравнения и названные владельцем числа; реализация на денежном пути идёт через `pre_cutover_gate` с тестами.

| карточка | выбор | ответ владельца | что дальше |
|---|---|---|---|
| `owner-decision-disk-mac-mini-zabit-pod-nol-odin-zhurnal` | закрыть | закрыть как устаревшую: свободно 43 ГБ из 460, журнал 7,1 ГБ не причина | ничего не удаляется; место сторожат resource_guard и system_health |
| `owner-decision-ubrat-2-gb-sluzhebnogo-musora-git-v-rabo` | 2 | ничего не делать (мусора 0,6 МБ, 2,4 ГБ — несжатые объекты) | git gc не запускается |
| `owner-decision-utochnenie-po-zametke-sto-tridtsat-devya` | закрыть | вопрос снят; уборка деревьев — задача агента | агент снимает ТОЛЬКО деревья, чья работа доказанно доставлена, штатным механизмом уборки |
| `owner-decision-razreshit-vosstanovit-propavshuyu-istori` | 1 | объединить записи — сделано 27.10 (161 + 6 + 1, tree_poorer 3 → 0) | резерв: ~/studio-os-serve/backups/tracker_record_merge_* |
| `owner-decision-kakoi-variant-ty-vybral-9-sentyabrya-po` | A | вариант 1 — решать при первом реальном долларе (подтверждено владельцем; ADR-832) | условие лицензии в гейте — когда в earn-defi появится переход к деньгам |
| `owner-decision-agent-nablyudatel-prosypaetsya-raz-v-7-6` | ускорить | расписание не менять; ускорить прогон decision_loop | агент: причина ~8000 вызовов аллокатора за прогон, правка без перезапуска службы |
| `owner-decision-zakryt-tri-chernovyh-pr-u-moego-klyucha` | 1 | выдать права — агент закрывает #50, #10, #9 сам | владелец добавляет правило Claude Code и право ключа Pull requests: write; #10/#9 не сливаются |
| `owner-decision-earn-defi-kanal-telegram-dlya-publikatsii` | 1 | публичный канал только для хешей | владелец создаёт канал, делает бота админом, присылает ссылку |
| `owner-decision-dva-mesta-zovut-odin-protokol-raznym-t` | A | выровнять morpho_steakhouse → T2, pendle → T2 + сторож расхождения тиров | денежный путь: правка через pre_cutover_gate, сторож — тест |
| `own-optimum-proigryvaet-resheniyu-nichego-ne-d` | 1 | сравнивать предложение аллокатора с «ничего не делать», брать лучшее | денежный путь, пороги не меняются |
| `owner-decision-potolok-base-tsepochki-zapisan-v-treh-mestah` | A | главное — spa_core/risk/policy.py; сайт и документ берут число оттуда | число 20 % не меняется |
| `owner-decision-pyat-protsentov-kesha-zapisany-v-dvuh-me` | 1 | одно правило: бэктест и тесты берут 0.05 у правила риска | число не меняется |
| `owner-decision-sistema-ne-sprashivaet-proderzhitsya-li` | 1 | ход — только если ставка цели держится выше источника N = 3 дня подряд; иначе откладывается | денежный путь, новая настройка N = 3 |
| `owner-decision-stoimost-perekladki-zaryazhaetsya-v-134` | 1 | допуск расхождения «заряжено ↔ наблюдено» ×3 | константа не меняется; газ в решении — отдельный вопрос |
| `owner-decision-zaschita-ot-kachelei-sravnivaet-ne-to-ch` | 1 | сравнивать с состоянием книги за 14 дней | пороги ×1,5 и 14 дней не меняются |
| `owner-decision-pereproverka-pered-sdelkoi-nazovi-dva-ch` | А | допуск свежести 60 с на бумаге / 15 с вживую; срок годности решения 10 мин | прибор начинает судить по этим числам |
