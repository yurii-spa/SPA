"""«Намеренно не доставлено» — пятый вердикт по пути (цикл #354).

Карточка `inbox-uborschik-ne-znaet-slova-namerenno-ne-dostavleno`, замер цикла #353.

**Настоящая авария, которую здесь воспроизводит каждый тест.** Цикл #353 поднял осиротевшую
R&D-итерацию из `/private/tmp/spa_rnd73` и одну вещь из того дерева доставлять ОТКАЗАЛСЯ по
результату замера: черновую карточку владельцу `own-2026-08-23-mertvye-knigi-...` — шаг 1a дал
вердикт `DONE` (тот же вопрос задан карточкой `own-54` и отвечен владельцем 19.08), а черновик
вдобавок советовал вариант ПРОТИВ выбранного. Доставить его значило второй раз спросить
отвеченное — шторм повторов, ADR-084.

Уборщик отказался снять дерево, и отказ САМ ПО СЕБЕ верен. Неверен словарь: у вердикта по пути
есть `delivered` · `superseded` · `unique` · `absent`, а слова «решено не везти, вот почему»
не было вовсе. Цена — дерево неснимаемо НАВСЕГДА, и шаг 0a называет его недоставленной работой
КАЖДЫЙ цикл: постоянный житель раздела «НЕ ДОСТАВЛЕНО» приучает пролистывать весь раздел, и
настоящая находка проедет вместе с осадком (класс #146–#176, он же #243, он же #268).

**Что здесь проверяется в ОБЕ стороны.** Признак берётся ТОЛЬКО из явного объявления с
причиной; молчание вердикта не даёт; `unique`/`absent` без объявления не ослаблены ни на йоту;
объявление одной сессии про СВОЙ путь не гасит находку о чужом дереве; путь из отчёта не
исчезает, а называется своим разделом с автором и причиной.

Тесты герметичны: настоящие git-репозитории в ``tmp_path``, `ps` подменён, сети нет, дат в
фикстурах нет — время подаётся входом.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: вердикт по пути считается сверкой с базовым ref",
)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_c354_guard", "scripts/check_undelivered_work.py")


@pytest.fixture(scope="module")
def reaper():
    sys.path.insert(0, str(ROOT / "scripts"))
    return _load("_c354_reaper", "scripts/reap_stale_worktrees.py")


@pytest.fixture(scope="module")
def writer():
    return _load("_c354_writer", "scripts/log_session_change.py")


# ── общая инфраструктура ─────────────────────────────────────────────────────

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)   # FROZEN-DATE-OK: время — ВХОД теста
NOW_TS = NOW.timestamp()
OLD_TS = NOW_TS - 72 * 3600

# Путь и причина — дословно из разбора цикла #353.
CARD = "nimbalyst-local/tracker/own-2026-08-23-mertvye-knigi-v-issledovatelskoi-paneli.md"
WHY = "дубль отвеченной own-54, шаг 1a = DONE, цикл #353"


def _run(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(cwd),
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env)
    assert p.returncode == 0, f"git {args} -> {p.returncode}: {p.stderr}"
    return p.stdout


def _age(path):
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            try:
                os.utime(os.path.join(dirpath, name), (OLD_TS, OLD_TS))
            except OSError:
                pass


@pytest.fixture
def repo(tmp_path):
    """(root, origin) — рабочий репозиторий с настоящим `origin/main`."""
    origin = tmp_path / "origin.git"
    _run(tmp_path, "init", "--bare", "-b", "main", str(origin))
    root = tmp_path / "work"
    _run(tmp_path, "clone", str(origin), str(root))
    (root / "docs").mkdir()
    (root / "docs" / "STATE.md").write_text("v1\n", encoding="utf-8")
    (root / "nimbalyst-local" / "tracker").mkdir(parents=True)
    (root / "nimbalyst-local" / "tracker" / "keep.md").write_text("status: new\n", encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-m", "base")
    _run(root, "push", "origin", "main")
    (root / "data").mkdir()
    (root / "data" / "session_changes.jsonl").write_text("", encoding="utf-8")
    return root, origin


def _worktree(root, name):
    wt = root.parent / name
    _run(root, "worktree", "add", "--detach", str(wt), "HEAD")
    return wt


def _journal(root, entries):
    path = root / "data" / "session_changes.jsonl"
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                    encoding="utf-8")
    return path


def _drop_entry(path, reason=WHY, session="cycle-353", card="inbox-uborschik-ne-znaet-slova"):
    return {"ts": "2026-08-20T08:13:01Z", "session": session, "summary": "подъём R&D #73",
            "files": [str(path)], "card": card,
            "dropped": [{"path": str(path), "reason": reason}]}


def _rnd73(root):
    """Дерево #353: в нём лежит черновая карточка, которой на origin нет вовсе."""
    wt = _worktree(root, "spa_rnd73")
    (wt / CARD).parent.mkdir(parents=True, exist_ok=True)
    (wt / CARD).write_text("---\nstatus: needs-owner\n---\nчерновик\n", encoding="utf-8")
    _age(wt)
    return wt


