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


def _svg_seed(lang: str) -> str:
    """Inline SVG: one seed phrase → private key → many public addresses (HD derivation)."""
    if lang == "en":
        t = ("Seed phrase (12 words)", "the master key — never share", "private key",
             "Address 1", "Address 2", "Address 3", "one seed derives many addresses")
    else:
        t = ("Seed-фраза (12 слов)", "мастер-ключ — никому и никогда", "приватный ключ",
             "Адрес 1", "Адрес 2", "Адрес 3", "один seed рождает много адресов")
    return (
        '<figure class="diagram"><svg viewBox="0 0 600 230" role="img" '
        'style="width:100%;max-width:560px;height:auto;font-family:system-ui,sans-serif">'
        '<rect x="150" y="12" width="300" height="52" rx="10" fill="rgba(239,68,68,.10)" stroke="#ef4444" stroke-width="1.5"/>'
        f'<text x="300" y="34" text-anchor="middle" fill="#ef4444" font-size="15" font-weight="700">🔑 {t[0]}</text>'
        f'<text x="300" y="52" text-anchor="middle" fill="#e5e7eb" font-size="11">{t[1]}</text>'
        f'<text x="300" y="92" text-anchor="middle" fill="#9ca3af" font-size="12" font-family="monospace">↓ {t[2]}</text>'
        '<line x1="300" y1="100" x2="120" y2="140" stroke="#14b8a6" stroke-width="1.2"/>'
        '<line x1="300" y1="100" x2="300" y2="140" stroke="#14b8a6" stroke-width="1.2"/>'
        '<line x1="300" y1="100" x2="480" y2="140" stroke="#14b8a6" stroke-width="1.2"/>'
        + "".join(
            f'<rect x="{x-70}" y="140" width="140" height="40" rx="8" fill="rgba(20,184,166,.08)" stroke="#14b8a6" stroke-width="1.2"/>'
            f'<text x="{x}" y="165" text-anchor="middle" fill="#14b8a6" font-size="12">{lbl}</text>'
            for x, lbl in ((120, t[3]), (300, t[4]), (480, t[5])))
        + f'<text x="300" y="212" text-anchor="middle" fill="#9ca3af" font-size="12">{t[6]}</text>'
        '</svg></figure>'
    )


def _svg_rollup(lang: str) -> str:
    """Inline SVG: Base L2 batches many txs into one L1 post — cost shared → low fees."""
    if lang == "en":
        t = ("many Base txs", "Base (L2) rolls them into one batch", "1 post to Ethereum (L1)",
             "L1 cost ÷ many txs = tiny fee each")
    else:
        t = ("много tx на Base", "Base (L2) сворачивает их в один пакет", "1 запись в Ethereum (L1)",
             "стоимость L1 ÷ много tx = крошечная комиссия")
    return (
        '<figure class="diagram"><svg viewBox="0 0 600 210" role="img" '
        'style="width:100%;max-width:560px;height:auto;font-family:system-ui,sans-serif">'
        + "".join(f'<rect x="{18+i*26}" y="{28+i*8}" width="90" height="26" rx="5" fill="rgba(20,184,166,.10)" stroke="#14b8a6" stroke-width="1"/>'
                  for i in range(4))
        + f'<text x="95" y="150" text-anchor="middle" fill="#9ca3af" font-size="12">{t[0]}</text>'
        '<rect x="210" y="60" width="180" height="60" rx="10" fill="rgba(20,184,166,.08)" stroke="#14b8a6" stroke-width="1.5"/>'
        f'<text x="300" y="86" text-anchor="middle" fill="#14b8a6" font-size="12" font-weight="700">📦 Base L2</text>'
        f'<text x="300" y="104" text-anchor="middle" fill="#e5e7eb" font-size="10">{t[1]}</text>'
        '<line x1="160" y1="90" x2="208" y2="90" stroke="#14b8a6" stroke-width="1.5" marker-end="url(#a)"/>'
        '<line x1="392" y1="90" x2="470" y2="90" stroke="#8b5cf6" stroke-width="1.5" marker-end="url(#a)"/>'
        '<defs><marker id="a" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto">'
        '<path d="M0,0 L6,3 L0,6 Z" fill="#9ca3af"/></marker></defs>'
        '<rect x="472" y="60" width="118" height="60" rx="10" fill="rgba(139,92,246,.10)" stroke="#8b5cf6" stroke-width="1.5"/>'
        f'<text x="531" y="94" text-anchor="middle" fill="#8b5cf6" font-size="11" font-weight="700">⛓ Ethereum L1</text>'
        f'<text x="300" y="188" text-anchor="middle" fill="#9ca3af" font-size="12">{t[3]}</text>'
        '</svg></figure>'
    )


