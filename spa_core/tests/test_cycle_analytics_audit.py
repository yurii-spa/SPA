# LLM_FORBIDDEN
"""Тесты шага цикла «ежедневный аудит аналитики» (`scripts/cycle_analytics_audit.py`).

Каждый тест — воспроизведение НАСТОЯЩЕЙ аварии, а не украшение
(`.claude/rules/deployment.md`, раздел «Проверка сторожа сторожей»):

* **07–20.08** аудит протокол-слепоты молча простоял 13 суток, и метрика владельца
  не сдвинулась ни на один модуль. Цикл #367 сделал простой ВИДИМЫМ, но гонять
  проверку было по-прежнему некому — владелец 24.08 выбрал вариант 2 (шаг цикла).
* **Замер 24.08 в чистом дереве:** один прогон аудита меняет 29 файлов состояния
  (27 в `data/`, 2 в `spa_core/data/`). В боевом дереве там живёт трек — ровно
  поэтому прогон обязан идти в песочнице, а обратно ехать РОВНО один файл разметки.
  Положительный контроль (`test_audit_in_source_tree_really_dirties_it`) показывает,
  что подделка аварии настоящая: прогон без песочницы дерево пачкает.

Часы — вход, дат-литералов нет (`spa_core/tests/_freshness.py::ts`): предмет теста —
поведение шага, а не календарь.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from spa_core.tests._freshness import ts

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_step():
    """Загрузить шаг ПО ПУТИ К ФАЙЛУ: `scripts/` пакетом не является."""
    path = REPO_ROOT / "scripts" / "cycle_analytics_audit.py"
    spec = importlib.util.spec_from_file_location("cycle_analytics_audit", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["cycle_analytics_audit"] = module
    spec.loader.exec_module(module)
    return module


step = _load_step()


# ─────────────────────────── поддельное дерево ───────────────────────────────

#: Подделка аудита: ведёт себя как настоящий — пишет рабочие логи ОТНОСИТЕЛЬНО
#: cwd (именно так пачкались 29 файлов) и по `--emit-markup` кладёт разметку
#: рядом со своим деревом. Метку берёт из переменной окружения, чтобы тест мог
#: закрепить обе стороны времени.
_FAKE_AUDIT = '''\
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--tier", default="B")
ap.add_argument("--emit-markup", action="store_true")
args = ap.parse_args()

# то самое, ради чего нужна песочница: модули пишут состояние рядом с корнем репо
for rel in ("data/dirty_log.json", "spa_core/data/dirty_log.json"):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"written_by": "fake_audit"}), encoding="utf-8")

Path(args.out).write_text(json.dumps({"tier": args.tier}), encoding="utf-8")

if args.emit_markup:
    stamp = os.environ.get("FAKE_AUDIT_STAMP", "")
    body = os.environ.get("FAKE_AUDIT_BODY", "")
    markup = ROOT / "spa_core" / "analytics" / "_protocol_blindness.py"
    markup.parent.mkdir(parents=True, exist_ok=True)
    markup.write_text(
        "AUDIT_GENERATED_AT = " + repr(stamp) + "\\n"
        "PROTOCOL_BLIND_DETAIL = {}\\n"
        "WIDE_OK_MODULES = frozenset()\\n"
        "# " + body + "\\n",
        encoding="utf-8")

sys.exit(int(os.environ.get("FAKE_AUDIT_RC", "0")))
'''

#: Подделка ПЕРЕПИСИ внетировых модулей (шаг обзавёлся ею 2026-08-29, аудит 90 %).
#: Дерево, в котором её нет, шаг честно отвергает: перепись отвечает на вопрос «кого
#: мы не меряем вовсе», и молча пропустить её значило бы вернуть исходный дефект —
#: корпус растёт незамеченным (67 модулей вне тиров 20.08, 83 к 29.08).
_FAKE_CENSUS = '''\
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument("--out")
ap.add_argument("--emit-markup", action="store_true")
args = ap.parse_args()

if args.out:
    Path(args.out).write_text(json.dumps({"untiered": 0}), encoding="utf-8")

if args.emit_markup:
    body = os.environ.get("FAKE_CENSUS_BODY", "")
    census = ROOT / "spa_core" / "analytics" / "_untiered_census.py"
    census.parent.mkdir(parents=True, exist_ok=True)
    census.write_text(
        "AUDIT_GENERATED_AT = " + repr(os.environ.get("FAKE_CENSUS_STAMP", "")) + "\\n"
        "OUT_OF_DENOMINATOR = frozenset()\\n"
        "WIRABLE = {}\\n"
        "# " + body + "\\n",
        encoding="utf-8")

sys.exit(int(os.environ.get("FAKE_CENSUS_RC", "0")))
'''

#: Подделка, которая ОТЧИТЫВАЕТСЯ об успехе, но разметки не оставляет —
#: «прогон был, продукта нет». Молчаливым «ок» это быть не должно.
_FAKE_AUDIT_NO_MARKUP = '''\
import argparse, json, sys
from pathlib import Path
ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--tier", default="B")
ap.add_argument("--emit-markup", action="store_true")
args = ap.parse_args()
Path(args.out).write_text(json.dumps({"tier": args.tier}), encoding="utf-8")
sys.exit(0)
'''


def _make_tree(root: Path, *, markup_age_h: float | None = 1.0,
               audit_src: str = _FAKE_AUDIT,
               census_src: str | None = _FAKE_CENSUS) -> Path:
    """Поддельное дерево: аудит, перепись, разметка нужного возраста, состояние.

    `census_src=None` — дерево БЕЗ переписи; так проверяется, что шаг её отсутствие
    замечает, а не молча пропускает.
    """
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "audit_protocol_blindness.py").write_text(
        audit_src, encoding="utf-8")
    if census_src is not None:
        (root / "scripts" / "audit_untiered_analytics.py").write_text(
            census_src, encoding="utf-8")
    (root / "spa_core" / "analytics").mkdir(parents=True, exist_ok=True)
    if markup_age_h is not None:
        (root / "spa_core" / "analytics" / "_protocol_blindness.py").write_text(
            f"AUDIT_GENERATED_AT = {ts(hours_ago=markup_age_h)!r}\n"
            "PROTOCOL_BLIND_DETAIL = {}\n"
            "WIDE_OK_MODULES = frozenset()\n",
            encoding="utf-8")
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "track.json").write_text('{"keep": "me"}', encoding="utf-8")
    (root / "spa_core" / "data").mkdir(parents=True, exist_ok=True)
    (root / "spa_core" / "data" / "track.json").write_text(
        '{"keep": "me"}', encoding="utf-8")
    return root


def _state_snapshot(root: Path) -> dict:
    """Отпечаток файлов состояния — ими и меряется «дерево не тронуто»."""
    out = {}
    for rel in ("data", "spa_core/data"):
        base = root / rel
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            if path.is_file():
                out[str(path.relative_to(root))] = path.read_bytes()
    return out


@pytest.fixture()
def env_stamp(monkeypatch):
    """Метка, которую положит подделка аудита; по умолчанию — «только что»."""
    def _set(hours_ago: float = 0.0, body: str = "", rc: int = 0):
        monkeypatch.setenv("FAKE_AUDIT_STAMP", ts(hours_ago=hours_ago))
        monkeypatch.setenv("FAKE_AUDIT_BODY", body)
        monkeypatch.setenv("FAKE_AUDIT_RC", str(rc))
    _set()
    return _set


# ───────────────── авария 1: прогон в живом дереве пачкает трек ──────────────

def test_audit_in_source_tree_really_dirties_it(tmp_path, env_stamp):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: без песочницы прогон пачкает дерево.

    Без этого теста проверка «дерево не тронуто» была бы украшением: она могла бы
    держаться зелёной просто потому, что подделка аудита ничего не пишет.
    """
    src = _make_tree(tmp_path / "src")
    before = _state_snapshot(src)
    step.run_audit(src)                      # cwd = само дерево — та самая авария
    after = _state_snapshot(src)
    assert after != before, "подделка аудита не воспроизводит аварию — тест ниже пуст"
    assert (src / "data" / "dirty_log.json").is_file()


