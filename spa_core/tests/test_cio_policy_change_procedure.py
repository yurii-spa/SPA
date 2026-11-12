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
    # ADR-993: схема поднята до v2 — артефакт несёт вторую ось `bypass_by_stage`;
    # офис отличает v1 (оси нет ⇒ «не измерено») от v2 именно по этому полю.
    assert doc["schema"] == "cio_policy_change_procedure/v2"
    assert "bypass_by_stage" in doc
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


# ─── вторая ось §48 (ADR-993): отказ политики обходят СТУПЕНЬЮ, не порогом ────
#
# Каждая сцена — живая запись трейла §43 в миниатюре: `allocation_proposal` →
# `risk_verdict` → `trade_executed` / `trade_blocked` под одним `correlation_id`.
# Положительные контроли — замер 12.11 (цикл #1112): T033 ($1 052,63 сверх гейта),
# 36 отказов и ни одного исполнения после отказа, один вердикт на цепочку.

import pytest as _pt


def _ev(cid: str, etype: str, ts: str, data: dict) -> dict:
    return {"event_id": f"{cid}-{etype}", "correlation_id": cid, "event_type": etype,
            "timestamp": ts, "data": data, "prev_event_id": None}


def chain(cid: str, day: str, *, target: dict, approved: bool = True,
          trimmed: bool = False, executed: dict | None = None, held: dict | None = None,
          blocked: bool = False, violations: list | None = None,
          extra_verdicts: int = 0, trade_id: str = "T900") -> list[dict]:
    ts = f"{day}T06:00:00+00:00"
    ev = [_ev(cid, "cycle_start", ts, {}),
          _ev(cid, "allocation_proposal", ts, {"target_usd": target}),
          _ev(cid, "risk_verdict", ts, {"approved": approved, "violations": violations or [],
                                        "trimmed": trimmed})]
    for _ in range(extra_verdicts):
        ev.append(_ev(cid, "risk_verdict", ts, {"approved": True, "violations": [], "trimmed": False}))
    if executed is not None:
        ev.append(_ev(cid, "trade_executed", ts, {"trade_id": trade_id, "from_allocation": held or {},
                                                   "to_allocation": executed}))
    if blocked:
        ev.append(_ev(cid, "trade_blocked", ts, {"violations": violations or []}))
    return ev


def shadow_rec(day: str, *, book_verdict: str = "HOLD", trim: dict | None = None,
               policy_version: str | None = "v1.0") -> dict:
    rec = {"schema": "shadow-hist-v2", "book_id": "conservative", "cycle_date": day,
           "generated_at": f"{day}T07:00:00+00:00", "verdict": book_verdict,
           "decision_id": f"adr060-shadow-{day}"}
    if policy_version is not None:
        rec["policy_version"] = policy_version
    if trim is not None:
        rec["admissible_trim"] = trim
    return rec


def data_scene(root: Path, chains: list[list[dict]], *, shadow: dict[str, list[dict]] | None = None,
               raw_trail: str | None = None) -> Path:
    """Каталог данных сцены: трейл + теневые журналы трёх книг (по умолчанию пустые)."""
    d = root / "data"
    d.mkdir(parents=True, exist_ok=True)
    if raw_trail is None:
        raw_trail = "".join(json.dumps(e) + "\n" for ch in chains for e in ch)
    (d / M.TRAIL_FILE).write_text(raw_trail, encoding="utf-8")
    for book, fname in M.SHADOW_HISTORY_FILES.items():
        rows = (shadow or {}).get(book, [])
        (d / fname).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return d


SINCE = "2026-09-06"
IN = "2026-09-10"      # день в окне заказа
BEFORE = "2026-08-20"  # день до окна — считается только за всю историю


def _bypass(doc: dict) -> dict:
    return doc["bypass_by_stage"]


def _texts(doc: dict, severity: str) -> list[str]:
    return [f["text"] for f in doc["findings"] if f["severity"] == severity]


