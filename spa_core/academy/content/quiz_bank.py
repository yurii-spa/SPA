"""
spa_core/academy/content/quiz_bank.py

Server-side quiz bank for Academy modules 0–8.

Structure:
    QUIZ_BANK: dict[int, list[Question]]
    Question: {
        "id": int,             # 1-based, stable within a module
        "text": str,
        "options": list[str],
        "correct_idx": int,    # SERVER-SIDE ONLY — never serialised to a client
        "explanation": str,
    }

Rules / invariants:
  - Each module has >=5 questions (M7 has >=10, and is harder).
  - Passing score: 80% (a question is right iff the chosen option index equals
    correct_idx; the pass threshold uses math.ceil so an 8/10 on M7 passes).
  - ``correct_idx`` and ``explanation`` are SERVER-SIDE ONLY. The only surface
    that ever leaves this process to a client is :func:`get_questions`, which
    strips both keys. Grading happens exclusively via :func:`grade_answers`.
  - M8 (capstone) has NO server-graded quiz: QUIZ_BANK[8] == []. An empty bank
    means :func:`grade_answers` returns score=100.0 / passed=True (auto-pass);
    the M8 gate lives entirely in notes + on-chain verification.

LLM FORBIDDEN in this module (deterministic content + grading, no model calls).
Academy stage 4.
"""

from __future__ import annotations

import math
from typing import Dict, List

# Pass threshold as a fraction of questions answered correctly.
PASS_FRACTION = 0.80


# ── Quiz bank ────────────────────────────────────────────────────────────────
# Every module is a plain list of Question dicts. correct_idx points at the
# 0-based index of the right option. Options are deliberately concrete so the
# distractors are plausible but wrong.

