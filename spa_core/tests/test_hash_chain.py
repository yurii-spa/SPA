"""
spa_core/tests/test_hash_chain.py — tests for the tamper-evident hash-chained audit trail.

Every test redirects the chain file to a tmp_path so the real
data/audit_chain.jsonl is never touched.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json

import pytest

from spa_core.audit import hash_chain


@pytest.fixture
def chain(tmp_path, monkeypatch):
    """Point the module at an isolated tmp chain file for each test."""
    p = tmp_path / "audit_chain.jsonl"
    monkeypatch.setattr(hash_chain, "_CHAIN", p)
    return p


# --------------------------------------------------------------------------- #
def test_empty_chain_head_and_verify(chain):
    assert hash_chain.head() is None
    assert hash_chain.tail() == []
    v = hash_chain.verify_chain()
    # НАМЕРЕННОЕ изменение (инв. #16, ADR-273, запись в docs/journal/2026-W37.md, 09.09):
    # у вердикта появилось ЧЕТВЁРТОЕ поле `torn_tail` — обрыв последней строки после
    # перехода на дописывание за O(1). Проверка остаётся ТОЧНЫМ равенством (ослаблением
    # было бы `v["valid"] is True`), в неё добавлено реально существующее поле со
    # значением, которого требует пустая цепочка.
    assert v == {"valid": True, "length": 0, "broken_at": None, "torn_tail": False}


def test_genesis_prev_hash(chain):
    e = hash_chain.append("cycle", {"k": 1}, ts="2026-06-24T08:00:00+00:00")
    assert e["seq"] == 0
    assert e["prev_hash"] == hash_chain.GENESIS_PREV
    assert e["prev_hash"] == "0" * 64
    assert len(e["entry_hash"]) == 64


def test_append_links_prev_hash(chain):
    e0 = hash_chain.append("cycle", {"n": 0}, ts="2026-06-24T08:00:00+00:00")
    e1 = hash_chain.append("cycle", {"n": 1}, ts="2026-06-24T08:01:00+00:00")
    e2 = hash_chain.append("risk_event", {"reason": "x"}, ts="2026-06-24T08:02:00+00:00")

    # Each entry's prev_hash is the previous entry's entry_hash.
    assert e1["prev_hash"] == e0["entry_hash"]
    assert e2["prev_hash"] == e1["entry_hash"]
    # Monotonic seq.
    assert [e0["seq"], e1["seq"], e2["seq"]] == [0, 1, 2]


def test_verify_valid_after_appends(chain):
    for i in range(5):
        hash_chain.append("cycle", {"i": i}, ts=f"2026-06-24T08:0{i}:00+00:00")
    v = hash_chain.verify_chain()
    assert v["valid"] is True
    assert v["length"] == 5
    assert v["broken_at"] is None


def test_determinism_same_inputs_same_hash():
    """Same inputs + ts → identical entry_hash, independent of any chain file."""
    h1 = hash_chain.compute_entry_hash(
        3, "2026-06-24T08:00:00+00:00", "cycle", {"a": 1, "b": [2, 3]}, "ab" * 32
    )
    h2 = hash_chain.compute_entry_hash(
        3, "2026-06-24T08:00:00+00:00", "cycle", {"b": [2, 3], "a": 1}, "ab" * 32
    )
    # Key order in the payload must NOT change the hash (canonical sort_keys).
    assert h1 == h2
    # And it is the real sha256, not some accidental constant.
    assert h1 != hash_chain.compute_entry_hash(
        3, "2026-06-24T08:00:00+00:00", "cycle", {"a": 2}, "ab" * 32
    )


def test_tamper_middle_entry_detected(chain):
    """Mutate a middle entry's payload ON DISK → verify_chain reports the break."""
    for i in range(5):
        hash_chain.append("cycle", {"i": i}, ts=f"2026-06-24T08:0{i}:00+00:00")
    assert hash_chain.verify_chain()["valid"] is True

    # Read raw lines, mutate entry seq=2's payload, write back (entry_hash left stale).
    lines = chain.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[2])
    entry["payload"] = {"i": 999}  # tampered value
    lines[2] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    chain.write_text("\n".join(lines) + "\n", encoding="utf-8")

    v = hash_chain.verify_chain()
    assert v["valid"] is False
    assert v["broken_at"] == 2
    assert v["length"] == 5


