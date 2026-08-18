"""spa_core/tests/test_red_team_finding_loop.py — храповик над каналом «red_team → сверка → карточка».

Почему файл существует (замер 2026-08-18 по карточке `inbox-nahodka-petli-analitik-red-team-critical`,
`finding_key: gap:analyst_red:red_team`). Канал устроен так:

    threat_reactor → data/threat_reactor_status.json
      → RedTeamAgent.analyze() (posture)
        → data/investment_os/red_team.json
          → house_view_gap.compute_gaps() (`gap:analyst_red:<name>`, WARN)
            → findings_bridge → карточка «требует реакции»

Измерено три состояния этого канала, и они РАЗНЫЕ по смыслу — храповик не даёт им слипнуться:

  1. НАСТОЯЩАЯ тревога (симуляция атак нашла критику) обязана дойти до канала карточек;
  2. ОСЛЕПШИЙ аналитик (нет/протухли данные об угрозах) обязан отличаться от СПОКОЙНОГО рынка —
     это самая частая форма fail-OPEN в этом репозитории: «я ничего не вижу» на выходе выглядит
     как «всё тихо»;
  3. ЭХО нашей же остановки (`kill_switch_already_active`, разведка не наблюдала ничего) обязано
     доезжать до читателя НАЗВАННЫМ — иначе слово CRITICAL от разведки читается как «нашли врага».

Тесты НИЧЕГО не ослабляют и поведение не меняют: они закрепляют то, что система делает сегодня.
Отдельно измеренная асимметрия канала (наблюдённая угроза `threats_present` до канала карточек НЕ
доходит, а собственное эхо доходит) здесь СПЕЦИАЛЬНО не закрепляется: закреплять кривое — значит
узаконить его. Она вынесена решением владельцу (лестница постур пиннится #198).

PURE / sandbox / no LLM / время — вход (`now=`), литеральных дат нет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json

from spa_core.investment_os.agents.red_team import RedTeamAgent
from spa_core.monitoring import house_view_gap as H
from spa_core.tests._freshness import now_utc

#: Опорная точка — «сейчас», а не календарь. Все отметки строятся ОТ неё и она же передаётся в
#: сверку как `now=`: обе стороны закреплены относительно друг друга, литеральных дат нет, и
#: сдвиг календаря не имеет права красить этот файл (урок 2026-08-04, `tests/_freshness.py`).
NOW = now_utc()


def _seed(tmp_path, *, name, threats=None, clear=True, kill=False, critical=0, threat_file=True):
    tp = tmp_path / f"threat_{name}.json"
    ap = tmp_path / f"attack_{name}.json"
    if threat_file:
        tp.write_text(json.dumps({"ts": (NOW - dt.timedelta(hours=1)).isoformat(),
                                  "threats": threats or [], "clear": clear,
                                  "kill_switch_already_active": kill}))
    ap.write_text(json.dumps([{"timestamp": (NOW - dt.timedelta(hours=1)).timestamp(),
                               "critical_count": critical, "average_security_score": 72.0,
                               "most_vulnerable": "X"}]))
    return tp, ap


def _analyst(tmp_path, **kw):
    """Артефакт аналитика со свежей отметкой (возраст меряется от `NOW`, не от календаря)."""
    tp, ap = _seed(tmp_path, **kw)
    out = RedTeamAgent(threat_path=tp, attack_path=ap, data_dir=tmp_path, allow_llm=False).analyze()
    out["generated_at"] = (NOW - dt.timedelta(hours=1)).isoformat()
    return out


def _gap_report(payload):
    ages = {"analyst:red_team": H.snapshot_age(payload, "/sandbox/red_team.json", NOW)}
    return H.compute_gaps(None, None, None, None, {"red_team": payload}, NOW, ages=ages)


def _analyst_unchecked(report):
    return [u for u in report["unchecked"] if u.get("input") == "analyst:red_team"]


# ── 1. НАСТОЯЩАЯ тревога доходит ─────────────────────────────────────────────────────────────
def test_real_critical_from_attack_sim_still_reaches_the_card_channel(tmp_path):
    """Положительный контроль «тревога доходит»: критика симуляции атак — не наш след, а находка.

    Краснеет при мутации лестницы аналитика (убрать `critical_count > 0` из ветки CRITICAL) и при
    мутации сверки (убрать `analyst_red` / сузить `_RED_TOKENS`).
    """
    payload = _analyst(tmp_path, name="real", critical=2, kill=False, threats=[], clear=True)
    assert payload["posture"] == "CRITICAL"
    assert "attack_surface_critical" in payload["posture_reason"]

    rep = _gap_report(payload)
    keys = [g["key"] for g in rep["gaps"]]
    assert "gap:analyst_red:red_team" in keys, "настоящая CRITICAL перестала доходить до канала карточек"
    g = [g for g in rep["gaps"] if g["key"] == "gap:analyst_red:red_team"][0]
    assert g["severity"] == "WARN"
    assert "критические находки в симуляции атак" in g["message"], (
        "тревога дошла безымянной — читателю нечем отличить находку от эха")
    assert not _analyst_unchecked(rep), "настоящая находка не имеет права уехать в 'не измерено'"


# ── 2. «Я ОСЛЕП» ≠ «ВСЁ СПОКОЙНО» ────────────────────────────────────────────────────────────
def test_blind_analyst_is_byte_different_from_a_calm_market(tmp_path):
    """Ослепшая разведка и спокойный рынок обязаны давать РАЗНЫЙ выход сверки.

    Замер 17.08: они были БАЙТ-В-БАЙТ одинаковы (пустой список находок), и карточка закрывалась
    мостом как «починили», когда разведка просто ослепла. Краснеет, если убрать ветку
    `refused_himself` в `house_view_gap` ИЛИ если аналитик перестанет фейлиться закрыто
    (`UNKNOWN_CAUTIOUS` при пропавших данных об угрозах).
    """
    blind = _analyst(tmp_path, name="blind", threat_file=False)
    calm = _analyst(tmp_path, name="calm", threats=[], clear=True, kill=False, critical=0)

    assert blind["posture"] == "UNKNOWN_CAUTIOUS"      # отказ судить
    assert calm["posture"] == "NO_THREAT_OBSERVED"     # наблюдение спокойствия
    assert blind["posture"] != calm["posture"]

    r_blind, r_calm = _gap_report(blind), _gap_report(calm)

    def body(r):  # всё, что читает потребитель, кроме отметки времени прогона
        return json.dumps({k: r[k] for k in ("gaps", "unchecked", "counts")},
                          ensure_ascii=False, sort_keys=True)

    assert body(r_blind) != body(r_calm), (
        "ослепшая разведка неотличима от спокойного рынка — молчание читается как наблюдение")
    assert _analyst_unchecked(r_blind), "отказ аналитика судить не назван в unchecked"
    assert not _analyst_unchecked(r_calm), "спокойный рынок не имеет права выглядеть отказом"
    assert not r_blind["gaps"] and not r_calm["gaps"]  # ни один из двух не выдумывает находку


# ── 3. ЭХО собственной остановки доезжает НАЗВАННЫМ ──────────────────────────────────────────
def test_self_halt_echo_can_never_arrive_nameless(tmp_path):
    """Наша же остановка красит аналитика (лестница #198 сохранена) — но обязана быть НАЗВАНА.

    Это единственная защита читателя от того, чтобы принять наш собственный след за врага в
    периметре. Краснеет, если из сообщения находки убрать причину или выбросить код
    `kill_switch_already_active` из `_REASON_RU` в пользу молчания.
    """
    payload = _analyst(tmp_path, name="echo", threats=[], clear=True, kill=True, critical=0)
    assert payload["posture_reason"] == ["kill_switch_already_active"]

    rep = _gap_report(payload)
    g = [g for g in rep["gaps"] if g["key"] == "gap:analyst_red:red_team"]
    assert g, "эхо перестало быть видимым вовсе — это уже глушение, а не разрыв петли"
    assert "эхо нашего же выключателя" in g[0]["message"], (
        "CRITICAL от разведки доехал без причины — читается как «нашли врага»")
    assert g[0]["posture_reason"] == ["kill_switch_already_active"]
