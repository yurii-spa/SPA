"""СОСТОЯНИЕ ключа доставки спрашивается у GitHub, а не у нашей записи (ADR-1094).

Каждый тест здесь — положительный контроль аварии 2026-11-24 (ADR-1093): единственный
`GITHUB_PAT_SPA` истёк, все три дороги к origin закрылись, а сторож срока в сборке,
снятой за 45 минут до смерти, сказал `WARNING "PAT rotation due soon: 2026-11-24
(0 days)"` — то есть ответил верно на свой вопрос («прошло ли 90 дней от даты, которую
мы сами записали») и ничего не сказал о нужном («принимает ли GitHub этот ключ»).
Замер той же аварии: в `scripts/pat_rotation_helper.py` не было НИ ОДНОГО обращения к
API (`grep api.github|urlopen|Authorization|expiration` — 0 попаданий).

# FROZEN-DATE-OK: injected-clock — каждая литеральная дата здесь идёт В ПАРЕ с `now=`,
# отданным коду под проверкой (`_compute_status(state, now=…)`), и обе стороны
# сравнения выведены из ОДНОГО якоря `_ANCHOR`: срок получается прибавлением дней к
# нему же, а «сегодня» передаётся входом. Ни одно сравнение не идёт против
# `date.today()`, поэтому сдвиг календаря на вердикт не влияет — это преференция №1
# `.claude/rules/deployment.md`. Двери наружу (связка ключей и сеть) тоже входы
# (`secret_reader=`, `http_probe=`): настоящего мёртвого ключа для проверки не нужно.
"""

import json
import shutil
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import pat_rotation_helper as prh  # noqa: E402

from spa_core.monitoring import problem_store as ps  # noqa: E402
from spa_core.monitoring.system_health_monitor import (  # noqa: E402
    CRITICAL,
    OK,
    WARNING,
    SystemHealthMonitor,
)

#: Якорь сцены. Всё, что сравнивается, выведено ИЗ НЕГО и передано входом.
_ANCHOR = date(2026, 11, 24)

#: Токен сцены. Не секрет и секретом никогда не был: он существует только внутри
#: этого файла и служит ровно одному вопросу — «не утёк ли он в вывод».
_SCENE_TOKEN = "scene_token_1234567890_not_a_real_secret"


def _reader(secret=_SCENE_TOKEN, reason=None):
    """Дверь к связке ключей как ВХОД."""
    def _read(_service, runner=None):
        return secret, reason
    return _read


def _door(status, headers=None, failure=None):
    """Дверь к GitHub как ВХОД: отвечает ровно тем, что просит сцена."""
    def _probe(_token, _timeout=None):
        return status, (headers or {}), failure
    return _probe


def _state(days_until, state_file):
    """Состояние с заданным остатком до срока — ОТ ЯКОРЯ, не от настенных часов."""
    nxt = _ANCHOR + timedelta(days=days_until)
    doc = {"last_rotation": (nxt - timedelta(days=90)).isoformat(),
           "next_rotation": nxt.isoformat(),
           "keychain_service": prh.KEYCHAIN_SERVICE}
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(doc), encoding="utf-8")
    return doc


@pytest.fixture()
def tmp_state_file(tmp_path, monkeypatch):
    fake = tmp_path / "data" / "pat_rotation_state.json"
    monkeypatch.setattr(prh, "STATE_FILE", fake)
    return fake


# ── наблюдение само по себе ──────────────────────────────────────────────────

def test_four_oh_one_is_rejected_and_names_delivery_as_stopped():
    """ДОСЛОВНАЯ авария 24.11: GitHub отвечает 401 ⇒ `rejected`, и отказ назван."""
    got = prh.probe_token_liveness(secret_reader=_reader(), http_probe=_door(401))
    assert got["liveness"] == prh.TOKEN_REJECTED
    assert got["http_status"] == 401
    assert "401" in got["reason"] and "доставка" in got["reason"]


def test_two_hundred_is_alive():
    """Обратная сторона: сторож, кричащий ВСЕГДА, наблюдением не является."""
    got = prh.probe_token_liveness(secret_reader=_reader(), http_probe=_door(200))
    assert got["liveness"] == prh.TOKEN_ALIVE
    assert got["reason"] is None