def _report(reaper, root, **kw):
    return reaper.build_report(root, "origin/main", root / "data" / "session_changes.jsonl",
                               kw.pop("grace_hours", 24.0), now=kw.pop("now", NOW),
                               now_ts=kw.pop("now_ts", NOW_TS), **kw)


def _verdict(report, wt):
    for t in report["trees"]:
        if Path(t["path"]).resolve() == Path(wt).resolve():
            return t
    raise AssertionError(f"{wt} нет в отчёте: {[t['path'] for t in report['trees']]}")


# ── 1. писатель: решение без причины не пишется вовсе ────────────────────────

class TestDeclarationNeedsAReason:
    """Признак, который можно поставить МОЛЧАНИЕМ, закрыл бы что угодно (карточка, п. 1)."""

    def test_declaration_is_written_with_path_and_reason(self, writer, tmp_path):
        log = tmp_path / "j.jsonl"
        e = writer.record("итог", [], "", log=log, session="cycle-353",
                          dropped=[(f"/tmp/spa_rnd73/{CARD}", WHY)])
        assert e["dropped"] == [{"path": f"/tmp/spa_rnd73/{CARD}", "reason": WHY}]
        assert json.loads(log.read_text(encoding="utf-8").strip())["dropped"][0]["reason"] == WHY

    def test_empty_reason_refuses_and_writes_nothing(self, writer, tmp_path):
        log = tmp_path / "j.jsonl"
        with pytest.raises(writer.DroppedWithoutReason):
            writer.record("итог", [], "", log=log, session="cycle-353",
                          dropped=[(f"/tmp/spa_rnd73/{CARD}", "   ")])
        assert not log.exists(), "отказ обязан быть ДО записи: пустышка в журнале хуже отказа"

    def test_cli_returns_two_on_a_reasonless_declaration(self, writer, tmp_path, monkeypatch):
        monkeypatch.setattr(writer, "_LOG", tmp_path / "j.jsonl")
        rc = writer.main(["--summary", "итог", "--dropped", f"/tmp/x/{CARD}", ""])
        assert rc == 2
        assert not (tmp_path / "j.jsonl").exists()

    def test_entry_without_the_flag_is_unchanged(self, writer, tmp_path):
        """Схема только ДОПОЛНЯЕТСЯ: читатели старых записей обязаны работать как прежде."""
        log = tmp_path / "j.jsonl"
        e = writer.record("итог", [], "", log=log, session="cycle-353")
        assert "dropped" not in e


# ── 2. уборщик: положительный контроль — авария #353 ────────────────────────