class TestTheGateQuestion:
    """execution_vs_gate: свежий капитал считается от потолка max(одобрено, удержано)."""

    def test_equal_books_are_consistent(self):
        r = M.execution_vs_gate({"a": 10.0}, {"a": 5.0}, {"a": 10.0})
        assert r["equal_to_decision"] and r["fresh_beyond_gate_usd"] == 0.0

    def test_capital_above_approved_and_held_is_fresh(self):
        r = M.execution_vs_gate({"a": 10.0}, {"a": 5.0}, {"a": 12.5})
        assert r["fresh_beyond_gate_usd"] == 2.5 and r["beyond_by_protocol"] == {"a": 2.5}

    def test_a_smaller_sale_is_not_fresh_capital(self):
        """ADR-992: удержано 20, одобрено 10, исполнено 15 — продажа меньше одобренной, свежего нет."""
        r = M.execution_vs_gate({"a": 10.0}, {"a": 20.0}, {"a": 15.0})
        assert r["fresh_beyond_gate_usd"] == 0.0 and not r["equal_to_decision"]

    def test_a_book_below_the_decision_is_not_a_bypass(self):
        """Срез гейта к буферу кэша (июнь: T003…T014, ×0.95) обходом не является."""
        r = M.execution_vs_gate({"a": 100.0, "b": 50.0}, {}, {"a": 95.0, "b": 47.5})
        assert r["fresh_beyond_gate_usd"] == 0.0 and r["introduced_unjudged"] == []

    def test_a_protocol_dropped_from_the_decision_is_not_equal(self):
        """Одобрено два протокола, исполнен один — книги НЕ равны (ключи решения тоже считаются)."""
        r = M.execution_vs_gate({"a": 10.0, "b": 5.0}, {}, {"a": 10.0})
        assert not r["equal_to_decision"] and r["fresh_beyond_gate_usd"] == 0.0

    def test_a_protocol_nobody_judged_is_introduced(self):
        r = M.execution_vs_gate({"a": 10.0}, {"a": 10.0}, {"a": 10.0, "z": 3.0})
        assert r["introduced_unjudged"] == ["z"] and r["fresh_beyond_gate_usd"] == 3.0

    def test_a_held_protocol_is_not_introduced(self):
        """Протокол удержан, но не в одобренной книге, — он не «введён», его не трогали."""
        r = M.execution_vs_gate({"a": 10.0}, {"z": 3.0}, {"a": 10.0, "z": 3.0})
        assert r["introduced_unjudged"] == [] and r["fresh_beyond_gate_usd"] == 0.0

    def test_t033_live_control(self):
        """Положительный контроль — живая запись 2026-09-08 дословно: $1 052,63 сверх гейта."""
        approved = {"aave_v3": 4736.84, "compound_v3": 37894.74, "fluid_fusdc": 18947.37,
                    "fluid_usdc": 9473.68, "pendle": 18947.37}
        held = {"compound_v3": 40000.0, "fluid_usdc": 20000.0, "maple": 20000.0,
                "morpho_blue_base": 10000.0, "aave_v3": 5000.0}
        executed = {"pendle": 20000.0, "fluid_usdc": 20000.0, "compound_v3": 40000.0,
                    "aave_v3": 4736.84, "maple": 5263.16, "morpho_blue_base": 4736.84}
        r = M.execution_vs_gate(approved, held, executed)
        assert r["fresh_beyond_gate_usd"] == 1052.63
        assert r["beyond_by_protocol"] == {"pendle": 1052.63}
        assert r["introduced_unjudged"] == []


