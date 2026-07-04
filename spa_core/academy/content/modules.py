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

_SAFETY_NOTE_EN = (
    "<p class=\"safety\"><strong>Safety:</strong> the practice-wallet limit is "
    "≤ $150 — do not fund more. The course never asks you to connect your main "
    "wallet. Never tell anyone your seed phrase — neither support nor this course "
    "will ever ask for it.</p>"
)


def _svg_testnet(lang: str) -> str:
    """Inline SVG: mainnet (real money, mistakes cost) vs Base Sepolia testnet (free, faucet-fed).
    Language-scoped labels; pure inline SVG (no external assets), scales, dark-theme friendly."""
    if lang == "en":
        t = ("Production Base", "real ETH · a mistake costs money", "chain 8453",
             "Base Sepolia", "test ETH · a mistake is free", "chain 84532", "faucet", "practise here first")
    else:
        t = ("Боевой Base", "реальный ETH · ошибка стоит денег", "chain 8453",
             "Base Sepolia", "тестовый ETH · ошибка бесплатна", "chain 84532", "faucet", "сначала тренируйтесь здесь")
    return (
        '<figure class="diagram"><svg viewBox="0 0 600 210" role="img" '
        'style="width:100%;max-width:560px;height:auto;font-family:system-ui,sans-serif">'
        '<rect x="8" y="20" width="270" height="150" rx="10" fill="rgba(239,68,68,.08)" stroke="#ef4444" stroke-width="1.5"/>'
        f'<text x="143" y="52" text-anchor="middle" fill="#ef4444" font-size="17" font-weight="700">{t[0]}</text>'
        f'<text x="143" y="80" text-anchor="middle" fill="#e5e7eb" font-size="12">{t[1]}</text>'
        f'<text x="143" y="140" text-anchor="middle" fill="#9ca3af" font-size="12" font-family="monospace">{t[2]}</text>'
        '<text x="143" y="112" text-anchor="middle" font-size="30">💸</text>'
        '<rect x="322" y="20" width="270" height="150" rx="10" fill="rgba(20,184,166,.08)" stroke="#14b8a6" stroke-width="1.5"/>'
        f'<text x="457" y="52" text-anchor="middle" fill="#14b8a6" font-size="17" font-weight="700">{t[3]}</text>'
        f'<text x="457" y="80" text-anchor="middle" fill="#e5e7eb" font-size="12">{t[4]}</text>'
        f'<text x="457" y="140" text-anchor="middle" fill="#9ca3af" font-size="12" font-family="monospace">{t[5]}</text>'
        '<text x="457" y="112" text-anchor="middle" font-size="30">🧪</text>'
        f'<text x="457" y="196" text-anchor="middle" fill="#14b8a6" font-size="12">💧 {t[6]} → {t[7]}</text>'
        '</svg></figure>'
    )