QUIZ_BANK: Dict[int, List[dict]] = {
    # ── M0 — Base Sepolia (testnet) ──────────────────────────────────────────
    0: [
        {
            "id": 1,
            "text": "Для чего нужен Base Sepolia?",
            "text_en": "What is Base Sepolia for?",
            "options": ["Хранить реальные деньги", "Тренироваться без риска", "Получить прибыль", "Майнинг ETH"],
            "options_en": ["Storing real money", "Practising risk-free", "Making a profit", "Mining ETH"],
            "correct_idx": 1,
            "explanation": (
                "Base Sepolia — это тестовая сеть (testnet). Токены в ней не "
                "стоят денег, поэтому на ней безопасно отрабатывать действия "
                "перед выходом в mainnet."
            ),
            "explanation_en": (
                "Base Sepolia is a testnet. Its tokens are worthless, so it's a safe place to rehearse "
                "actions before going to mainnet."
            ),
        },
        {
            "id": 2,
            "text": "Что такое faucet?",
            "text_en": "What is a faucet?",
            "options": ["Кошелёк для хранения ключей", "Сервис для получения тестового ETH бесплатно",
                        "Биржа для обмена токенов", "Смарт-контракт кредитования"],
            "options_en": ["A wallet for storing keys", "A service that gives out test ETH for free",
                           "An exchange for swapping tokens", "A lending smart contract"],
            "correct_idx": 1,
            "explanation": (
                "Faucet («кран») бесплатно выдаёт небольшое количество "
                "тестового ETH, чтобы оплачивать газ в тестовой сети."
            ),
            "explanation_en": (
                "A faucet gives out a small amount of test ETH for free, to pay for gas on the test network."
            ),
        },
        {
            "id": 3,
            "text": "Testnet-транзакция подтверждена — это значит...",
            "text_en": "A testnet transaction is confirmed — this means...",
            "options": ["Вы заработали реальные деньги", "Транзакция внесена в блок тестнета, реальных денег нет",
                        "Средства выведены на биржу", "Транзакция ждёт ручного одобрения"],
            "options_en": ["You earned real money", "The tx is in a testnet block; no real money moved",
                           "Funds were sent to an exchange", "The tx awaits manual approval"],
            "correct_idx": 1,
            "explanation": (
                "Подтверждение в тестнете означает лишь включение транзакции в "
                "блок тестовой сети; никакой реальной стоимости при этом не "
                "перемещается."
            ),
            "explanation_en": (
                "A testnet confirmation only means the tx was included in a test-network block; no real "
                "value moves."
            ),
        },
        {
            "id": 4,
            "text": "Chain ID сети Base Sepolia?",
            "text_en": "What is Base Sepolia's Chain ID?",
            "options": ["1", "137", "8453", "84532"],
            "options_en": ["1", "137", "8453", "84532"],
            "correct_idx": 3,
            "explanation": (
                "Chain ID Base Sepolia — 84532. (1 — Ethereum mainnet, 137 — "
                "Polygon, 8453 — Base mainnet.)"
            ),
            "explanation_en": (
                "Base Sepolia's Chain ID is 84532. (1 = Ethereum mainnet, 137 = Polygon, 8453 = Base "
                "mainnet.)"
            ),
        },
        {
            "id": 5,
            "text": "После практики на тестнете стоит...",
            "text_en": "After practising on the testnet you should...",
            "options": ["Сразу вложить крупную сумму в mainnet", "Повторить те же действия на mainnet с малой суммой",
                        "Больше никогда не заходить в mainnet", "Продать тестовый ETH за реальные деньги"],
            "options_en": ["Immediately put a large sum into mainnet", "Repeat the same steps on mainnet with a small amount",
                           "Never touch mainnet again", "Sell the test ETH for real money"],
            "correct_idx": 1,
            "explanation": (
                "Тестнет — это репетиция. Переходя в mainnet, повторяйте те же "
                "шаги с маленькой суммой (учебный лимит ≤ $150), а не сразу с "
                "большим капиталом."
            ),
            "explanation_en": (
                "A testnet is a rehearsal. Moving to mainnet, repeat the same steps with a small amount "
                "(the ≤ $150 educational limit), not a large capital at once."
            ),
        },
        {
            "id": 6,
            "text": "Сайт-«faucet» просит подключить кошелёк и прислать депозит «для разблокировки». Это...",
            "text_en": "A \"faucet\" site asks you to connect your wallet and send a deposit \"to unlock.\" This is...",
            "options": ["Нормально для faucet", "Признак мошенничества — настоящий faucet просит только адрес",
                        "Обязательный шаг верификации", "Способ ускорить выдачу"],
            "options_en": ["Normal for a faucet", "A scam sign — a real faucet asks only for your address",
                           "A required verification step", "A way to speed up the payout"],
            "correct_idx": 1,
            "explanation": (
                "Настоящий faucet НИЧЕГО не просит, кроме адреса. Просьба «подключить кошелёк» или прислать "
                "депозит — типичный фишинг/drainer."
            ),
            "explanation_en": (
                "A real faucet asks for nothing but your address. A request to \"connect your wallet\" or "
                "send a deposit is classic phishing/drainer behaviour."
            ),
        },
    ],
    # ── M1 — Кошелёк и сид-фраза ─────────────────────────────────────────────
    1: [
        {
            "id": 1,
            "text": "Кому можно показывать seed-фразу?",
            "options": [
                "Службе поддержки протокола",
                "Никому и никогда",
                "Только доверенному другу",
                "Сайту, если он выглядит официально",
            ],
            "correct_idx": 1,
            "explanation": (
                "Seed-фраза — это мастер-ключ ко всем средствам. Её нельзя "
                "показывать никому и никогда; настоящая поддержка её не просит."
            ),
        },
        {
            "id": 2,
            "text": "Что произойдёт, если потерять seed-фразу?",
            "options": [
                "Кошелёк восстановится по email",
                "Потеряете доступ к кошельку навсегда",
                "Средства автоматически вернутся на биржу",
                "Ничего, ключ хранится в браузере",
            ],
            "correct_idx": 1,
            "explanation": (
                "Без seed-фразы восстановить самостоятельный (non-custodial) "
                "кошелёк невозможно — доступ к средствам теряется навсегда."
            ),
        },
        {
            "id": 3,
            "text": "SIWE (Sign-In With Ethereum) — это...",
            "options": [
                "Перевод средств на сайт",
                "Стандарт подтверждения владения адресом через подпись",
                "Способ раскрыть приватный ключ сервису",
                "Комиссия за вход в приложение",
            ],
            "correct_idx": 1,
            "explanation": (
                "SIWE — вход через криптографическую подпись, доказывающую "
                "владение адресом. Подпись бесплатна и не двигает средства."
            ),
        },
        {
            "id": 4,
            "text": "Бумажный бэкап seed хранить...",
            "options": [
                "В облаке и в переписке для надёжности",
                "В физически защищённом месте, не в цифровом виде",
                "Скриншотом в галерее телефона",
                "В открытом текстовом файле на рабочем столе",
            ],
            "correct_idx": 1,
            "explanation": (
                "Цифровые копии seed (фото, файлы, облако) уязвимы к взлому. "
                "Надёжнее — офлайн-бэкап в физически защищённом месте."
            ),
        },
        {
            "id": 5,
            "text": "Что такое hardware wallet?",
            "options": [
                "Онлайн-биржа с высокой доходностью",
                "Устройство, хранящее ключи оффлайн",
                "Расширение браузера с паролем",
                "Резервная копия seed в облаке",
            ],
            "correct_idx": 1,
            "explanation": (
                "Аппаратный кошелёк хранит приватные ключи на изолированном "
                "устройстве, недоступном заражённому компьютеру."
            ),
        },
    ],
    # ── M2 — Сети и газ ──────────────────────────────────────────────────────
    2: [
        {
            "id": 1,
            "text": "Почему Base дешевле Ethereum mainnet?",
            "options": [
                "Base — L2, батчует транзакции",
                "Base не использует блокчейн",
                "Base субсидирует газ из своего кармана",
                "На Base нет комиссий вообще",
            ],
            "correct_idx": 0,
            "explanation": (
                "Base — это L2 (rollup): он собирает много транзакций в пакет и "
                "публикует их в L1 вместе, деля стоимость → комиссии ниже."
            ),
        },
        {
            "id": 2,
            "text": "Gas — это...",
            "options": [
                "Токен для голосования",
                "Вычислительная стоимость транзакции в ETH",
                "Комиссия биржи за вывод",
                "Проценты по депозиту",
            ],
            "correct_idx": 1,
            "explanation": (
                "Газ — мера вычислительной работы транзакции; оплачивается в "
                "ETH и достаётся тем, кто обрабатывает сеть."
            ),
        },
        {
            "id": 3,
            "text": "Если газ закончился до завершения транзакции...",
            "options": [
                "Транзакция завершится позже сама",
                "Транзакция откатывается, ETH за газ всё равно списывается",
                "ETH за газ полностью возвращается",
                "Сеть доплатит недостающий газ",
            ],
            "correct_idx": 1,
            "explanation": (
                "При нехватке газа транзакция откатывается (revert), но "
                "потраченный на вычисления газ не возвращается."
            ),
        },
        {
            "id": 4,
            "text": "Base chainId?",
            "options": ["1", "8453", "137", "42161"],
            "correct_idx": 1,
            "explanation": (
                "Chain ID Base mainnet — 8453. (1 — Ethereum, 137 — Polygon, "
                "42161 — Arbitrum.)"
            ),
        },
        {
            "id": 5,
            "text": "ETH на газ нужен для...",
            "options": [
                "Только для покупки NFT",
                "Оплаты любых транзакций на Base, включая transfer стейблов",
                "Хранения на бирже",
                "Начисления процентов в Aave",
            ],
            "correct_idx": 1,
            "explanation": (
                "Даже перевод стейблкоина — это транзакция, а значит требует "
                "немного ETH на газ. Держите ETH-подушку на учебном кошельке "
                "(лимит ≤ $150)."
            ),
        },
    ],
    # ── M3 — Первая транзакция ───────────────────────────────────────────────
    3: [
        {
            "id": 1,
            "text": "Pending транзакция означает...",
            "options": [
                "Транзакция отклонена сетью",
                "Ожидает включения в блок",
                "Средства уже зачислены",
                "Требуется повторная подпись",
            ],
            "correct_idx": 1,
            "explanation": (
                "Pending — транзакция отправлена в mempool и ждёт включения в "
                "блок; она ещё не финальна."
            ),
        },
        {
            "id": 2,
            "text": "После скольких подтверждений транзакция считается финальной?",
            "options": [
                "Достаточно 0 подтверждений",
                "≥5 подтверждений для разумной уверенности",
                "Ровно 1 подтверждение всегда достаточно",
                "Не менее 1000 подтверждений",
            ],
            "correct_idx": 1,
            "explanation": (
                "Одно подтверждение уже почти финально на L2, но для разумной "
                "уверенности принято дождаться нескольких (≥5) блоков."
            ),
        },
        {
            "id": 3,
            "text": "Что такое tx hash?",
            "options": [
                "Пароль от кошелька",
                "Уникальный ID транзакции в блокчейне",
                "Адрес получателя",
                "Сумма комиссии",
            ],
            "correct_idx": 1,
            "explanation": (
                "Tx hash — уникальный идентификатор транзакции; по нему её "
                "можно найти и проверить в block explorer."
            ),
        },
        {
            "id": 4,
            "text": "Как проверить статус транзакции?",
            "options": [
                "Позвонить в поддержку сети",
                "По tx hash в block explorer (basescan.org)",
                "Переслать seed-фразу боту",
                "Подождать письмо на email",
            ],
            "correct_idx": 1,
            "explanation": (
                "Статус любой транзакции публично виден в block explorer по её "
                "tx hash — например, на basescan.org."
            ),
        },
        {
            "id": 5,
            "text": "Transfer стейбла не прошёл — что проверить?",
            "options": [
                "Скорость интернета",
                "Баланс газа, одобрение, корректность адреса",
                "Курс доллара",
                "Погоду в сети",
            ],
            "correct_idx": 1,
            "explanation": (
                "Типичные причины неуспеха: нет ETH на газ, отсутствует "
                "нужный approval, неверный адрес получателя."
            ),
        },
    ],
    # ── M4 — Подписи и approvals ─────────────────────────────────────────────
    4: [
        {
            "id": 1,
            "text": "Approval — это...",
            "options": [
                "Перевод токенов на биржу",
                "Разрешение контракту тратить ваши токены",
                "Подтверждение личности",
                "Начисление процентов",
            ],
            "correct_idx": 1,
            "explanation": (
                "Approval даёт смарт-контракту право списывать ваши токены до "
                "указанного лимита — сам по себе он не переводит средства."
            ),
        },
        {
            "id": 2,
            "text": "Unlimited approval опасен, потому что...",
            "options": [
                "Он замедляет транзакции",
                "Взломанный контракт может вывести все токены",
                "Он повышает комиссию сети",
                "Он блокирует ваш кошелёк",
            ],
            "correct_idx": 1,
            "explanation": (
                "Безлимитный approval позволяет контракту (или его взломщику) "
                "списать весь баланс токена. Одобряйте только нужную сумму."
            ),
        },
        {
            "id": 3,
            "text": "Revoke — это...",
            "options": [
                "Повторный депозит",
                "Отзыв разрешения (approval с value=0)",
                "Смена сети",
                "Восстановление seed-фразы",
            ],
            "correct_idx": 1,
            "explanation": (
                "Revoke — это установка approval в 0, то есть отзыв ранее "
                "выданного контракту разрешения тратить токены."
            ),
        },
        {
            "id": 4,
            "text": "Разница между подписью (sign) и транзакцией?",
            "options": [
                "Подпись дороже транзакции",
                "Подпись бесплатна, транзакция списывает газ",
                "Обе всегда двигают средства",
                "Транзакция бесплатна, подпись платная",
            ],
            "correct_idx": 1,
            "explanation": (
                "Подпись сообщения не отправляется в сеть и бесплатна; "
                "транзакция меняет состояние блокчейна и требует газа."
            ),
        },
        {
            "id": 5,
            "text": "Перед depositом в протокол нужно...",
            "options": [
                "Отправить seed-фразу протоколу",
                "Сделать Approval на нужную сумму",
                "Отключить кошелёк",
                "Купить токен протокола",
            ],
            "correct_idx": 1,
            "explanation": (
                "Чтобы контракт мог принять ваш токен в депозит, ему сперва "
                "нужен approval на конкретную сумму."
            ),
        },
    ],
    # ── M5 — Депозит в Aave ──────────────────────────────────────────────────
    5: [
        {
            "id": 1,
            "text": "Что происходит при Supply в Aave?",
            "options": [
                "Токены сгорают",
                "Токены идут в пул, вы получаете aToken (процентный)",
                "Токены уходят на биржу",
                "Открывается заём под залог",
            ],
            "correct_idx": 1,
            "explanation": (
                "Supply вносит ваши токены в пул ликвидности; взамен вы "
                "получаете aToken, который автоматически растёт с процентами."
            ),
        },
        {
            "id": 2,
            "text": "aUSDC — это...",
            "options": [
                "Отдельная монета-мем",
                "Токен, подтверждающий депозит, автоматически начисляет проценты",
                "Долговая расписка биржи",
                "Тестовый токен без ценности",
            ],
            "correct_idx": 1,
            "explanation": (
                "aUSDC — процентный токен-квитанция депозита USDC в Aave; его "
                "баланс сам растёт по мере начисления процентов."
            ),
        },
        {
            "id": 3,
            "text": "Перед подтверждением Supply надо проверить...",
            "options": [
                "Курс биткоина",
                "Адрес контракта, сумму, газ",
                "Погоду",
                "Номер телефона поддержки",
            ],
            "correct_idx": 1,
            "explanation": (
                "Всегда сверяйте адрес контракта (официальный ли), вносимую "
                "сумму и наличие ETH на газ перед подписью."
            ),
        },
        {
            "id": 4,
            "text": "Liquidation в Aave происходит при...",
            "options": [
                "Любом депозите",
                "Падении стоимости залога ниже порога (для stablecoin-only — редко)",
                "Выводе средств",
                "Начислении процентов",
            ],
            "correct_idx": 1,
            "explanation": (
                "Ликвидация грозит заёмщикам, чей залог упал ниже порога. При "
                "чисто стейблкоиновой позиции без займа это крайне редко."
            ),
        },
        {
            "id": 5,
            "text": "APY в Aave означает...",
            "options": [
                "Разовую комиссию",
                "Годовую доходность с учётом сложных процентов",
                "Налог на прибыль",
                "Цену газа",
            ],
            "correct_idx": 1,
            "explanation": (
                "APY — годовая доходность с учётом капитализации (сложных "
                "процентов). Она плавает вместе со ставками пула."
            ),
        },
    ],
    # ── M6 — Вывод из Aave ───────────────────────────────────────────────────
    6: [
        {
            "id": 1,
            "text": "Withdraw возвращает...",
            "options": [
                "Только проценты",
                "Первоначальный депозит + накопленные проценты",
                "Половину депозита",
                "Токен протокола вместо стейбла",
            ],
            "correct_idx": 1,
            "explanation": (
                "Withdraw возвращает исходный депозит вместе с процентами, "
                "накопившимися за время удержания."
            ),
        },
        {
            "id": 2,
            "text": "aToken после Withdraw...",
            "options": [
                "Остаётся на кошельке навсегда",
                "Сжигается (burn) автоматически",
                "Переводится другому пользователю",
                "Превращается в NFT",
            ],
            "correct_idx": 1,
            "explanation": (
                "При выводе соответствующий aToken сжигается — он был лишь "
                "квитанцией на депозит."
            ),
        },
        {
            "id": 3,
            "text": "Почему важно мониторить позицию?",
            "options": [
                "Чтобы платить меньше налогов",
                "Чтобы реагировать на изменение APY или рисков протокола",
                "Чтобы увеличить газ",
                "Это не важно",
            ],
            "correct_idx": 1,
            "explanation": (
                "Ставки и риски протокола меняются. Мониторинг позволяет "
                "вовремя выйти, если условия ухудшились."
            ),
        },
        {
            "id": 4,
            "text": "Что проверить перед крупным выводом?",
            "options": [
                "Курс акций",
                "Доступную ликвидность в пуле",
                "Скорость интернета",
                "Баланс на бирже",
            ],
            "correct_idx": 1,
            "explanation": (
                "Если пул временно исчерпан заёмщиками, крупный вывод может "
                "быть недоступен сразу — проверяйте доступную ликвидность."
            ),
        },
        {
            "id": 5,
            "text": "Kill-rule — это...",
            "options": [
                "Комиссия за вывод",
                "Заранее определённое условие для немедленного выхода",
                "Максимальный размер депозита",
                "Ставка налога",
            ],
            "correct_idx": 1,
            "explanation": (
                "Kill-rule — заранее прописанное правило, при срабатывании "
                "которого вы немедленно выходите из позиции без раздумий."
            ),
        },
    ],
    # ── M7 — Инциденты (СЛОЖНЫЙ, >=10 вопросов, порог 80%) ───────────────────
    7: [
        {
            "id": 1,
            "text": "Фишинговый сайт — как распознать?",
            "options": [
                "По красивому дизайну",
                "Проверить точный URL, SSL, источник ссылки",
                "По обещанию высокой доходности",
                "Никак, все сайты безопасны",
            ],
            "correct_idx": 1,
            "explanation": (
                "Фишинг маскируется под настоящий сайт. Сверяйте точный URL "
                "по символам, наличие HTTPS и откуда пришла ссылка."
            ),
        },
        {
            "id": 2,
            "text": "Drainer-подпись — это...",
            "options": [
                "Подпись для входа в аккаунт",
                "Вредоносный approve/permit, отдающий все токены злоумышленнику",
                "Обычная транзакция перевода",
                "Подпись для получения airdrop",
            ],
            "correct_idx": 1,
            "explanation": (
                "Drainer выманивает подпись approve/permit, которая даёт "
                "атакующему право вывести все ваши токены."
            ),
        },
        {
            "id": 3,
            "text": "Подписал permit — как отозвать?",
            "options": [
                "Никак, ничего не поделать",
                "Revoke через revoke.cash или etherscan; если уже исполнен — невозможно",
                "Сменить пароль от email",
                "Перезагрузить кошелёк",
            ],
            "correct_idx": 1,
            "explanation": (
                "Пока permit не исполнен, отзовите разрешение (revoke.cash / "
                "etherscan). Если атакующий уже исполнил его — отмена невозможна."
            ),
        },
        {
            "id": 4,
            "text": "Permit (EIP-2612) опаснее Approval, потому что...",
            "options": [
                "Он требует больше газа",
                "Не требует газа от жертвы, подпись может быть использована офлайн",
                "Он виден в block explorer",
                "Он работает только на тестнете",
            ],
            "correct_idx": 1,
            "explanation": (
                "Permit — это подпись, не транзакция: жертва не платит газ и не "
                "видит её в истории, а атакующий может предъявить её позже."
            ),
        },
        {
            "id": 5,
            "text": "Поддельный токен airdrop — правило?",
            "options": [
                "Быстро продать через любой dex",
                "Не взаимодействовать, не продавать через неизвестные dex",
                "Одобрить его контракту",
                "Отправить другу",
            ],
            "correct_idx": 1,
            "explanation": (
                "Неизвестные «подарочные» токены — приманка: их продажа ведёт "
                "на вредоносный контракт. Не взаимодействуйте с ними."
            ),
        },
        {
            "id": 6,
            "text": "Если нажал 'Connect' на фишинге — достаточно ли disconnect?",
            "options": [
                "Да, disconnect всё решает",
                "Нет — проверить активные approvals и при подозрении перевести средства",
                "Достаточно закрыть вкладку",
                "Нужно только сменить сеть",
            ],
            "correct_idx": 1,
            "explanation": (
                "Само подключение не крадёт средства, но если вы что-то "
                "подписали — disconnect не отменит approval. Проверьте "
                "разрешения и при риске выведите средства."
            ),
        },
        {
            "id": 7,
            "text": "Social engineering — как подтвердить подлинность сайта?",
            "options": [
                "Довериться ссылке из чата поддержки",
                "Bookmarks из официальных источников, не по ссылкам из chat",
                "Искать сайт в рекламе поисковика",
                "Спросить в комментариях",
            ],
            "correct_idx": 1,
            "explanation": (
                "Ссылки из чатов, DM и рекламы — частый вектор фишинга. "
                "Заходите по сохранённым закладкам из официальных источников."
            ),
        },
        {
            "id": 8,
            "text": "Транзакция застряла в pending — правильное действие?",
            "options": [
                "Отправить ещё десять таких же",
                "Speed-up с тем же nonce или cancel (замена нулевой суммой)",
                "Переслать seed-фразу в поддержку",
                "Просто ждать неделю",
            ],
            "correct_idx": 1,
            "explanation": (
                "Застрявшую транзакцию можно ускорить (speed-up, тот же nonce, "
                "выше комиссия) или отменить заменяющей нулевой транзакцией."
            ),
        },
        {
            "id": 9,
            "text": "При каждой подписи проверить...",
            "options": [
                "Только сумму",
                "Адрес контракта, что именно подписываешь, наличие в whitelist",
                "Цвет кнопки",
                "Скорость интернета",
            ],
            "correct_idx": 1,
            "explanation": (
                "Перед подписью сверяйте адрес контракта, суть операции и то, "
                "что домен/контракт есть в вашем whitelist доверенных."
            ),
        },
        {
            "id": 10,
            "text": "Hardware wallet защищает от...",
            "options": [
                "Любых ошибок пользователя",
                "Кражи ключей с заражённого компьютера, но не от фишинговых подписей",
                "Роста комиссий сети",
                "Падения курса токена",
            ],
            "correct_idx": 1,
            "explanation": (
                "Аппаратный кошелёк изолирует ключи от заражённого ПК, но если "
                "вы сами подпишете вредоносный permit — он это исполнит."
            ),
        },
    ],
    # ── M8 — Капстоун: НЕТ серверной проверки квиза (только notes + on-chain) ──
    # Пустой банк → grade_answers возвращает score=100.0 / passed=True.
    8: [],
}