def test_absent_key_dead_network_and_odd_answer_are_three_distinct_unmeasured():
    """Инв. #17: три разные нехватки наблюдения — три РАЗНЫЕ названные причины."""
    scenes = {
        "no_key": prh.probe_token_liveness(
            secret_reader=_reader(secret=None, reason="в связке нет записи"),
            http_probe=_door(200)),
        "no_net": prh.probe_token_liveness(
            secret_reader=_reader(),
            http_probe=_door(None, failure="сеть не ответила (URLError)")),
        "odd": prh.probe_token_liveness(
            secret_reader=_reader(), http_probe=_door(503)),
    }
    assert {s["liveness"] for s in scenes.values()} == {prh.TOKEN_UNMEASURED}
    reasons = [s["reason"] for s in scenes.values()]
    assert all(reasons) and len(set(reasons)) == 3, reasons
    # и ни одна причина не похожа на вердикт о принятии/отказе
    assert "НЕ ИЗМЕРЕНО" in scenes["odd"]["reason"]
    assert scenes["odd"]["http_status"] == 503


def test_the_keychain_cause_reaches_the_reason_not_just_the_kind():
    """Дыра покрытия, найденная МУТАЦИЕЙ M03 (#1239): род исхода (`unmeasured`) был
    закреплён, а ПРИЧИНА внутри него — нет, и мутация «склеить все причины в одну
    строку» выживала. «В связке нет записи», «нет самой `security` (не macOS)» и
    «запись пуста» требуют РАЗНЫХ действий; склеить их значило бы оставить читателю
    род без действия — то же «не измерено», только безадресное.
    """
    causes = [
        "в связке ключей нет записи с именем сервиса `GITHUB_PAT_SPA`",
        "команды `security` на этой машине нет (не macOS) — связка не наблюдаема отсюда",
        "запись `GITHUB_PAT_SPA` в связке ключей пуста",
    ]
    seen = []
    for cause in causes:
        got = prh.probe_token_liveness(
            secret_reader=_reader(secret=None, reason=cause), http_probe=_door(200))
        assert got["liveness"] == prh.TOKEN_UNMEASURED
        assert cause in got["reason"], got["reason"]
        seen.append(got["reason"])
    assert len(set(seen)) == 3, seen


def test_declared_expiration_comes_from_the_service_header_any_case():
    """Срок знает СЕРВИС. Заголовки регистронезависимы — спрашивать точным именем
    значило бы отвечать «срок не объявлен» от того, что сервер написал иначе."""
    for name in ("github-authentication-token-expiration",
                 "GitHub-Authentication-Token-Expiration"):
        got = prh.probe_token_liveness(
            secret_reader=_reader(),
            http_probe=_door(200, {name: "2027-02-22 19:48:26 UTC"}))
        assert got["declared_expiration"] == "2027-02-22", name
        assert got["declared_expiration_raw"] == "2027-02-22 19:48:26 UTC"


def test_unparseable_expiration_keeps_the_raw_and_refuses_to_invent_a_date():
    """«Сервер прислал непонятное» и «сервер не прислал ничего» — разные состояния."""
    got = prh.probe_token_liveness(
        secret_reader=_reader(),
        http_probe=_door(200, {prh.TOKEN_EXPIRATION_HEADER: "никогда"}))
    assert got["declared_expiration"] is None
    assert got["declared_expiration_raw"] == "никогда"
    silent = prh.probe_token_liveness(secret_reader=_reader(), http_probe=_door(200))
    assert silent["declared_expiration_raw"] is None


def test_record_against_declared_is_a_named_finding_not_a_silent_rewrite(tmp_state_file):
    """Расхождение нашей записи с объявленным сроком — НАХОДКА. Перезаписать запись
    значило бы стереть единственный след того, что наш календарь не про этот ключ."""
    before = json.dumps(_state(30, tmp_state_file), sort_keys=True)
    got = prh.probe_token_liveness(
        secret_reader=_reader(),
        http_probe=_door(200, {prh.TOKEN_EXPIRATION_HEADER: "2027-02-22 00:00:00 UTC"}),
        recorded_next_rotation=(_ANCHOR + timedelta(days=30)).isoformat())
    assert got["record_vs_declared"] == "differs"
    assert "расхождение" in got["record_vs_declared_detail"]
    assert json.dumps(json.loads(tmp_state_file.read_text()), sort_keys=True) == before

    agree = prh.probe_token_liveness(
        secret_reader=_reader(),
        http_probe=_door(200, {prh.TOKEN_EXPIRATION_HEADER: "2027-02-22 00:00:00 UTC"}),
        recorded_next_rotation="2027-02-22")
    assert agree["record_vs_declared"] == "agrees"


