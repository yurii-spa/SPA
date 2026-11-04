"""Разбор входящих: отчёт без правки карточек — тип, готовность, дубли, возраст (ADR-154 §3)."""
from datetime import datetime, timezone

from spa_core.owner_queue import triage as t

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — triage(..., now=NOW)


def _w(d, name, fm, body=""):
    (d / name).write_text("---\n" + "".join(f"{k}: {v}\n" for k, v in fm.items()) + "---\n" + body,
                          encoding="utf-8")


def test_counts_ready_dups_and_never_touches_cards(tmp_path):
    _w(tmp_path, "inbox-a.md", {"status": "new", "title": "Проверь дашборд", "created": "2026-10-20"})
    _w(tmp_path, "inbox-b.md", {"status": "new", "title": "Проверь, дашборд!", "intake_kind": "task"},
       "проба: problem_absent:x\n")
    _w(tmp_path, "inbox-c.md", {"status": "done", "title": "Проверь дашборд"})
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    r = t.triage(tmp_path, now=NOW)
    assert (r["new_total"], r["ready"], r["kind_unknown"]) == (2, 1, 1)
    assert r["dup_groups"] == [["inbox-a.md", "inbox-b.md"]]
    assert r["age_unmeasured"] == 1 and r["oldest_days"] == 7.0
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before, "разбор правит карточки"


def test_cli_writes_report_and_unmeasured_is_loud(tmp_path, capsys):
    _w(tmp_path, "inbox-a.md", {"status": "new", "title": "x"})
    out = tmp_path / "r.json"
    assert t.main(["--tracker-dir", str(tmp_path), "--out", str(out)]) == 0 and out.exists()
    assert "РАЗБОР ВХОДЯЩИХ" in capsys.readouterr().out
    assert t.main(["--tracker-dir", str(tmp_path), "--out", str(tmp_path / "f" / "x" / "\0bad")]) == 2
    assert "НЕ ИЗМЕРЕН" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# ADR-914: отчёт НАЗЫВАЕТ дерево, в котором мерил, и знаменатель
#
# Предмет (замер цикла #1027): шаг цикла зовут с `--tracker-dir` ПРОД-дерева, и
# прод-копия трекера дрейфует от origin по построению. Строка «new 40, род записи
# НЕ ОБЪЯВЛЕН 4» читалась как утверждение О ПРОЕКТЕ, тогда как на origin/main в тот
# же час было new 342 и НЕ ОБЪЯВЛЕН 306 — а все ЧЕТЫРЕ названных карточки род
# ОБЪЯВЛЯЮТ (`intake_kind: task`), просто в прод-копиях этого объявления ещё нет.
# Контроли ниже — на НАСТОЯЩЕМ читателе (`t.triage` / `t.summary_line`), а не на
# словаре, собранном руками: урок #944/#945.
# --------------------------------------------------------------------------- #

def test_the_report_names_the_tree_it_measured_and_the_denominator(tmp_path):
    _w(tmp_path, "inbox-a.md", {"status": "new", "title": "x"})
    _w(tmp_path, "inbox-b.md", {"status": "done", "title": "y"})
    r = t.triage(tmp_path, now=NOW)
    # ГДЕ мерено — разрешённый путь, а не тот, которым позвали.
    assert r["tracker"] == str(tmp_path.resolve())
    # Знаменатель — ВСЕ inbox-карточки любого статуса, а не только `new`.
    assert (r["cards_total"], r["new_total"]) == (2, 1)
    assert r["tracker_unmeasured"] is None
    line = t.summary_line(r)
    assert str(tmp_path.resolve()) in line and "ВСЕГО 2" in line
    assert "не о проекте" in line


def test_a_missing_tracker_is_unmeasured_and_never_a_zero(tmp_path):
    gone = tmp_path / "нет-такого-каталога"
    r = t.triage(gone, now=NOW)
    # Ноль карточек и «каталога нет» — РАЗНЫЕ утверждения (инв. #17).
    assert r["cards_total"] is None
    assert r["tracker_unmeasured"] == "каталога трекера нет"
    line = t.summary_line(r)
    assert "НЕ ИЗМЕРЕНО" in line and "каталога трекера нет" in line


def test_an_old_schema_report_says_the_tree_is_not_named(tmp_path):
    # Положительный контроль на четвёртый исход: отчёт БЕЗ поля `tracker` обязан
    # сказать «НЕ НАЗВАНО», а не подставить известный прод-путь — подстановка
    # утверждала бы о дереве, которого замер не видел.
    _w(tmp_path, "inbox-a.md", {"status": "new", "title": "x"})
    r = t.triage(tmp_path, now=NOW)
    old = {k: v for k, v in r.items() if k not in ("tracker", "cards_total", "tracker_unmeasured")}
    line = t.summary_line(old)
    assert "дерево замера НЕ НАЗВАНО" in line
    assert str(tmp_path.resolve()) not in line


def test_the_four_named_cards_of_the_measurement_are_a_property_of_the_tree(tmp_path):
    """Сцена аварии 04.11: ОДНА карточка, ДВА дерева, разные вердикты о роде.

    Это и есть опровержение премисы заказа G904 п. 8 («род не пишет ПРОИЗВОДИТЕЛЬ»):
    карточка одна и та же, производитель один, а «род объявлен» зависит от того, в
    каком дереве спросили.
    """
    origin, prod = tmp_path / "origin", tmp_path / "prod"
    origin.mkdir(); prod.mkdir()
    fm = {"status": "new", "title": "Инъекция часов кончается на границе подпроцесса",
          "source": "nimbalyst", "created": "2026-11-02"}
    _w(origin, "inbox-c.md", {**fm, "intake_kind": "task"})   # как на origin/main
    _w(prod, "inbox-c.md", fm)                                # как в прод-дереве
    a, b = t.triage(origin, now=NOW), t.triage(prod, now=NOW)
    assert (a["kind_declared"], a["kind_unknown"]) == (1, 0)
    assert (b["kind_declared"], b["kind_unknown"]) == (0, 1)
    # И по строке их теперь НЕЛЬЗЯ спутать: каждая называет своё дерево.
    assert str(origin.resolve()) in t.summary_line(a)
    assert str(prod.resolve()) in t.summary_line(b)
