#!/usr/bin/env python3
"""Линтер инструкции владельцу: каждый тест — воспроизведение НАСТОЯЩЕЙ аварии.

Проверка, никогда не видевшая настоящей поломки, — украшение (`.claude/rules/deployment.md`).
Здесь три аварии, и все они измерены, а не предположены:

1. **22.08.2026 — авария, породившая модуль.** Владельцу ушёл вопрос «открой
   ``/api/pilot/requests/count`` и посмотри поле ``notify_channel``». Поля в коде не было
   НИ РАЗУ; владелец ответил «вариант 1 — там ``configured: true``», и этот ответ
   неотличим от настоящего замера. Карточка ``inbox-vopros-vladeltsu-velel-prochitat-pole-ko``.

2. **#365 — три дефекта в самой проверке**, найденные при подъёме осиротевшей работы
   цикла #364 (сессия умерла, написав модуль и НЕ написав ни одного теста):
   - путь API внутри АДРЕСА не проверялся вовсе (перед ``/api/`` стоит цифра порта, и
     lookbehind ``(?<![\\w.])`` её не пропускал) — ровно карточка 22.08 уезжала «не измерено»;
   - докстринг самого линтера внёс ``notify_channel`` в корпус, по которому линтер судит:
     сторож начал доказывать себя своим же текстом;
   - ``data/`` — рантайм-состояние, которого в свежем рабочем дереве нет ПО ПОСТРОЕНИЮ:
     5 настоящих вопросов владельцу были бы ЗАПРЕЩЕНЫ из-за свойства дерева.

**Время и дерево — ВХОД, а не окружение:** каждый тест строит свой корень (``root=``) и не
зависит ни от живого ``data/``, ни от того, из какого дерева его запустили.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from spa_core.owner_queue import card_instruction_lint as L

# ── Замороженная копия инструкции из карточки 22.08 ────────────────────────────────────
# FROZEN-TEXT-OK: это исторический артефакт (текст, реально ушедший владельцу 22.08.2026),
# а не текущее состояние системы. Его неизменность — предмет проверки, а не недосмотр.
# Тест `test_frozen_fixture_still_matches_the_real_card` не даёт копии разойтись с оригиналом.
ACCIDENT_CARD_ID = "owner-decision-prover-odno-pole-dohodyat-li-do-tebya-za"
ACCIDENT_INSTRUCTION = textwrap.dedent("""\
    ## Что случилось и почему это важно

    На сайте есть живая форма «оставить контакт». Она записывает заявку в файл.

    ## Что от тебя нужно

    Одна минута:

    **Шаг 1.** Открой на рабочем Маке `https://api.earn-defi.com:8765/api/pilot/requests/count`
    (или админ-страницу воронок) и посмотри поле `notify_channel`.

    **Шаг 2.** Ответь одним из двух:

    **Вариант 1 — там `configured: true`.** Канал настроен, заявки до тебя доходят.

    ## Как понять, что готово

    Ты нажал одну из двух кнопок.
    """)


def _tree(tmp_path: Path, files: dict) -> Path:
    """Построить дерево-корень из ``{относительный путь: содержимое}``."""
    root = tmp_path / "root"
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


#: Система ПОСЛЕ ADR-121: поле живёт строковым литералом, роут объявлен литералом.
SYSTEM_AFTER_ADR121 = {
    "spa_core/api/routers/interest.py": (
        '"""Роутер заявок."""\n'
        '@router.get("/api/pilot/requests/count")\n'
        'def counts():\n'
        # Форма МНОГОСТРОЧНАЯ намеренно: в живом `interest.py` ключ стоит на своей строке
        # внутри скобок, и вторая версия починки #365 читала такой ключ ДОКСТРИНГОМ
        # (внутри скобок перевод строки приходит как NL). Однострочная фикстура этого
        # не ловила — тест проверял бы случай легче настоящего.
        '    return {\n'
        '        "notify_channel": _notify_channel_status(),\n'
        '    }\n'
    ),
}

#: Система 22.08 (ДО ADR-121): роут есть, а поля нет ни одним вхождением.
SYSTEM_BEFORE_ADR121 = {
    "spa_core/api/routers/interest.py": (
        '"""Роутер заявок."""\n'
        '@router.get("/api/pilot/requests/count")\n'
        'def counts():\n'
        '    return {"saved": 1}\n'
    ),
}


# ══════════════════ АВАРИЯ 1 — 22.08, положительный контроль (п.4 карточки) ══════════════════

def test_accident_2026_08_22_card_is_blocked_by_the_system_of_that_day(tmp_path):
    """ГЛАВНЫЙ положительный контроль: на системе 22.08 карточка НЕ уезжает.

    Красный без починки: до линтера этот вопрос ушёл владельцу и получил ответ.
    """
    root = _tree(tmp_path, SYSTEM_BEFORE_ADR121)
    res = L.lint_text(ACCIDENT_INSTRUCTION, card_id=ACCIDENT_CARD_ID, root=root)

    assert res.blocked, "карточка 22.08 обязана быть запрещена системой 22.08"
    missing = {r.token for r in res.missing}
    assert missing == {"notify_channel"}, (
        f"запрещать должно РОВНО несуществующее поле, а не что попало: {missing}")
    # Причина обязана называть предмет словами — «не уехало» без причины неисполнимо.
    assert "notify_channel" in res.reason_line()


def test_same_card_passes_after_adr_121_added_the_field(tmp_path):
    """Тот же текст на системе ПОСЛЕ ADR-121 — молчит.

    Пара к предыдущему тесту: без неё «краснеет всегда» неотличимо от «краснеет по делу».
    ВАЖНО: изменился НЕ текст карточки (он побайтово тот же), а СИСТЕМА.
    """
    root = _tree(tmp_path, SYSTEM_AFTER_ADR121)
    res = L.lint_text(ACCIDENT_INSTRUCTION, card_id=ACCIDENT_CARD_ID, root=root)

    assert not res.blocked, f"после ADR-121 запрещать нечего: {res.reason_line()}"
    assert {r.token: r.status for r in res.refs} == {
        "/api/pilot/requests/count": L.OK, "notify_channel": L.OK}


def test_frozen_fixture_still_matches_the_real_card():
    """Замороженная копия не имеет права разойтись с настоящей карточкой.

    Иначе положительный контроль однажды начнёт проверять текст, которого не было.
    """
    real = L.repo_root() / "nimbalyst-local" / "tracker" / f"{ACCIDENT_CARD_ID}.md"
    if not real.exists():
        pytest.skip(f"карточки {ACCIDENT_CARD_ID} нет в этом дереве — сверять не с чем")
    section = L.instruction_section(real.read_text(encoding="utf-8"))
    assert section is not None, "у настоящей карточки пропала секция «Что от тебя нужно»"
    for token in ("notify_channel", "/api/pilot/requests/count"):
        assert token in section, (
            f"настоящая карточка больше не упоминает {token} — фикстуру пора обновить")


# ══════════════════ АВАРИЯ 2 — #365, дефект 1: путь API внутри адреса ══════════════════

def test_api_path_inside_a_url_with_a_port_is_measured_not_skipped(tmp_path):
    """Цифра порта перед ``/api/`` не имеет права отменять проверку пути.

    Красный на исходной версии #364: ``_API_RE`` c lookbehind ``(?<![\\w.])`` не находил
    путь в ``...:8765/api/...``, и ссылка уезжала как ``site_url``/``unchecked`` — то есть
    РОВНО тот путь, который владельцу велели открыть, не проверялся вовсе.
    """
    refs = L.extract_references(
        "## Что от тебя нужно\n"
        "Открой `https://api.earn-defi.com:8765/api/pilot/requests/count`\n")
    kinds = {r.kind: r.token for r in refs}

    assert "api_path" in kinds, f"путь API в адресе не распознан: {refs}"
    assert kinds["api_path"] == "/api/pilot/requests/count"
    assert "site_url" not in kinds, "адрес с НАШИМ путём — не внешняя страница"


def test_fabricated_api_path_inside_a_url_is_forbidden(tmp_path):
    """Следствие: выдуманный путь в адресе теперь ЗАПРЕЩАЕТ карточку, а не молчит."""
    root = _tree(tmp_path, SYSTEM_AFTER_ADR121)
    res = L.lint_text(
        "## Что от тебя нужно\nОткрой `https://api.earn-defi.com:8765/api/vydumannyi/put`\n",
        root=root)
    assert res.blocked
    assert [r.token for r in res.missing] == ["/api/vydumannyi/put"]


def test_a_genuinely_external_url_stays_unchecked(tmp_path):
    """Внешняя страница — не наш роут: сеть в проверке запрещена, значит «не измерено».

    Обратный контроль к предыдущему: запрет не должен расползаться на чужие адреса.
    """
    root = _tree(tmp_path, SYSTEM_AFTER_ADR121)
    res = L.lint_text("## Что от тебя нужно\nОткрой `https://earn-defi.com/pilot/`\n", root=root)
    assert not res.blocked
    assert [r.status for r in res.refs] == [L.UNCHECKED]


# ══════════════ АВАРИЯ 3 — #365, дефект 2: сторож доказывает себя своим текстом ══════════════

def test_token_only_in_a_docstring_is_not_evidence_that_the_system_has_it(tmp_path):
    """Рассказ о поле — не поле.

    Красный на исходной версии #364: докстринг самого линтера (4 вхождения
    ``notify_channel``) попадал в корпус, и после посадки модуля откат ADR-121 остался бы
    незамеченным — сторож ответил бы ``ok`` о том, чего в системе нет.
    """
    # Система 22.08 (роут есть, поля нет) ПЛЮС файл, который лишь РАССКАЗЫВАЕТ о поле.
    # Единственная переменная теста — notify_channel; путь API держим существующим,
    # иначе карточку запретил бы он, и тест доказывал бы не то (урок #365).
    root = _tree(tmp_path, dict(SYSTEM_BEFORE_ADR121, **{
        "spa_core/owner_queue/opisanie.py":
            '"""Авария 22.08: владельцу велели прочитать поле notify_channel."""\n'
            '# и ещё раз в комментарии: notify_channel\n'
            'def f():\n    return 1\n',
    }))
    idx = L.build_index(root)
    assert "notify_channel" not in idx.identifiers, "докстринг просочился в код"
    assert "notify_channel" in idx.prose_identifiers, "проза потерялась целиком"

    res = L.lint_text(ACCIDENT_INSTRUCTION, root=root)
    statuses = {r.token: r.status for r in res.refs}
    assert statuses["notify_channel"] == L.UNCHECKED, (
        f"ни ok (это не наличие), ни missing (это не доказанное отсутствие): {statuses}")
    assert not res.blocked, "описание не даёт права запрещать (п.3 карточки)"
    reason = next(r.reason for r in res.refs if r.token == "notify_channel")
    assert "комментар" in reason or "докстринг" in reason, f"причина не названа: {reason}"


def test_string_literals_are_code_not_prose(tmp_path):
    """Строковый литерал — это система, снимать его нельзя.

    Обратный контроль: перестарайся с вырезанием прозы — и настоящее доказательство
    (``"notify_channel": ...`` в ``interest.py``) исчезнет, а линтер начнёт ЗАПРЕЩАТЬ
    карточки о существующих полях. Ложный запрет дороже ложного «ok».
    """
    root = _tree(tmp_path, SYSTEM_AFTER_ADR121)
    idx = L.build_index(root)
    assert "notify_channel" in idx.identifiers
    assert "/api/pilot/requests/count" in idx.paths


def test_docstring_with_escape_sequences_is_really_stripped(tmp_path):
    """Докстринг с ``\\w`` обязан вырезаться — на этом сломалась первая версия починки.

    ``ast.get_docstring`` отдаёт РАЗОБРАННОЕ значение (``\\\\w`` в исходнике приходит как
    ``\\w``), поэтому вырезание подстрокой молча не находило ничего и докстринг оставался
    в коде — тест на самопитание был бы зелёным украшением. Делим по токенам.
    """
    root = _tree(tmp_path, {
        "spa_core/x.py": '"""Regex ``(?<![\\\\w.])`` и поле vydumannoe_pole."""\ndef f():\n    return 1\n',
    })
    idx = L.build_index(root)
    assert "vydumannoe_pole" not in idx.identifiers, "докстринг с экранированием не вырезан"
    assert "vydumannoe_pole" in idx.prose_identifiers


def test_unparseable_python_is_treated_as_code_never_as_absence(tmp_path):
    """Споткнулись о синтаксис — считаем весь файл кодом.

    Fail-OPEN осознанно: проверка не имеет права выдумывать отсутствие из-за того, что
    сама не разобрала файл (п.3 карточки).
    """
    root = _tree(tmp_path, {"spa_core/broken.py": "def (((( notify_channel\n"})
    idx = L.build_index(root)
    assert "notify_channel" in idx.identifiers


# ═══════════ АВАРИЯ 4 — #365, дефект 3: рантайм-состояние, которого нет в дереве ═══════════

def test_runtime_data_path_absent_from_the_tree_is_never_called_missing(tmp_path):
    """``data/`` в рабочем дереве отсутствует ПО ПОСТРОЕНИЮ — это свойство дерева.

    Замер #365: из 12 «несуществующих» файлов ПЯТЬ жили в проде прямо сейчас
    (``data/intraday_equity.json`` и др.). Линтер из worktree запретил бы пять настоящих
    вопросов владельцу — молчащая очередь дороже лечимой аварии.
    """
    root = _tree(tmp_path, SYSTEM_AFTER_ADR121)
    res = L.lint_text(
        "## Что от тебя нужно\nОткрой `data/intraday_equity.json` и посмотри статус\n",
        root=root)
    assert not res.blocked, "рантайм-файл не даёт права запрещать"
    ref = next(r for r in res.refs if r.token == "data/intraday_equity.json")
    assert ref.status == L.UNCHECKED
    assert "рантайм" in ref.reason


def test_runtime_data_path_that_exists_is_ok(tmp_path):
    """Если файл есть — это обычное ``ok``, послабление ничего не размывает."""
    root = _tree(tmp_path, dict(SYSTEM_AFTER_ADR121, **{"data/intraday_equity.json": "{}"}))
    res = L.lint_text("## Что от тебя нужно\nОткрой `data/intraday_equity.json`\n", root=root)
    assert [r.status for r in res.refs] == [L.OK]


def test_missing_code_path_is_still_forbidden(tmp_path):
    """Обратный контроль к послаблению: вне ``data/`` отсутствие файла ЗАПРЕЩАЕТ.

    Без этого теста починка дефекта 3 могла бы обезоружить проверку целиком, и никто
    бы не заметил. Замер #365 нашёл такой случай настоящим:
    ``spa_core/paper_trading/deflated_sharpe.py`` не существует нигде.
    """
    root = _tree(tmp_path, SYSTEM_AFTER_ADR121)
    res = L.lint_text(
        "## Что от тебя нужно\nОткрой `spa_core/paper_trading/deflated_sharpe.py`\n", root=root)
    assert res.blocked
    assert [r.token for r in res.missing] == ["spa_core/paper_trading/deflated_sharpe.py"]


# ═════════════════════ Границы: что линтер читать НЕ имеет права ═════════════════════

def test_only_the_instruction_section_is_judged(tmp_path):
    """Читается РОВНО «Что от тебя нужно».

    «Что случилось» и «Что будет после» — рассказ о системе, ссылка на будущий артефакт
    там законна. Судить их значило бы запрещать карточки за описание планов.
    """
    root = _tree(tmp_path, SYSTEM_AFTER_ADR121)
    text = ("## Что случилось и почему это важно\n"
            "Файла `spa_core/budushchii_modul.py` пока нет — его и построим.\n\n"
            "## Что от тебя нужно\n"
            "Ответь: вариант 1 или вариант 2.\n\n"
            "## Что будет после\n"
            "Создам `spa_core/eshche_ne_sozdan.py`.\n")
    res = L.lint_text(text, root=root)
    assert not res.blocked, f"судим не ту секцию: {res.reason_line()}"


def test_card_without_the_section_is_unmeasured_not_forbidden(tmp_path):
    """Нет секции — мерить нечего. Это «не измерено», а не запрет."""
    root = _tree(tmp_path, SYSTEM_AFTER_ADR121)
    res = L.lint_text("## Просто заметка\nбез поручения\n", root=root)
    assert not res.section_found
    assert not res.blocked
    assert res.unmeasured_reason


def test_unreadable_card_is_unmeasured_not_forbidden(tmp_path):
    """Нечитаемый файл карточки — тоже «не измерено»: проверка не молчит владельцу."""
    res = L.lint_card(tmp_path / "net-takoi-kartochki.md")
    assert not res.blocked
    assert res.unmeasured_reason


def test_tracker_and_docs_are_not_part_of_the_corpus(tmp_path):
    """Карточка не может быть сама себе доказательством.

    22.08 единственным вхождением ``notify_channel`` был текст самой карточки: корпус,
    включающий трекер, назвал бы аварию нормой.
    """
    root = _tree(tmp_path, dict(SYSTEM_BEFORE_ADR121, **{
        "nimbalyst-local/tracker/some-card.md": "поле `notify_channel` тут упомянуто\n",
        "docs/zametka.md": "и тут `notify_channel`\n",
    }))
    res = L.lint_text(ACCIDENT_INSTRUCTION, root=root)
    assert res.blocked, "трекер/docs просочились в корпус — авария 22.08 стала бы нормой"


# ═════════════════════ Проводка: заслон в первой доставке ═════════════════════

class _FakeCard:
    def __init__(self, path: Path):
        self.path = path


def _card(tmp_path: Path, name: str, body: str) -> _FakeCard:
    p = tmp_path / f"{name}.md"
    p.write_text(body, encoding="utf-8")
    return _FakeCard(p)


def test_lint_gate_drops_the_unexecutable_card_and_names_it(tmp_path, monkeypatch):
    """Заблокированная карточка не уезжает и НАЗВАНА поимённо в отчёте."""
    from spa_core.owner_queue import first_delivery as FD

    root = _tree(tmp_path, SYSTEM_AFTER_ADR121)
    monkeypatch.setattr(L, "repo_root", lambda: root)
    L._INDEX_CACHE.clear()

    good = _card(tmp_path, "horoshaya", "## Что от тебя нужно\nОтветь: вариант 1 или 2.\n")
    bad = _card(tmp_path, "plohaya",
                "## Что от тебя нужно\nОткрой поле `sovsem_vydumannoe_pole`.\n")

    report = FD.FirstDeliveryReport(requested_at="2026-08-24T00:00:00Z")
    kept = FD._lint_gate([good, bad], report)

    assert [c.path.stem for c in kept] == ["horoshaya"]
    assert [b["card"] for b in report.lint_blocked] == ["plohaya"]
    assert "sovsem_vydumannoe_pole" in report.lint_blocked[0]["reason"]
    L._INDEX_CACHE.clear()


def test_lint_gate_failure_never_stops_delivery(tmp_path, monkeypatch):
    """Линтер упал ⇒ карточка едет как раньше.

    Молчащая очередь вопросов владельцу дороже той аварии, которую линтер лечит:
    отказ ПРОВЕРКИ не имеет права превращаться в отказ ДОСТАВКИ (fail-open осознанно).
    """
    from spa_core.owner_queue import first_delivery as FD

    def boom(*a, **kw):
        raise RuntimeError("линтер сломался")

    monkeypatch.setattr(L, "lint_card", boom)
    monkeypatch.setattr("spa_core.owner_queue.card_instruction_lint.lint_card", boom)

    card = _card(tmp_path, "lyubaya", "## Что от тебя нужно\nОткрой `chto_ugodno_pole`.\n")
    report = FD.FirstDeliveryReport(requested_at="2026-08-24T00:00:00Z")
    kept = FD._lint_gate([card], report)

    assert [c.path.stem for c in kept] == ["lyubaya"], "падение линтера съело доставку"
    assert report.lint_blocked == []


def test_audit_counts_what_exists_and_what_does_not(tmp_path):
    """Замер п.1 карточки: считаем ссылки по видам и статусам, а не «на глаз»."""
    root = _tree(tmp_path, SYSTEM_AFTER_ADR121)
    tracker = tmp_path / "tracker"
    tracker.mkdir()
    (tracker / "a.md").write_text(
        "## Что от тебя нужно\nОткрой поле `notify_channel`.\n", encoding="utf-8")
    (tracker / "b.md").write_text(
        "## Что от тебя нужно\nОткрой поле `net_takogo_polya`.\n", encoding="utf-8")
    (tracker / "_BOARD.md").write_text("авто-индекс, не карточка\n", encoding="utf-8")

    rep = L.audit(tracker, root=root)
    assert rep["cards_with_instruction_section"] == 2, "_BOARD.md — не карточка"
    assert rep["totals"][L.OK] == 1
    assert rep["totals"][L.MISSING] == 1
    assert [b["card"] for b in rep["blocked_cards"]] == ["b"]


def test_blocked_card_is_named_in_the_human_line(monkeypatch):
    """Заблокированное НАЗЫВАЕТСЯ человеку, а не исчезает из строки отчёта.

    Замер #365: поле ``lint_blocked`` в отчёте было, а `summary_line` о нём молчала —
    вопрос владельцу, не уехавший из-за неисполнимой инструкции, читался бы как «отправлять
    было нечего». Это ровно та тишина в очереди, против которой заслон и ставился
    (тот же принцип, что у ``deferred``: молчаливое усечение читается как «доставили всё»).
    """
    from spa_core.owner_queue import first_delivery as FD

    report = FD.FirstDeliveryReport(requested_at="2026-08-24T00:00:00Z", open_total=1)
    report.lint_blocked = [{"card": "plohaya", "reason": "нет поля vydumannoe",
                            "missing": ["vydumannoe"]}]
    line = FD.summary_line(report)

    assert "plohaya" in line, f"заблокированная карточка пропала из строки: {line}"
    assert "vydumannoe" in line, f"причина не названа человеку: {line}"


def test_literal_inside_a_multiline_bracket_is_code_not_a_docstring(tmp_path):
    """Ключ многострочного словаря — литерал, а не докстринг.

    Замер #365 (вторая версия починки): внутри скобок перевод строки приходит токеном
    ``NL``, который стоит в списке «начал оператора» ⇒ ключ на своей строке уезжал в прозу.
    Форма — ровно та, в которой лежит НАСТОЯЩЕЕ доказательство (`interest.py`), так что
    проверка молча теряла бы литералы по всему корпусу: `ok` вырождался в «не измерено».
    """
    root = _tree(tmp_path, {
        "spa_core/mnogostrochno.py":
            "CONFIG = {\n"
            '    "notify_channel": 1,\n'
            "}\n"
            "PUTI = [\n"
            '    "/api/pilot/requests/count",\n'
            "]\n",
    })
    idx = L.build_index(root)
    assert "notify_channel" in idx.identifiers, "ключ словаря прочитан как докстринг"
    assert "/api/pilot/requests/count" in idx.paths, "элемент списка прочитан как докстринг"
    assert "notify_channel" not in idx.prose_identifiers


def test_module_docstring_after_a_shebang_is_still_prose(tmp_path):
    """Обратный контроль к учёту глубины: докстринг после `#!` обязан остаться прозой.

    Лечить NL запретом «NL не начинает оператор» было нельзя: почти каждый наш модуль
    начинается с `#!/usr/bin/env python3`, после которого идёт NL, — и все докстринги
    проекта разом вернулись бы в корпус, тихо восстановив самопитание сторожа.
    """
    root = _tree(tmp_path, {
        "spa_core/s_shebang.py":
            "#!/usr/bin/env python3\n"
            '"""Тут упомянуто pole_iz_dokstringa."""\n'
            "def f():\n    return 1\n",
    })
    idx = L.build_index(root)
    assert "pole_iz_dokstringa" not in idx.identifiers, "докстринг после shebang не вырезан"
    assert "pole_iz_dokstringa" in idx.prose_identifiers