_SVG_SEED_RU, _SVG_SEED_EN = _svg_seed("ru"), _svg_seed("en")
_SVG_ROLLUP_RU, _SVG_ROLLUP_EN = _svg_rollup("ru"), _svg_rollup("en")


def _svg_txflow(lang: str) -> str:
    """Inline SVG: transaction lifecycle — submitted → pending → in a block → confirmed."""
    if lang == "en":
        steps = ("You send", "Pending", "In a block", "Confirmed")
        cap = "each step is public — look it up by tx hash in an explorer"
    else:
        steps = ("Вы отправили", "Pending", "В блоке", "Подтверждено")
        cap = "каждый шаг публичен — ищите по tx hash в explorer"
    boxes = ""
    for i, s in enumerate(steps):
        x = 12 + i * 148
        col = "#8b5cf6" if i == 0 else ("#f59e0b" if i == 1 else "#14b8a6")
        boxes += (f'<rect x="{x}" y="55" width="120" height="42" rx="8" fill="rgba(148,163,184,.06)" '
                  f'stroke="{col}" stroke-width="1.4"/>'
                  f'<text x="{x+60}" y="81" text-anchor="middle" fill="{col}" font-size="13" font-weight="600">{s}</text>')
        if i < 3:
            boxes += f'<text x="{x+134}" y="81" text-anchor="middle" fill="#9ca3af" font-size="16">→</text>'
    return ('<figure class="diagram"><svg viewBox="0 0 600 130" role="img" '
            'style="width:100%;max-width:560px;height:auto;font-family:system-ui,sans-serif">'
            + boxes +
            f'<text x="300" y="120" text-anchor="middle" fill="#9ca3af" font-size="12">{cap}</text>'
            '</svg></figure>')


def _svg_approval(lang: str) -> str:
    """Inline SVG: approval grants a contract the right to spend up to a limit — limited vs unlimited."""
    if lang == "en":
        t = ("Your wallet", "approve(limit)", "Contract", "can spend UP TO the limit",
             "✅ limited = capped loss", "⛔ unlimited = whole balance at risk")
    else:
        t = ("Ваш кошелёк", "approve(лимит)", "Контракт", "может тратить ДО лимита",
             "✅ лимит = потеря ограничена", "⛔ безлимит = под риском весь баланс")
    return ('<figure class="diagram"><svg viewBox="0 0 600 170" role="img" '
            'style="width:100%;max-width:560px;height:auto;font-family:system-ui,sans-serif">'
            '<rect x="20" y="30" width="180" height="50" rx="10" fill="rgba(20,184,166,.08)" stroke="#14b8a6" stroke-width="1.5"/>'
            f'<text x="110" y="60" text-anchor="middle" fill="#14b8a6" font-size="14" font-weight="700">👛 {t[0]}</text>'
            '<line x1="200" y1="55" x2="398" y2="55" stroke="#9ca3af" stroke-width="1.4" marker-end="url(#ap)"/>'
            f'<text x="300" y="48" text-anchor="middle" fill="#e5e7eb" font-size="12" font-family="monospace">{t[1]}</text>'
            f'<text x="300" y="72" text-anchor="middle" fill="#9ca3af" font-size="11">{t[3]}</text>'
            '<defs><marker id="ap" markerWidth="7" markerHeight="7" refX="5" refY="3" orient="auto">'
            '<path d="M0,0 L6,3 L0,6 Z" fill="#9ca3af"/></marker></defs>'
            '<rect x="400" y="30" width="180" height="50" rx="10" fill="rgba(139,92,246,.08)" stroke="#8b5cf6" stroke-width="1.5"/>'
            f'<text x="490" y="60" text-anchor="middle" fill="#8b5cf6" font-size="14" font-weight="700">📄 {t[2]}</text>'
            f'<text x="300" y="120" text-anchor="middle" fill="#14b8a6" font-size="12">{t[4]}</text>'
            f'<text x="300" y="146" text-anchor="middle" fill="#ef4444" font-size="12">{t[5]}</text>'
            '</svg></figure>')


