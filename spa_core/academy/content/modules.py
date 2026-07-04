"""
spa_core/academy/content/modules.py

Module metadata for the Academy: Real-Money Onboarding contour (modules 0–8).

MODULES: dict[int, ModuleMeta]
ModuleMeta keys:
    id: int
    title_ru / title_en: str
    description_ru / description_en: str
    practice_type: Literal[
        "on_chain_tx", "siwe", "balance", "event_log", "quiz_only", "capstone"
    ]
    chain: Literal["base", "base_sepolia", "none"]
    wallet_limit_usd: int          # 150 for every real-money module
    theory_html_ru: str            # brief theory (2–3 paragraphs)
    practice_html_ru: str          # the module's practical task
    spa_connection_html_ru: str    # "what SPA would do here" — kill-rules / refusal

Invariants baked into the copy (do NOT drop when editing):
  - "лимит учебного кошелька ≤ $150" appears in every real-money module (M2–M8).
  - "курс никогда не просит подключать основной кошелёк".
  - "никогда и никому не сообщайте seed-фразу".
  - Each SPA block ties the module to SPA's kill-rules and refusal-first stance.

This is the ONLY module content that is served to the client. Quiz answers live
separately in :mod:`spa_core.academy.content.quiz_bank` and are never serialised.

LLM FORBIDDEN in this module (static content, no model calls).
Academy stage 4.
"""

from __future__ import annotations

from typing import Dict, List

# Shared safety footer woven into practice blocks of every real-money module.
_SAFETY_NOTE = (
    "<p class=\"safety\"><strong>Безопасность:</strong> лимит учебного кошелька "
    "≤ $150 — не заводите больше. Курс никогда не просит подключать основной "
    "кошелёк. Никогда и никому не сообщайте seed-фразу — её не спрашивает "
    "ни поддержка, ни этот курс.</p>"
)


