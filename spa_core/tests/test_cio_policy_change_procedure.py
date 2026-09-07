"""Тесты §48 ТЗ «Portfolio CIO» — исполняется ли процедура изменения Risk Policy.

Каждый тест — положительный контроль на замер 2026-09-07 (цикл #516) либо на
ловушку, в которую прибор РЕАЛЬНО попал при разработке. Тест, никогда не
видевший настоящей поломки, — украшение (`.claude/rules/deployment.md`).

Время — ВХОД: `run(now=...)`. Живого дерева тесты не судят там, где проверяют
поведение: сцены строятся в `tmp_path`.
"""

# FROZEN-DATE-OK: injected-clock — единственный литерал даты в файле это `NOW`, и он
# уходит аргументом `now=NOW` в `M.run(...)`; отметок времени, читаемых со стены, у
# проверяемого кода нет — `generated_at` берётся из того же входа
# (`test_now_is_an_input` закрепляет это в обе стороны). Маркер обязан быть
# КОММЕНТАРИЕМ: храповик ищет `#\s*FROZEN-DATE-OK`, и та же запись прозой внутри
# докстроки им не читается — на этом уже стои́т красным `test_cio_failure_modes.py`.

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spa_core.monitoring import cio_policy_change_procedure as M

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)

_POLICY = """
from dataclasses import dataclass

@dataclass
class RiskConfig:
    changelog: str = {changelog!r}
    min_cash_pct: float = {cash}
    max_concentration_t1: float = {t1}
"""

_SNAP = """
from dataclasses import dataclass

@dataclass
class _V1_0_RiskConfig:
    min_cash_pct: float = 0.05
    max_concentration_t1: float = 0.40
"""


def scene(root: Path, *, cash: float = 0.05, t1: float = 0.40,
          changelog: str = "", canon: str = "# INDEX\n",
          decisions: dict[str, str] | None = None,
          adr_home: dict[str, str] | None = None,
          guard: str | None = "DECISIONS_DIR = \"docs/decisions\"\n") -> Path:
    """Дерево-сцена: политика, снимок v1.0, реестр и дома решений."""
    (root / "spa_core/risk/versions").mkdir(parents=True, exist_ok=True)
    (root / "docs/decisions").mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / M.POLICY_REL).write_text(
        _POLICY.format(cash=cash, t1=t1, changelog=changelog), encoding="utf-8")
    (root / M.SNAPSHOT_REL).write_text(_SNAP, encoding="utf-8")
    (root / M.CANON_INDEX_REL).write_text(canon, encoding="utf-8")
    # Дом ОПОЗНАЁТСЯ по файлам решений, а не по индексу: каталог с одним лишь
    # INDEX.md домом не является. Поэтому канонический дом наполняется всегда —
    # иначе сцена меряла бы дерево, которого в проде не бывает.
    (root / "docs/decisions/ADR-500-filler.md").write_text(
        "# ADR-500\nнейтральное решение сцены\n", encoding="utf-8")
    for name, body in (decisions or {}).items():
        (root / "docs/decisions" / name).write_text(body, encoding="utf-8")
    if adr_home:
        (root / "docs/adr").mkdir(parents=True, exist_ok=True)
        for name, body in adr_home.items():
            (root / "docs/adr" / name).write_text(body, encoding="utf-8")
    if guard is not None:
        (root / M.NUMBER_GUARD_REL).write_text(guard, encoding="utf-8")
    return root


# ─── направление правки ──────────────────────────────────────────────────────

def test_lowering_a_floor_is_a_relaxation(tmp_path):
    """Опустить `min_cash_pct` = пустить больше риска. Полярность объявлена, не угадана."""
    m = M.measure_knobs(scene(tmp_path, cash=0.01))
    assert m["knobs"]["min_cash_pct"]["verdict"] == "RELAXED"


def test_raising_a_floor_is_not_a_relaxation(tmp_path):
    """Обратная половина: у пола рост — ужесточение.

    Без неё «видит ослабление» проходило бы и у сторожа, который объявляет
    ослаблением ЛЮБУЮ правку.
    """
    m = M.measure_knobs(scene(tmp_path, cash=0.20))
    assert m["knobs"]["min_cash_pct"]["verdict"] == "TIGHTENED"


def test_raising_a_ceiling_is_a_relaxation(tmp_path):
    """У потолка направление ПРОТИВОПОЛОЖНО полу — иначе полярность не нужна вовсе."""
    m = M.measure_knobs(scene(tmp_path, t1=0.80))
    assert m["knobs"]["max_concentration_t1"]["verdict"] == "RELAXED"