_SVG_TXFLOW_RU, _SVG_TXFLOW_EN = _svg_txflow("ru"), _svg_txflow("en")
_SVG_APPROVAL_RU, _SVG_APPROVAL_EN = _svg_approval("ru"), _svg_approval("en")


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
            "<p><strong>Некастодиальный кошелёк</strong> — это пара ключей, которой владеете только вы. "
            "Никакая биржа и никакой сервис не могут заморозить или изъять средства. Обратная сторона: "
            "ответственность тоже только на вас.</p>"
            + _SVG_SEED_RU +
            "<h4>Как это устроено</h4>"
            "<p><strong>Seed-фраза</strong> (обычно 12 слов по стандарту BIP-39) — это мастер-ключ. Из неё "
            "детерминированно выводится приватный ключ, а из него — множество адресов (HD-деривация). "
            "Поэтому один seed — это доступ ко ВСЕМ вашим адресам сразу. Потеря seed = потеря доступа "
            "навсегда; утечка seed = кража всего. Опциональная <em>passphrase</em> (25-е слово) создаёт "
            "отдельный «скрытый» кошелёк поверх того же seed.</p>"
            "<h4>Разбор на примере</h4>"
            "<p>Вы записываете 12 слов на бумагу и кладёте в сейф. Даже если ноутбук украдут или сломается — "
            "по этим 12 словам вы восстановите кошелёк на любом устройстве. <strong>SIWE</strong> "
            "(Sign-In With Ethereum) — вход по криптографической подписи: вы доказываете владение адресом, "
            "подписав сообщение. Подпись бесплатна и НЕ двигает средства — это не транзакция.</p>"
            "<h4>Что может пойти не так</h4>"
            "<ul>"
            "<li><strong>Seed в цифре.</strong> Скриншот, облако, заметка, переписка — всё это векторы кражи. "
            "Seed хранят ТОЛЬКО офлайн, физически.</li>"
            "<li><strong>Фейковый «саппорт».</strong> Никто и никогда не имеет права спрашивать seed — ни "
            "поддержка, ни «валидатор», ни этот курс. Любой такой запрос = мошенничество.</li>"
            "<li><strong>Hot vs hardware.</strong> Hot-кошелёк (в браузере/телефоне) удобен, но ключ на "
            "устройстве с интернетом. <em>Hardware wallet</em> держит ключ изолированно — для крупных сумм "
            "это резко безопаснее.</li>"
            "</ul>"
            "<p class=\"glossary\"><strong>Словарь:</strong> <em>seed-фраза</em> — 12 слов, мастер-ключ; "
            "<em>приватный ключ</em> — то, чем подписывают; <em>HD-деривация</em> — вывод многих адресов из "
            "одного seed; <em>passphrase</em> — 25-е слово, скрытый кошелёк; <em>SIWE</em> — вход подписью.</p>"
        ),
        "theory_html_en": (
            "<p>A <strong>non-custodial wallet</strong> is a key pair only you own. No exchange or service "
            "can freeze or seize the funds. The flip side: the responsibility is entirely yours too.</p>"
            + _SVG_SEED_EN +
            "<h4>How it works</h4>"
            "<p>A <strong>seed phrase</strong> (usually 12 words, the BIP-39 standard) is the master key. It "
            "deterministically derives a private key, and from that, many addresses (HD derivation). So one "
            "seed is access to ALL your addresses at once. Lose the seed = lose access forever; leak the seed "
            "= lose everything. An optional <em>passphrase</em> (a 25th word) creates a separate \"hidden\" "
            "wallet on top of the same seed.</p>"
            "<h4>Worked example</h4>"
            "<p>You write the 12 words on paper and put it in a safe. Even if the laptop is stolen or dies, "
            "those 12 words restore the wallet on any device. <strong>SIWE</strong> (Sign-In With Ethereum) "
            "is sign-in by cryptographic signature: you prove you own an address by signing a message. The "
            "signature is free and does NOT move funds — it is not a transaction.</p>"
            "<h4>What can go wrong</h4>"
            "<ul>"
            "<li><strong>Seed in digital form.</strong> A screenshot, cloud note, or chat message are all "
            "theft vectors. Store the seed OFFLINE only, physically.</li>"
            "<li><strong>Fake \"support.\"</strong> No one may ever ask for your seed — not support, not a "
            "\"validator,\" not this course. Any such request is a scam.</li>"
            "<li><strong>Hot vs hardware.</strong> A hot wallet (browser/phone) is convenient but the key "
            "lives on an internet-connected device. A <em>hardware wallet</em> keeps the key isolated — for "
            "larger sums that is dramatically safer.</li>"
            "</ul>"
            "<p class=\"glossary\"><strong>Glossary:</strong> <em>seed phrase</em> — 12 words, the master "
            "key; <em>private key</em> — what signs; <em>HD derivation</em> — deriving many addresses from "
            "one seed; <em>passphrase</em> — a 25th word, a hidden wallet; <em>SIWE</em> — sign-in by "
            "signature.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> надёжно сохраните seed-фразу учебного кошелька офлайн, затем "
            "войдите в Академию через SIWE-подпись. Вы подтверждаете владение адресом, ничего не переводя.</p>"
            "<p><strong>Шаги:</strong> (1) создайте кошелёк и запишите 12 слов на бумагу (не в цифру); "
            "(2) уберите бумагу в защищённое место; (3) нажмите «Войти через кошелёк» и подпишите сообщение; "
            "(4) убедитесь, что вход прошёл без какой-либо транзакции.</p>" + _SAFETY_NOTE
        ),
        "practice_html_en": (
            "<p><strong>Task:</strong> safely store your practice wallet's seed phrase offline, then sign in "
            "to the Academy via a SIWE signature. You prove you own the address without transferring "
            "anything.</p>"
            "<p><strong>Steps:</strong> (1) create a wallet and write the 12 words on paper (not digitally); "
            "(2) put the paper somewhere secure; (3) click \"Sign in with wallet\" and sign the message; "
            "(4) confirm the sign-in happened with no transaction at all.</p>" + _SAFETY_NOTE_EN
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> SPA принципиально non-custodial и никогда не хранит "
            "приватных ключей или seed — вся архитектура запрещает подпись и движение средств из read-only "
            "кода (это захардкожено, а не «политика»). Тот же принцип для вас: ключи — только ваши, курс их "
            "не видит и не может видеть. Custody — это не фича, это то, чего у сервиса НЕ должно быть.</p>"
        ),
        "spa_connection_html_en": (
            "<p><strong>What SPA would do here:</strong> SPA is non-custodial on principle and never stores "
            "private keys or seeds — the whole architecture forbids signing and fund movement from read-only "
            "code (hard-coded, not a \"policy\"). The same principle for you: the keys are yours alone, the "
            "course does not and cannot see them. Custody is not a feature — it is the thing a service "
            "should NOT have.</p>"
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
            "<p><strong>Газ</strong> — это вычислительная стоимость транзакции, оплачиваемая в ETH. Любое "
            "действие on-chain, даже перевод стейблкоина, требует немного ETH на газ. Нет ETH — не можете "
            "сделать ничего, даже если на балансе полно USDC.</p>"
            + _SVG_ROLLUP_RU +
            "<h4>Как это устроено</h4>"
            "<p>Base — это <strong>L2</strong> (rollup): он собирает множество транзакций в один пакет и "
            "публикует их в Ethereum (L1) вместе, деля дорогую L1-стоимость на всех. Поэтому комиссии на "
            "Base кратно ниже, чем на mainnet. Chain ID Base — <code>8453</code>. Комиссия складывается из "
            "<em>base fee</em> (цена сети) + <em>priority fee</em> (чаевые за скорость) + доли L1-data-fee.</p>"
            "<h4>Разбор на примере</h4>"
            "<p>Перевод USDC на Ethereum mainnet может стоить несколько долларов газа; тот же перевод на "
            "Base — центы. Разница — ровно эффект rollup'а. Держите на кошельке маленькую ETH-подушку "
            "(например, эквивалент $2-5): её хватит на десятки операций.</p>"
            "<h4>Что может пойти не так</h4>"
            "<ul>"
            "<li><strong>Ноль ETH на газ.</strong> Завели только USDC — и не можете даже его отправить. "
            "Всегда держите немного ETH именно в той сети, где действуете.</li>"
            "<li><strong>Revert съедает газ.</strong> Если транзакция падает (недостаточно газа, ошибка "
            "контракта), потраченный газ НЕ возвращается. Проверяйте параметры до подтверждения.</li>"
            "<li><strong>Не та сеть для газа.</strong> ETH на Ethereum не оплатит газ на Base — газ нужен "
            "в той же сети. Мосты (bridge) переносят активы между сетями, но это отдельный риск.</li>"
            "</ul>"
            "<p class=\"glossary\"><strong>Словарь:</strong> <em>газ</em> — плата за вычисление в ETH; "
            "<em>L2/rollup</em> — сеть, сворачивающая tx в пакет для L1; <em>base/priority fee</em> — "
            "компоненты комиссии; <em>revert</em> — откат транзакции с потерей газа.</p>"
        ),
        "theory_html_en": (
            "<p><strong>Gas</strong> is the computational cost of a transaction, paid in ETH. Every on-chain "
            "action, even a stablecoin transfer, needs a little ETH for gas. No ETH — you can do nothing, "
            "even with a wallet full of USDC.</p>"
            + _SVG_ROLLUP_EN +
            "<h4>How it works</h4>"
            "<p>Base is an <strong>L2</strong> (rollup): it bundles many transactions into one batch and "
            "posts them to Ethereum (L1) together, splitting the expensive L1 cost across all of them. That "
            "is why Base fees are a fraction of mainnet's. Base's Chain ID is <code>8453</code>. A fee is "
            "made of a <em>base fee</em> (the network price) + a <em>priority fee</em> (a tip for speed) + a "
            "share of the L1 data fee.</p>"
            "<h4>Worked example</h4>"
            "<p>A USDC transfer on Ethereum mainnet can cost several dollars of gas; the same transfer on "
            "Base costs cents. That gap is exactly the rollup effect. Keep a small ETH cushion in the wallet "
            "(say the equivalent of $2-5): it covers dozens of actions.</p>"
            "<h4>What can go wrong</h4>"
            "<ul>"
            "<li><strong>Zero ETH for gas.</strong> You funded only USDC — and can't even send it. Always "
            "keep some ETH in the exact network you are acting on.</li>"
            "<li><strong>A revert still burns gas.</strong> If a transaction fails (out of gas, contract "
            "error), the spent gas is NOT refunded. Check the parameters before confirming.</li>"
            "<li><strong>Gas on the wrong network.</strong> ETH on Ethereum won't pay gas on Base — gas is "
            "needed on the same network. Bridges move assets between networks, but that is a separate "
            "risk.</li>"
            "</ul>"
            "<p class=\"glossary\"><strong>Glossary:</strong> <em>gas</em> — the compute fee in ETH; "
            "<em>L2/rollup</em> — a network that batches txs for L1; <em>base/priority fee</em> — fee "
            "components; <em>revert</em> — a transaction rollback that still costs gas.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> переведите учебный кошелёк в сеть Base (mainnet), заведите на него "
            "малую сумму в пределах лимита и убедитесь, что на балансе есть немного ETH на газ.</p>"
            "<p><strong>Шаги:</strong> (1) переключите кошелёк на Base (Chain ID 8453); (2) заведите немного "
            "ETH на газ + учебную сумму USDC (в пределах ≤$150); (3) проверьте, что баланс ETH > 0; "
            "(4) убедитесь, что видите оба баланса в кошельке.</p>" + _SAFETY_NOTE
        ),
        "practice_html_en": (
            "<p><strong>Task:</strong> move your practice wallet to the Base network (mainnet), fund it with "
            "a small amount within the limit, and confirm you have a little ETH for gas.</p>"
            "<p><strong>Steps:</strong> (1) switch the wallet to Base (Chain ID 8453); (2) add a little ETH "
            "for gas + a practice USDC amount (within ≤$150); (3) check that the ETH balance is > 0; "
            "(4) confirm you can see both balances in the wallet.</p>" + _SAFETY_NOTE_EN
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> SPA закладывает gas-cost и breakeven в каждое "
            "решение о ребалансе — маленький трейд, который съест комиссия, он отклоняет ещё до исполнения. "
            "Ваш аналог: не гоняйте капитал туда-сюда, если комиссия сопоставима с суммой. Издержки — часть "
            "доходности, а не «мелочь после».</p>"
        ),
        "spa_connection_html_en": (
            "<p><strong>What SPA would do here:</strong> SPA builds gas cost and breakeven into every "
            "rebalance decision — a small trade the fee would eat is rejected before it ever executes. Your "
            "version: don't shuffle capital back and forth when the fee is comparable to the amount. Costs "
            "are part of the yield, not an afterthought.</p>"
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
            "<p>Транзакция — это ваша инструкция сети, которую вы <strong>подписываете</strong> и "
            "отправляете. Она не исполняется мгновенно: сперва попадает в <em>pending</em> (ждёт включения "
            "в блок), затем валидаторы включают её в блок, и она становится подтверждённой.</p>"
            + _SVG_TXFLOW_RU +
            "<h4>Как это устроено</h4>"
            "<p>У каждой транзакции есть <strong>tx hash</strong> — уникальный публичный идентификатор. По "
            "нему любой может посмотреть её в <em>block explorer</em> (например, <code>basescan.org</code>): "
            "статус, сумму, комиссию, отправителя и получателя. У каждого адреса есть <em>nonce</em> — "
            "счётчик его транзакций по порядку; он не даёт исполнить одну tx дважды и задаёт очерёдность.</p>"
            "<h4>Разбор на примере</h4>"
            "<p>Вы отправляете 5 USDC → кошелёк показывает «pending» + tx hash → через пару секунд на Base "
            "статус «Success» → открываете hash в explorer и видите перевод. Одно подтверждение на L2 уже "
            "почти финально; для крупных сумм принято дождаться нескольких блоков. Зависла в pending? Её "
            "можно <em>ускорить</em> (speed-up) или <em>отменить</em> (cancel), переотправив с тем же nonce "
            "и большей комиссией.</p>"
            "<h4>Что может пойти не так</h4>"
            "<ul>"
            "<li><strong>Нет ETH на газ</strong> → транзакция не отправится вовсе.</li>"
            "<li><strong>Неверный адрес получателя.</strong> On-chain перевод <em>необратим</em> — отправили "
            "не туда, вернуть некому. Всегда сверяйте адрес (первые и последние символы).</li>"
            "<li><strong>Нет нужного approval.</strong> Для взаимодействия с контрактом часто нужно сперва "
            "разрешение (следующий модуль) — без него tx откатится.</li>"
            "</ul>"
            "<p class=\"glossary\"><strong>Словарь:</strong> <em>pending</em> — ждёт блока; <em>tx hash</em> "
            "— публичный id транзакции; <em>block explorer</em> — обозреватель сети; <em>nonce</em> — "
            "счётчик tx адреса; <em>confirmation</em> — блок, включивший транзакцию.</p>"
        ),
        "theory_html_en": (
            "<p>A transaction is your instruction to the network, which you <strong>sign</strong> and send. "
            "It does not execute instantly: it first enters <em>pending</em> (waiting to be included in a "
            "block), then validators put it in a block, and it becomes confirmed.</p>"
            + _SVG_TXFLOW_EN +
            "<h4>How it works</h4>"
            "<p>Every transaction has a <strong>tx hash</strong> — a unique public identifier. Anyone can "
            "look it up in a <em>block explorer</em> (e.g. <code>basescan.org</code>): status, amount, fee, "
            "sender, and recipient. Each address has a <em>nonce</em> — an in-order counter of its "
            "transactions; it prevents one tx from executing twice and sets the ordering.</p>"
            "<h4>Worked example</h4>"
            "<p>You send 5 USDC → the wallet shows \"pending\" + a tx hash → seconds later on Base the status "
            "is \"Success\" → you open the hash in an explorer and see the transfer. One confirmation on L2 "
            "is nearly final; for large amounts it is customary to wait a few blocks. Stuck in pending? You "
            "can <em>speed it up</em> or <em>cancel</em> it by resending with the same nonce and a higher "
            "fee.</p>"
            "<h4>What can go wrong</h4>"
            "<ul>"
            "<li><strong>No ETH for gas</strong> → the transaction won't send at all.</li>"
            "<li><strong>Wrong recipient address.</strong> An on-chain transfer is <em>irreversible</em> — "
            "send to the wrong place and no one can return it. Always check the address (first and last "
            "characters).</li>"
            "<li><strong>Missing approval.</strong> Interacting with a contract often needs a prior allowance "
            "(next module) — without it the tx reverts.</li>"
            "</ul>"
            "<p class=\"glossary\"><strong>Glossary:</strong> <em>pending</em> — waiting for a block; "
            "<em>tx hash</em> — a transaction's public id; <em>block explorer</em> — a network viewer; "
            "<em>nonce</em> — an address's tx counter; <em>confirmation</em> — the block that included it.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> отправьте небольшой перевод стейблкоина на Base в пределах лимита "
            "и найдите свою транзакцию в basescan.org по её tx hash. Сохраните hash как доказательство.</p>"
            "<p><strong>Шаги:</strong> (1) отправьте малую сумму USDC себе или на известный адрес; "
            "(2) скопируйте tx hash из кошелька; (3) вставьте его в basescan.org; (4) убедитесь в статусе "
            "«Success» и сверьте сумму/получателя.</p>" + _SAFETY_NOTE
        ),
        "practice_html_en": (
            "<p><strong>Task:</strong> send a small stablecoin transfer on Base within the limit and find "
            "your transaction on basescan.org by its tx hash. Save the hash as proof.</p>"
            "<p><strong>Steps:</strong> (1) send a small USDC amount to yourself or a known address; "
            "(2) copy the tx hash from your wallet; (3) paste it into basescan.org; (4) confirm the "
            "\"Success\" status and check the amount/recipient.</p>" + _SAFETY_NOTE_EN
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> каждый шаг SPA оставляет проверяемый след (audit "
            "trail, on-chain proof, hash-chain) — принцип «не верь, проверь». Вы делаете то же: "
            "доказательство действия — это tx hash в explorer, а не слова. Публичная проверяемость — это то, "
            "что отличает честную систему от «поверьте нам».</p>"
        ),
        "spa_connection_html_en": (
            "<p><strong>What SPA would do here:</strong> every SPA step leaves a verifiable trail (audit "
            "trail, on-chain proof, hash-chain) — the \"don't trust, verify\" principle. You do the same: the "
            "proof of an action is the tx hash in an explorer, not words. Public verifiability is what "
            "separates an honest system from \"trust us.\"</p>"
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
            "<p><strong>Approval</strong> — разрешение смарт-контракту тратить ваши токены до указанного "
            "лимита. Сам по себе approval не двигает средства — он лишь <em>открывает</em> контракту доступ "
            "к ним. Почти любое действие в DeFi (депозит, своп) начинается с approval.</p>"
            + _SVG_APPROVAL_RU +
            "<h4>Как это устроено</h4>"
            "<p>Важно различать два разных действия. <strong>Транзакция</strong> (approve) идёт в сеть, "
            "меняет состояние и требует газа. <strong>Подпись</strong> (sign) — бесплатна, не идёт в сеть "
            "сразу, но <em>авторизует</em> действие. Особый и опасный случай — <strong>permit</strong> "
            "(EIP-2612): approval через одну лишь подпись, без отдельной on-chain tx. Одна подпись permit "
            "может отдать доступ ко всему балансу токена.</p>"
            "<h4>Разбор на примере</h4>"
            "<p>Перед вкладом в Aave кошелёк просит approve(USDC, 100) — вы разрешаете пулу списать до 100 "
            "USDC. Событие <em>Approval</em> видно в explorer. После вы делаете supply. Когда закончили — "
            "<strong>revoke</strong> (approve со значением 0) закрывает разрешение. Проверить и отозвать "
            "старые allowance удобно на <code>revoke.cash</code>.</p>"
            "<h4>Что может пойти не так</h4>"
            "<ul>"
            "<li><strong>Unlimited approval.</strong> Многие интерфейсы по умолчанию просят безлимит. Если "
            "контракт скомпрометирован — атакующий выведет весь баланс токена. Одобряйте только нужную "
            "сумму.</li>"
            "<li><strong>Drainer-подпись.</strong> Вредоносный сайт подсовывает permit/approve, отдающий всё "
            "злоумышленнику. Читайте, ЧТО подписываете — не кликайте вслепую.</li>"
            "<li><strong>Забытые allowance.</strong> Старые разрешения живут годами. Периодически "
            "ревокайте неиспользуемые.</li>"
            "</ul>"
            "<p class=\"glossary\"><strong>Словарь:</strong> <em>approval/allowance</em> — лимит трат для "
            "контракта; <em>permit (EIP-2612)</em> — approval подписью; <em>revoke</em> — approval=0; "
            "<em>подпись vs транзакция</em> — авторизация без газа vs изменение состояния с газом.</p>"
        ),
        "theory_html_en": (
            "<p>An <strong>approval</strong> lets a smart contract spend your tokens up to a stated limit. "
            "The approval itself moves no funds — it just <em>opens</em> the contract's access to them. "
            "Almost every DeFi action (deposit, swap) begins with an approval.</p>"
            + _SVG_APPROVAL_EN +
            "<h4>How it works</h4>"
            "<p>Distinguish two different actions. A <strong>transaction</strong> (approve) goes to the "
            "network, changes state, and costs gas. A <strong>signature</strong> (sign) is free, does not "
            "go on-chain immediately, but <em>authorizes</em> an action. A special and dangerous case is "
            "<strong>permit</strong> (EIP-2612): an approval via a signature alone, with no separate "
            "on-chain tx. A single permit signature can hand over access to your entire token balance.</p>"
            "<h4>Worked example</h4>"
            "<p>Before depositing to Aave, the wallet asks approve(USDC, 100) — you let the pool pull up to "
            "100 USDC. The <em>Approval</em> event is visible in an explorer. Then you supply. When done, "
            "<strong>revoke</strong> (approve with 0) closes the allowance. You can review and revoke old "
            "allowances easily at <code>revoke.cash</code>.</p>"
            "<h4>What can go wrong</h4>"
            "<ul>"
            "<li><strong>Unlimited approval.</strong> Many interfaces default to unlimited. If the contract "
            "is compromised, an attacker drains the whole token balance. Approve only the amount needed.</li>"
            "<li><strong>Drainer signature.</strong> A malicious site slips you a permit/approve that hands "
            "everything to the attacker. Read WHAT you are signing — don't click blindly.</li>"
            "<li><strong>Forgotten allowances.</strong> Old approvals persist for years. Periodically revoke "
            "the unused ones.</li>"
            "</ul>"
            "<p class=\"glossary\"><strong>Glossary:</strong> <em>approval/allowance</em> — a contract's "
            "spend limit; <em>permit (EIP-2612)</em> — approval by signature; <em>revoke</em> — approval=0; "
            "<em>signature vs transaction</em> — gasless authorization vs a state change that costs gas.</p>"
        ),
        "practice_html_ru": (
            "<p><strong>Задание:</strong> выдайте контракту approval на конкретную (не безлимитную) сумму, "
            "посмотрите событие Approval в explorer, затем отзовите его (revoke). Убедитесь, что понимаете "
            "разницу между подписью и транзакцией.</p>"
            "<p><strong>Шаги:</strong> (1) approve на конкретную сумму (не unlimited); (2) найдите событие "
            "Approval в explorer; (3) сделайте revoke (approve=0) или через revoke.cash; (4) сформулируйте "
            "своими словами разницу sign vs transaction.</p>" + _SAFETY_NOTE
        ),
        "practice_html_en": (
            "<p><strong>Task:</strong> grant a contract an approval for a specific (not unlimited) amount, "
            "view the Approval event in an explorer, then revoke it. Make sure you understand the difference "
            "between a signature and a transaction.</p>"
            "<p><strong>Steps:</strong> (1) approve a specific amount (not unlimited); (2) find the Approval "
            "event in an explorer; (3) revoke it (approve=0) or via revoke.cash; (4) state in your own words "
            "the difference between sign and transaction.</p>" + _SAFETY_NOTE_EN
        ),
        "spa_connection_html_ru": (
            "<p><strong>Что бы здесь сделал SPA:</strong> подход SPA — <em>refusal-first</em>: доступ "
            "выдаётся минимально необходимый и отзывается, когда не нужен; execution изолирован и требует "
            "явного «armed»-флага (по умолчанию всё заблокировано). Ваш аналог: минимальные approvals и "
            "регулярный revoke неиспользуемых. Наименьшая привилегия — не паранойя, а гигиена.</p>"
        ),
        "spa_connection_html_en": (
            "<p><strong>What SPA would do here:</strong> SPA is <em>refusal-first</em>: access is granted at "
            "the minimum needed and revoked when not; execution is isolated and requires an explicit "
            "\"armed\" flag (everything is blocked by default). Your version: minimal approvals and regular "
            "revokes of the unused ones. Least privilege isn't paranoia — it's hygiene.</p>"
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