class TestTheTrailAxisDiscriminates:
    def test_refusal_held_to_blocked_is_not_a_bypass(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 10.0}, approved=False, blocked=True,
                                        violations=["a: cap"])])
        bp = M.measure_bypass(d, since=SINCE, declared_version="v1.0")
        w = bp["trail"]["window"]
        assert (w["refused"], w["refused_then_blocked"], w["refused_then_executed"]) == (1, 1, [])
        doc = M.run(scene(tmp_path), write=False, now=NOW, data_dir=d, since=SINCE)
        assert not any("ОБОЙДЁН" in t for t in _texts(doc, "critical"))

    def test_refusal_followed_by_execution_is_named_critical(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 10.0}, approved=False,
                                        violations=["a: cap"], executed={"a": 10.0}, held={},
                                        trade_id="T777")])
        doc = M.run(scene(tmp_path), write=False, now=NOW, data_dir=d, since=SINCE)
        w = _bypass(doc)["trail"]["window"]
        assert len(w["refused_then_executed"]) == 1
        assert w["refused_then_executed"][0]["trade_ids"] == ["T777"]
        hits = [t for t in _texts(doc, "critical") if "ОБОЙДЁН" in t and "c1" in t and "T777" in t]
        assert hits, doc["findings"]
        assert doc["overall"] == "CRITICAL"

    def test_execution_equal_to_the_decision_is_consistent(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 10.0}, executed={"a": 10.0}, held={})])
        w = M.measure_bypass(d, since=SINCE)["trail"]["window"]
        assert (w["executions"], w["executions_equal_to_decision"],
                w["executions_fresh_beyond_gate"]) == (1, 1, [])

    def test_fresh_capital_beyond_the_gate_is_named_with_dollars_and_protocols(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 10.0}, held={"a": 4.0},
                                        executed={"a": 10.0, "z": 5.0}, trade_id="T801")])
        doc = M.run(scene(tmp_path), write=False, now=NOW, data_dir=d, since=SINCE)
        w = _bypass(doc)["trail"]["window"]
        rec = w["executions_fresh_beyond_gate"][0]
        assert rec["trade_id"] == "T801" and rec["introduced_unjudged"] == ["z"]
        assert w["fresh_beyond_gate_usd"] == 5.0
        assert rec["stage"] is None and "ADR-850" in rec["stage_reason"]
        crit = [t for t in _texts(doc, "critical") if "СВЕРХ потолка" in t]
        assert crit and "$5.00" in crit[0] and "'z'" in crit[0], crit

    def test_a_gate_trimmed_book_below_the_decision_is_counted_but_not_fresh(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 100.0}, trimmed=True,
                                        executed={"a": 95.0}, held={})])
        w = M.measure_bypass(d, since=SINCE)["trail"]["window"]
        assert w["executions_below_decision_only"] == 1
        assert w["executions_fresh_beyond_gate"] == [] and w["fresh_beyond_gate_usd"] == 0.0

    def test_a_chain_before_the_window_counts_only_all_time(self, tmp_path):
        d = data_scene(tmp_path, [chain("old", BEFORE, target={"a": 1.0}, held={},
                                        executed={"a": 9.0}, trade_id="T001"),
                                  chain("new", IN, target={"a": 1.0}, executed={"a": 1.0}, held={})])
        doc = M.run(scene(tmp_path), write=False, now=NOW, data_dir=d, since=SINCE)
        t = _bypass(doc)["trail"]
        assert t["window"]["executions_fresh_beyond_gate"] == []
        assert [r["trade_id"] for r in t["all_time"]["executions_fresh_beyond_gate"]] == ["T001"]
        # окно чисто, история нет — об истории говорится WARN, не CRITICAL
        assert not any("СВЕРХ потолка" in x for x in _texts(doc, "critical"))
        assert any("за всю историю" in x for x in _texts(doc, "warn"))

    def test_the_window_is_an_input(self, tmp_path):
        d = data_scene(tmp_path, [chain("old", BEFORE, target={"a": 1.0}, held={},
                                        executed={"a": 9.0})])
        assert M.measure_bypass(d, since="2026-08-01")["trail"]["window"]["executions"] == 1
        assert M.measure_bypass(d, since=SINCE)["trail"]["window"]["executions"] == 0

    def test_one_verdict_per_chain_makes_rejudgement_unmeasured_not_zero(self, tmp_path):
        """Замер 12.11: 615 цепочек, с двумя вердиктами — 0. Это свойство носителя."""
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 1.0})])
        rj = M.measure_bypass(d, since=SINCE)["trail"]["rejudged_within_chain"]
        assert rj["verdict"] == M.BYPASS_UNMEASURED and rj["carrier"] == M.CARRIER_ONE_VERDICT
        doc = M.run(scene(tmp_path), write=False, now=NOW, data_dir=d, since=SINCE)
        assert any("переспрос RiskPolicy внутри цепочки: НЕ ИЗМЕРЕНО" in t
                   for t in _texts(doc, "unchecked"))

    def test_a_second_verdict_in_a_chain_is_a_measured_rejudgement(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 1.0}, extra_verdicts=1)])
        rj = M.measure_bypass(d, since=SINCE)["trail"]["rejudged_within_chain"]
        assert rj == {"events": 1, "verdict": M.BYPASS_MEASURED, "reason": ""}

    def test_a_chain_without_a_verdict_is_counted_apart(self, tmp_path):
        ch = [e for e in chain("c1", IN, target={"a": 1.0}) if e["event_type"] != "risk_verdict"]
        w = M.measure_bypass(data_scene(tmp_path, [ch]), since=SINCE)["trail"]["window"]
        assert (w["chains"], w["chains_without_verdict"], w["refused"]) == (1, 1, 0)