MODULES: Dict[int, dict] = {
    # ── M0 — Base Sepolia (testnet) ──────────────────────────────────────────
    0: {
        "id": 0,
        "title_ru": "Тестовая сеть Base Sepolia",
        "title_en": "The Base Sepolia testnet",
        "description_ru": "Первые действия on-chain без риска — на тестовой сети.",
        "description_en": "Your first on-chain actions, risk-free, on a testnet.",
        "practice_type": "on_chain_tx",
        "chain": "base_sepolia",
        "wallet_limit_usd": 150,
        "theory_html_ru": (
            "<p>Base Sepolia — это <strong>тестовая сеть</strong> (testnet). Она "
            "устроена как настоящий Base, но токены в ней ничего не стоят. Это "
            "идеальный полигон: любую ошибку здесь можно совершить бесплатно.</p>"
            "<p>Тестовый ETH берётся из <em>faucet</em> — сервиса, который "
            "бесплатно выдаёт немного тестовых монет на газ. Chain ID Base "
            "Sepolia — <code>84532</code> (у Base mainnet — 8453).</p>"
            "<p>Подтверждённая транзакция в тестнете означает лишь, что она "
            "внесена в блок тестовой сети. Реальных денег не двигается — это "
            "репетиция перед mainnet.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> создайте учебный кошелёк, получите "
            "тестовый ETH из faucet Base Sepolia и отправьте небольшую тестовую "
            "транзакцию себе. Сохраните tx hash — вы проверите его в block "
            "explorer.</p>" + _SAFETY_NOTE
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> SPA сам начинает всё "
            "новое в песочнице (paper trading), прежде чем рисковать капиталом. "
            "Тестнет для вас — то же, что paper-режим для SPA: сначала доказать "
            "механику без риска, только потом реальные деньги.</p>"
        ),
    },
    # ── M1 — Кошелёк и сид-фраза ─────────────────────────────────────────────
    1: {
        "id": 1,
        "title_ru": "Кошелёк и сид-фраза",
        "title_en": "Wallet and seed phrase",
        "description_ru": "Самостоятельное хранение ключей и вход через подпись.",
        "description_en": "Self-custody of keys and sign-in by signature.",
        "practice_type": "siwe",
        "chain": "base_sepolia",
        "wallet_limit_usd": 150,
        "theory_html_ru": (
            "<p>Некастодиальный кошелёк — это пара ключей, которой владеете "
            "только вы. <strong>Seed-фраза</strong> (обычно 12 слов) — мастер-"
            "ключ ко всем средствам. Её нельзя показывать никому и никогда; "
            "потеря seed = потеря доступа навсегда.</p>"
            "<p>Бэкап seed хранят офлайн, в физически защищённом месте — не в "
            "облаке, не скриншотом, не в переписке. Ещё надёжнее — hardware "
            "wallet, который держит ключи на изолированном устройстве.</p>"
            "<p><strong>SIWE</strong> (Sign-In With Ethereum) — вход через "
            "криптографическую подпись, доказывающую владение адресом. Подпись "
            "бесплатна и не двигает средства — это не транзакция.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> надёжно сохраните seed-фразу учебного "
            "кошелька офлайн, затем войдите в Академию через SIWE-подпись. Вы "
            "подтверждаете владение адресом, ничего не переводя.</p>"
            + _SAFETY_NOTE
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> SPA принципиально "
            "non-custodial и никогда не хранит приватных ключей или seed — вся "
            "архитектура запрещает подпись и движение средств из read-only "
            "кода. Тот же принцип для вас: ключи — только ваши, курс их не видит.</p>"
        ),
    },
    # ── M2 — Сети и газ ──────────────────────────────────────────────────────
    2: {
        "id": 2,
        "title_ru": "Сети и газ",
        "title_en": "Networks and gas",
        "description_ru": "Почему Base дёшев и зачем держать ETH на газ.",
        "description_en": "Why Base is cheap and why you keep ETH for gas.",
        "practice_type": "balance",
        "chain": "base",
        "wallet_limit_usd": 150,
        "theory_html_ru": (
            "<p><strong>Газ</strong> — вычислительная стоимость транзакции, "
            "оплачиваемая в ETH. Любое действие on-chain, даже перевод "
            "стейблкоина, требует немного ETH на газ.</p>"
            "<p>Base — это <strong>L2</strong> (rollup): он собирает множество "
            "транзакций в пакет и публикует их в Ethereum вместе, деля "
            "стоимость. Поэтому комиссии на Base кратно ниже, чем на mainnet. "
            "Chain ID Base — <code>8453</code>.</p>"
            "<p>Если газа не хватит до завершения, транзакция откатывается "
            "(revert), но потраченный газ не возвращается. Поэтому на кошельке "
            "всегда держат небольшую ETH-подушку.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> переведите учебный кошелёк в сеть Base "
            "(mainnet), заведите на него малую сумму в пределах лимита и "
            "убедитесь, что на балансе есть немного ETH на газ.</p>"
            + _SAFETY_NOTE
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> SPA закладывает "
            "gas-cost и breakeven в каждое решение о ребалансе — маленький "
            "трейд, съедаемый комиссией, он отклоняет. Ваш аналог: не гоняйте "
            "капитал туда-сюда, если комиссия сопоставима с суммой.</p>"
        ),
    },
    # ── M3 — Первая транзакция ───────────────────────────────────────────────
    3: {
        "id": 3,
        "title_ru": "Первая транзакция",
        "title_en": "Your first transaction",
        "description_ru": "Отправить перевод и проверить его в explorer.",
        "description_en": "Send a transfer and verify it in an explorer.",
        "practice_type": "on_chain_tx",
        "chain": "base",
        "wallet_limit_usd": 150,
        "theory_html_ru": (
            "<p>Отправленная транзакция сперва попадает в <em>pending</em> — "
            "ждёт включения в блок. У каждой транзакции есть <strong>tx hash</"
            "strong> — уникальный идентификатор, по которому её видно публично.</p>"
            "<p>Статус проверяют в block explorer (например, <code>basescan.org"
            "</code>) по tx hash. Одно подтверждение на L2 уже почти финально, "
            "но для уверенности принято дождаться нескольких блоков.</p>"
            "<p>Если перевод не прошёл, типичные причины: нет ETH на газ, нет "
            "нужного approval, неверный адрес получателя.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> отправьте небольшой перевод "
            "стейблкоина на Base в пределах лимита и найдите свою транзакцию в "
            "basescan.org по её tx hash. Сохраните hash как доказательство.</p>"
            + _SAFETY_NOTE
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> каждый шаг SPA "
            "оставляет проверяемый след (audit trail, on-chain proof) — «не "
            "верь, проверь». Вы делаете то же: доказательство действия — это "
            "tx hash в explorer, а не слова.</p>"
        ),
    },
    # ── M4 — Подписи и approvals ─────────────────────────────────────────────
    4: {
        "id": 4,
        "title_ru": "Подписи и approvals",
        "title_en": "Signatures and approvals",
        "description_ru": "Разрешения контрактам и почему unlimited опасен.",
        "description_en": "Contract allowances and why unlimited is dangerous.",
        "practice_type": "event_log",
        "chain": "base",
        "wallet_limit_usd": 150,
        "theory_html_ru": (
            "<p><strong>Approval</strong> — разрешение смарт-контракту тратить "
            "ваши токены до указанного лимита. Сам по себе approval не двигает "
            "средства, но открывает контракту доступ к ним.</p>"
            "<p><em>Unlimited approval</em> опасен: если контракт взломан, "
            "атакующий может вывести весь баланс токена. Одобряйте только "
            "нужную сумму, а лишние разрешения отзывайте — <strong>revoke</"
            "strong> (approval со значением 0).</p>"
            "<p>Подпись (sign) и транзакция — разное: подпись бесплатна и не "
            "идёт в сеть, транзакция меняет состояние и требует газа. Перед "
            "депозитом в протокол обычно нужен approval на нужную сумму.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> выдайте контракту approval на "
            "конкретную (не безлимитную) сумму, посмотрите событие Approval в "
            "explorer, затем отзовите его (revoke). Убедитесь, что понимаете "
            "разницу между подписью и транзакцией.</p>" + _SAFETY_NOTE
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> подход SPA — "
            "refusal-first: доступ выдаётся минимально необходимый и "
            "отзывается, когда не нужен; execution изолирован и требует явного "
            "«armed»-флага. Ваш аналог: минимальные approvals и регулярный "
            "revoke неиспользуемых.</p>"
        ),
    },
    # ── M5 — Депозит в Aave ──────────────────────────────────────────────────
    5: {
        "id": 5,
        "title_ru": "Депозит в Aave",
        "title_en": "Depositing into Aave",
        "description_ru": "Внести стейбл в пул и получить процентный aToken.",
        "description_en": "Supply a stablecoin and receive an interest aToken.",
        "practice_type": "balance",
        "chain": "base",
        "wallet_limit_usd": 150,
        "theory_html_ru": (
            "<p>Операция <strong>Supply</strong> вносит ваши токены в пул "
            "ликвидности Aave. Взамен вы получаете <strong>aToken</strong> "
            "(например, aUSDC) — квитанцию депозита, баланс которой сам растёт "
            "с процентами.</p>"
            "<p><strong>APY</strong> — годовая доходность с учётом сложных "
            "процентов; она плавает вместе со ставками пула. Перед "
            "подтверждением Supply всегда проверяйте адрес контракта, сумму и "
            "наличие ETH на газ.</p>"
            "<p>Ликвидация грозит заёмщикам, чей залог упал ниже порога. При "
            "чисто стейблкоиновом депозите без займа это крайне редкий "
            "сценарий.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> внесите малую сумму стейбла (в "
            "пределах лимита) в Aave на Base и убедитесь, что на кошельке "
            "появился aToken. Сверьте адрес официального контракта Aave перед "
            "подписью.</p>" + _SAFETY_NOTE
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> Aave V3 — T1-протокол "
            "в whitelist SPA; допуск проходит детерминированную RiskPolicy "
            "(TVL-floor ≥ $5M, APY-границы, cap'ы). Ваш аналог: депонируйте "
            "только в проверенные протоколы с реальной ликвидностью, а не в "
            "то, что обещает больше всех.</p>"
        ),
    },
    # ── M6 — Вывод из Aave ───────────────────────────────────────────────────
    6: {
        "id": 6,
        "title_ru": "Вывод из Aave",
        "title_en": "Withdrawing from Aave",
        "description_ru": "Забрать депозит с процентами и мониторить позицию.",
        "description_en": "Withdraw principal plus interest and monitor.",
        "practice_type": "balance",
        "chain": "base",
        "wallet_limit_usd": 150,
        "theory_html_ru": (
            "<p><strong>Withdraw</strong> возвращает первоначальный депозит "
            "вместе с процентами, накопившимися за время удержания. "
            "Соответствующий aToken при этом автоматически сжигается (burn).</p>"
            "<p>Перед крупным выводом проверяйте доступную ликвидность в пуле: "
            "если она временно исчерпана заёмщиками, вывод может быть "
            "недоступен сразу. Позицию важно мониторить — ставки и риски "
            "протокола меняются со временем.</p>"
            "<p><strong>Kill-rule</strong> — заранее прописанное условие, при "
            "срабатывании которого вы немедленно выходите из позиции, не "
            "раздумывая и не надеясь на разворот.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> выведите свой депозит из Aave "
            "(withdraw), убедитесь, что aToken сожжён, а стейбл с процентами "
            "вернулся на кошелёк. Сформулируйте свой личный kill-rule.</p>"
            + _SAFETY_NOTE
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> у SPA — двухуровневый "
            "kill-switch (SOFT-derisk при −5%, HARD all-cash при −10%): выход "
            "заранее задан правилом, а не эмоцией. Ваш аналог: определите "
            "kill-rule до входа и исполняйте его механически.</p>"
        ),
    },
    # ── M7 — Инциденты (СЛОЖНЫЙ модуль, порог квиза 80%) ─────────────────────
    7: {
        "id": 7,
        "title_ru": "Инциденты и защита",
        "title_en": "Incidents and defence",
        "description_ru": "Фишинг, drainer-подписи, permit и как реагировать.",
        "description_en": "Phishing, drainer signatures, permits, and response.",
        "practice_type": "quiz_only",
        "chain": "none",
        "wallet_limit_usd": 150,
        "theory_html_ru": (
            "<p>Большинство потерь — не взлом протокола, а обман пользователя. "
            "Фишинговый сайт маскируется под настоящий: сверяйте точный URL, "
            "HTTPS и источник ссылки. <strong>Drainer-подпись</strong> — "
            "вредоносный approve/permit, отдающий все токены злоумышленнику.</p>"
            "<p><strong>Permit (EIP-2612)</strong> опаснее обычного approval: "
            "это подпись, а не транзакция — жертва не платит газ, не видит её в "
            "истории, а атакующий может предъявить её позже. Если permit ещё не "
            "исполнен — отзывайте разрешение (revoke.cash / etherscan); если "
            "уже исполнен, отмена невозможна.</p>"
            "<p>Правила гигиены: заходите по сохранённым закладкам, а не по "
            "ссылкам из чатов; при каждой подписи проверяйте адрес контракта и "
            "что именно подписываете; hardware wallet защищает ключи от "
            "заражённого ПК, но не от вашей собственной вредоносной подписи.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> это самый сложный модуль — пройдите "
            "квиз по инцидентам (≥10 вопросов, порог 80%). Разберите каждый "
            "сценарий: фишинг, drainer, застрявший pending, отзыв permit.</p>"
            + _SAFETY_NOTE
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> SPA — refusal-first: "
            "он скорее откажется от доходности, которая лишь компенсирует "
            "скрытый хвостовой риск, чем подпишется под ним; threat-reactor "
            "автоматически поднимает kill-switch при критической угрозе "
            "удерживаемому протоколу. Ваш аналог: подозрительное — отклоняйте, "
            "не подписывайте на всякий случай.</p>"
        ),
    },
    # ── M8 — Капстоун (без серверного квиза; notes + on-chain) ───────────────
    8: {
        "id": 8,
        "title_ru": "Капстоун",
        "title_en": "Capstone",
        "description_ru": "Сквозной прогон пути и рефлексия — без квиза.",
        "description_en": "An end-to-end run of the path and reflection.",
        "practice_type": "capstone",
        "chain": "base",
        "wallet_limit_usd": 150,
        "theory_html_ru": (
            "<p>Капстоун связывает всё вместе: вы самостоятельно проходите "
            "полный цикл — кошелёк → сеть → депозит → мониторинг → вывод — на "
            "Base, оставаясь в пределах учебного лимита.</p>"
            "<p>У этого модуля <strong>нет серверного квиза</strong>. Его "
            "прохождение подтверждается вашими заметками (рефлексией пройденного "
            "пути) и реальным on-chain действием, а не тестом.</p>"
            "<p>Задача — не заработать, а доказать себе, что вы владеете "
            "механикой и дисциплиной: действуете по правилам, а не по эмоциям.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> выполните полный цикл на Base в "
            "пределах лимита и запишите в заметки рефлексию: что было сложным, "
            "какой ваш kill-rule, чему научились. Подтверждение — on-chain "
            "действие + заметки, без квиза.</p>" + _SAFETY_NOTE
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> SPA доказывает свой "
            "track record непрерывным честным paper-циклом с проверяемым "
            "evidence, прежде чем управлять внешним капиталом. Ваш капстоун — "
            "то же: доказанная дисциплина, а не обещание.</p>"
        ),
    },
}

# Lessons served in order.
LESSON_IDS: List[int] = sorted(MODULES.keys())


def get_module(lesson_id: int) -> dict:
    """Return the full ModuleMeta for *lesson_id* (raises KeyError if unknown)."""
    return MODULES[lesson_id]


def list_modules() -> List[dict]:
    """Return every ModuleMeta in lesson order."""
    return [MODULES[i] for i in LESSON_IDS]