def test_unchanged_knob_is_not_a_change(tmp_path):
    m = M.measure_knobs(scene(tmp_path))
    assert m["knobs"]["min_cash_pct"]["verdict"] == "UNCHANGED"


def test_unknown_polarity_is_unmeasured_not_a_guess(monkeypatch, tmp_path):
    """Незнакомое поле даёт ТРЕТИЙ исход, а не догадку по имени.

    «max_» в имени не есть полярность: у `max_var_pct` рост ослабляет, у
    гипотетического `max_required_quorum` — ужесточает. Догадка здесь стоила бы
    уверенного неверного ответа.
    """
    monkeypatch.setitem(M.KNOB_POLARITY, "min_cash_pct", None)
    M.KNOB_POLARITY.pop("min_cash_pct")
    try:
        m = M.measure_knobs(scene(tmp_path, cash=0.01))
        k = m["knobs"]["min_cash_pct"]
        assert k["verdict"] == "UNMEASURED"
        assert "полярность" in k["why"]
    finally:
        M.KNOB_POLARITY["min_cash_pct"] = M.LOOSER_WHEN_LOWER


def test_unparsable_policy_file_names_the_exception(tmp_path):
    """Ветка ИСКЛЮЧЕНИЯ отдельно от ветки «класса нет» — они разные.

    Найдено собственным харнессом мутаций: мутация «разбор падает молча»
    (`return {}, None` вместо причины) НЕ краснела, потому что единственный тест
    про сломанный файл подавал СИНТАКСИЧЕСКИ ВЕРНЫЙ файл с другим именем класса
    и попадал в соседнюю ветку. Тест утверждал верное о НЕ ТОЙ ветке.
    """
    root = scene(tmp_path)
    (root / M.POLICY_REL).write_text("class RiskConfig(:\n", encoding="utf-8")
    fields, err = M._class_fields(root / M.POLICY_REL, M.POLICY_CLASS)
    assert fields == {}
    assert err and "SyntaxError" in err, err


def test_broken_policy_file_is_unmeasured_with_a_reason(tmp_path):
    """Разбор не удался ⇒ «не измерено» с ПРИЧИНОЙ, а не «изменений нет».

    Пустой словарь неотличим от «класса нет», и обе формы читались бы как норма.
    """
    root = scene(tmp_path)
    (root / M.POLICY_REL).write_text("class NotRiskConfig:\n    pass\n", encoding="utf-8")
    m = M.measure_knobs(root)
    assert m["error"] and "RiskConfig" in m["error"]


# ─── §48: молчаливое ослабление и достижимость решения ───────────────────────

def test_silent_relaxation_is_critical(tmp_path):
    """Ослабили и не сослались ни на что — ровно то, что §48 запрещает."""
    doc = M.run(scene(tmp_path, cash=0.01), write=False, now=NOW)
    f = [x for x in doc["findings"] if x["field"] == "min_cash_pct"]
    assert f and f[0]["severity"] == "critical", doc["findings"]
    assert doc["overall"] == "CRITICAL"


def test_relaxation_with_a_registered_decision_is_not_a_finding(tmp_path):
    """Обратная половина: процедура исполнена ⇒ находки нет.

    Без неё «критично на ослаблении» проходило бы и у сторожа, который краснеет
    на любом ослаблении, то есть игнорирует ровно то, что меряет §48.
    """
    doc = M.run(scene(tmp_path, cash=0.01,
                      changelog="ADR-900 (2026-01-01): снижен буфер",
                      canon="# INDEX\n| ADR-900 | x | Accepted | [x](ADR-900-cash.md) |\n",
                      decisions={"ADR-900-cash.md": "# ADR-900\n`min_cash_pct`\n"}),
                write=False, now=NOW)
    assert [x for x in doc["findings"] if x["field"] == "min_cash_pct"] == []


def test_decision_outside_the_canonical_registry_is_named(tmp_path):
    """Решение ЕСТЬ, но лежит вне реестра — предупреждение, а не тишина и не CRITICAL.

    Это замер 07.09 на живом дереве: `max_total_t2_allocation` 0.35 → 0.50
    решал ADR-019 из `docs/adr/`, которого в `docs/decisions/INDEX.md` нет.
    """
    doc = M.run(scene(tmp_path, cash=0.01,
                      changelog="ADR-900 (2026-01-01): снижен буфер",
                      adr_home={"ADR-900-cash.md": "# ADR-900\n`min_cash_pct`\n"}),
                write=False, now=NOW)
    f = [x for x in doc["findings"] if x["field"] == "min_cash_pct"]
    assert f and f[0]["severity"] == "warn", doc["findings"]
    assert "docs/adr/ADR-900-cash.md" in f[0]["text"]