class TestReaperLearnsTheWord:
    """До правки этот тест краснеет: `dropped` уборщику неизвестен, дерево остаётся навсегда."""

    def test_without_a_declaration_the_tree_stays_forever(self, reaper, repo):
        """Обратный контроль и ровно состояние #353: отказ верен, снимать нельзя."""
        root, _ = repo
        wt = _rnd73(root)
        _journal(root, [])
        t = _verdict(_report(reaper, root), wt)
        assert t["verdict"] == reaper.KEEP
        assert "НЕДОСТАВЛЕННАЯ" in t["reasons"][0]
        assert [p["state"] for p in t["paths"]] == [reaper.ABSENT]

    def test_a_declared_path_becomes_dropped_and_the_tree_is_reaped(self, reaper, repo):
        root, _ = repo
        wt = _rnd73(root)
        _journal(root, [_drop_entry(wt / CARD)])
        t = _verdict(_report(reaper, root), wt)
        assert t["verdict"] == reaper.REAP, t["reasons"]
        assert [p["state"] for p in t["paths"]] == [reaper.DROPPED]

    def test_the_original_verdict_is_kept_as_was(self, reaper, repo):
        """«Сняли, потому что кто-то так решил» обязано быть проверяемо задним числом."""
        root, _ = repo
        wt = _rnd73(root)
        _journal(root, [_drop_entry(wt / CARD)])
        path = _verdict(_report(reaper, root), wt)["paths"][0]
        assert path["was"] == reaper.ABSENT
        assert path["dropped"]["reason"] == WHY

    def test_the_reason_and_its_author_are_printed_aloud(self, reaper, repo):
        """Иначе признак станет тихой кнопкой «снять что угодно»."""
        root, _ = repo
        wt = _rnd73(root)
        _journal(root, [_drop_entry(wt / CARD)])
        text = reaper.render(_report(reaper, root))
        assert "НАМЕРЕННО НЕ ДОСТАВЛЕНО" in text
        assert WHY in text
        assert "cycle-353" in text

    def test_tmp_and_private_tmp_are_one_directory(self, reaper, repo, tmp_path):
        """macOS отдаёт `/tmp/x` и `/private/tmp/x` за один каталог (класс #301/#303).

        Проверяется НА КЛЮЧАХ, а не через `tmp_path`: pytest выдаёт каталоги под
        `/private/var`, и тест «по дереву» тихо превратился бы в пропуск — украшение вместо
        проверки. Здесь обе формы объявляются явно и обе обязаны находиться."""
        declared = f"/private/tmp/spa_rnd73/{CARD}"
        journal = tmp_path / "j.jsonl"
        journal.write_text(json.dumps(_drop_entry(declared), ensure_ascii=False) + "\n",
                           encoding="utf-8")
        decls, why = reaper.dropped_declarations(journal)
        assert why is None
        assert decls[declared]["reason"] == WHY
        assert decls[f"/tmp/spa_rnd73/{CARD}"]["reason"] == WHY


# ── 3. уборщик: обратные контроли — молчание вердикта не даёт ────────────────

