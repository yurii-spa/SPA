"""ADR-066 Фаза 3 — у ЖИВОГО контура решений обязан быть тот, кто его зовёт.

Самый дорогой класс дефекта этого проекта — не «проверка неверна», а «проверку некому
звать». `fleet_parity_check` был исправен и молчал 597 часов, потому что вызывающего у
него не было; отчёты 12 аналитиков `io_*` месяцами писались в никуда по той же причине.
Контур C1/C2, забытый без вызывающего, воспроизвёл бы аварию в третий раз — и заметить
это было бы особенно трудно, потому что он молчит по построению, когда находок нет.

**Что здесь проверяется.** В ночь на 2026-08-06 Фазу 3 независимо сделали ДВЕ сессии.
Канонические имена (`spa_core/monitoring/house_view_gap.py`, `findings_bridge.py`,
`data/house_view_gap.json`) остались за той реализацией, которая **развёрнута и работает**
— агент `com.spa.decision_loop`. Вторая (цикл #125) сохранена рядом под именами `*_c125`
с отдельными файлами вывода и НИКЕМ не вызывается; выбор, что оставить насовсем, за
владельцем (карточка `owner-decision-nochyu-odnu-zadachu-sdelali-dvazhdy-moya`).
Поэтому тесты сторожат ЖИВУЮ цепочку, а не мою:

1. агент объявлен в конституции как `active` и производит артефакты со своим SLO;
2. его точка входа (bash-обёртка) существует и исполняема — режим 100644 у
   launchd-обёртки означает мёртвого агента с exit 126 и не виден ни по одному пульсу
   (авария 2026-08-04, `.claude/rules/deployment.md`);
3. модуль, который обёртка запускает, реально импортируется и имеет CLI-вход;
4. дневной цикл НЕ дублирует этот контур — два писателя за один
   `data/house_view_gap.json` затирали бы друг друга в разных схемах;
5. параллельная реализация действительно разведена по файлам вывода (никакого общего
   артефакта) — иначе «сохранена, не подключена» было бы неправдой.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CYCLE_SH = _REPO_ROOT / "scripts" / "run_daily_paper_cycle.sh"
_MANIFEST = _REPO_ROOT / "architecture" / "manifest.json"

LIVE_AGENT = "com.spa.decision_loop"
LIVE_PRODUCT = "data/house_view_gap.json"


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _agent(label: str) -> dict:
    return next(a for a in _manifest()["agents"] if a["label"] == label)


# ── 1–3: у живого контура есть вызывающий, и он способен стартовать ──────────

def test_live_decision_loop_is_declared_active_in_the_constitution():
    """Агент вне манифеста невидим сторожу B1 — ровно так `swarm_dwell` работал,
    не будучи объявленным, и этого никто не замечал."""
    a = _agent(LIVE_AGENT)
    assert a["intent"] == "active"
    assert "ADR-066" in a["governed_by"]
    assert a["schedule"], "у агента нет расписания — некому его звать"


def test_live_agent_declares_the_product_with_an_slo():
    """Продукт без SLO не протухает «официально»: `agent_registry.json` так молчал
    19 дней. Артефакт обязан быть объявлен и с обеих сторон."""
    produced = {p["artifact"]: p for p in _agent(LIVE_AGENT)["produces"]}
    assert LIVE_PRODUCT in produced
    assert produced[LIVE_PRODUCT]["slo_hours"] > 0
    art = next(a for a in _manifest()["artifacts"] if a["path"] == LIVE_PRODUCT)
    assert art["status"] == "active"
    assert art["producer"] == LIVE_AGENT


def test_live_agent_entrypoint_exists_and_is_executable():
    """Режим 100644 у launchd-обёртки = агент мёртв (exit 126), и ни один пульс этого
    не показывает. 2026-08-04 так молча умерли 67 агентов из 69."""
    program = _agent(LIVE_AGENT).get("program")
    assert program, "в манифесте не назван исполняемый файл агента"
    path = _REPO_ROOT / "scripts" / program
    assert path.is_file(), f"точки входа нет на диске: {path}"
    assert os.stat(path).st_mode & stat.S_IXUSR, f"{path}: нет бита исполнения"


def test_live_module_imports_and_has_a_cli_entry():
    """Импортируемость проверяется отдельно от «файл на месте»: deployment_drift
    показывал 0 дрейфа, пока импорты были сломаны (2026-08-03)."""
    from spa_core.monitoring import findings_bridge

    assert callable(getattr(findings_bridge, "main", None))


# ── 4–5: две реализации не спорят за один файл ──────────────────────────────

def test_daily_cycle_does_not_duplicate_the_live_loop():
    """Дневной цикл НЕ должен звать сверку/мост: это делает развёрнутый агент.
    Два писателя за один `data/house_view_gap.json` в разных схемах затирали бы
    друг друга, и потребитель читал бы то одну форму, то другую."""
    code = "\n".join(ln.split("#", 1)[0] for ln in
                     _CYCLE_SH.read_text(encoding="utf-8").splitlines())
    assert "house_view_gap" not in code
    assert "findings_to_cards" not in code
    assert "findings_bridge" not in code


def test_parallel_implementation_writes_only_its_own_files():
    """«Сохранена, но не подключена» обязано быть правдой в файлах, а не на словах:
    у параллельной версии ни одного общего артефакта с живой."""
    from spa_core.monitoring import findings_bridge_c125, house_view_gap_c125

    assert house_view_gap_c125.REPORT_PATH.endswith("house_view_gap_c125.json")
    assert findings_bridge_c125.REPORT_REL.endswith("findings_bridge_c125.json")
    assert findings_bridge_c125.STATE_REL.endswith("findings_bridge_c125_state.json")
    assert findings_bridge_c125.SOURCES["hvg"].endswith("house_view_gap_c125.json")
    assert LIVE_PRODUCT not in set(findings_bridge_c125.SOURCES.values())


def test_parallel_implementation_has_no_caller():
    """Если у неё вдруг появится вызывающий — это должно быть осознанным решением
    (и тогда этот тест меняют вместе с ним), а не случайно уехавшей строкой."""
    hits = []
    for base in ("scripts", "launchd"):
        for path in (_REPO_ROOT / base).rglob("*"):
            if path.is_file() and path.suffix in (".sh", ".plist", ".py"):
                text = path.read_text(encoding="utf-8", errors="ignore")
                if "_c125" in text:
                    hits.append(str(path.relative_to(_REPO_ROOT)))
    assert hits == [], f"у сохранённой-но-не-подключённой версии появился вызывающий: {hits}"