def test_sandbox_run_leaves_source_state_untouched(tmp_path, env_stamp):
    """Шаг прогоняет аудит в песочнице: `data/` судимого дерева байт-в-байт та же."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    env_stamp(hours_ago=0.0, body="fresh-run")
    before = _state_snapshot(src)

    report = step.run_step(src, src, sandbox=tmp_path / "box")

    assert report["ran_audit"] is True
    assert _state_snapshot(src) == before, (
        "прогон изменил состояние судимого дерева — в проде там живёт трек")
    assert not (src / "data" / "dirty_log.json").exists()
    assert not (src / "spa_core" / "data" / "dirty_log.json").exists()


def test_only_the_markup_travels_back(tmp_path, env_stamp):
    """Из песочницы возвращается РОВНО один путь — разметка, и она обновлена."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    env_stamp(hours_ago=0.0, body="fresh-run")

    report = step.run_step(src, src, sandbox=tmp_path / "box", keep_sandbox=True)

    assert report["markup_changed"] is True
    assert report["exit_code"] == step.NEEDS_DELIVERY
    text = (src / "spa_core" / "analytics" / "_protocol_blindness.py").read_text()
    assert "fresh-run" in text
    # песочница нагадила у себя — и это осталось у неё
    assert (Path(report["sandbox"]) / "data" / "dirty_log.json").is_file()


