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
    """A tmp tracker dir wired into the queue module globals the CLI reads."""
    d = tmp_path / "tracker"
    d.mkdir()
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


def test_notify_send_reports_ok(cli, tracker, monkeypatch, capsys):
    p = _write(tracker, "own-9.md", CARD)
    calls = {}

    def _fake(path, dry_run=False):
        calls["path"] = path
        calls["dry_run"] = dry_run
        return "sent"

    monkeypatch.setattr(cli, "notify_needs_owner", _fake)
    rc = cli.main(["notify", str(p)])
    assert rc == 0
    assert calls == {"path": str(p), "dry_run": False}
    assert "OK: notified" in capsys.readouterr().out


# ----------------------------------------------------------------------------- main

def test_main_requires_a_subcommand(cli):
    with pytest.raises(SystemExit):
        cli.main([])