_SVG_TESTNET_RU = _svg_testnet("ru")
_SVG_TESTNET_EN = _svg_testnet("en")


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
            "<p><strong>Base Sepolia</strong> — это <strong>тестовая сеть</strong> (testnet): точная копия "
            "боевого Base, но токены в ней ничего не стоят. Это ваш полигон — любую ошибку здесь можно "
            "совершить бесплатно и потом повторить правильно.</p>"
            + _SVG_TESTNET_RU +
            "<h4>Как это устроено</h4>"
            "<p>Каждая сеть имеет <strong>Chain ID</strong> — числовой идентификатор, по которому кошелёк "
            "понимает, куда шлёт транзакцию. У Base Sepolia он <code>84532</code>, у боевого Base — "
            "<code>8453</code>. Кошелёк подключается к сети через <em>RPC-эндпоинт</em> (URL-шлюз к узлу). "
            "Тестовый ETH нельзя купить — его выдаёт <em>faucet</em> (кран): вы вставляете свой адрес, "
            "сервис бесплатно присылает немного тестовых монет на газ.</p>"
            "<h4>Разбор на примере</h4>"
            "<p>Вы получаете ~0.05 тестового ETH из faucet → отправляете 0.001 самому себе → транзакция "
            "попадает в блок Base Sepolia → её видно в explorer по <code>tx hash</code>. Реальные деньги "
            "не двигаются: подтверждение в тестнете значит лишь «внесено в блок тестовой сети». Это "
            "полная репетиция боевого действия — те же кнопки, тот же газ, ноль риска.</p>"
            "<h4>Что может пойти не так</h4>"
            "<ul>"
            "<li><strong>Фейковый faucet.</strong> Сайты-обманки просят «подключить кошелёк» или прислать "
            "«депозит для разблокировки». Настоящий faucet НИЧЕГО не просит, кроме адреса.</li>"
            "<li><strong>Не та сеть.</strong> Легко по привычке переключиться на mainnet и потратить "
            "реальный ETH там, где ждали тестовый. Всегда сверяйте Chain ID перед подтверждением.</li>"
            "<li><strong>Chain-ID mismatch.</strong> Транзакция, подписанная для одной сети, недействительна "
            "в другой — но подпись на фишинговом сайте может увести реальные средства. Подписывайте только "
            "то, что понимаете.</li>"
            "</ul>"
            "<p class=\"glossary\"><strong>Словарь:</strong> <em>testnet</em> — тестовая сеть с бесплатными "
            "токенами; <em>faucet</em> — кран тестовых монет; <em>Chain ID</em> — номер сети; "
            "<em>RPC</em> — шлюз кошелька к узлу; <em>tx hash</em> — публичный идентификатор транзакции.</p>"
        ),
        "theory_html_en": (
            "<p><strong>Base Sepolia</strong> is a <strong>testnet</strong>: an exact copy of production "
            "Base where the tokens are worthless. It is your practice ground — make any mistake here for "
            "free, then repeat it correctly.</p>"
            + _SVG_TESTNET_EN +
            "<h4>How it works</h4>"
            "<p>Every network has a <strong>Chain ID</strong> — a numeric identifier your wallet uses to "
            "know where it is sending a transaction. Base Sepolia's is <code>84532</code>; production Base "
            "is <code>8453</code>. The wallet reaches the network through an <em>RPC endpoint</em> (a URL "
            "gateway to a node). You cannot buy test ETH — a <em>faucet</em> hands it out: you paste your "
            "address and the service sends a little test coin for gas, free.</p>"
            "<h4>Worked example</h4>"
            "<p>You get ~0.05 test ETH from a faucet → send 0.001 to yourself → the transaction lands in a "
            "Base Sepolia block → it is visible in an explorer by its <code>tx hash</code>. No real money "
            "moves: a testnet confirmation only means \"included in a test-network block.\" It is a full "
            "dress rehearsal of the real action — same buttons, same gas, zero risk.</p>"
            "<h4>What can go wrong</h4>"
            "<ul>"
            "<li><strong>Fake faucet.</strong> Scam sites ask you to \"connect your wallet\" or send a "
            "\"deposit to unlock.\" A real faucet asks for nothing but your address.</li>"
            "<li><strong>Wrong network.</strong> It is easy to switch to mainnet out of habit and spend "
            "real ETH where you meant to spend test ETH. Always check the Chain ID before confirming.</li>"
            "<li><strong>Chain-ID mismatch.</strong> A transaction signed for one network is invalid on "
            "another — but a signature on a phishing site can still drain real funds. Only sign what you "
            "understand.</li>"
            "</ul>"
            "<p class=\"glossary\"><strong>Glossary:</strong> <em>testnet</em> — a test network with free "
            "tokens; <em>faucet</em> — a tap for test coins; <em>Chain ID</em> — the network's number; "
            "<em>RPC</em> — the wallet's gateway to a node; <em>tx hash</em> — a transaction's public id.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> создайте учебный кошелёк, получите тестовый ETH из faucet Base "
            "Sepolia и отправьте небольшую тестовую транзакцию себе. Сохраните <code>tx hash</code> — вы "
            "проверите его в block explorer (basescan.org для Sepolia).</p>"
            "<p><strong>Шаги:</strong> (1) подключите кошелёк к сети Base Sepolia (Chain ID 84532); "
            "(2) вставьте адрес в faucet и дождитесь тестового ETH; (3) отправьте 0.001 себе; "
            "(4) откройте tx hash в explorer и убедитесь в статусе «Success».</p>" + _SAFETY_NOTE
        ),
        "practice_html_en": (
            "<p><strong>Task:</strong> create a practice wallet, get test ETH from a Base Sepolia faucet, "
            "and send a small test transaction to yourself. Save the <code>tx hash</code> — you will check "
            "it in a block explorer (basescan.org for Sepolia).</p>"
            "<p><strong>Steps:</strong> (1) connect your wallet to Base Sepolia (Chain ID 84532); "
            "(2) paste your address into a faucet and wait for the test ETH; (3) send 0.001 to yourself; "
            "(4) open the tx hash in an explorer and confirm the \"Success\" status.</p>" + _SAFETY_NOTE_EN
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> SPA начинает всё новое в песочнице "
            "(<em>paper trading</em>) — с виртуальным капиталом, прежде чем рисковать реальным. Тестнет для "
            "вас — ровно то же, что paper-режим для SPA: сначала доказать механику без риска, только потом "
            "реальные деньги. Этот принцип «докажи в песочнице» — не осторожность ради осторожности, а "
            "способ отделить настоящий edge от случайной удачи.</p>"
        ),
        "spa_connection_html_en": (
            "<p><strong>What SPA would do here:</strong> SPA starts everything new in a sandbox "
            "(<em>paper trading</em>) — with virtual capital, before risking real money. A testnet is to "
            "you exactly what paper mode is to SPA: prove the mechanics with zero risk first, real money "
            "only after. That \"prove it in the sandbox\" rule is not caution for its own sake — it is how "
            "you separate a genuine edge from lucky noise.</p>"
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
            "<div class=\"checklist\"><p><strong>Печатный чеклист «перед каждой "
            "подписью» (11 пунктов):</strong></p><ol>"
            "<li>Я зашёл по своей закладке, а не по ссылке из чата/письма/рекламы.</li>"
            "<li>Точный URL и HTTPS-замок совпадают с официальным доменом (без "
            "подмены букв).</li>"
            "<li>Я понимаю, что именно подписываю: транзакция или подпись "
            "(permit/off-chain).</li>"
            "<li>Адрес контракта совпадает с официальным адресом протокола.</li>"
            "<li>Сумма approval — конкретная и минимальная, а не «unlimited».</li>"
            "<li>Spender (кому даю доступ) — это тот контракт, что я ожидаю.</li>"
            "<li>Это не «сбор наград»/«клейм»/«разблокировка» от неизвестного сайта.</li>"
            "<li>Симуляция кошелька не показывает вывод всех токенов/NFT.</li>"
            "<li>Меня не торопят и не пугают срочностью («успей за 5 минут»).</li>"
            "<li>Hardware-кошелёк показывает те же адрес и данные, что и экран.</li>"
            "<li>Если хоть один пункт вызывает сомнение — я отклоняю подпись.</li>"
            "</ol></div>" + _SAFETY_NOTE
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
            "пределах лимита (свежие Supply и Withdraw в рамках капстоуна) и "
            "запишите в заметки рефлексию по трём вопросам: <em>что вас "
            "удивило</em> на этом пути; <em>что вы бы автоматизировали</em> "
            "(и почему); <em>что осознанно оставили бы ручным</em> (и почему). "
            "Подтверждение — on-chain действие + заметки, без квиза.</p>"
            + _SAFETY_NOTE
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