# ───────────── авария 2: измеритель молчит, а никто не гоняет ────────────────

def test_fresh_markup_means_no_run(tmp_path, env_stamp):
    """Свежий аудит — прогона нет: шаг обязан быть дешёвым в КАЖДОМ цикле."""
    src = _make_tree(tmp_path / "src", markup_age_h=1.0)
    report = step.run_step(src, src, sandbox=tmp_path / "box")
    assert report["ran_audit"] is False
    assert report["exit_code"] == step.OK
    assert report["freshness_before"]["status"] == "FRESH"


def test_stale_markup_triggers_the_run(tmp_path, env_stamp):
    """13 суток молчания: STALE обязан ЗАПУСКАТЬ прогон, а не только краснеть."""
    src = _make_tree(tmp_path / "src", markup_age_h=13 * 24)
    env_stamp(hours_ago=0.0, body="after-stale")
    report = step.run_step(src, src, sandbox=tmp_path / "box")
    assert report["freshness_before"]["status"] == "STALE"
    assert report["ran_audit"] is True
    assert report["exit_code"] == step.NEEDS_DELIVERY
    assert report["freshness_after"]["status"] == "FRESH"


def test_missing_markup_triggers_the_run(tmp_path, env_stamp):
    """Разметки нет вовсе (MISSING) — это тоже повод гнать, а не молчать."""
    src = _make_tree(tmp_path / "src", markup_age_h=None)
    env_stamp(hours_ago=0.0, body="from-scratch")
    report = step.run_step(src, src, sandbox=tmp_path / "box")
    assert report["freshness_before"]["status"] == "MISSING"
    assert report["ran_audit"] is True
    assert report["exit_code"] == step.NEEDS_DELIVERY


def test_force_runs_even_when_fresh(tmp_path, env_stamp):
    """`--force` — осознанный повторный замер; свежесть его не отменяет."""
    src = _make_tree(tmp_path / "src", markup_age_h=1.0)
    env_stamp(hours_ago=0.0, body="forced")
    report = step.run_step(src, src, sandbox=tmp_path / "box", force=True)
    assert report["ran_audit"] is True
    assert "forced" in (src / "spa_core" / "analytics"
                        / "_protocol_blindness.py").read_text()


def test_identical_content_is_not_a_delivery(tmp_path):
    """Единичный случай переноса: байты те же ⇒ файла не трогаем, доставки нет.

    Проверяется на самом переносе, а не на прогоне: у НАСТОЯЩЕГО аудита отметка
    двигается всегда (`_utc_now_iso`), поэтому «прогон дал байт-в-байт то же»
    в жизни недостижимо — и выдавать такой сценарий за прогон было бы подлогом.
    """
    box = _make_tree(tmp_path / "box", markup_age_h=1.0)
    into = tmp_path / "into"
    (into / "spa_core" / "analytics").mkdir(parents=True)
    same = (box / "spa_core" / "analytics" / "_protocol_blindness.py").read_text()
    target = into / "spa_core" / "analytics" / "_protocol_blindness.py"
    target.write_text(same, encoding="utf-8")
    mtime_before = target.stat().st_mtime_ns

    assert step.deliver_markup(box, into) is False
    assert target.stat().st_mtime_ns == mtime_before