def test_no_comparison_key_when_there_was_nothing_to_compare():
    """Ключа-суждения нет вовсе, когда сравнивать не с чем: присутствующий и ложный
    ключ — ровно тот способ, которым «не измерено» читается как «совпало»."""
    got = prh.probe_token_liveness(secret_reader=_reader(), http_probe=_door(200))
    assert "record_vs_declared" not in got


def test_the_token_itself_never_leaves_the_probe(capsys):
    """Инв. #7: наружу уходят код ответа и срок, но НИКОГДА сам ключ."""
    got = prh.probe_token_liveness(secret_reader=_reader(), http_probe=_door(401))
    assert _SCENE_TOKEN not in json.dumps(got, ensure_ascii=False)
    prh.cmd_probe_token(got)
    assert _SCENE_TOKEN not in capsys.readouterr().out


# ── коды возврата и голос ────────────────────────────────────────────────────

def test_probe_token_has_three_exit_codes():
    """0 принят · 1 отклонён · 2 НЕ ИЗМЕРЕНО. Сеть легла и ключ мёртв обязаны
    выглядеть РАЗНО, иначе первое молча закроет тревогу о втором."""
    alive = prh.probe_token_liveness(secret_reader=_reader(), http_probe=_door(200))
    dead = prh.probe_token_liveness(secret_reader=_reader(), http_probe=_door(401))
    unknown = prh.probe_token_liveness(
        secret_reader=_reader(), http_probe=_door(None, failure="сеть не ответила"))
    assert (prh.cmd_probe_token(alive), prh.cmd_probe_token(dead),
            prh.cmd_probe_token(unknown)) == (0, 1, 2)


def test_check_prints_the_reason_for_every_nonzero_exit(tmp_state_file, capsys):
    """Молчаливый ненулевой код неотличим от упавшего интерпретатора (ADR-1093)."""
    assert prh.cmd_check(prh._compute_status(None, now=_ANCHOR)) == 1
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err

    overdue = prh._compute_status(_state(-2, tmp_state_file), now=_ANCHOR)
    assert prh.cmd_check(overdue) == 1
    assert "ПРОСРОЧЕНО" in capsys.readouterr().err

    soon = prh._compute_status(_state(10, tmp_state_file), now=_ANCHOR)
    assert prh.cmd_check(soon) == 1
    assert "СРОК БЛИЗКО" in capsys.readouterr().err

    fine = prh._compute_status(_state(60, tmp_state_file), now=_ANCHOR)
    assert prh.cmd_check(fine) == 0
    assert capsys.readouterr().err == ""


# ── лестница: авария ДО остановки доставки, а не после ───────────────────────

@pytest.mark.parametrize("days_until,critical", [
    (60, False), (14, False), (4, False), (3, True), (1, True), (0, True), (-1, True),
])
def test_critical_window_opens_before_the_deadline(tmp_state_file, days_until, critical):
    """24.11 срок был «сегодня» (0 дней) и вердикт был WARNING: CRITICAL приходил на
    СЛЕДУЮЩИЙ день, когда доставка уже стояла. Порог — трое суток ДО срока."""
    status = prh._compute_status(_state(days_until, tmp_state_file), now=_ANCHOR)
    assert status["days_until_rotation"] == days_until
    assert status["is_critical_window"] is critical


def test_the_day_of_the_outage_is_no_longer_a_mere_warning(tmp_state_file):
    """Дословный вердикт 24.11 — `(0 days)` — обязан быть аварией, а не девятым
    предупреждением из девяти."""
    status = prh._compute_status(_state(0, tmp_state_file), now=_ANCHOR)
    assert status["is_overdue"] is False          # срок ЕЩЁ не прошёл
    assert status["is_critical_window"] is True   # и это уже авария


def test_unknown_status_has_no_critical_window_key(tmp_state_file):
    """Новый ключ-суждение тоже отсутствует в статусе «не знаю» — иначе наивный
    `if status["is_critical_window"]` прочитал бы отсутствие как «спокойно»."""
    status = prh._compute_status(None, now=_ANCHOR)
    assert "is_critical_window" not in status


# ── сторож здоровья: проводка трёх исходов ───────────────────────────────────

_SCENE_OVERRIDE = '''

import os as _probe_os


def _read_keychain_secret(service, runner=None):  # noqa: F811
    if _probe_os.environ.get("SPA_TEST_PAT_SCENE") == "no_key":
        return None, "в связке ключей нет записи с именем сервиса"
    return "scene_token_not_a_real_secret", None


def _github_identity_probe(token, timeout=None):  # noqa: F811
    scene = _probe_os.environ.get("SPA_TEST_PAT_SCENE")
    if scene == "alive":
        return 200, {"github-authentication-token-expiration": "2027-02-22 19:48:26 UTC"}, None
    if scene == "rejected":
        return 401, {}, None
    if scene == "odd":
        return 503, {}, None
    return None, {}, "сеть не ответила (сцена теста)"
'''