def test_tamper_rewrite_hash_breaks_linkage(chain):
    """Recomputing the tampered entry's OWN hash still breaks the next entry's prev_hash."""
    for i in range(4):
        hash_chain.append("cycle", {"i": i}, ts=f"2026-06-24T08:0{i}:00+00:00")

    lines = chain.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[1])
    entry["payload"] = {"i": 777}
    # Forge a self-consistent entry_hash for the tampered entry...
    entry["entry_hash"] = hash_chain.compute_entry_hash(
        entry["seq"], entry["ts"], entry["event_type"], entry["payload"], entry["prev_hash"]
    )
    lines[1] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    chain.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Entry 1 verifies internally now, but entry 2's prev_hash no longer matches → break at 2.
    v = hash_chain.verify_chain()
    assert v["valid"] is False
    assert v["broken_at"] == 2


def test_record_helpers(chain):
    c = hash_chain.record_cycle({"equity_usd": 100149.54}, ts="2026-06-24T08:00:00+00:00")
    r = hash_chain.record_risk_event("kill switch armed", ts="2026-06-24T08:05:00+00:00")
    assert c["event_type"] == "cycle"
    assert r["event_type"] == "risk_event"
    assert r["payload"] == {"reason": "kill switch armed"}
    assert r["prev_hash"] == c["entry_hash"]
    assert hash_chain.verify_chain()["valid"] is True


def test_head_and_tail(chain):
    first = hash_chain.append("cycle", {"i": 0}, ts="2026-06-24T08:00:00+00:00")
    for i in range(1, 6):
        hash_chain.append("cycle", {"i": i}, ts=f"2026-06-24T08:0{i}:00+00:00")
    assert hash_chain.head() == first
    t = hash_chain.tail(3)
    assert len(t) == 3
    assert [e["payload"]["i"] for e in t] == [3, 4, 5]


def test_persistence_across_reads(chain):
    """Atomic write + re-read returns the same chain (no torn lines)."""
    hash_chain.append("cycle", {"i": 0}, ts="2026-06-24T08:00:00+00:00")
    hash_chain.append("cycle", {"i": 1}, ts="2026-06-24T08:01:00+00:00")
    reread = hash_chain._read_all()
    assert len(reread) == 2
    assert reread[0]["payload"] == {"i": 0}
    # No stray tmp files left behind.
    leftovers = list(chain.parent.glob(".audit_chain_*"))
    assert leftovers == []


# ── ADR-273: дописывание за O(1) ──────────────────────────────────────────────────────
# Замер 2026-09-09: data/audit_chain.jsonl = 18.9 МБ / 22 738 записей при ~190 дописываниях
# в день. Прежний append читал и переписывал ВЕСЬ файл ⇒ ≈3.6 ГБ записи в сутки, и цена
# одной записи росла вместе с длиной защищаемой истории.
import io
import json as _json
import os as _os

import pytest as _pytest

from spa_core.audit import hash_chain as _hc


@_pytest.fixture()
def chain(tmp_path, monkeypatch):
    monkeypatch.setattr(_hc, "_CHAIN", tmp_path / "audit_chain.jsonl")
    return tmp_path / "audit_chain.jsonl"


def test_append_does_not_read_the_whole_chain(chain, monkeypatch):
    """Проводка, а не намерение: `_read_all` при дописывании не зовётся ни разу."""
    for i in range(5):
        _hc.append("cycle", {"i": i}, ts=f"2030-01-0{i + 1}T00:00:00+00:00")
    calls = []
    monkeypatch.setattr(_hc, "_read_all", lambda **kw: calls.append(1) or [])
    _hc.append("cycle", {"i": 99}, ts="2030-02-01T00:00:00+00:00")
    assert calls == [], "append снова читает всю цепочку — вернулось квадратичное поведение"


def test_append_writes_only_the_new_line(chain):
    """Файл РАСТЁТ на одну строку, а его начало не переписывается (тот же байт-в-байт префикс)."""
    _hc.append("cycle", {"i": 0}, ts="2030-01-01T00:00:00+00:00")
    before = chain.read_bytes()
    _hc.append("cycle", {"i": 1}, ts="2030-01-02T00:00:00+00:00")
    after = chain.read_bytes()
    assert after.startswith(before)
    assert after[len(before):].count(b"\n") == 1


def test_chain_still_links_and_verifies_after_o1_appends(chain):
    for i in range(20):
        _hc.append("cycle", {"i": i}, ts=f"2030-03-{i + 1:02d}T00:00:00+00:00")
    v = _hc.verify_chain()
    assert v["valid"] is True and v["length"] == 20 and v["broken_at"] is None
    assert v["torn_tail"] is False
    entries = _hc._read_all()
    assert [e["seq"] for e in entries] == list(range(20))
    assert all(entries[i]["prev_hash"] == entries[i - 1]["entry_hash"] for i in range(1, 20))