def test_run_moves_the_stamp_but_keeps_the_classes(tmp_path, env_stamp):
    """Прогон обязан СДВИНУТЬ отметку; классы при этом устойчивы (аудит детерминирован)."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    before = (src / "spa_core" / "analytics" / "_protocol_blindness.py").read_text()
    env_stamp(hours_ago=0.0, body="")
    report = step.run_step(src, src, sandbox=tmp_path / "box", force=True)
    after = (src / "spa_core" / "analytics" / "_protocol_blindness.py").read_text()

    assert report["markup_stamp_after"] != report["markup_stamp_before"]
    assert report["markup_changed"] is True
    assert "PROTOCOL_BLIND_DETAIL = {}" in before
    assert "PROTOCOL_BLIND_DETAIL = {}" in after


def test_markup_lands_in_into_tree_not_source(tmp_path, env_stamp):
    """Дерево цикла (`--into`) — не то же, что судимое: разметка едет ТУДА."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    into = _make_tree(tmp_path / "into", markup_age_h=99.0)
    env_stamp(hours_ago=0.0, body="delivered-here")
    step.run_step(src, into, sandbox=tmp_path / "box")
    assert "delivered-here" in (into / "spa_core" / "analytics"
                                / "_protocol_blindness.py").read_text()
    assert "delivered-here" not in (src / "spa_core" / "analytics"
                                    / "_protocol_blindness.py").read_text()


# ───────────────────────── отказы: fail-CLOSED ───────────────────────────────

def test_sandbox_equal_to_source_is_refused(tmp_path, env_stamp):
    """Песочница = судимое дерево — это и есть прогон в живом дереве."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    report = step.run_step(src, src, sandbox=src)
    assert report["exit_code"] == step.REFUSED
    assert report["ran_audit"] is False
    assert "живом дереве" in report["error"]
    assert not (src / "data" / "dirty_log.json").exists()


def test_nested_sandbox_is_refused(tmp_path, env_stamp):
    """Песочница ВНУТРИ судимого дерева изоляции не даёт."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    report = step.run_step(src, src, sandbox=src / "box")
    assert report["exit_code"] == step.REFUSED
    assert "вложены" in report["error"]


def test_source_nested_in_sandbox_is_refused(tmp_path, env_stamp):
    """И обратная вложенность тоже: копирование в самого себя."""
    outer = tmp_path / "outer"
    src = _make_tree(outer / "src", markup_age_h=99.0)
    report = step.run_step(src, src, sandbox=outer)
    assert report["exit_code"] == step.REFUSED
    assert "вложены" in report["error"]


def test_nonempty_sandbox_is_refused(tmp_path, env_stamp):
    """Чужие байты в песочнице делают вердикт нечитаемым — отказ, не «поверх»."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    box = tmp_path / "box"
    box.mkdir()
    (box / "someone_elses.txt").write_text("x", encoding="utf-8")
    report = step.run_step(src, src, sandbox=box)
    assert report["exit_code"] == step.REFUSED
    assert "непуста" in report["error"]


def test_reuse_sandbox_is_an_explicit_decision(tmp_path, env_stamp):
    """`--reuse-sandbox` снимает ровно этот отказ и ничего больше."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    box = tmp_path / "box"
    box.mkdir()
    (box / "someone_elses.txt").write_text("x", encoding="utf-8")
    env_stamp(hours_ago=0.0, body="reused")
    report = step.run_step(src, src, sandbox=box, reuse_sandbox=True)
    assert report["exit_code"] == step.NEEDS_DELIVERY


