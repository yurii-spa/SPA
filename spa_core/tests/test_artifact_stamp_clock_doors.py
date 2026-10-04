"""Контроли прибора «доходит ли now до САМОЙ отметки» (заказ G97 п. 3, ADR-562).

Каждый контроль назван по той форме обмана, которую он воспроизводит. Главный из
них — ``test_pin_not_observed_is_unmeasured_not_a_finding``: пин ПРОВЕРЯЕТСЯ
ЗАМЕРОМ у двери, а не верой в переданный флаг (урок ADR-414), и строка, где он
не сработал, обязана быть третьим исходом, а не находкой.

Время здесь не берётся у стенных часов: моменты выводятся из КОНСТАНТ прибора
(``FAKE_WALL``/``ANCHOR``), поэтому у набора нет литеральной даты и нет бомбы
календаря (`.claude/rules/deployment.md`, приём №1 — часы суть вход).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from spa_core.monitoring import _artifact_stamp_clock_probe as probe
from spa_core.monitoring import artifact_stamp_clock_doors as doors


PRODUCER_REL = "spa_core/monitoring/artifact_stamp_clock_doors.py"


def _anchor() -> dt.datetime:
    """Момент прогона — константа прибора, а не календарь машины."""
    return dt.datetime.fromisoformat(doors.ANCHOR)


# ── чьи это часы ────────────────────────────────────────────────────────────────

def test_which_clock_names_the_substituted_wall_clock():
    assert doors.which_clock(doors.FAKE_WALL) == doors.FAKE


def test_which_clock_names_the_injected_anchor():
    assert doors.which_clock(doors.ANCHOR) == doors.ANCH


def test_which_clock_compares_moments_not_text_so_a_z_suffix_is_the_same_moment():
    """Производитель вправе печатать `Z` вместо `+00:00`.

    Равенство ТЕКСТА объявило бы один и тот же момент двумя разными и дало бы
    ложную находку `stamp_from_a_third_source`.
    """
    as_zulu = doors.ANCHOR.replace("+00:00", "Z")
    assert as_zulu != doors.ANCHOR
    assert doors.which_clock(as_zulu) == doors.ANCH


def test_which_clock_reads_an_epoch_number_as_a_moment():
    """Отметка, снятая `time.time()`, другого вида не имеет."""
    epoch = dt.datetime.fromisoformat(doors.FAKE_WALL).timestamp()
    assert doors.which_clock(epoch) == doors.FAKE


def test_which_clock_separates_a_third_source_from_an_absent_stamp():
    """«Отметки нет» и «отметка чужая» — РАЗНЫЕ факты (инв. #17)."""
    third = (_anchor() + dt.timedelta(days=11)).isoformat()
    assert doors.which_clock(third) == doors.OTHER
    assert doors.which_clock(None) == doors.NONE
    assert doors.which_clock("") == doors.NONE
    assert doors.which_clock("не дата вовсе") == doors.OTHER


def test_which_clock_treats_a_naive_stamp_as_utc_rather_than_refusing():
    """Отметка без пояса — у производителей встречается; момент тот же."""
    naive = doors.ANCHOR.replace("+00:00", "")
    assert doors.which_clock(naive) == doors.ANCH


# ── исходы по двум плечам ───────────────────────────────────────────────────────

def _arm(stamp, *, wrote=True, error=None, key="generated_at"):
    return {"stamp": stamp, "stamp_key": key, "wrote_artifact": wrote,
            "error": error}


def test_classify_calls_the_anchor_in_arm_b_a_reaching_injection():
    verdict, why = doors.classify(_arm(doors.FAKE_WALL), _arm(doors.ANCHOR))
    assert verdict == doors.REACHES
    assert "якорь" in why


def test_classify_names_the_wall_clock_stamp_a_finding():
    """Та самая форма заказа: инъекция дошла до логики, но не до отметки."""
    verdict, why = doors.classify(_arm(doors.FAKE_WALL), _arm(doors.FAKE_WALL))
    assert verdict == doors.WALL_CLOCK
    assert verdict in doors.FINDINGS
    assert "НЕ до отметки" in why


def test_classify_names_a_third_source_the_order_did_not_foresee():
    """Отметка не от якоря и не от подменённых часов — отдельный исход."""
    stranger = (_anchor() + dt.timedelta(days=3)).isoformat()
    verdict, why = doors.classify(_arm(doors.FAKE_WALL), _arm(stranger))
    assert verdict == doors.THIRD_SOURCE
    assert verdict in doors.FINDINGS
    assert stranger in why


def test_pin_not_observed_is_unmeasured_not_a_finding():
    """ЗАМЕР у двери, а не вера в флаг (урок ADR-414).

    Отметка плеча A не есть подменённый момент ⇒ часы берутся не у подменяемого
    класса. Назвать это находкой значило бы выдумать её: про инъекцию здесь не
    измерено НИЧЕГО.
    """
    own_clock = (_anchor() - dt.timedelta(days=900)).isoformat()
    verdict, why = doors.classify(_arm(own_clock), _arm(doors.FAKE_WALL))
    assert verdict == doors.UNMEASURED
    assert verdict not in doors.FINDINGS
    assert "пин НЕ сработал" in why


def test_classify_refuses_when_arm_a_wrote_nothing():
    verdict, why = doors.classify(_arm(None, wrote=False), _arm(doors.ANCHOR))
    assert verdict == doors.UNMEASURED
    assert "не написал артефакт" in why


def test_classify_carries_the_arm_a_error_into_the_reason():
    verdict, why = doors.classify(
        _arm(None, wrote=False, error="ImportError: нет модуля"),
        _arm(doors.ANCHOR))
    assert verdict == doors.UNMEASURED
    assert "ImportError" in why


def test_classify_refuses_when_arm_b_wrote_nothing_and_names_arm_b():
    verdict, why = doors.classify(_arm(doors.FAKE_WALL),
                                  _arm(None, wrote=False, error="TypeError: now"))
    assert verdict == doors.UNMEASURED
    assert "плечо B" in why and "TypeError" in why


def test_classify_distinguishes_a_missing_arm_row_from_a_failed_call():
    """Плечо умерло до этого модуля ⇒ не измерено, и сказано КАКОЕ плечо."""
    assert doors.classify(None, _arm(doors.ANCHOR))[1].endswith(
        "не дало строки по этому производителю")
    assert "плечо B" in doors.classify(_arm(doors.FAKE_WALL), None)[1]


# ── точка инъекции ──────────────────────────────────────────────────────────────

def test_injection_entry_requires_both_a_now_parameter_and_zero_arg_callability():
    """Параметр `now` без возможности позвать без аргументов дверью НЕ является:
    прибор не умеет выдумать остальные аргументы, и притворяться, что умеет,
    значило бы выдать догадку за замер."""
    src = "def run(doc, now=None):\n    return doc\n"
    assert doors.injection_entry(src) is None


def test_injection_entry_requires_the_now_parameter_itself():
    src = "def run(root='.', write=True):\n    return 1\n"
    assert doors.injection_entry(src) is None


def test_injection_entry_accepts_an_all_defaulted_signature():
    src = "def run(root='.', now=None, write=True):\n    return 1\n"
    assert doors.injection_entry(src) == "run"


def test_injection_entry_accepts_a_keyword_only_now_with_a_default():
    src = "def run(root='.', *, now=None):\n    return 1\n"
    assert doors.injection_entry(src) == "run"


def test_injection_entry_refuses_a_keyword_only_now_without_a_default():
    """`*, now` без умолчания позвать без аргументов нельзя."""
    src = "def run(root='.', *, now):\n    return 1\n"
    assert doors.injection_entry(src) is None


def test_injection_entry_ignores_private_helpers():
    src = "def _build(now=None):\n    return 1\n"
    assert doors.injection_entry(src) is None


def test_injection_entry_prefers_run_over_an_alphabetically_earlier_name():
    """Выбор детерминирован: иначе ответ зависел бы от порядка обхода файла."""
    src = ("def measure(now=None):\n    return 1\n\n"
           "def run(now=None):\n    return 2\n")
    assert doors.injection_entry(src) == "run"


def test_injection_entry_falls_back_to_the_alphabetically_first_name():
    src = ("def zeta(now=None):\n    return 1\n\n"
           "def measure(now=None):\n    return 2\n")
    assert doors.injection_entry(src) == "measure"


def test_injection_entry_does_not_look_inside_a_class():
    """Метод класса позвать без объекта нельзя — он не точка инъекции."""
    src = ("class Runner:\n"
           "    def run(self, now=None):\n        return 1\n")
    assert doors.injection_entry(src) is None


def test_injection_entry_returns_none_on_unparsable_source():
    assert doors.injection_entry("def run(:\n") is None


# ── одноразовость дерева ────────────────────────────────────────────────────────

def test_main_worktree_is_refused_because_producers_write():
    """Прогон в главном дереве затёр бы живое состояние — авария #361 без git."""
    ok, why = doors.is_disposable_tree(Path(doors._ROOT))
    # дерево прогона тестов может быть и пристёгнутым; утверждение — о МЕХАНИКЕ
    own = subprocess.run(["git", "rev-parse", "--absolute-git-dir",
                          "--git-common-dir"], cwd=str(doors._ROOT),
                         capture_output=True, text=True)
    lines = [ln.strip() for ln in own.stdout.splitlines() if ln.strip()]
    if len(lines) == 2 and os.path.realpath(lines[0]) == os.path.realpath(lines[1]):
        assert ok is False and "ГЛАВНОЕ" in why
    else:
        assert ok is True and "пристёгнутое" in why


def test_a_tree_without_git_is_refused_fail_closed(tmp_path):
    """«Не смог проверить» не имеет права читаться как «можно»."""
    ok, why = doors.is_disposable_tree(tmp_path)
    assert ok is False
    assert why


def test_assert_disposable_tree_raises_on_a_non_disposable_tree(tmp_path):
    with pytest.raises(RuntimeError) as exc:
        doors.assert_disposable_tree(tmp_path)
    assert "отказан" in str(exc.value)


def test_assert_disposable_tree_lets_an_explicit_override_through(tmp_path):
    doors.assert_disposable_tree(tmp_path, allow_live=True)


def test_a_linked_worktree_is_accepted(tmp_path):
    """Признак измерим у git, а не угадан по имени каталога."""
    origin = tmp_path / "repo"
    origin.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    # `-b` обязателен: имя ветки по умолчанию есть свойство ХОСТА (ADR-479)
    subprocess.run(["git", "init", "-b", "main"], cwd=origin, check=True,
                   capture_output=True)
    (origin / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=origin, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "seed"], cwd=origin, check=True,
                   capture_output=True, env=env)
    linked = tmp_path / "linked"
    subprocess.run(["git", "worktree", "add", "--detach", str(linked)],
                   cwd=origin, check=True, capture_output=True, env=env)
    assert doors.is_disposable_tree(origin)[0] is False
    assert doors.is_disposable_tree(linked)[0] is True


