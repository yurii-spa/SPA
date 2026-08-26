"""Regression coverage for ``scripts/orchestrator_queue.py`` — the deterministic,
stdlib-only CLI that drives the WHOLE orchestrator protocol (docs/ORCHESTRATOR_PROTOCOL.md):
``list`` / ``set-status`` / ``create`` / ``ingest-notes`` / ``promotions`` / ``notify``.

The LaunchAgent orchestrator (``com.spa.orchestrator``) shells out to this entrypoint every
cycle, so a silent break here (wrong exit code, dropped ``owner-done`` refusal, garbled JSON)
would corrupt the owner-queue loop without any test catching it. On origin the module had
**0 dedicated tests**; this file pins the CLI *dispatch layer* — exit codes, output shape,
and the invariant #14 ``owner-done`` refusal — end to end through ``main(argv=...)``.

The module is a script (``scripts/`` has no ``__init__.py``), so — exactly like
``test_build_agent_registry.py`` and the API router do at runtime — we load it by file path
via ``importlib.util.spec_from_file_location``.

Hermetic & offline: we repoint ``queue.TRACKER_DIR`` / ``queue.INBOX_NOTES_DIR`` at tmp dirs
(the CLI resolves the tracker location through those module globals), and for the real-send
``notify`` path we monkeypatch the CLI's ``notify_needs_owner`` so no Telegram bot / Keychain
is ever touched. ``owner-done`` is never written (invariant #14). Tests only — the module is
NOT modified (invariant #16).
"""
from __future__ import annotations

import importlib.util
import json
import textwrap
from pathlib import Path

import pytest

from spa_core.owner_queue import queue

_REPO = Path(__file__).resolve().parents[2]
_CLI = _REPO / "scripts" / "orchestrator_queue.py"


def _load_cli():
    spec = importlib.util.spec_from_file_location("orchestrator_queue_cli", _CLI)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CARD = textwrap.dedent(
    """\
    ---
    trackerStatus:
      type: owner-decision
    title: Test card title
    status: needs-owner
    priority: high
    owner: someone@example.com
    legacy_id: Q-OWN-99
    ---

    ## Контекст
    Some context here.

    ## Инструкция владельцу
    1. Do the first concrete thing.

    ## Критерий «сделано»
    It is done when X.
    """
)

INBOX_CARD = CARD.replace("type: owner-decision", "type: inbox").replace(
    "status: needs-owner", "status: new"
)


@pytest.fixture
def cli():
    return _load_cli()


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    """A tmp tracker dir wired into the queue module globals the CLI reads.

    Каталог лежит внутри НАСТОЯЩЕГО (пустого) git-репозитория, и это не украшение.
    `cmd_list` спрашивает «нет ли ответа владельца в ГЛАВНОМ рабочем дереве», а какое
    дерево главное, решает `git worktree list`. Каталог вне репозитория этому вопросу
    неизмерим ⇒ CLI честно возвращает код 2 («список пуст и НЕ ПОДТВЕРЖДЁН») — правило
    верное, и гасить его нельзя. Репозиторий-песочница делает сверку ИЗМЕРИМОЙ и при
    этом замкнутой на tmp: единственное дерево — своё, чужих карточек взяться неоткуда.
    Раньше изоляции не было вовсе, и сверка отвечала про НАСТОЯЩИЕ рабочие деревья
    (замер 21.08: в stdout приезжали живые `owner-done` карточки прода).
    """
    import subprocess

    root = tmp_path / "repo"
    d = root / "nimbalyst-local" / "tracker"
    d.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    monkeypatch.setattr(queue, "TRACKER_DIR", d)
    return d