def test_missing_audit_script_is_refused(tmp_path, env_stamp):
    """Дерево без аудита — отказ: «нечего гнать» не равно «всё в порядке»."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    (src / "scripts" / "audit_protocol_blindness.py").unlink()
    report = step.run_step(src, src, sandbox=tmp_path / "box")
    assert report["exit_code"] == step.REFUSED
    assert "в судимом дереве нет" in report["error"]


def test_audit_nonzero_exit_is_refused(tmp_path, env_stamp):
    """Аудит упал — шаг обязан краснеть, а не отчитаться о свежести."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    env_stamp(hours_ago=0.0, body="broken", rc=3)
    report = step.run_step(src, src, sandbox=tmp_path / "box")
    assert report["exit_code"] == step.REFUSED
    assert "код 3" in report["error"]
    # разметка судимого дерева не тронута — сломанный прогон ничего не доставляет
    assert "broken" not in (src / "spa_core" / "analytics"
                            / "_protocol_blindness.py").read_text()


def test_copied_markup_is_not_mistaken_for_a_product(tmp_path, env_stamp):
    """Код 0, разметки не написал — в песочнице лежит КОПИЯ, и она не доказательство.

    Это наш известный класс «сторож, сверяющий копии, слеп»: файл на месте только
    потому, что мы сами его туда принесли. Доказывает продукт только сдвиг отметки.
    """
    src = _make_tree(tmp_path / "src", markup_age_h=99.0,
                     audit_src=_FAKE_AUDIT_NO_MARKUP)
    report = step.run_step(src, src, sandbox=tmp_path / "box")
    assert report["exit_code"] == step.REFUSED
    assert "КОПИЯ" in report["error"]


def test_no_markup_anywhere_is_refused(tmp_path, env_stamp):
    """Разметки нет ни в дереве, ни после прогона — отказ, а не «нечего доставлять»."""
    src = _make_tree(tmp_path / "src", markup_age_h=None,
                     audit_src=_FAKE_AUDIT_NO_MARKUP)
    report = step.run_step(src, src, sandbox=tmp_path / "box")
    assert report["exit_code"] == step.REFUSED
    assert "не оставил разметки" in report["error"]