def _scene_tree(tmp_path, *, with_liveness=True):
    """Дерево-сцена: НАСТОЯЩИЙ страж, у которого подменены только двери наружу."""
    root = tmp_path / "scene"
    (root / "scripts").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    src = (_PROJECT_ROOT / "scripts" / "pat_rotation_helper.py").read_text(encoding="utf-8")
    if not with_liveness:
        # Сцена «страж СТАРШЕ ADR-1094»: наблюдения о состоянии нет вовсе — ровно
        # то дерево, в котором 24.11 встала доставка.
        src = src.replace("def probe_token_liveness(", "def _removed_probe_token_liveness(")
    (root / "scripts" / "pat_rotation_helper.py").write_text(src + _SCENE_OVERRIDE,
                                                             encoding="utf-8")
    return root


@pytest.mark.parametrize("scene,expected", [
    ("rejected", CRITICAL), ("alive", OK), ("no_key", WARNING), ("odd", WARNING),
])
def test_health_check_maps_the_three_outcomes(tmp_path, monkeypatch, scene, expected):
    """Отклонённый ключ — АВАРИЯ (CRITICAL уходит в Telegram и в problem_store);
    не измерено — WARNING с названной причиной и НИКОГДА OK."""
    monkeypatch.setenv("SPA_TEST_PAT_SCENE", scene)
    root = _scene_tree(tmp_path)
    monitor = SystemHealthMonitor(project_root=root, data_dir=str(root / "data"))
    got = monitor._check_pat_token_alive("d5_code_integrity")
    assert got.status == expected, got.to_dict()
    if expected != OK:
        assert got.error, "непринятый ключ обязан нести названную причину"


def test_health_check_refuses_to_say_ok_about_a_guard_that_cannot_ask(tmp_path, monkeypatch):
    """Сцена дерева 24.11: у стража нет наблюдения о состоянии ⇒ WARNING с причиной,
    а не OK. «Сторож не умеет спросить» и «ключ в порядке» — разные ответы."""
    monkeypatch.setenv("SPA_TEST_PAT_SCENE", "alive")
    root = _scene_tree(tmp_path, with_liveness=False)
    monitor = SystemHealthMonitor(project_root=root, data_dir=str(root / "data"))
    got = monitor._check_pat_token_alive("d5_code_integrity")
    assert got.status == WARNING
    assert "probe_token_liveness" in (got.error or "")


def test_health_check_is_wired_into_the_domain(tmp_path, monkeypatch):
    """Проверка без вызывающего — ровно тот класс, против которого правило приёмки.

    Мерится ИСХОДОМ домена, а не подстрокой в исходнике: домен зовётся целиком, и
    вердикт о ключе обязан оказаться в его списке рядом с календарным.
    """
    monkeypatch.setenv("SPA_TEST_PAT_SCENE", "rejected")
    root = _scene_tree(tmp_path)
    monitor = SystemHealthMonitor(project_root=root, data_dir=str(root / "data"))
    results = monitor.check_d5_code_integrity()
    by_id = {r.id: r for r in results}
    assert "d5.security.pat_token_alive" in by_id, sorted(by_id)
    assert "d5.security.pat_rotation" in by_id, "календарный вопрос не заменён, а дополнен"
    assert by_id["d5.security.pat_token_alive"].status == CRITICAL


def test_mismatch_between_our_record_and_the_service_is_not_swallowed(tmp_path, monkeypatch):
    """Ключ принят, но наш календарь считает про другой срок — WARNING с причиной:
    зелёный вердикт здесь и был бы возвратом исходного дефекта."""
    monkeypatch.setenv("SPA_TEST_PAT_SCENE", "alive")
    root = _scene_tree(tmp_path)
    state = root / "data" / "pat_rotation_state.json"
    state.write_text(json.dumps({
        "last_rotation": "2026-08-26", "next_rotation": "2026-11-24",
        "keychain_service": prh.KEYCHAIN_SERVICE}), encoding="utf-8")
    # страж читает состояние относительно СВОЕГО дерева — положим его туда же
    monitor = SystemHealthMonitor(project_root=root, data_dir=str(root / "data"))
    got = monitor._check_pat_token_alive("d5_code_integrity")
    assert got.value == prh.TOKEN_ALIVE
    assert got.status == WARNING, got.to_dict()
    assert "2027-02-22" in (got.error or "") and "расхождение" in (got.error or "")
    assert got.evidence.get("record_vs_declared") == "differs"