def test_tampering_in_the_middle_is_still_detected(chain):
    """Контроль неослабления: правка исторической записи по-прежнему рвёт цепочку."""
    for i in range(6):
        _hc.append("cycle", {"i": i}, ts=f"2030-04-0{i + 1}T00:00:00+00:00")
    rows = _hc._read_all()
    rows[2]["payload"] = {"i": "подделка"}
    _hc.rewrite_all(rows)
    v = _hc.verify_chain()
    assert v["valid"] is False and v["broken_at"] == 2


def test_a_torn_last_line_is_named_not_swallowed_and_not_called_tampering(chain):
    """Обрыв ПОСЛЕДНЕЙ строки — след падения между записью и fsync, а не подделка.

    Третий исход: префикс верен, факт назван (`torn_tail`), молча он не исчезает."""
    for i in range(4):
        _hc.append("cycle", {"i": i}, ts=f"2030-05-0{i + 1}T00:00:00+00:00")
    raw = chain.read_bytes()
    chain.write_bytes(raw + b'{"seq": 4, "ts": "2030-05-05T00:00')   # обрыв на середине
    v = _hc.verify_chain()
    assert v["valid"] is True and v["broken_at"] is None
    assert v["torn_tail"] is True, "обрыв хвоста не назван — «не измерено» выдано за норму"
    assert _hc._read_head()["seq"] == 3, "голова должна быть последней ЦЕЛОЙ записью"


def test_the_next_append_after_a_torn_tail_continues_from_the_last_complete_entry(chain):
    for i in range(3):
        _hc.append("cycle", {"i": i}, ts=f"2030-06-0{i + 1}T00:00:00+00:00")
    chain.write_bytes(chain.read_bytes() + b'{"seq": 3, "ts": "2030-06')
    e = _hc.append("cycle", {"i": 3}, ts="2030-06-04T00:00:00+00:00")
    assert e["seq"] == 3 and e["prev_hash"] == _json.loads(
        [ln for ln in chain.read_text().splitlines() if ln.strip()][2])["entry_hash"]


def test_a_broken_line_in_the_middle_is_still_a_hard_error(chain):
    """Послабление касается ТОЛЬКО последней строки: битая строка в середине по-прежнему падает."""
    for i in range(4):
        _hc.append("cycle", {"i": i}, ts=f"2030-07-0{i + 1}T00:00:00+00:00")
    lines = chain.read_text().splitlines()
    lines[1] = '{"seq": 1, "broken'
    chain.write_text("\n".join(lines) + "\n")
    with _pytest.raises(ValueError):
        _hc._read_all()


def test_head_is_found_even_when_the_last_entry_is_larger_than_the_window(chain):
    """Окно чтения растёт: одна запись может быть больше 64 КБ."""
    _hc.append("cycle", {"i": 0}, ts="2030-08-01T00:00:00+00:00")
    _hc.append("cycle", {"blob": "x" * 200_000}, ts="2030-08-02T00:00:00+00:00")
    assert _hc._read_head()["seq"] == 1


def test_concurrent_appends_from_separate_processes_keep_the_chain_valid(chain, tmp_path):
    """Двадцать дописываний из ЧЕТЫРЁХ процессов — ни одной потери и ни одного двойного seq.

    Прежний путь (перечитать всё → переписать) терял запись молча; O(1)-дописывание без
    блокировки выдало бы два `seq` с одним номером. Мерится настоящими процессами, а не
    потоками: блокировка межпроцессная."""
    import subprocess
    import sys as _sys
    root = str(_Path_root())
    prog = (
        "import sys; sys.path.insert(0, %r)\n"
        "from pathlib import Path\n"
        "from spa_core.audit import hash_chain as hc\n"
        "hc._CHAIN = Path(%r)\n"
        "import sys as s\n"
        "i = int(s.argv[1])\n"
        "for k in range(5):\n"
        "    hc.append('cycle', {'w': i, 'k': k}, ts='2031-01-%%02d T00:00:00+00:00' %% (i * 5 + k + 1))\n"
    ) % (root, str(chain))
    script = tmp_path / "worker.py"
    script.write_text(prog)
    procs = [subprocess.Popen([_sys.executable, str(script), str(i)]) for i in range(4)]
    assert [p.wait(timeout=120) for p in procs] == [0, 0, 0, 0]
    v = _hc.verify_chain()
    assert v["valid"] is True, v
    assert v["length"] == 20, f"потеряны записи: {v['length']} из 20"
    seqs = [e["seq"] for e in _hc._read_all()]
    assert seqs == list(range(20)) and len(set(seqs)) == 20


def _Path_root():
    from pathlib import Path as _P
    return _P(__file__).resolve().parents[2]