def test_tier_c_does_not_pretend_to_be_tier_b(tmp_path, env_stamp):
    """Tier C разметки не производит — и шаг НЕ выдаёт его прогон за замер Tier B."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    env_stamp(hours_ago=0.0, body="tier-c")
    report = step.run_step(src, src, sandbox=tmp_path / "box", tier="C")
    assert report["ran_audit"] is True
    assert report["markup_changed"] is False
    assert report["exit_code"] == step.OK
    assert "tier-c" not in (src / "spa_core" / "analytics"
                            / "_protocol_blindness.py").read_text()


# ─────────────── связка с настоящим деревом и с протоколом ───────────────────

def test_constants_match_the_freshness_guard():
    """Шаг и сторож обязаны судить ОДИН предмет — иначе зелёное про разное.

    Сверяется с ИСТОЧНИКОМ (импортированный модуль сторожа), не с копией.
    """
    from spa_core.monitoring import analytics_audit_freshness as guard
    assert step.MARKUP_REL == guard.MARKUP_REL
    assert "audit_protocol_blindness" in guard.AUDIT_COMMAND
    assert step.AUDIT_REL.endswith("audit_protocol_blindness.py")


def test_real_repo_has_the_audit_the_step_calls():
    """Шаг зовёт файл, который в дереве действительно есть."""
    assert (REPO_ROOT / step.AUDIT_REL).is_file()


def test_step_is_written_into_the_orchestrator_protocol():
    """Решение владельца (вариант 2) — это ШАГ ПРОТОКОЛА, а не только скрипт.

    Скрипт без записи в протоколе исполняется «когда вспомнят» — ровно тем
    способом, который и дал простой на 13 суток.
    """
    text = (REPO_ROOT / "docs" / "ORCHESTRATOR_PROTOCOL.md").read_text(
        encoding="utf-8")
    assert "cycle_analytics_audit.py" in text


def test_step_is_named_in_the_cycle_prompt():
    """И в промпте обёртки: её читает КАЖДЫЙ автономный цикл."""
    text = (REPO_ROOT / "scripts" / "agent_orchestrator.sh").read_text(
        encoding="utf-8")
    assert "cycle_analytics_audit.py" in text


def test_cli_json_output_is_machine_readable(tmp_path, env_stamp, capsys):
    """`--json` — вход для сторожей: вердикт обязан быть разбираемым."""
    src = _make_tree(tmp_path / "src", markup_age_h=1.0)
    rc = step.main(["--source", str(src), "--sandbox", str(tmp_path / "box"),
                    "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == step.OK
    assert payload["exit_code"] == step.OK
    assert payload["llm_forbidden"] is True
    assert payload["advisory"] is True


# ───── авария 4: корпус растёт за пределы измеряемого, и этого никто не видит ──
#
# Аудит тиров отвечает «как работают те, кого мы меряем», и на вопрос «кого мы не
# меряем вовсе» не отвечает НИКОГДА — он его не задаёт. Замеры аудита 90 %: модулей
# вне всех тиров было 67 (20.08), 82 (27.08), 83 (29.08). Знаменатель метрики
# дрейфовал три недели, и ни один сторож не покраснел. С 2026-08-29 перепись —
# часть того же шага, чтобы вопрос задавался с той же частотой, что и основной.

def test_census_output_travels_back_too(tmp_path, env_stamp, monkeypatch):
    """Перепись обязана ДОЕЗЖАТЬ в дерево, а не оставаться в песочнице.

    Положительный контроль проводки: до 29.08 файла не было вовсе, и «перепись
    прогнали» ничем не отличалось от «переписи нет»."""
    monkeypatch.setenv("FAKE_CENSUS_BODY", "census-arrived")
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    env_stamp(hours_ago=0.0, body="fresh-run")

    report = step.run_step(src, src, sandbox=tmp_path / "box")

    assert report["census_returncode"] == 0
    assert report["census_changed"] is True
    text = (src / "spa_core" / "analytics" / "_untiered_census.py").read_text(
        encoding="utf-8")
    assert "census-arrived" in text


def test_a_failing_census_refuses_the_step(tmp_path, env_stamp, monkeypatch):
    """Перепись упала ⇒ шаг ОТКАЗЫВАЕТ (fail-CLOSED), а не отчитывается об успехе.

    Мера против самого дешёвого способа потерять проверку: «прогнали, не получилось,
    поехали дальше». Знаменатель, посчитанный без переписи, — не оценка."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    env_stamp(hours_ago=0.0)
    monkeypatch.setenv("FAKE_CENSUS_RC", "3")

    report = step.run_step(src, src, sandbox=tmp_path / "box")

    assert report["exit_code"] == step.REFUSED
    assert "перепись" in report["error"]


def test_a_tree_without_the_census_tool_is_refused(tmp_path, env_stamp):
    """Инструмента нет ⇒ отказ. «Нечем мерить» не равно «мерить нечего»."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0, census_src=None)
    env_stamp(hours_ago=0.0)

    report = step.run_step(src, src, sandbox=tmp_path / "box")

    assert report["exit_code"] == step.REFUSED


def test_the_writeoff_selfcheck_has_a_third_outcome(tmp_path, env_stamp):
    """У самопроверки генератора три исхода, а не два.

    Инструмента в дереве нет (поддельное дерево его не несёт) — вердикт обязан быть
    «НЕ ИЗМЕРЕНО», и он обязан ОТЛИЧАТЬСЯ от «сошлось». Иначе отсутствие проверки
    неотличимо от её успеха — известный класс fail-open, из-за которого сторожа
    перестают что-либо значить.

    Отдельно проверяется, что этот исход шаг НЕ роняет: самопроверка соседнего
    инструмента не имеет права глушить ежедневный замер слепоты."""
    src = _make_tree(tmp_path / "src", markup_age_h=99.0)
    env_stamp(hours_ago=0.0)

    report = step.run_step(src, src, sandbox=tmp_path / "box")

    assert report["writeoff_selfcheck_returncode"] is None
    assert "НЕ ИЗМЕРЕНО" in report["writeoff_selfcheck"]
    assert "воспроизводит" not in report["writeoff_selfcheck"]
    assert report["exit_code"] != step.REFUSED, (
        "самопроверка соседа уронила ежедневный замер слепоты")