# ── население ───────────────────────────────────────────────────────────────────

def test_an_unreadable_manifest_is_a_named_reason_not_an_empty_population(tmp_path):
    """Пустое население дало бы ноль дверей, и ноль прочёлся бы как ответ."""
    rows, why = doors.declared_artifacts(tmp_path)
    assert rows == []
    assert why and "манифест не прочитан" in why


def test_a_manifest_without_an_artifacts_list_is_unmeasured(tmp_path):
    arch = tmp_path / "architecture"
    arch.mkdir()
    (arch / "manifest.json").write_text(json.dumps({"agents": []}),
                                        encoding="utf-8")
    rows, why = doors.declared_artifacts(tmp_path)
    assert rows == [] and "нет списка artifacts" in why


def test_retired_artifacts_are_not_part_of_the_population(tmp_path):
    arch = tmp_path / "architecture"
    arch.mkdir()
    (arch / "manifest.json").write_text(json.dumps({"artifacts": [
        {"path": "data/a.json", "status": "active"},
        {"path": "data/b.json", "status": "retired"},
        {"path": "data/c.json"},
    ]}), encoding="utf-8")
    rows, why = doors.declared_artifacts(tmp_path)
    assert why is None
    assert [r["path"] for r in rows] == ["data/a.json", "data/c.json"]