def test_a_mention_is_not_provenance(tmp_path):
    """ЛОВУШКА, в которую прибор ПОПАЛ 07.09 — и это его первая редакция.

    Документ, лишь ЦИТИРУЮЩИЙ поле, объявлялся его proposal'ом: на живом дереве
    ADR-131 и ADR-144 упоминают `max_total_t2_allocation` (оба — и старое, и
    новое значение), и вердикт стал «proposal достижим», хотя правку решал
    ADR-019, которого в реестре нет. Здесь: в реестре лежит документ, который
    поле упоминает, но ссылки на него политика НЕ предъявляет — вердикт обязан
    остаться «вне реестра».
    """
    doc = M.run(scene(tmp_path, cash=0.01,
                      changelog="ADR-900 (2026-01-01): снижен буфер",
                      canon="# INDEX\n| ADR-777 | x | Accepted | [x](ADR-777-cites.md) |\n",
                      decisions={"ADR-777-cites.md": "# ADR-777\nупоминаю `min_cash_pct` 0.05\n"},
                      adr_home={"ADR-900-cash.md": "# ADR-900\n`min_cash_pct`\n"}),
                write=False, now=NOW)
    p = doc["proposals"]["min_cash_pct"]
    assert p["verdict"] == "PROPOSAL_OUTSIDE_CANON_INDEX", p
    assert any(m["file"] == "ADR-777-cites.md" for m in p["mentioned_in"])


def test_unresolvable_reference_is_critical(tmp_path):
    """Ссылка есть, документа нет — CURRENT RULE не предъявить вовсе."""
    doc = M.run(scene(tmp_path, cash=0.01,
                      changelog="ADR-901 (2026-01-01): снижен буфер"),
                write=False, now=NOW)
    assert doc["proposals"]["min_cash_pct"]["verdict"] == "PROPOSAL_UNRESOLVED"
    assert doc["overall"] == "CRITICAL"


def test_tightening_needs_no_proposal(tmp_path):
    """§48 запрещает молчаливое ОСЛАБЛЕНИЕ. Новый потолок находкой не является."""
    doc = M.run(scene(tmp_path, cash=0.20), write=False, now=NOW)
    assert [x for x in doc["findings"] if x["field"] == "min_cash_pct"] == []


# ─── дома решений, реестр, сторож номера ─────────────────────────────────────

def test_homes_are_discovered_not_declared(tmp_path):
    """Наличие ВТОРОГО дома и есть предмет замера — списком его задавать нельзя."""
    root = scene(tmp_path, adr_home={"ADR-900-x.md": "# x\n"})
    h = M.measure_homes(root)
    assert set(h["homes"]) == {"docs/decisions", "docs/adr"}


def test_number_collision_across_homes_is_reported(tmp_path):
    """Один номер — два разных решения: ссылка не разрешается однозначно.

    Замер 07.09: так заняты ADR-009/010/011/029/030/031/032/048/050/053, и
    среди них ADR-053 (`docs/adr/…tvl-floor-fail-closed` про `min_tvl_usd`
    против `docs/decisions/…rtmr-sense-loop`).
    """
    root = scene(tmp_path, decisions={"ADR-053-rtmr.md": "# rtmr\n"},
                 adr_home={"ADR-053-tvl-floor.md": "# tvl floor\n"})
    h = M.measure_homes(root)
    assert [c["number"] for c in h["collisions"]] == [53]


def test_no_collision_when_numbers_do_not_overlap(tmp_path):
    """Обратная половина: разные номера в разных домах коллизией НЕ являются."""
    root = scene(tmp_path, decisions={"ADR-053-rtmr.md": "# rtmr\n"},
                 adr_home={"ADR-054-other.md": "# other\n"})
    assert M.measure_homes(root)["collisions"] == []


def test_guard_reading_one_home_of_two_is_reported(tmp_path):
    """Сторож уникальности читает один дом — номер выдаётся по неполной картине."""
    root = scene(tmp_path, adr_home={"ADR-900-x.md": "# x\n"})
    doc = M.run(root, write=False, now=NOW)
    t = [f["text"] for f in doc["findings"] if "сторож уникальности" in f["text"]]
    assert t and "docs/adr" in t[0], doc["findings"]