# ── Public helpers ───────────────────────────────────────────────────────────


def _bank_for(lesson_id: int) -> List[dict]:
    """Return the question list for *lesson_id* or raise KeyError."""
    if lesson_id not in QUIZ_BANK:
        raise KeyError(f"no quiz bank for lesson_id={lesson_id!r}")
    return QUIZ_BANK[lesson_id]


def get_questions(lesson_id: int, lang: str = "ru") -> List[dict]:
    """Return this module's questions WITHOUT server-side answer fields.

    Each returned item is ``{"id", "text", "options"}`` — ``correct_idx`` and
    ``explanation`` are stripped so the correct answers never reach the client.
    Returns an empty list for a module with no quiz (e.g. M8).
    """
    out = []
    for q in _bank_for(lesson_id):
        if lang == "en" and q.get("text_en"):
            out.append({"id": q["id"], "text": q["text_en"],
                        "options": list(q.get("options_en") or q["options"])})
        else:
            out.append({"id": q["id"], "text": q["text"], "options": list(q["options"])})
    return out


def passing_threshold(lesson_id: int) -> int:
    """Number of correct answers required to pass (ceil of 80%)."""
    n = len(_bank_for(lesson_id))
    if n == 0:
        return 0
    return int(math.ceil(PASS_FRACTION * n))