class TestTheTrailAxisFailsClosed:
    def test_missing_trail_is_unmeasured_and_overall_is_not_ok(self, tmp_path):
        doc = M.run(scene(tmp_path), write=False, now=NOW, data_dir=tmp_path / "nowhere",
                    since=SINCE)
        bp = _bypass(doc)
        assert bp["verdict"] == M.BYPASS_UNMEASURED and "audit_trail.jsonl" in bp["reason"]
        assert bp["trail"] is None and bp["shadow"] is None
        assert any("НЕ ИЗМЕРЕНА" in t for t in _texts(doc, "unchecked"))
        assert doc["overall"] == "UNCHECKED"

    def test_a_non_numeric_book_is_unmeasured_not_a_zero_gap(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": "ten"}, executed={"a": 10.0}, held={})])
        w = M.measure_bypass(d, since=SINCE)["trail"]["window"]
        assert (w["executions"], w["executions_unmeasured"],
                w["executions_equal_to_decision"]) == (1, 1, 0)

    def test_unparsable_lines_are_counted_not_dropped_silently(self, tmp_path):
        good = "".join(json.dumps(e) + "\n" for e in chain("c1", IN, target={"a": 1.0}))
        d = data_scene(tmp_path, [], raw_trail=good + "{not json\n[1,2]\n")
        t = M.measure_bypass(d, since=SINCE)["trail"]
        assert t["unparsable_lines"] == 2 and t["chains_total"] == 1

    def test_a_row_without_correlation_id_is_counted_apart(self, tmp_path):
        ev = chain("c1", IN, target={"a": 1.0})
        ev[0] = dict(ev[0]); del ev[0]["correlation_id"]
        t = M.measure_bypass(data_scene(tmp_path, [ev]), since=SINCE)["trail"]
        assert t["rows_without_correlation"] == 1

    def test_missing_shadow_journal_is_unmeasured_per_book(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 1.0})])
        (d / M.SHADOW_HISTORY_FILES["balanced"]).unlink()
        doc = M.run(scene(tmp_path), write=False, now=NOW, data_dir=d, since=SINCE)
        sh = _bypass(doc)["shadow"]
        assert sh["balanced"]["verdict"] == M.BYPASS_UNMEASURED
        assert sh["conservative"]["verdict"] == M.BYPASS_MEASURED
        assert any("«balanced» не прочитан" in t for t in _texts(doc, "unchecked"))


