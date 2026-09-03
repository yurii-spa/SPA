"""Отказ моста «перенести нечем» — вердикт РЕШАТЕЛЯ, и решатель под ним сменился.

Замер цикла #471 (03.09.2026), живой, на настоящих файлах прод-дерева:

  11:46:08Z  `findings_bridge` производит отчёт: `ДОСТАВКА КАРТОЧЕК PARTIAL:
             уехало 2, ЗАСТРЯЛО 2` — по обеим карточкам `…gas-price-agent…`
             причина «расхождение с origin не сводится к строке status: и следу
             status_trail: — перенести правку автоматически нечем; **сделать это
             вручную** из worktree на origin/main»;
  16:04:31Z  коммит `3425bd28` (**ADR-219**, цикл #470) учит
             `card_delivery.rebase_onto_ahead_origin` везти РОВНО этот случай:
             origin обогнал прод по телу карточки и по захвату;
  17:2xZ     обязательный шаг 0-офис печатает отчёт 11:46 дословно, и цикл #471
             начинает делать руками то, что машина уже умеет. Перемерено перед
             правкой: `rebase_card(local, remote)` строит кандидата для ОБЕИХ
             карточек — ручной перенос был бы дублем поверх автоматики.

Возраст отчёта (5.6ч) на этот вопрос не отвечает: он меряет, давно ли ходил
мост, а не сменился ли под ним тот, кто выносит вердикт. Ровно тот же класс, что
#337 закрыл для конституции (`test_office_verdict_about_previous_subject.py`) —
там предметом был манифест, здесь предмет отказа — САМ РЕШАТЕЛЬ `card_delivery`.

Карточки предметом объявлять нельзя: они живое состояние, и находку давал бы
каждый прогон (правило реестра `_SUBJECT`). Решатель — код, 7 правок за 30 дней.

Каждый тест ниже — положительный контроль: на дереве до правки он краснеет
(`_SUBJECT` не знает отчёта моста, `run_bridge` не пишет `inputs`), и он
воспроизводит настоящую аварию 03.09, а не воображаемую.
"""
# FROZEN-DATE-OK: исторический инцидент — отметки 2026-09-03 11:46Z/16:04Z и есть
# ПРЕДМЕТ проверки (правило `.claude/rules/deployment.md`, преференция #3). Часы
# при этом инъектируются (`now=NOW`), обе стороны сравнения закреплены.
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path

from spa_core.tests._freshness import at

_REPO = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO / "scripts" / "consume_office_reports.py"