class TestReaperFailsClosed:

    def test_a_declaration_without_a_reason_grants_nothing(self, reaper, repo):
        """Пара, дописанная в журнал руками в обход писателя, вердикта не даёт."""
        root, _ = repo
        wt = _rnd73(root)
        _journal(root, [_drop_entry(wt / CARD, reason="")])
        assert _verdict(_report(reaper, root), wt)["verdict"] == reaper.KEEP

    def test_a_declaration_about_another_path_grants_nothing(self, reaper, repo):
        root, _ = repo
        wt = _rnd73(root)
        _journal(root, [_drop_entry(wt / "docs" / "OTHER.md")])
        assert _verdict(_report(reaper, root), wt)["verdict"] == reaper.KEEP

    def test_a_declaration_about_another_tree_grants_nothing(self, reaper, repo):
        """Один и тот же ОТНОСИТЕЛЬНЫЙ путь лежит в десятках деревьев — решение про одно."""
        root, _ = repo
        wt = _rnd73(root)
        _journal(root, [_drop_entry(Path("/tmp/spa_someone_else") / CARD)])
        assert _verdict(_report(reaper, root), wt)["verdict"] == reaper.KEEP

    def test_positive_verdicts_are_never_overwritten(self, reaper, repo):
        """Объявление имеет власть над РЕШЕНИЕМ, а не над ИЗМЕРЕНИЕМ."""
        root, _ = repo
        wt = _worktree(root, "spa_c300")
        (wt / "docs" / "STATE.md").write_text("доставленное\n", encoding="utf-8")
        _age(wt)
        (root / "docs" / "STATE.md").write_text("доставленное\n", encoding="utf-8")
        _run(root, "commit", "-am", "delivered via API")
        (root / "docs" / "STATE.md").write_text("ещё позже\n", encoding="utf-8")
        _run(root, "commit", "-am", "later")
        _run(root, "push", "origin", "main")
        _journal(root, [_drop_entry(wt / "docs" / "STATE.md")])
        assert [p["state"] for p in _verdict(_report(reaper, root), wt)["paths"]] == \
            [reaper.DELIVERED]

    def test_a_second_undeclared_path_still_keeps_the_tree(self, reaper, repo):
        """Одно объявление не снимает дерево целиком: остальное судится как раньше."""
        root, _ = repo
        wt = _rnd73(root)
        (wt / "docs" / "STATE.md").write_text("работа, которой нигде больше нет\n",
                                              encoding="utf-8")
        _age(wt)
        _journal(root, [_drop_entry(wt / CARD)])
        t = _verdict(_report(reaper, root), wt)
        assert t["verdict"] == reaper.KEEP
        assert "docs/STATE.md" in t["reasons"][0]


# ── 4. квитанция: причина ложится рядом с архивом, содержимое не теряется ────

class TestReceiptCarriesTheDecision:

    def test_receipt_records_the_reason_next_to_the_archive(self, reaper, repo, tmp_path):
        root, _ = repo
        wt = _rnd73(root)
        _journal(root, [_drop_entry(wt / CARD)])
        t = _verdict(_report(reaper, root), wt)
        ledger = tmp_path / "reap.jsonl"
        reaper.record_reap(root, wt, "origin/main", t["paths"], t["churn"], "/arch/x",
                           ledger=ledger, head=t["head"])
        row = json.loads(ledger.read_text(encoding="utf-8").strip())
        assert row["paths"][CARD] == reaper.DROPPED
        assert row["dropped"][CARD]["reason"] == WHY
        assert row["dropped"][CARD]["session"] == "cycle-353"

    def test_the_dropped_file_is_still_archived(self, reaper, repo, tmp_path):
        """«Не везём на origin» ≠ «уничтожаем»: архив снимается как обычно."""
        root, _ = repo
        wt = _rnd73(root)
        _journal(root, [_drop_entry(wt / CARD)])
        t = _verdict(_report(reaper, root), wt)
        dest, why = reaper.archive(wt, "origin/main", t["paths"], archive_root=tmp_path / "a",
                                   stamp="20260823T120000Z")
        assert why is None, why
        assert (Path(dest) / "files" / CARD).read_text(encoding="utf-8").startswith("---")


# ── 5. шаг 0a: живое дерево — находка меняет РАЗДЕЛ, а не видимость ─────────

_STEP0A_NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)  # FROZEN-DATE-OK: вход теста


def _entry(session, files, ts="2026-08-20T12:00:00Z", dropped=None):
    e = {"ts": ts, "session": session, "summary": "работа", "files": [str(f) for f in files]}
    if dropped is not None:
        e["dropped"] = dropped
    return e


def _step0a(guard, root, entries, **kw):
    kw.setdefault("ps", lambda pid: (1, ""))
    return guard.build_report(entries=entries, root=root, base_ref="origin/main",
                              self_session="pid999999", now=_STEP0A_NOW, grace_hours=3.0, **kw)