_TRIM_OK = {"adr": "ADR-850", "verdict": "TRIMMED_TO_ADMISSIBLE", "k": 0.375,
            "policy": {"approved": True, "violations": [], "trimmed_by_gate": False}}


class TestTheShadowAxis:
    def test_rejudgements_are_counted_from_the_trim_record(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 1.0})],
                       shadow={"conservative": [shadow_rec(IN, trim=_TRIM_OK),
                                                shadow_rec("2026-09-11", trim={"verdict": "ALREADY_WITHIN_SIZE_CAPS"}),
                                                shadow_rec("2026-09-12")]})
        b = M.measure_bypass(d, since=SINCE)["shadow"]["conservative"]
        assert (b["records"], b["trims"], b["rejudged"], b["rejudged_approved"]) == (3, 2, 1, 1)
        assert b["trim_verdicts"] == {"ALREADY_WITHIN_SIZE_CAPS": 1, "TRIMMED_TO_ADMISSIBLE": 1}
        assert b["trims_on_act_days"] == 0 and b["refusal_to_approval_same_day"] == []

    def test_refusal_turned_into_approval_the_same_day_is_critical(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 10.0}, approved=False, blocked=True,
                                        violations=["a: cap"])],
                       shadow={"conservative": [shadow_rec(IN, trim=_TRIM_OK)]})
        doc = M.run(scene(tmp_path), write=False, now=NOW, data_dir=d, since=SINCE)
        conv = _bypass(doc)["shadow"]["conservative"]["refusal_to_approval_same_day"]
        assert conv and conv[0]["day"] == IN
        assert any("отказ стал одобрением" in t for t in _texts(doc, "critical"))

    def test_approval_on_a_day_without_refusal_is_not_a_conversion(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 10.0}, approved=True)],
                       shadow={"conservative": [shadow_rec(IN, trim=_TRIM_OK)]})
        b = M.measure_bypass(d, since=SINCE)["shadow"]["conservative"]
        assert b["refusal_to_approval_same_day"] == [] and b["rejudged_approved"] == 1

    def test_a_trim_on_an_act_day_is_a_warning(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 1.0})],
                       shadow={"conservative": [shadow_rec(IN, book_verdict="ACT", trim=_TRIM_OK)]})
        doc = M.run(scene(tmp_path), write=False, now=NOW, data_dir=d, since=SINCE)
        assert _bypass(doc)["shadow"]["conservative"]["trims_on_act_days"] == 1
        assert any("на днях с ходом" in t for t in _texts(doc, "warn"))

    def test_shadow_records_before_the_window_are_not_counted(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 1.0})],
                       shadow={"conservative": [shadow_rec(BEFORE, trim=_TRIM_OK)]})
        b = M.measure_bypass(d, since=SINCE)["shadow"]["conservative"]
        assert (b["records"], b["trims"]) == (0, 0)