def _load():
    spec = importlib.util.spec_from_file_location("_cor_decider", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MOD = _load()

NAME = "findings_bridge_report.json"
REL = "spa_core/monitoring/card_delivery.py"

# Отметки настоящей аварии 03.09 (см. модульный докстринг).
VERDICT_AT = "2026-09-03T11:46:08.528919+00:00"   # отчёт моста
DECIDER_AT = "2026-09-03T16:04:31+00:00"          # ADR-219 сменил решателя
NOW = at("2026-09-03T17:21:00+00:00")             # шаг 0-офис читает отчёт

# Отказ, который отчёт печатал про обе карточки — дословно из data/ прода 03.09.
REFUSAL = ("расхождение с origin не сводится к строке status: и следу "
           "status_trail: — перенести правку автоматически нечем; сделать это "
           "вручную из worktree на origin/main")


def _stamp(path: Path, iso: str) -> None:
    """Время правки предмета — ВХОД проверки, поэтому задаётся явно."""
    ts = at(iso).timestamp()
    os.utime(path, (ts, ts))


def _decider(root: Path, body: str = "# решатель после ADR-219\n",
             *, mtime: str = DECIDER_AT) -> Path:
    path = root / "spa_core" / "monitoring" / "card_delivery.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    _stamp(path, mtime)
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _report(generated_at: str = VERDICT_AT, *, inputs=None, stuck: bool = True) -> dict:
    """Отчёт моста 11:46Z — форма СНЯТА с настоящего `data/findings_bridge_report.json`
    прода того дня: две карточки уехали, две застряли с отказом решателя."""
    stuck_paths = ["nimbalyst-local/tracker/"
                   "inbox-nahodka-petli-com-spa-gas-price-agent-ra.md",
                   "nimbalyst-local/tracker/"
                   "inbox-nahodka-petli-manifest-fakty-com-spa-gas.md"]
    delivery = {
        "generated_at": generated_at, "adr": "ADR-066",
        "attempted": stuck_paths if stuck else [],
        "delivered": [], "refused": [],
        "rebased": [], "already_on_origin": [], "covered_by_origin": [],
        "same_outcome_on_origin": [], "rebase_unmeasured": [], "held": [],
        "rebase_refused": ([{"path": p, "reason": REFUSAL} for p in stuck_paths]
                           if stuck else []),
        "status": "PARTIAL" if stuck else "IDLE",
        "reason": ("уехало 0, ЗАСТРЯЛО 2 — "
                   + "; ".join(f"{p}: {REFUSAL}" for p in stuck_paths)) if stuck else "",
        "returncode": 0,
        "debt": {"count": 2 if stuck else 0, "stale_after": 5,
                 "paths": stuck_paths if stuck else [], "oldest_hours": 0.0,
                 "undated": 0, "max_attempts": 1, "stale": [], "retried": [],
                 "dropped": []},
    }
    r = {"generated_at": generated_at, "adr": "ADR-066", "delivery": delivery,
         "owner_answer_delivery": {"status": "IDLE", "delivered": [], "pending": []},
         "created": [], "closed": [], "deferred": [], "waiting_hysteresis": [],
         "closing_hysteresis": [], "escalated": [], "sources_unread": [],
         "reconciled_from_tracker": [], "withdrawn": [], "open_cards": 3,
         "rate_limit": {"max_per_day": 3, "used_today": 0}}
    if inputs is not None:
        r["inputs"] = inputs
    return r


def _inputs(sha: str, *, path: str = REL, mtime: str = VERDICT_AT) -> list:
    return [{"path": path, "role": "subject", "measured": True,
             "mtime": mtime, "sha256": sha, "reason": ""}]


def _text(lines) -> str:
    return "\n".join(lines)


# ── 1. авария 03.09 дословно ─────────────────────────────────────────────────

def test_decider_changed_after_the_refusal_is_a_finding(tmp_path) -> None:
    """Отказ 11:46Z, решатель сменился в 16:04Z ⇒ находка, а не приказ «руками».

    Это и есть авария: шаг 0-офис 4.3 ч звал человека делать то, что машина уже
    умела, и отличить «нечем» от «уже есть чем» читателю было НЕЧЕМ.
    """
    _decider(tmp_path)
    rep = _report(inputs=_inputs("0" * 64))     # мост мерил ПРЕЖНЕГО решателя
    lines = MOD._subject_drift(NAME, rep, root=str(tmp_path), now=NOW)
    out = _text(lines)
    assert lines, "отказ прежнего решателя прошёл молча — это авария 03.09"
    assert "ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ" in out, out
    assert REL in out, out
    assert "находка" in out, out
    # Основание сравнения НАЗВАНО: «сошлось по хэшу» и «сошлось, потому что
    # мерить было нечем» обязаны выглядеть по-разному (урок #337).
    assert "по содержимому" in out, out


def test_unchanged_decider_stays_silent(tmp_path) -> None:
    """Обратный контроль: решатель тот же ⇒ ни строки.

    Без него правка была бы неотличима от «печатать находку всегда»: шаг стал бы
    шумнее, а не честнее, и находку научились бы пролистывать.
    """
    path = _decider(tmp_path)
    rep = _report(inputs=_inputs(_sha(path)))
    assert MOD._subject_drift(NAME, rep, root=str(tmp_path), now=NOW) == []


def test_touched_decider_with_identical_bytes_is_not_a_finding(tmp_path) -> None:
    """Капкан, в который упала бы сверка по одному mtime.

    Прод-дерево синкает `spa_core/` перед КАЖДЫМ запуском (CLAUDE.md §1), и
    холостой синк переписывает решателя байт-в-байт. По mtime это неотличимо от
    настоящей правки — находка печаталась бы каждый прогон, а класс, ради
    которого проверка написана, утонул бы в собственном шуме.
    """
    path = _decider(tmp_path, mtime="2026-09-03T09:00:00+00:00")
    sha = _sha(path)
    _stamp(path, DECIDER_AT)            # переписан тем же содержимым, ПОЗЖЕ отчёта
    rep = _report(inputs=_inputs(sha, mtime="2026-09-03T09:00:00+00:00"))
    assert MOD._subject_drift(NAME, rep, root=str(tmp_path), now=NOW) == [], (
        "холостой синк объявлен находкой — сверка идёт по mtime, а не по байтам")


# ── 2. fail-CLOSED: неизмеримое называется, а не молчит ──────────────────────

def test_unreadable_decider_is_unmeasured_not_silence(tmp_path) -> None:
    """Решателя нет ⇒ «НЕ ИЗМЕРЕНО» вслух (инвариант 2), а не тишина."""
    out = _text(MOD._subject_drift(NAME, _report(inputs=_inputs("0" * 64)),
                                   root=str(tmp_path), now=NOW))
    assert MOD._UNMEASURED in out, out
    assert REL in out, out
    assert "не прочитан" in out, out


# ── 3. проводка целиком: писатель и читатель зовут ОДИН файл ─────────────────

def test_writer_and_reader_name_the_same_decider() -> None:
    """Читатель без писателя — украшение, а разъехавшиеся пути — молчание.

    Назови производитель путь A, а `_SUBJECT` — путь B, и проверка не покраснеет
    никогда: `inputs` без совпадающего `path` тихо сваливается в сверку по mtime.
    Поэтому имя предмета проверяется у ОБОИХ концов, а не у одного.
    """
    from spa_core.monitoring import findings_bridge as fb

    assert MOD._SUBJECT[NAME] == (fb.DECIDER_REL,), (
        f"шаг 0-офис ждёт {MOD._SUBJECT[NAME]}, мост пишет {fb.DECIDER_REL!r}")


def test_bridge_report_carries_the_decider_provenance(tmp_path) -> None:
    """Мост обязан сказать, ПО КАКОМУ решателю вынес отказ — прогоном, не чтением.

    Гоняется настоящий `run_bridge` (побочные действия инъектированы), потому
    что проверка формы в отрыве бывала зелёной при мёртвой проводке (урок #144).
    """
    from spa_core.monitoring import findings_bridge as fb

    (tmp_path / "data").mkdir(parents=True)
    path = _decider(tmp_path)
    report = fb.run_bridge(
        root=str(tmp_path), now=at(VERDICT_AT),
        create=lambda *a, **k: None, close=lambda *a, **k: False,
        notify=lambda *a, **k: None, deliver=lambda *a, **k: {"status": "IDLE"},
        retract=lambda *a, **k: True, deliver_answers=lambda **k: {"status": "IDLE"})
    row = next(r for r in report["inputs"] if r["path"] == fb.DECIDER_REL)
    assert row["measured"] is True, row
    assert row["sha256"] == _sha(path), row
    # И блок доезжает до ФАЙЛА, а не только до возвращённого словаря.
    on_disk = json.loads((tmp_path / "data" / "findings_bridge_report.json").read_text())
    assert on_disk.get("inputs") == report["inputs"], on_disk.get("inputs")


def test_bridge_provenance_is_fail_closed(tmp_path) -> None:
    """Решатель не прочитан ⇒ `measured: false` с причиной, а не «сошлось»."""
    from spa_core.monitoring import architecture_conformance as ac
    from spa_core.monitoring import findings_bridge as fb

    row = next(r for r in ac.subject_inputs(str(tmp_path), (fb.DECIDER_REL,))
               if r["path"] == fb.DECIDER_REL)
    assert row["measured"] is False, row
    assert row["sha256"] is None and row["reason"], row


def test_step_prints_the_finding_before_the_order_to_do_it_by_hand(tmp_path) -> None:
    """Тот же путь, каким шаг зовёт протокол: находка стоит ДО приказа «руками».

    Порядок — не косметика. Читатель, дошедший до слова «вручную» раньше, чем до
    «вердикт о прежнем предмете», уже встал и пошёл делать руками; ровно так
    цикл #471 и потратил первые минуты.
    """
    root = tmp_path
    (root / "data").mkdir(parents=True)
    (root / "architecture").mkdir(parents=True)
    # Конституция-фикстура: без неё шаг отказывается целиком (fail-CLOSED) и
    # тест судил бы об отказе разбора, а не о порядке строк.
    (root / "architecture" / "manifest.json").write_text(json.dumps({
        "agents": [], "artifacts": [{"path": f"data/{NAME}", "status": "active",
                                     "consumers": ["orchestrator_protocol"]}]}),
        encoding="utf-8")
    _decider(root)
    (root / "data" / NAME).write_text(
        json.dumps(_report(inputs=_inputs("0" * 64)), ensure_ascii=False),
        encoding="utf-8")

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = MOD.main(["--root", str(root), "--no-receipts"], now=NOW)
    out = buf.getvalue()

    assert rc == 0, out
    assert "ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ" in out, out
    assert "вручную" in out, out
    assert out.index("ВЕРДИКТ О ПРЕЖНЕМ ПРЕДМЕТЕ") < out.index("вручную"), out