def test_guard_reading_every_home_is_not_a_finding(tmp_path):
    """Обратная половина — иначе проверка краснела бы всегда."""
    root = scene(tmp_path, adr_home={"ADR-900-x.md": "# x\n"},
                 guard='DECISIONS_DIR = "docs/decisions"\nEXTRA = "docs/adr"\n')
    doc = M.run(root, write=False, now=NOW)
    assert [f for f in doc["findings"] if "сторож уникальности" in f["text"]] == []


def test_missing_guard_is_unmeasured_not_pass(tmp_path):
    """Инструмента нет ⇒ ТРЕТИЙ исход с причиной, а не «охват полон»."""
    root = scene(tmp_path, adr_home={"ADR-900-x.md": "# x\n"}, guard=None)
    doc = M.run(root, write=False, now=NOW)
    assert doc["overall"] == "UNCHECKED"
    assert any(f["severity"] == "unchecked" and "охват сторожа не измерен" in f["text"]
               for f in doc["findings"]), doc["findings"]


# ─── контракт отчёта ─────────────────────────────────────────────────────────

def test_positive_control_runs_and_passes():
    """Контроль прибора — четыре половины, каждая управляет своим ответом."""
    c = M.positive_control()
    assert c["passed"], c["checks"]
    assert len(c["checks"]) == 4


def test_positive_control_can_actually_fail(monkeypatch):
    """Контроль обязан быть СПОСОБЕН упасть — иначе он штамп, а не контроль.

    Найдено собственным харнессом: мутация «контроль пройден всегда»
    (`passed: True`) не краснела ни на одном тесте — проверка «контроль
    проходит» проходит и у штампа. Здесь ломается измеритель, которым контроль
    пользуется, и контроль ОБЯЗАН это заметить.
    """
    monkeypatch.setattr(M, "measure_knobs",
                        lambda root: {"knobs": {"min_cash_pct":
                                                {"verdict": "UNCHANGED"}},
                                      "error": None, "changelog": "",
                                      "snapshot_fields": 0, "current_fields": 0})
    c = M.positive_control()
    assert not c["passed"], c["checks"]


def test_failed_control_forces_unchecked(monkeypatch, tmp_path):
    """ПРОВОДКА: контроль не прошёл ⇒ вердикт обязан пойти за ним, а не за находками."""
    monkeypatch.setattr(M, "positive_control",
                        lambda: {"passed": False, "checks": []})
    doc = M.run(scene(tmp_path), write=False, now=NOW)
    assert doc["overall"] == "UNCHECKED"


def test_now_is_an_input(tmp_path):
    """Часы инъектируются — фикстура не зависит от календаря."""
    doc = M.run(scene(tmp_path), write=False, now=NOW)
    assert doc["generated_at"] == NOW.isoformat()


def test_artifact_is_written_atomically(tmp_path):
    root = scene(tmp_path)
    (root / "data").mkdir(exist_ok=True)
    M.run(root, write=True, now=NOW)
    doc = json.loads((root / M.REPORT_REL).read_text(encoding="utf-8"))
    assert doc["schema"] == "cio_policy_change_procedure/v1"
    assert doc["generated_at"] == NOW.isoformat()


def test_report_names_the_advisory_boundary(tmp_path):
    """Модуль ничего не двигает — и обязан говорить это в артефакте."""
    doc = M.run(scene(tmp_path), write=False, now=NOW)
    assert "ADVISORY" in doc["advisory"]


def test_run_on_the_live_tree_does_not_crash():
    """Прибор обязан отработать на НАСТОЯЩЕМ дереве, не только на сцене."""
    doc = M.run(write=False, now=NOW)
    assert doc["overall"] in ("OK", "WARN", "CRITICAL", "UNCHECKED")
    assert doc["knobs_total"] > 0


@pytest.mark.parametrize("field", sorted(M.KNOB_POLARITY))
def test_every_declared_polarity_is_a_known_kind(field):
    assert M.KNOB_POLARITY[field] in (
        M.LOOSER_WHEN_HIGHER, M.LOOSER_WHEN_LOWER, M.NOT_A_LIMIT)


def test_every_live_knob_has_a_declared_polarity():
    """Новое поле политики без объявленной полярности = молчаливая дыра в §48.

    Храповик в обе стороны: поле добавили — объяви направление, иначе его
    ослабление станет `UNMEASURED` и пройдёт мимо находки.
    """
    root = Path(M.__file__).resolve().parents[2]
    cur, err = M._class_fields(root / M.POLICY_REL, M.POLICY_CLASS)
    assert not err, err
    missing = sorted(set(cur) - set(M.KNOB_POLARITY))
    assert not missing, f"полярность не объявлена: {missing}"