class TestVersionLabels:
    def test_labels_other_than_the_declared_version_are_named(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 1.0})],
                       shadow={"conservative": [shadow_rec(IN, policy_version="v1.2"),
                                                shadow_rec("2026-09-11", policy_version="v1.0")]})
        bp = M.measure_bypass(d, since=SINCE, declared_version="v1.0")
        assert bp["version_labels"] == {"verdict": M.BYPASS_MEASURED, "declared": "v1.0",
                                        "on_records": ["v1.0", "v1.2"], "undeclared": ["v1.2"]}

    def test_matching_labels_are_not_a_finding(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 1.0})],
                       shadow={"conservative": [shadow_rec(IN, policy_version="v1.0")]})
        doc = M.run(scene(tmp_path), write=False, now=NOW, data_dir=d, since=SINCE)
        # у сцены политика без поля `version` ⇒ объявленной версии нет ⇒ НЕ ИЗМЕРЕНО, не WARN
        vl = _bypass(doc)["version_labels"]
        assert vl["verdict"] == M.BYPASS_UNMEASURED and vl["on_records"] == ["v1.0"]
        assert not any("больше одного имени" in t for t in _texts(doc, "warn"))
        assert any("подписи версии политики" in t for t in _texts(doc, "unchecked"))

    def test_undeclared_label_reaches_the_findings_on_a_declared_policy(self, tmp_path):
        root = scene(tmp_path)
        (root / M.POLICY_REL).write_text(
            _POLICY.format(cash=0.05, t1=0.40, changelog="") + "    version: str = \"v1.0\"\n",
            encoding="utf-8")
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 1.0})],
                       shadow={"conservative": [shadow_rec(IN, policy_version="v1.2")]})
        doc = M.run(root, write=False, now=NOW, data_dir=d, since=SINCE)
        assert _bypass(doc)["declared_version"] == "v1.0"
        assert any("['v1.2']" in t and "больше одного имени" in t for t in _texts(doc, "warn"))


class TestTheAxisInTheReport:
    def test_report_carries_window_provenance_and_candidates(self, tmp_path):
        d = data_scene(tmp_path, [chain("c1", IN, target={"a": 1.0})])
        bp = _bypass(M.run(scene(tmp_path), write=False, now=NOW, data_dir=d, since=SINCE))
        assert bp["since"] == SINCE and "G981" in bp["since_provenance"]
        assert [c["adr"] for c in bp["stage_candidates"]] == ["ADR-850", "ADR-108", "ADR-072"]
        assert bp["data_dir"] == str(d)

    def test_data_dir_defaults_to_root_data(self, tmp_path):
        root = scene(tmp_path)
        data_scene(root, [chain("c1", IN, target={"a": 1.0})])
        bp = _bypass(M.run(root, write=False, now=NOW, since=SINCE))
        assert bp["verdict"] == M.BYPASS_MEASURED and bp["data_dir"] == str(root / "data")

    def test_cli_accepts_data_dir_and_since(self, tmp_path, capsys):
        root = scene(tmp_path)
        d = data_scene(tmp_path / "elsewhere", [chain("c1", IN, target={"a": 1.0})])
        (root / "data").mkdir(exist_ok=True)
        rc = M.main(["--root", str(root), "--data-dir", str(d), "--since", "2026-09-01"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "вторая ось (с 2026-09-01" in out
        written = json.loads((root / M.REPORT_REL).read_text(encoding="utf-8"))
        assert written["bypass_by_stage"]["since"] == "2026-09-01"

    def test_live_tree_report_carries_the_axis(self):
        """На НАСТОЯЩЕМ дереве ось либо измерена, либо честно не измерена — но присутствует."""
        doc = M.run(write=False, now=NOW)
        bp = doc["bypass_by_stage"]
        assert bp["verdict"] in (M.BYPASS_MEASURED, M.BYPASS_UNMEASURED)
        if bp["verdict"] == M.BYPASS_MEASURED:
            assert bp["trail"]["rejudged_within_chain"]["verdict"] in (M.BYPASS_MEASURED, M.BYPASS_UNMEASURED)


class TestTheOfficeBranch:
    """Шаг 0-офис печатает ось именной веткой; артефакт v1 → «не измерено», не «обходов нет»."""

    @staticmethod
    def _office():
        import importlib.util
        import sys
        path = Path(M.__file__).resolve().parents[2] / "scripts" / "consume_office_reports.py"
        if "consume_office_reports" in sys.modules:
            return sys.modules["consume_office_reports"]
        spec = importlib.util.spec_from_file_location("consume_office_reports", path)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["consume_office_reports"] = mod
        spec.loader.exec_module(mod)
        return mod

    def test_schema_declares_the_axis(self):
        office = self._office()
        assert "bypass_by_stage" in office._READ_SCHEMA["cio_policy_change_procedure.json"]