def grade_answers(lesson_id: int, answers: List[int]) -> dict:
    """Grade *answers* (list of chosen option indices) against the bank.

    Returns ``{"score": float, "passed": bool, "feedback": list[str]}``.
      - ``score`` is the percentage correct (0.0–100.0).
      - ``passed`` is True iff correct count >= ceil(80% of questions).
      - ``feedback`` is one human string per question — right/wrong plus the
        explanation. It NEVER reveals the correct option index or text of an
        unanswered-correctly question beyond the pre-authored explanation.

    An empty bank (M8) auto-passes: score=100.0, passed=True, feedback=[].
    Extra/short/None answers grade as wrong for the corresponding question
    (no exception): only an in-range index equal to correct_idx counts.
    """
    bank = _bank_for(lesson_id)
    if not bank:
        # M8 capstone / any answer-less module: automatic pass.
        return {"score": 100.0, "passed": True, "feedback": []}

    answers = list(answers) if answers is not None else []
    correct = 0
    feedback: List[str] = []
    for i, q in enumerate(bank):
        chosen = answers[i] if i < len(answers) else None
        is_right = isinstance(chosen, int) and chosen == q["correct_idx"]
        if is_right:
            correct += 1
            feedback.append(f"Вопрос {q['id']}: верно. {q['explanation']}")
        else:
            feedback.append(f"Вопрос {q['id']}: неверно. {q['explanation']}")

    n = len(bank)
    score = round(100.0 * correct / n, 2)
    passed = correct >= passing_threshold(lesson_id)
    return {"score": score, "passed": passed, "feedback": feedback}