def _write(d: Path, name: str, text: str) -> Path:
    p = d / name
    p.write_text(text, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- list

def test_list_json_emits_card_dicts(cli, tracker, capsys):
    _write(tracker, "own-1.md", CARD)
    _write(tracker, "inbox-1.md", INBOX_CARD)

    rc = cli.main(["list", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 2
    keys = set(out[0])
    # the CLI's _card_dict contract the dashboard / callers depend on:
    assert {"id", "path", "type", "status", "title", "first_instruction"} <= keys


def test_list_filters_by_type_and_status(cli, tracker, capsys):
    _write(tracker, "own-1.md", CARD)
    _write(tracker, "own-2.md", CARD.replace("status: needs-owner", "status: owner-done"))
    _write(tracker, "inbox-1.md", INBOX_CARD)

    rc = cli.main(["list", "--type", "owner-decision", "--status", "needs-owner", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out) == 1
    assert out[0]["type"] == "owner-decision"
    assert out[0]["status"] == "needs-owner"


def test_list_human_empty(cli, tracker, capsys):
    rc = cli.main(["list"])
    assert rc == 0
    assert "(no matching cards)" in capsys.readouterr().out


# ----------------------------------------------------------------------- set-status

def test_set_status_ok(cli, tracker, capsys):
    p = _write(tracker, "own-9.md", CARD)
    rc = cli.main(["set-status", str(p), "ingested"])
    assert rc == 0
    assert "OK:" in capsys.readouterr().out
    assert "status: ingested" in p.read_text(encoding="utf-8")


def test_set_status_refuses_owner_done(cli, tracker, capsys):
    """Invariant #14: the agent CLI must never move a card to owner-done."""
    p = _write(tracker, "own-9.md", CARD)
    rc = cli.main(["set-status", str(p), "owner-done"])
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err
    # the card is untouched — still needs-owner
    assert "status: needs-owner" in p.read_text(encoding="utf-8")


def test_set_status_missing_file_returns_1(cli, tracker, capsys):
    rc = cli.main(["set-status", str(tracker / "nope.md"), "ingested"])
    assert rc == 1
    assert "ERROR" in capsys.readouterr().err


# --------------------------------------------------------------------------- create

def test_create_writes_file_and_prints_path(cli, tracker, capsys):
    rc = cli.main(["create", "--type", "inbox", "--title", "Add a button", "--body", "please"])
    assert rc == 0
    printed = capsys.readouterr().out.strip()
    created = Path(printed)
    assert created.exists()
    assert created.parent == tracker
    text = created.read_text(encoding="utf-8")
    assert "status: new" in text          # inbox default status
    assert "please" in text


def test_create_refuses_owner_done(cli, tracker, capsys):
    """Invariant #14: create must not stamp owner-done even if asked."""
    rc = cli.main(
        ["create", "--type", "owner-decision", "--title", "X", "--status", "owner-done"]
    )
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err
    assert not list(tracker.glob("*.md"))


def test_create_parses_repeatable_extra_fields(cli, tracker, capsys):
    rc = cli.main(
        ["create", "--type", "inbox", "--title", "T", "--field", "source=telegram",
         "--field", "priority=high"]
    )
    assert rc == 0
    created = Path(capsys.readouterr().out.strip())
    text = created.read_text(encoding="utf-8")
    assert "source: telegram" in text
    assert "priority: high" in text


def test_create_reads_body_file(cli, tracker, tmp_path, capsys):
    bf = tmp_path / "body.md"
    bf.write_text("body from file", encoding="utf-8")
    rc = cli.main(["create", "--type", "inbox", "--title", "T", "--body-file", str(bf)])
    assert rc == 0
    created = Path(capsys.readouterr().out.strip())
    assert "body from file" in created.read_text(encoding="utf-8")


# ---------------------------------------------------------------------- ingest-notes

def test_ingest_notes_empty(cli, tracker, tmp_path, capsys):
    notes = tmp_path / "inbox"
    notes.mkdir()
    rc = cli.main(["ingest-notes", "--dir", str(notes)])
    assert rc == 0
    assert "(no loose notes to ingest)" in capsys.readouterr().out


def test_ingest_notes_creates_card(cli, tracker, tmp_path, capsys):
    notes = tmp_path / "inbox"
    notes.mkdir()
    (notes / "idea.md").write_text("Сделать кнопку наверх", encoding="utf-8")
    rc = cli.main(["ingest-notes", "--dir", str(notes)])
    assert rc == 0
    assert "ingested ->" in capsys.readouterr().out
    # a card landed in the (tmp) tracker dir
    assert list(tracker.glob("*.md"))


# ---------------------------------------------------------------------- promotions

def test_promotions_json_uses_scan_output(cli, monkeypatch, capsys):
    class _P:
        path = Path("docs/ideas/x.md")
        title = "An idea"
        snippet = "do it #promote"

    monkeypatch.setattr(cli, "scan_promotions", lambda: [_P()])
    rc = cli.main(["promotions", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out == [{"path": "docs/ideas/x.md", "title": "An idea", "snippet": "do it #promote"}]


def test_promotions_human_empty(cli, monkeypatch, capsys):
    monkeypatch.setattr(cli, "scan_promotions", lambda: [])
    rc = cli.main(["promotions"])
    assert rc == 0
    assert "no #promote" in capsys.readouterr().out


# --------------------------------------------------------------------------- notify

def test_notify_check_builds_message_without_sending(cli, tracker, monkeypatch, capsys):
    """--check must build & print the message and NEVER hit the send path."""
    p = _write(tracker, "own-9.md", CARD)

    def _boom(*_a, **_k):  # pragma: no cover - must not be reached
        raise AssertionError("real send must not run under --check")

    monkeypatch.setattr(cli, "notify_needs_owner",
                        lambda path, dry_run=False: "BUILT" if dry_run else _boom())
    rc = cli.main(["notify", str(p), "--check"])
    assert rc == 0
    assert "BUILT" in capsys.readouterr().out


def _notify_cli(cli, tracker, monkeypatch, verdict):
    """Общая обвязка: отправку подменяем, ИСХОД задаём вердиктом журнала."""
    p = _write(tracker, "own-9.md", CARD)
    calls = {}

    def _fake(path, dry_run=False):
        calls["path"] = path
        calls["dry_run"] = dry_run
        return "sent"

    monkeypatch.setattr(cli, "notify_needs_owner", _fake)
    monkeypatch.setattr(cli, "delivery_verdict", lambda path, **kw: verdict)
    return p, calls


def test_notify_send_reports_ok_when_the_message_actually_left(cli, tracker, monkeypatch,
                                                               capsys):
    """Доставлено ⇒ код 0 и «OK», с ИЗМЕРЕННОЙ подробностью.

    НАМЕРЕННАЯ ПРАВКА ТЕСТА (инвариант #16; обоснование здесь, в теле коммита и в
    `docs/journal/2026-W35.md`). Прежний `test_notify_send_reports_ok` требовал «OK» и код 0
    БЕЗУСЛОВНО — то есть закреплял отчёт о НАМЕРЕНИИ отправить. Между `notify_needs_owner`
    и владельцем стоит `guard_outbound` (дедуп по тексту 30 мин + лимит потока), который
    роняет сообщение молча; живой случай цикла #385 — два гашения подряд, оба раза «OK».
    Проверка не ослаблена, а РАЗВЁРНУТА на три исхода (см. два теста ниже), которых не было
    вовсе.
    """
    p, calls = _notify_cli(cli, tracker, monkeypatch, (True, "доставлено, message_ids=[42]"))
    rc = cli.main(["notify", str(p)])
    assert rc == 0
    assert calls == {"path": str(p), "dry_run": False}
    out = capsys.readouterr().out
    assert "OK: notified" in out
    assert "message_ids=[42]" in out


def test_notify_reports_failure_when_the_sender_dropped_it(cli, tracker, monkeypatch, capsys):
    """Заслон погасил отправку ⇒ код 1 и «НЕ ОТПРАВЛЕНО», а не «OK».

    Положительный контроль: на origin-версии команды здесь код 0 и «OK: notified».
    """
    p, _ = _notify_cli(cli, tracker, monkeypatch, (False, "дедуп по тексту (30 мин)"))
    rc = cli.main(["notify", str(p)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "НЕ ОТПРАВЛЕНО" in out
    assert "дедуп" in out
    assert "OK: notified" not in out


def test_notify_reports_unmeasured_as_its_own_outcome(cli, tracker, monkeypatch, capsys):
    """Исхода в журнале нет ⇒ код 2 («не измерено»), а не 0 и не 1.

    Третий исход отдельным именем: «не знаю, дошло ли» — это не «дошло» и не «не дошло».
    """
    p, _ = _notify_cli(cli, tracker, monkeypatch, (None, "записи об этой карточке нет"))
    rc = cli.main(["notify", str(p)])
    assert rc == 2
    out = capsys.readouterr().out
    assert "НЕ ИЗМЕРЕНО" in out
    assert "OK: notified" not in out


def test_notify_never_reports_ok_for_a_send_the_journal_never_saw(cli, tracker,
                                                                   monkeypatch, capsys):
    """Сквозной положительный контроль: подменён только ЖУРНАЛ, ничего из новых имён.

    Остальные тесты этого раздела на origin-версии краснеют `AttributeError` — «такой
    способности нет», а это более слабый класс контроля, чем «способность врёт». Здесь
    подменяется существующий и на origin `owner_decisions._push_by_card_id`, поэтому тест
    исполним ОБЕИМИ версиями: origin отвечает «OK: notified» с кодом 0 на отправку, о
    которой журнал не знает ничего, — ровно тот отчёт о намерении, ради которого правка и
    делалась.
    """
    from spa_core.telegram import owner_decisions

    p = _write(tracker, "own-9.md", CARD)
    monkeypatch.setattr(cli, "notify_needs_owner", lambda path, dry_run=False: "sent")
    monkeypatch.setattr(owner_decisions, "_push_by_card_id", lambda *a, **kw: None)
    rc = cli.main(["notify", str(p)])
    out = capsys.readouterr().out
    assert rc != 0, "команда отчиталась успехом об отправке, которой журнал не видел"
    assert "OK: notified" not in out
    assert "НЕ ИЗМЕРЕНО" in out


def test_notify_dry_run_never_asks_about_delivery(cli, tracker, monkeypatch, capsys):
    """`--check` ничего не отправляет ⇒ спрашивать журнал о доставке нечего (код 0)."""
    p = _write(tracker, "own-9.md", CARD)
    monkeypatch.setattr(cli, "notify_needs_owner", lambda path, dry_run=False: "BUILT-MSG")
    asked = []
    monkeypatch.setattr(cli, "delivery_verdict",
                        lambda path, **kw: asked.append(path) or (None, "не должно быть вызвано"))
    rc = cli.main(["notify", str(p), "--check"])
    assert rc == 0
    assert asked == [], "сухой прогон спросил журнал о доставке несуществующей отправки"
    assert "BUILT-MSG" in capsys.readouterr().out


# ----------------------------------------------------------------------------- main

def test_main_requires_a_subcommand(cli):
    with pytest.raises(SystemExit):
        cli.main([])


# ------------------------------------------- одна команда — ОДИН каталог очереди
#
# Авария 21.08 (цикл #333). Полный прогон на чистом `origin/main` давал два падения
# (`test_list_human_empty`, `test_list_json_emits_card_dicts`), и оба — не про код:
# `cmd_list` печатал список из УКАЗАННОГО каталога, а сверку «нет ли ответа владельца
# в главном дереве» вёл по копии `TRACKER_DIR`, снятой в момент импорта скрипта. Под
# тестом это НАСТОЯЩИЕ рабочие деревья, поэтому в stdout приезжали живые `owner-done`
# карточки прода — и вердикт набора начинал зависеть от того, разобрал ли кто-то почту
# владельца. Утверждения самих тестов были ВЕРНЫ; чинился адрес, а не проверка (инв. #16).


def _git(cwd, *args):
    import subprocess

    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


@pytest.fixture
def two_trees(tmp_path):
    """Настоящая пара деревьев: главное (куда пишет бот) + линкованный worktree.

    Фикстура нужна именно НАСТОЯЩАЯ: вопрос «какое дерево главное» решает
    `git worktree list`, и подменённая заглушка проверила бы наш пересказ, а не факт.
    """
    import subprocess

    main = tmp_path / "main"
    (main / "nimbalyst-local" / "tracker").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(main)], check=True)
    _git(main, "config", "user.email", "t@example.com")
    _git(main, "config", "user.name", "test")
    (main / "seed.txt").write_text("seed", encoding="utf-8")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "seed")

    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "--detach", str(wt))
    (wt / "nimbalyst-local" / "tracker").mkdir(parents=True, exist_ok=True)
    return main / "nimbalyst-local" / "tracker", wt / "nimbalyst-local" / "tracker"


def test_the_cross_tree_check_answers_about_the_tracker_being_listed(
        cli, two_trees, monkeypatch, capsys):
    """Положительный контроль: сверка деревьев обязана быть про ТОТ ЖЕ каталог.

    Ответ владельца лежит в главном дереве фикстуры, читаем — worktree фикстуры.
    До починки CLI спрашивал про СОВСЕМ ДРУГУЮ пару деревьев (настоящий репозиторий),
    поэтому засеянная карточка была ему невидима, а вместо неё в вывод попадало то,
    что лежало в живом проде.
    """
    main_tracker, wt_tracker = two_trees
    answered = CARD.replace("status: needs-owner", "status: owner-done")
    _write(main_tracker, "own-42.md", answered)
    _write(wt_tracker, "own-42.md", CARD)          # здесь ответа ещё нет
    monkeypatch.setattr(queue, "TRACKER_DIR", wt_tracker)

    rc = cli.main(["list", "--json", "--no-origin-check"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    found = [c for c in out if c["id"] == "own-42" and c["status"] == "owner-done"]
    assert found, "ответ владельца из ГЛАВНОГО дерева обязан доехать в stdout (#246)"
    assert str(main_tracker) in found[0]["path"], "путь обязан указывать на прочитанную копию"


def test_a_sandbox_tracker_never_carries_cards_from_the_real_production_tree(
        cli, tracker, monkeypatch, capsys):
    """Вторая половина того же: песочница не имеет права принести чужие карточки.

    Каталог песочницы не лежит ни в одном рабочем дереве ⇒ сверка честно отвечает
    «НЕ ИЗМЕРЕНО» (fail-CLOSED, причина словами), а не подмешивает живую очередь.
    """
    seen = []
    real = cli.scan_owner_answers_elsewhere

    def _spy(tracker_dir, **kw):
        seen.append(Path(tracker_dir))
        return real(tracker_dir, **kw)

    monkeypatch.setattr(cli, "scan_owner_answers_elsewhere", _spy)

    rc = cli.main(["list", "--no-origin-check"])
    assert rc == 0
    assert seen == [tracker], f"сверка ушла в чужой каталог: {seen}"
    assert "(no matching cards)" in capsys.readouterr().out


def test_an_explicit_tracker_dir_still_wins_for_both_halves(
        cli, tmp_path, monkeypatch, capsys):
    """Обратный контроль: явный `--tracker-dir` главнее умолчания — и был таким.

    Эта половина работала и до починки; тест закрепляет, что она НЕ изменилась.
    """
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    seen = []
    monkeypatch.setattr(cli, "scan_owner_answers_elsewhere",
                        lambda d, **kw: (seen.append(Path(d)), (cli.CROSS_UNMEASURED,
                                                                [], "тест"))[1])

    rc = cli.main(["list", "--tracker-dir", str(explicit), "--no-origin-check"])
    assert seen == [explicit]
    # Заглушка выше отвечает «не измерено», а список пуст ⇒ код 2 — ЭТО ВЕРНО
    # («решений нет» здесь не измерено). Правило не ослабляем, а закрепляем.
    assert rc == 2