def _scene(tmp_path: Path, modules: dict, artifacts: list) -> Path:
    """Одноразовая сцена: манифест + модули-производители, без живого дерева."""
    (tmp_path / "architecture").mkdir(exist_ok=True)
    (tmp_path / "architecture" / "manifest.json").write_text(
        json.dumps({"artifacts": artifacts}), encoding="utf-8")
    (tmp_path / "data").mkdir(exist_ok=True)
    for rel, src in modules.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(src), encoding="utf-8")
    for pkg in ("spa_core", "spa_core/monitoring", "scripts"):
        d = tmp_path / pkg
        if d.is_dir() and not (d / "__init__.py").exists() and pkg != "scripts":
            (d / "__init__.py").write_text("", encoding="utf-8")
    return tmp_path


def test_population_refuses_to_guess_when_several_modules_write_one_artifact(tmp_path):
    """Писателей несколько ⇒ НЕ ИЗМЕРЕНО, а не выбор наугад."""
    src = """
        from spa_core.utils.atomic import atomic_save
        REL = "data/twice.json"
        def run(root=".", now=None):
            atomic_save({"generated_at": now.isoformat()}, root + "/" + REL)
    """
    _scene(tmp_path, {"spa_core/monitoring/one.py": src,
                      "spa_core/monitoring/two.py": src},
           [{"path": "data/twice.json"}])
    rows, why = doors.population(tmp_path)
    assert why is None and len(rows) == 1
    assert rows[0]["verdict"] == doors.PRODUCER_AMBIGUOUS
    assert len(rows[0]["writers"]) == 2
    assert rows[0]["verdict"] in doors.NOT_MEASURED


def test_population_names_an_artifact_nobody_writes(tmp_path):
    _scene(tmp_path, {}, [{"path": "data/orphan.json"}])
    rows, _ = doors.population(tmp_path)
    assert rows[0]["verdict"] == doors.PRODUCER_UNRESOLVED
    assert rows[0]["writers"] == []


def test_population_calls_a_writer_without_an_injection_door_a_finding(tmp_path):
    src = """
        import datetime as dt
        from spa_core.utils.atomic import atomic_save
        REL = "data/nodoor.json"
        def main():
            atomic_save({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat()},
                        REL)
    """
    _scene(tmp_path, {"spa_core/monitoring/nodoor.py": src},
           [{"path": "data/nodoor.json"}])
    rows, _ = doors.population(tmp_path)
    assert rows[0]["verdict"] == doors.NO_DOOR
    assert rows[0]["verdict"] in doors.FINDINGS
    assert rows[0]["module"] == "spa_core.monitoring.nodoor"


def test_population_does_not_plan_a_call_to_the_instrument_itself(tmp_path):
    """Зов себя внутри своего же плеча дал бы рекурсию процессов, не замер."""
    assert doors.SELF_MODULES == (
        "spa_core.monitoring.artifact_stamp_clock_doors",
        "spa_core.monitoring._artifact_stamp_clock_probe")
    rows, why = doors.population(Path(doors._ROOT))
    assert why is None
    planned = {r["module"] for r in rows if r["module"]}
    assert not (planned & set(doors.SELF_MODULES))


def test_population_of_the_live_tree_is_not_empty_and_carries_a_verdict_everywhere():
    """Положительный контроль самого населения: строка без исхода — дыра меры."""
    rows, why = doors.population(Path(doors._ROOT))
    assert why is None
    assert len(rows) > 50
    for row in rows:
        assert row["verdict"] is not None or row["entry"]


# ── зонд: отметка и доказательство записи ───────────────────────────────────────

def test_read_stamp_prefers_generated_at_then_the_older_names():
    assert probe.read_stamp({"generated_at": "a", "as_of": "b"}) == ("a", "generated_at")
    assert probe.read_stamp({"as_of": "b"}) == ("b", "as_of")


def test_read_stamp_separates_no_stamp_at_all_from_a_stamp_under_another_name():
    assert probe.read_stamp({"rows": []}) == (None, None)
    assert probe.read_stamp({"timestamp": "t"}) == ("t", "timestamp")


def test_read_stamp_treats_a_null_stamp_as_absent_not_as_a_value():
    assert probe.read_stamp({"generated_at": None, "as_of": "b"}) == ("b", "as_of")


def test_read_stamp_refuses_a_non_dict_document():
    assert probe.read_stamp([1, 2, 3]) == (None, None)
    assert probe.read_stamp(None) == (None, None)