# ── дорога до карточки ───────────────────────────────────────────────────────

def _health_doc(check_status):
    return {"domains": {"d5_code_integrity": {"status": check_status}},
            "checks": [{"id": "d5.security.pat_token_alive", "status": check_status,
                        "title": "GitHub REJECTS the delivery key",
                        "error": "GitHub ответил 401"}]}


def test_rejected_key_gets_its_own_problem_not_the_collapsed_one():
    """Свёрнутая `domains_degraded` открыта месяцами и новой карточки не заводит:
    авария, неотличимая от соседа, действием не является."""
    causes = [c["cause_code"] for c in ps._conditions_from_system_health(_health_doc("CRITICAL"))]
    assert "pat_token_rejected" in causes
    assert "domains_degraded" in causes, "свёртка владельца (RM-TRUTH-01) остаётся в силе"


def test_accepted_key_produces_no_such_problem():
    """Обратная сторона: условие, присутствующее ВСЕГДА, карточкой не управляет."""
    causes = [c["cause_code"] for c in ps._conditions_from_system_health(_health_doc("OK"))]
    assert "pat_token_rejected" not in causes


def test_doc_without_checks_is_not_read_as_a_healthy_key():
    """Нет `checks` ⇒ условия нет, и это НЕ «ключ в порядке»: о нём не наблюдали."""
    causes = [c["cause_code"] for c in ps._conditions_from_system_health(
        {"domains": {"d5_code_integrity": {"status": "WARNING"}}})]
    assert causes == ["domains_degraded"]


def test_the_rejected_key_reaches_an_open_problem_with_a_card_event():
    """Голос доходит до ДЕЙСТВИЯ: запись открывается и отдаёт событие, по которому
    `run_once` заводит карточку."""
    conditions = [c for c in ps._conditions_from_system_health(_health_doc("CRITICAL"))
                  if c["cause_code"] == "pat_token_rejected"]
    store, opened = {}, []
    for hour in (1, 2):
        store, events = ps.update_store(
            store, conditions, {ps.SOURCE_SYSTEM_HEALTH: {"status": "measured"}},
            now=datetime(_ANCHOR.year, _ANCHOR.month, _ANCHOR.day, hour,
                         tzinfo=timezone.utc))
        opened.extend(events)
    key = ps.problem_key("system_health", "pat_token_rejected")
    assert store["problems"][key]["status"] == ps.STATUS_OPEN
    assert any(e.key == key for e in opened)
    assert store["problems"][key]["severity"] == "CRITICAL"


# ── приёмка и границы ────────────────────────────────────────────────────────

def test_the_acceptance_probe_is_registered_and_satisfied():
    """Критерий карточки машинный и зарегистрирован (`.claude/rules/acceptance.md`)."""
    from spa_core.monitoring.card_acceptance import PROBES, SATISFIED
    assert "pat_token_state_is_asked_of_github" in PROBES
    status, detail = PROBES["pat_token_state_is_asked_of_github"](None)
    assert status == SATISFIED, detail


def test_status_and_check_still_never_touch_the_keychain(tmp_state_file, monkeypatch):
    """Граница MP-071 цела: читателю КАЛЕНДАРЯ секрет не нужен, и новый путь к связке
    её не открыл. Эта проверка — обратная сторона `probe_token_liveness`."""
    _state(60, tmp_state_file)
    called = []
    monkeypatch.setattr(prh, "_read_keychain_secret",
                        lambda *a, **k: called.append(a) or (None, "не должно быть"))
    assert prh.main(["--check"]) == 0
    assert prh.main(["--status"]) == 0
    assert called == [], "режим статуса полез в связку ключей"


def test_the_single_door_to_github_is_declared_in_the_guard():
    """Адрес и заголовок срока живут В ОДНОМ месте: своя копия у читателя означала
    бы, что сторож и доставка спрашивают о разном."""
    assert prh.TOKEN_PROBE_URL.startswith("https://api.github.com")
    assert prh.TOKEN_EXPIRATION_HEADER == "github-authentication-token-expiration"
    source = (_PROJECT_ROOT / "scripts" / "pat_rotation_helper.py").read_text(encoding="utf-8")
    assert source.count("api.github.com/user") == 1, "адрес размножен копией"