class TestStep0aNamesTheDecision:

    def test_without_a_declaration_the_path_is_a_finding(self, guard, repo):
        """Обратный контроль: сегодняшнее поведение, и оно верное."""
        root, _ = repo
        (root / "docs" / "NEW.md").write_text("работа\n", encoding="utf-8")
        rep = _step0a(guard, root, [_entry("pid21014", [root / "docs" / "NEW.md"])])
        assert [f["path"] for f in rep["findings"]] == ["docs/NEW.md"]
        assert rep["exit_code"] == 1
        assert (rep.get("dropped") or []) == []

    def test_a_declared_path_moves_to_its_own_section(self, guard, repo):
        root, _ = repo
        p = root / "docs" / "NEW.md"
        p.write_text("работа\n", encoding="utf-8")
        rep = _step0a(guard, root, [
            _entry("pid21014", [p], dropped=[{"path": str(p), "reason": WHY}])])
        assert rep["findings"] == []
        assert len(rep["dropped"]) == 1
        row = rep["dropped"][0]
        assert row["path"] == "docs/NEW.md" and row["reason"] == WHY
        assert row["decided_by"] == "pid21014"
        assert row["was"], "исходное состояние обязано сохраниться"

    def test_the_decision_alone_does_not_hold_exit_code_one(self, guard, repo):
        root, _ = repo
        p = root / "docs" / "NEW.md"
        p.write_text("работа\n", encoding="utf-8")
        rep = _step0a(guard, root, [
            _entry("pid21014", [p], dropped=[{"path": str(p), "reason": WHY}])])
        assert rep["exit_code"] == 0

    def test_render_prints_the_author_and_the_reason(self, guard, repo):
        root, _ = repo
        p = root / "docs" / "NEW.md"
        p.write_text("работа\n", encoding="utf-8")
        text = guard.render(_step0a(guard, root, [
            _entry("pid21014", [p], dropped=[{"path": str(p), "reason": WHY}])]))
        assert "НАМЕРЕННО НЕ ДОСТАВЛЕНО" in text
        assert WHY in text and "pid21014" in text
        assert "решено не доставлять" in text

    def test_the_pre_decision_measurement_is_labelled_as_such(self, guard, repo):
        """Живой замер #354: перенесённая строка кончается словами «её надо поднять» —
        в разделе решения она спорила бы с собственным заголовком. Замер не переписывается
        (он верен и сделан ДО решения), а называется его место во времени."""
        root, _ = repo
        p = root / "docs" / "NEW.md"
        p.write_text("работа\n", encoding="utf-8")
        text = guard.render(_step0a(guard, root, [
            _entry("pid21014", [p], dropped=[{"path": str(p), "reason": WHY}])]))
        for line in text.splitlines():
            if "надо поднять" in line:
                assert "измерено до решения" in line, line

    def test_a_declaration_of_another_session_about_another_tree_does_not_hide_it(self, guard,
                                                                                 repo):
        """Ключ — объявленная СТРОКА, не relative-путь: иначе одно решение гасило бы чужие."""
        root, _ = repo
        p = root / "docs" / "NEW.md"
        p.write_text("работа\n", encoding="utf-8")
        rep = _step0a(guard, root, [
            _entry("pid21014", [p]),
            _entry("pid31439", [],
                   dropped=[{"path": "/tmp/spa_other/docs/NEW.md", "reason": WHY}])])
        assert [f["path"] for f in rep["findings"]] == ["docs/NEW.md"]
        assert rep["exit_code"] == 1

    def test_a_reasonless_declaration_hides_nothing(self, guard, repo):
        root, _ = repo
        p = root / "docs" / "NEW.md"
        p.write_text("работа\n", encoding="utf-8")
        rep = _step0a(guard, root, [
            _entry("pid21014", [p], dropped=[{"path": str(p), "reason": ""}])])
        assert [f["path"] for f in rep["findings"]] == ["docs/NEW.md"]