def test_call_producer_deletes_the_artifact_first_so_wrote_is_proven(tmp_path):
    """Иначе «написал отметку» неотличимо от «отметка лежала тут и раньше»."""
    art = tmp_path / "data" / "x.json"
    art.parent.mkdir()
    art.write_text(json.dumps({"generated_at": doors.FAKE_WALL}), encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        (tmp_path / "quiet_producer.py").write_text(
            "def run(now=None):\n    return None\n", encoding="utf-8")
        row = probe.call_producer("quiet_producer", "run", art, _anchor(),
                                  inject=True)
    finally:
        sys.path.remove(str(tmp_path))
    assert row["wrote_artifact"] is False
    assert row["stamp"] is None
    assert row["artifact_existed_before"] is True
    assert json.loads(art.read_text())["generated_at"] == doors.FAKE_WALL


def test_call_producer_restores_a_backup_so_the_walk_order_cannot_change_answers(
        tmp_path):
    art = tmp_path / "data" / "y.json"
    art.parent.mkdir()
    art.write_text("ПРЕЖНИЕ БАЙТЫ", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    try:
        (tmp_path / "overwriting_producer.py").write_text(
            "import json, pathlib\n"
            "def run(now=None):\n"
            "    p = pathlib.Path(__file__).parent / 'data' / 'y.json'\n"
            "    p.write_text(json.dumps({'generated_at': now.isoformat()}))\n",
            encoding="utf-8")
        row = probe.call_producer("overwriting_producer", "run", art, _anchor(),
                                  inject=True)
    finally:
        sys.path.remove(str(tmp_path))
    assert row["wrote_artifact"] is True
    assert doors.which_clock(row["stamp"]) == doors.ANCH
    assert art.read_text(encoding="utf-8") == "ПРЕЖНИЕ БАЙТЫ"


def test_call_producer_removes_an_artifact_that_did_not_exist_before(tmp_path):
    """Мера не имеет права ОСТАВЛЯТЬ после себя артефакт, которого не было."""
    art = tmp_path / "data" / "fresh.json"
    art.parent.mkdir()
    sys.path.insert(0, str(tmp_path))
    try:
        (tmp_path / "creating_producer.py").write_text(
            "import json, pathlib\n"
            "def run(now=None):\n"
            "    p = pathlib.Path(__file__).parent / 'data' / 'fresh.json'\n"
            "    p.write_text(json.dumps({'generated_at': now.isoformat()}))\n",
            encoding="utf-8")
        row = probe.call_producer("creating_producer", "run", art, _anchor(),
                                  inject=True)
    finally:
        sys.path.remove(str(tmp_path))
    assert row["wrote_artifact"] is True
    assert row["artifact_existed_before"] is False
    assert not art.exists()


def test_call_producer_names_a_raising_producer_instead_of_ending_the_walk(tmp_path):
    art = tmp_path / "data" / "z.json"
    art.parent.mkdir()
    sys.path.insert(0, str(tmp_path))
    try:
        (tmp_path / "angry_producer.py").write_text(
            "def run(now=None):\n    raise ValueError('вход не прочитан')\n",
            encoding="utf-8")
        row = probe.call_producer("angry_producer", "run", art, _anchor(),
                                  inject=True)
    finally:
        sys.path.remove(str(tmp_path))
    assert "ValueError" in str(row["error"])
    assert row["wrote_artifact"] is False


def test_call_producer_names_a_module_that_cannot_be_imported(tmp_path):
    art = tmp_path / "data" / "none.json"
    art.parent.mkdir()
    row = probe.call_producer("нет_такого_модуля_вовсе", "run", art, _anchor(),
                              inject=False)
    assert "ModuleNotFoundError" in str(row["error"])


def test_call_producer_names_a_missing_entry_rather_than_crashing(tmp_path):
    art = tmp_path / "data" / "noentry.json"
    art.parent.mkdir()
    sys.path.insert(0, str(tmp_path))
    try:
        (tmp_path / "entryless.py").write_text("X = 1\n", encoding="utf-8")
        row = probe.call_producer("entryless", "run", art, _anchor(), inject=False)
    finally:
        sys.path.remove(str(tmp_path))
    assert "AttributeError" in str(row["error"])


def test_call_producer_reads_the_last_line_of_a_journal(tmp_path):
    """У `.jsonl` отметку несёт последняя строка, а не первая."""
    art = tmp_path / "data" / "log.jsonl"
    art.parent.mkdir()
    sys.path.insert(0, str(tmp_path))
    try:
        (tmp_path / "journal_producer.py").write_text(
            "import json, pathlib\n"
            "def run(now=None):\n"
            "    p = pathlib.Path(__file__).parent / 'data' / 'log.jsonl'\n"
            "    p.write_text(json.dumps({'generated_at': 'СТАРАЯ'}) + chr(10)\n"
            "                 + json.dumps({'generated_at': now.isoformat()}) + chr(10))\n",
            encoding="utf-8")
        row = probe.call_producer("journal_producer", "run", art, _anchor(),
                                  inject=True)
    finally:
        sys.path.remove(str(tmp_path))
    assert doors.which_clock(row["stamp"]) == doors.ANCH


def test_probe_plan_writes_the_answer_after_every_module(tmp_path):
    """Плечо — чужой код: ответ, записанный один раз в конце, теряет уже
    измеренное, и «плечо умерло» становится неотличимо от «ничего не измерено».
    """
    seen = []

    class _Spy:
        """Приёмник ответа: запоминает, СКОЛЬКО строк было в каждой записи."""

        def write_text(self, text, **_kw):
            seen.append(len((json.loads(text) or {}).get("rows") or {}))
            return len(text)

    sys.path.insert(0, str(tmp_path))
    try:
        for name in ("p_one", "p_two"):
            (tmp_path / f"{name}.py").write_text(
                "def run(now=None):\n    return None\n", encoding="utf-8")
        (tmp_path / "data").mkdir()
        plan = [{"module": "p_one", "entry": "run", "artifact": "data/a.json"},
                {"module": "p_two", "entry": "run", "artifact": "data/b.json"}]
        answers = probe.probe_plan(plan, tmp_path, _anchor(), inject=False,
                                   out=_Spy())
    finally:
        sys.path.remove(str(tmp_path))
    assert seen == [1, 2], seen
    assert set(answers) == {"p_one", "p_two"}


# ── такт ────────────────────────────────────────────────────────────────────────

def test_measurement_due_when_the_artifact_is_absent(tmp_path):
    due, why = doors.measurement_due(tmp_path, _anchor())
    assert due is True and "артефакта нет" in why


def test_measurement_not_due_inside_the_tact(tmp_path):
    stamp = _anchor() - dt.timedelta(days=doors.MEASUREMENT_TACT_DAYS - 1)
    (tmp_path / doors.ARTIFACT).write_text(
        json.dumps({"generated_at": stamp.isoformat()}), encoding="utf-8")
    due, why = doors.measurement_due(tmp_path, _anchor())
    assert due is False and "из" in why


def test_measurement_due_exactly_on_the_tact_boundary(tmp_path):
    stamp = _anchor() - dt.timedelta(days=doors.MEASUREMENT_TACT_DAYS)
    (tmp_path / doors.ARTIFACT).write_text(
        json.dumps({"generated_at": stamp.isoformat()}), encoding="utf-8")
    assert doors.measurement_due(tmp_path, _anchor())[0] is True


def test_measurement_due_when_the_stamp_is_unparsable(tmp_path):
    """Отметка есть, но она не дата ⇒ мерить, а не считать свежим."""
    (tmp_path / doors.ARTIFACT).write_text(
        json.dumps({"generated_at": "вчера"}), encoding="utf-8")
    due, why = doors.measurement_due(tmp_path, _anchor())
    assert due is True and "разбираемой" in why


def test_if_due_inside_the_tact_does_not_call_a_single_producer(tmp_path):
    stamp = _anchor() - dt.timedelta(hours=1)
    data = tmp_path / "data"
    data.mkdir()
    (data / doors.ARTIFACT).write_text(
        json.dumps({"generated_at": stamp.isoformat()}), encoding="utf-8")
    report = doors.run(root=str(tmp_path), now=_anchor(), if_due=True, write=False)
    assert report.get("skipped") is True
    assert "rows" not in report


# ── отчёт и коды возврата ───────────────────────────────────────────────────────

def _body(counts: dict, rows=None) -> dict:
    return {"population_reason": None, "counts": counts, "rows": rows or [],
            "arms": {"a": {}, "b": {}}, "planned": sum(counts.values())}


def test_report_counts_findings_and_unmeasured_separately():
    report = doors.build_report(
        _body({doors.REACHES: 4, doors.WALL_CLOCK: 2, doors.NO_DOOR: 1,
               doors.UNMEASURED: 3, doors.PRODUCER_AMBIGUOUS: 1}), _anchor())
    assert report["findings_total"] == 3
    assert report["unmeasured_total"] == 4
    assert report["applied"] is False


def test_describe_never_reads_as_clean_while_something_is_unmeasured():
    """Ноль находок при непустом «не измерено» — не «чисто»."""
    lines = doors.describe(doors.build_report(
        _body({doors.REACHES: 1, doors.UNMEASURED: 7}), _anchor()))
    assert any("НЕ ИЗМЕРЕНО 7" in ln for ln in lines)


def test_describe_names_a_dead_arm():
    body = _body({doors.REACHES: 1})
    body["arms"] = {"a": {"died": "плечо не уложилось"}, "b": {}}
    lines = doors.describe(doors.build_report(body, _anchor()))
    assert any("плечо A" in ln and "не уложилось" in ln for ln in lines)


def test_describe_of_an_unmeasured_population_says_so_and_nothing_else():
    report = doors.build_report(
        {"population_reason": "манифест не прочитан", "counts": {}, "rows": [],
         "arms": {}, "planned": 0}, _anchor())
    lines = doors.describe(report)
    assert lines == ["НЕ ИЗМЕРЕНО: манифест не прочитан"]


def test_main_returns_two_when_the_population_could_not_be_built(tmp_path):
    assert doors.main(["--root", str(tmp_path), "--no-write"]) == 2


def test_main_returns_two_when_the_tree_is_not_disposable(tmp_path, capsys):
    """Отказ по одноразовости — НЕ ИЗМЕРЕНО, а не «дверей нет»."""
    arch = tmp_path / "architecture"
    arch.mkdir()
    (arch / "manifest.json").write_text(
        json.dumps({"artifacts": [{"path": "data/a.json"}]}), encoding="utf-8")
    assert doors.main(["--root", str(tmp_path), "--no-write"]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


def test_main_returns_one_when_a_finding_is_named(tmp_path, monkeypatch, capsys):
    src = """
        import datetime as dt
        from spa_core.utils.atomic import atomic_save
        def main():
            atomic_save({"generated_at": dt.datetime.now(dt.timezone.utc).isoformat()},
                        "data/nodoor.json")
    """
    _scene(tmp_path, {"spa_core/monitoring/nodoor.py": src},
           [{"path": "data/nodoor.json"}])
    monkeypatch.setattr(doors, "assert_disposable_tree",
                        lambda *a, **k: None)
    assert doors.main(["--root", str(tmp_path), "--no-write"]) == 1
    assert doors.NO_DOOR in capsys.readouterr().out


def test_run_writes_the_artifact_it_declares(tmp_path, monkeypatch):
    _scene(tmp_path, {}, [{"path": "data/orphan.json"}])
    monkeypatch.setattr(doors, "assert_disposable_tree", lambda *a, **k: None)
    doors.run(root=str(tmp_path), now=_anchor())
    written = json.loads((tmp_path / "data" / doors.ARTIFACT).read_text())
    assert written["generated_at"] == doors.ANCHOR
    assert doors.PRODUCES == (f"data/{doors.ARTIFACT}",)


def test_run_takes_now_as_an_input_all_the_way_to_its_own_stamp():
    """Прибор обязан проходить СВОЮ же меру: иначе он судил бы соседей по
    свойству, которого сам не имеет."""
    src = Path(doors.__file__).read_text(encoding="utf-8")
    assert doors.injection_entry(src) == "run"


# ── сквозной прогон двух плеч на одноразовой сцене ──────────────────────────────

def _two_arm_scene(tmp_path: Path) -> Path:
    """Сцена со СВОИМ зондом: два производителя — честный и врущий в отметке."""
    mon = tmp_path / "spa_core" / "monitoring"
    mon.mkdir(parents=True)
    (tmp_path / "spa_core" / "__init__.py").write_text("", encoding="utf-8")
    (mon / "__init__.py").write_text("", encoding="utf-8")
    here = Path(doors.__file__).parent
    for name in ("_artifact_stamp_clock_probe.py", "_http_reader_probe.py"):
        shutil.copy2(here / name, mon / name)
    (tmp_path / "data").mkdir()
    (tmp_path / "honest_producer.py").write_text(
        "import json, pathlib, datetime as dt\n"
        "def run(now=None):\n"
        "    now = now or dt.datetime.now(dt.timezone.utc)\n"
        "    p = pathlib.Path(__file__).parent / 'data' / 'honest.json'\n"
        "    p.write_text(json.dumps({'generated_at': now.isoformat()}))\n",
        encoding="utf-8")
    (tmp_path / "liar_producer.py").write_text(
        "import json, pathlib, datetime as dt\n"
        "def run(now=None):\n"
        "    now = now or dt.datetime.now(dt.timezone.utc)\n"
        "    verdict = {'checked': True} if now else {}\n"
        "    p = pathlib.Path(__file__).parent / 'data' / 'liar.json'\n"
        "    p.write_text(json.dumps(dict(verdict,\n"
        "        generated_at=dt.datetime.now(dt.timezone.utc).isoformat())))\n",
        encoding="utf-8")
    return tmp_path


def test_two_arms_find_the_producer_that_stamps_from_the_wall_clock(tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ всей меры, и он воспроизводит форму заказа.

    `liar_producer` принимает `now`, пользуется им в ЛОГИКЕ (вердикт зависит от
    него) и ставит отметку стенными часами. Герметичный тест такого вердикта
    зелен; возраст артефакта — выдумка. Мера обязана назвать его и не назвать
    честного соседа.
    """
    scene = _two_arm_scene(tmp_path)
    plan = [{"module": "honest_producer", "entry": "run",
             "artifact": "data/honest.json"},
            {"module": "liar_producer", "entry": "run",
             "artifact": "data/liar.json"}]
    arm_a, why_a = doors.run_arm(plan, scene, inject=False)
    arm_b, why_b = doors.run_arm(plan, scene, inject=True)
    assert why_a is None and why_b is None, (why_a, why_b)
    rows_a, rows_b = arm_a["rows"], arm_b["rows"]
    assert doors.classify(rows_a["honest_producer"],
                          rows_b["honest_producer"])[0] == doors.REACHES
    verdict, why = doors.classify(rows_a["liar_producer"],
                                  rows_b["liar_producer"])
    assert verdict == doors.WALL_CLOCK, (verdict, why)


def test_the_pin_itself_is_observed_at_the_door_in_a_real_arm(tmp_path):
    """Плечо обязано доказать, что подмена часов СРАБОТАЛА, а не просилась."""
    scene = _two_arm_scene(tmp_path)
    arm, why = doors.run_arm(
        [{"module": "honest_producer", "entry": "run",
          "artifact": "data/honest.json"}], scene, inject=False)
    assert why is None
    assert doors.which_clock(arm["door"]) == doors.FAKE


def test_an_arm_whose_probe_is_missing_is_a_named_reason_not_zero_doors(tmp_path):
    scene = _two_arm_scene(tmp_path)
    (scene / "spa_core" / "monitoring" / "_artifact_stamp_clock_probe.py").unlink()
    arm, why = doors.run_arm(
        [{"module": "honest_producer", "entry": "run",
          "artifact": "data/honest.json"}], scene, inject=False)
    assert arm is None
    assert why and ("зонд" in why or "вернул" in why)


# ── песочница: единственный способ зова из боевого дерева ──────────────────────

def test_make_sandbox_copies_the_dirs_the_measure_needs_and_marks_itself(tmp_path):
    src = tmp_path / "src"
    for rel in doors.SANDBOX_DIRS:
        (src / rel).mkdir(parents=True)
        (src / rel / "f.txt").write_text("x", encoding="utf-8")
    (src / "spa_core" / "__pycache__").mkdir()
    (src / "spa_core" / "__pycache__" / "junk.pyc").write_text("j", encoding="utf-8")
    box = doors.make_sandbox(src, tmp_path / "box")
    for rel in doors.SANDBOX_DIRS:
        assert (box / rel / "f.txt").is_file()
    assert not (box / "spa_core" / "__pycache__").exists()
    assert doors.is_own_sandbox(box) is True


def test_make_sandbox_refuses_a_box_nested_in_its_own_source(tmp_path):
    """Иначе «копия» была бы тем же деревом, и производители писали бы в живое."""
    src = tmp_path / "src"
    (src / "data").mkdir(parents=True)
    with pytest.raises(RuntimeError) as exc:
        doors.make_sandbox(src, src / "inner")
    assert "не изолирует" in str(exc.value)


def test_make_sandbox_refuses_a_box_that_already_has_foreign_bytes(tmp_path):
    src = tmp_path / "src"
    (src / "data").mkdir(parents=True)
    box = tmp_path / "box"
    box.mkdir()
    (box / "stranger.txt").write_text("чужое", encoding="utf-8")
    with pytest.raises(RuntimeError) as exc:
        doors.make_sandbox(src, box)
    assert "непуста" in str(exc.value)


def test_an_own_sandbox_is_accepted_though_it_has_no_git_at_all(tmp_path):
    """Признак «пристёгнутое дерево git» у временной копии не выполняется вовсе,
    и один он отказал бы безопасной копии."""
    src = tmp_path / "src"
    (src / "data").mkdir(parents=True)
    box = doors.make_sandbox(src, tmp_path / "box")
    assert doors.is_disposable_tree(box)[0] is False      # git там нет
    doors.assert_disposable_tree(box)                     # но метка своя


def test_the_marker_never_excuses_the_main_worktree(monkeypatch, tmp_path):
    """Проверка главного дерева отвечает РАНЬШЕ метки — подделка не помогает."""
    monkeypatch.setattr(doors, "is_disposable_tree",
                        lambda _t: (False, "это ГЛАВНОЕ рабочее дерево"))
    (tmp_path / doors.SANDBOX_MARKER).write_text("подделка", encoding="utf-8")
    assert doors.is_own_sandbox(tmp_path) is True
    with pytest.raises(RuntimeError) as exc:
        doors.assert_disposable_tree(tmp_path)
    assert "ГЛАВНОЕ" in str(exc.value)


def test_sandbox_mode_writes_the_report_to_the_source_tree_not_the_copy(tmp_path):
    """Живое состояние получает ровно ОДИН новый файл — отчёт прибора."""
    src = tmp_path / "src"
    (src / "architecture").mkdir(parents=True)
    (src / "architecture" / "manifest.json").write_text(
        json.dumps({"artifacts": [{"path": "data/orphan.json"}]}),
        encoding="utf-8")
    (src / "data").mkdir()
    before = {p.name for p in (src / "data").iterdir()}
    report = doors.run(root=str(src), now=_anchor(), sandbox=True)
    after = {p.name for p in (src / "data").iterdir()}
    assert after - before == {doors.ARTIFACT}
    assert report["measured_in"] == "sandbox"
    assert report["counts"][doors.PRODUCER_UNRESOLVED] == 1


# ── читатель: секция шага 0-офис ────────────────────────────────────────────────

def test_office_section_says_unmeasured_when_the_artifact_is_absent(tmp_path):
    """«Никто не мерил» обязано отличаться от «измерено, находок нет»."""
    lines = doors.office_section(tmp_path, _anchor())
    assert any("НЕ ИЗМЕРЕНО" in ln for ln in lines)
    assert any("--sandbox" in ln for ln in lines)


def test_office_section_reddens_on_an_overdue_measurement(tmp_path):
    stamp = _anchor() - dt.timedelta(days=doors.MEASUREMENT_TACT_DAYS + 2)
    (tmp_path / doors.ARTIFACT).write_text(json.dumps({
        "generated_at": stamp.isoformat(),
        "counts": {doors.REACHES: 90}}), encoding="utf-8")
    lines = doors.office_section(tmp_path, _anchor())
    assert any("ПРОСРОЧЕН" in ln for ln in lines)


def test_office_section_is_quiet_about_the_age_inside_the_tact(tmp_path):
    stamp = _anchor() - dt.timedelta(hours=3)
    (tmp_path / doors.ARTIFACT).write_text(json.dumps({
        "generated_at": stamp.isoformat(),
        "counts": {doors.REACHES: 90}}), encoding="utf-8")
    lines = doors.office_section(tmp_path, _anchor())
    assert not any("ПРОСРОЧЕН" in ln for ln in lines)
    assert any("✅" in ln for ln in lines)


def test_office_section_says_so_when_the_rows_list_is_unreadable(tmp_path):
    """Находки назвать поимённо нечем — отдельная строка, а не пустой перечень."""
    (tmp_path / doors.ARTIFACT).write_text(json.dumps({
        "generated_at": _anchor().isoformat(),
        "counts": {doors.WALL_CLOCK: 1}, "rows": "НЕ СПИСОК"}), encoding="utf-8")
    lines = doors.office_section(tmp_path, _anchor())
    assert any("нет читаемого списка rows" in ln for ln in lines)


def test_office_section_names_each_finding_by_artifact_and_module(tmp_path):
    (tmp_path / doors.ARTIFACT).write_text(json.dumps({
        "generated_at": _anchor().isoformat(),
        "counts": {doors.WALL_CLOCK: 1, doors.REACHES: 2},
        "rows": [{"artifact": "data/liar.json", "module": "spa_core.x",
                  "verdict": doors.WALL_CLOCK},
                 {"artifact": "data/ok.json", "module": "spa_core.y",
                  "verdict": doors.REACHES}]}), encoding="utf-8")
    lines = doors.office_section(tmp_path, _anchor())
    assert any("data/liar.json" in ln for ln in lines)
    assert not any("data/ok.json" in ln for ln in lines)


def test_office_section_says_unmeasured_when_the_stamp_cannot_be_parsed(tmp_path):
    (tmp_path / doors.ARTIFACT).write_text(json.dumps({
        "generated_at": "позавчера", "counts": {}}), encoding="utf-8")
    lines = doors.office_section(tmp_path, _anchor())
    assert any("возраст назвать нечем" in ln for ln in lines)


def test_office_section_does_not_read_a_missing_counts_block_as_zeroes(tmp_path):
    """Отсутствие счётчиков — не ноль находок (инв. #17): строка о находках
    обязана строиться из ЧИТАЕМОГО блока, а не из подставленного словаря."""
    (tmp_path / doors.ARTIFACT).write_text(json.dumps({
        "generated_at": _anchor().isoformat(), "counts": "НЕ СЛОВАРЬ"}),
        encoding="utf-8")
    lines = doors.office_section(tmp_path, _anchor())
    assert any("нет читаемого блока counts" in ln for ln in lines)
    assert not any("находок 0" in ln for ln in lines)


def test_the_office_step_CALLS_the_section_and_not_merely_imports_it():
    """Импорт не есть вызов (урок ADR-547): храповик проводки зеленеет от одного
    импорта ради чужого правила, а читателя при этом нет. Проверяется ФОРМА
    ВЫЗОВА в теле шага, а не упоминание имени."""
    import ast as _ast

    src = (Path(doors._ROOT) / "scripts" / "consume_office_reports.py").read_text(
        encoding="utf-8")
    calls = [n for n in _ast.walk(_ast.parse(src))
             if isinstance(n, _ast.Call)
             and isinstance(n.func, _ast.Name)
             and n.func.id == "office_section"]
    assert calls, "шаг 0-офис не ЗОВЁТ office_section — читателя нет"


def test_the_office_step_feeds_the_section_a_data_dir_and_a_moment():
    """Два аргумента, и оба существенны: без каталога секция прочла бы чужой
    артефакт, без момента возраст считался бы от стенных часов шага."""
    import ast as _ast

    src = (Path(doors._ROOT) / "scripts" / "consume_office_reports.py").read_text(
        encoding="utf-8")
    calls = [n for n in _ast.walk(_ast.parse(src))
             if isinstance(n, _ast.Call) and isinstance(n.func, _ast.Name)
             and n.func.id == "office_section"]
    assert all(len(c.args) == 2 for c in calls), [len(c.args) for c in calls]


# ── исход, найденный замером: артефакт без отметки вовсе ────────────────────────

def test_an_artifact_written_without_any_stamp_is_its_own_outcome():
    """НАЙДЕНО ЗАМЕРОМ 04.10 на `census_consumer_census`.

    Первая редакция меры объявила его неудачей пина — то есть обвинила подмену
    часов в том, чего она не делала. Артефакт написан, отметки в нём нет ни под
    одним известным именем: сторожу свежести читать нечего ВООБЩЕ, и это
    отдельный факт, а не разновидность «не измерено».
    """
    verdict, why = doors.classify(_arm(None, key=None), _arm(None, key=None))
    assert verdict == doors.NO_STAMP_IN_ARTIFACT
    assert verdict in doors.FINDINGS
    assert "ни под одним известным" in why


def test_an_absent_stamp_is_not_confused_with_a_failed_pin():
    """Две причины — две строки. Смешать их значит послать читателя не туда."""
    stranger = (_anchor() - dt.timedelta(days=900)).isoformat()
    assert doors.classify(_arm(stranger), _arm(doors.FAKE_WALL))[0] == doors.UNMEASURED
    assert doors.classify(_arm(None), _arm(doors.FAKE_WALL))[0] == \
        doors.NO_STAMP_IN_ARTIFACT


def test_a_missing_stamp_is_judged_only_after_the_write_is_proven():
    """Порядок существенен: «не написал» отвечает РАНЬШЕ «написал без отметки»,
    иначе молчащий производитель читался бы как производитель без отметки."""
    verdict, _ = doors.classify(_arm(None, wrote=False), _arm(doors.ANCHOR))
    assert verdict == doors.UNMEASURED


def test_describe_names_the_absent_stamp_class_in_its_own_column():
    lines = doors.describe(doors.build_report(
        _body({doors.REACHES: 1, doors.NO_STAMP_IN_ARTIFACT: 2}), _anchor()))
    assert any("отметки в артефакте нет 2" in ln for ln in lines)


# ── свой же храповик поймал прибор на его собственной мере ─────────────────────

def test_a_report_without_counts_does_not_read_as_zero_findings():
    """Инв. #17 на СЕБЕ: `or {}` превратило бы «не измерено» в «находок ноль».

    Храповик `test_absent_observation_ratchet` покраснел на этом приборе дважды
    (строки `build_report` и `describe`), и в базу не дописано ничего — чинился
    писатель. Контроль воспроизводит форму: блока нет ⇒ счётчики НЕ ИЗМЕРЕНЫ.
    """
    report = doors.build_report({"population_reason": None, "rows": [],
                                 "arms": {}, "planned": 0}, _anchor())
    assert report["counts"] is None
    assert report["findings_total"] is None
    assert report["unmeasured_total"] is None
    assert any("не ноль находок" in ln for ln in doors.describe(report))


def test_main_returns_two_when_the_finding_counter_was_never_measured(
        tmp_path, monkeypatch):
    """Вердикт «находок нет» на НЕ ИЗМЕРЕННОМ счётчике — fail-OPEN."""
    monkeypatch.setattr(doors, "measure", lambda *a, **k: {
        "population_reason": None, "rows": [], "arms": {}, "planned": 0})
    assert doors.main(["--root", str(tmp_path), "--no-write"]) == 2


# ── проводка: ступень моста есть ВЫЗОВ, а не имя в реестре ─────────────────────

def test_the_bridge_declares_the_artifact_the_stage_and_the_product():
    """Три реестра моста, и промах любого делает ступень невидимой."""
    from spa_core.monitoring import findings_bridge as fb

    assert f"data/{doors.ARTIFACT}" in fb.PRODUCES
    assert "artifact_stamp_clock_doors" in fb.CENSUS_STAGE
    assert fb.CENSUS_PRODUCT["artifact_stamp_clock_doors"] == {
        "module": PRODUCER_REL, "artifact": f"data/{doors.ARTIFACT}"}


def test_the_bridge_CALLS_run_and_passes_sandbox_true():
    """Имя в реестре не есть вызов (урок ADR-547), а `sandbox=True` не есть
    осторожность: без него плечо позвало бы ЧУЖИХ производителей в боевом
    дереве, и они бы в него ПИСАЛИ."""
    import ast as _ast

    src = (Path(doors._ROOT) / "spa_core" / "monitoring"
           / "findings_bridge.py").read_text(encoding="utf-8")
    calls = [n for n in _ast.walk(_ast.parse(src))
             if isinstance(n, _ast.Call)
             and isinstance(n.func, _ast.Attribute)
             and n.func.attr == "run"
             and isinstance(n.func.value, _ast.Name)
             and n.func.value.id == "artifact_stamp_clock_doors"]
    assert calls, "мост не ЗОВЁТ artifact_stamp_clock_doors.run"
    for call in calls:
        kwargs = {k.arg: k.value for k in call.keywords}
        assert "sandbox" in kwargs, "ступень зовёт без sandbox=True"
        assert getattr(kwargs["sandbox"], "value", None) is True
        assert "if_due" in kwargs, "ступень зовёт без гейта такта"
        assert getattr(kwargs["if_due"], "value", None) is True


def test_the_declared_slo_is_longer_than_the_tact_itself():
    """SLO, равный такту, объявил бы артефакт протухшим в ту самую минуту,
    когда ему только предстоит перемериться."""
    import json as _json

    doc = _json.loads((Path(doors._ROOT) / "architecture"
                       / "manifest.json").read_text(encoding="utf-8"))
    rows = [a for a in doc["artifacts"]
            if a.get("path") == f"data/{doors.ARTIFACT}"]
    assert len(rows) == 1, rows
    assert rows[0]["slo_hours"] > doors.MEASUREMENT_TACT_DAYS * 24
    assert rows[0]["producer"] == "com.spa.decision_loop"
    assert rows[0]["status"] == "active"


def test_the_instruments_own_artifact_is_not_called_an_orphan():
    """«Никто не пишет» и «пишу я сам» — РАЗНЫЕ факты.

    Прибор объявлен в конституции и пишет свой артефакт сам; звать себя внутри
    своего же плеча значило бы рекурсию процессов. Слить это с
    `producer_not_resolved` значило бы оболгать собственный артефакт — то есть
    напечатать о себе ровно ту неправду, которую прибор ищет у соседей.
    """
    rows, why = doors.population(Path(doors._ROOT))
    assert why is None
    mine = [r for r in rows if r["artifact"] == f"data/{doors.ARTIFACT}"]
    assert len(mine) == 1, mine
    assert mine[0]["verdict"] == doors.PRODUCER_IS_SELF
    assert mine[0]["writers"] == [PRODUCER_REL]
    assert doors.PRODUCER_IS_SELF in doors.NOT_MEASURED
    assert doors.PRODUCER_IS_SELF not in doors.FINDINGS