# ── 6. шаг 0a: дерево уже СНЯТО — квитанция говорит за него ─────────────────

def _ledger(root, rows):
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "worktree_reap_log.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _receipt(wt, paths, dropped=None):
    row = {"ts": "2026-08-23T08:13:01Z", "worktree": str(wt), "base": "origin/main",
           "archive": "/arch/spa_rnd73-20260823T081301Z", "churn_paths": 3, "paths": dict(paths)}
    if dropped is not None:
        row["dropped"] = dropped
    return row


class TestStep0aReadsTheReceiptAfterTheTreeIsGone:
    """Без этой ветки починка уборщика РОДИЛА БЫ «не измерено навсегда» (код 2).

    Квитанция со словом `dropped` попала бы в ветку «помечен неизвестно чем» — то есть цена
    уборки снова оказалась бы выше выгоды, как до цикла #292."""

    def test_the_receipt_verdict_is_a_decision_not_an_unmeasured(self, guard, repo, tmp_path):
        root, _ = repo
        wt = tmp_path / "spa_rnd73"
        _ledger(root, [_receipt(wt, {CARD: "dropped"},
                                dropped={CARD: {"reason": WHY, "session": "cycle-353",
                                                "ts": "2026-08-23T08:13:01Z"}})])
        rep = _step0a(guard, root, [_entry("pid95478", [wt / CARD])])
        assert rep["unmeasured"] == [], rep["unmeasured"]
        assert rep["findings"] == []
        assert len(rep["dropped"]) == 1
        assert WHY in rep["dropped"][0]["detail"]
        assert "cycle-353" in rep["dropped"][0]["detail"]
        assert rep["exit_code"] == 0

    def test_a_receipt_without_the_reason_stays_unmeasured(self, guard, repo, tmp_path):
        """Слово есть, причины нет — решение это было или порча записи, НЕ ИЗМЕРЕНО."""
        root, _ = repo
        wt = tmp_path / "spa_rnd73"
        _ledger(root, [_receipt(wt, {CARD: "dropped"})])
        rep = _step0a(guard, root, [_entry("pid95478", [wt / CARD])])
        assert (rep.get("dropped") or []) == []
        assert rep["exit_code"] == 2
        assert any("НЕ ИЗМЕРЕНО" in u["reason"] for u in rep["unmeasured"])

    def test_a_path_marked_unique_in_the_receipt_still_fails_closed(self, guard, repo, tmp_path):
        """Граница цикла #292 не сдвинута: снятие не стало способом гасить находки."""
        root, _ = repo
        wt = tmp_path / "spa_rnd73"
        _ledger(root, [_receipt(wt, {CARD: "unique"})])
        rep = _step0a(guard, root, [_entry("pid95478", [wt / CARD])])
        assert (rep.get("dropped") or []) == []
        assert rep["exit_code"] == 2


# ── 7. недоставленная КАРТОЧКА — второй раздел, зовущий «поднять» ───────────

class TestUndeliveredCardCanBeDropped:

    def test_without_a_declaration_the_card_is_a_finding(self, guard, repo):
        root, _ = repo
        wt = _rnd73(root)
        rep = _step0a(guard, root, [_entry("pid95478", [wt / CARD])])
        assert [c["card"] for c in rep["card_findings"]] == \
            ["own-2026-08-23-mertvye-knigi-v-issledovatelskoi-paneli"]

    def test_a_declared_card_moves_to_the_decision_section(self, guard, repo):
        root, _ = repo
        wt = _rnd73(root)
        rep = _step0a(guard, root, [
            _entry("pid95478", [wt / CARD],
                   dropped=[{"path": str(wt / CARD), "reason": WHY}])])
        assert rep["card_findings"] == []
        assert any(row["was"] == "card" for row in rep["dropped"])
        assert any(row["reason"] == WHY for row in rep["dropped"])
