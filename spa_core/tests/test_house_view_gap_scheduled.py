"""ADR-066 C1/C2 — контур обязан БЫТЬ ПОЗВАН, а его продукты обязаны быть в конституции.

Самый дорогой класс дефекта этого проекта — не «проверка неверна», а «проверку некому
звать». `fleet_parity_check` был исправен и молчал 597 часов, потому что ни одного
вызывающего у него не было (карточка `agent-fleet-parity-guard-never-scheduled`);
отчёты 12 аналитиков `io_*` месяцами писались в никуда ровно по той же причине. Мост
находка→карточка, забытый в дневном цикле, воспроизвёл бы ту же аварию в третий раз —
и её было бы особенно трудно заметить, потому что он молчит по построению, когда
находок нет.

Поэтому здесь проверяется не логика (для неё есть `test_house_view_gap.py` и
`test_findings_to_cards.py`), а три факта доставки:

1. дневной цикл реально зовёт сверку C1 и мост C2 — **не в комментарии**;
2. продукты обоих объявлены в `architecture/manifest.json` со своим SLO, то есть
   их протухание становится находкой сторожа B2, а не археологией;
3. оркестраторский шаг 0-офис реально их читает — они объявлены потребляемыми
   `orchestrator_protocol`, и `consume_office_reports.py` берёт список ИЗ манифеста.
"""
from __future__ import annotations

import json
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CYCLE_SH = _REPO_ROOT / "scripts" / "run_daily_paper_cycle.sh"
_MANIFEST = _REPO_ROOT / "architecture" / "manifest.json"

C1_PRODUCT = "data/house_view_gap.json"
C2_PRODUCT = "data/findings_bridge.json"
DAILY_CYCLE = "com.spa.daily_cycle"


def _cycle_code_lines() -> list[str]:
    """Строки раннера без shell-комментариев: упоминание в комментарии вызовом не является."""
    text = _CYCLE_SH.read_text(encoding="utf-8")
    return [ln.split("#", 1)[0] for ln in text.splitlines() if ln.split("#", 1)[0].strip()]


def test_daily_cycle_invokes_house_view_gap():
    """Уберите шаг — тест краснеет. Без него сверка офис↔книга не выполняется НИКОГДА,
    а её отчёт молча протухает."""
    code = "\n".join(_cycle_code_lines())
    assert "spa_core.monitoring.house_view_gap" in code


def test_daily_cycle_invokes_the_findings_bridge_with_apply():
    """Мост без `--apply` — это красивый отчёт и пустая очередь: по умолчанию он
    НИЧЕГО не мутирует (fail-safe). В цикле флаг обязателен, иначе находки снова
    остаются в JSON, который никто не обязан открывать."""
    lines = _cycle_code_lines()
    calls = [ln for ln in lines if "findings_to_cards.py" in ln]
    assert calls, "мост находка→карточка не вызывается дневным циклом"
    assert any("--apply" in ln for ln in calls)


def test_cycle_steps_are_non_fatal():
    """Ни сверка, ни мост не смеют валить дневной цикл: находка — это находка,
    а не сломанный цикл (тот же принцип, что у Step 4)."""
    text = _CYCLE_SH.read_text(encoding="utf-8")
    for needle in ("spa_core.monitoring.house_view_gap", "findings_to_cards.py"):
        idx = text.index(needle)
        tail = text[idx:idx + 400]
        assert "||" in tail, f"{needle}: нет не-фатальной ветки — падение уронит цикл"


def _manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def test_new_products_are_declared_in_the_constitution():
    """Продукт вне манифеста невидим сторожу B2 — ровно так `agent_registry.json`
    протухал 19 дней и этого никто не заметил."""
    m = _manifest()
    by_path = {a["path"]: a for a in m["artifacts"]}
    for path in (C1_PRODUCT, C2_PRODUCT):
        assert path in by_path, f"{path} не объявлен в architecture/manifest.json"
        art = by_path[path]
        assert art["status"] == "active"
        assert art["producer"] == DAILY_CYCLE
        assert art["slo_hours"] > 0


def test_producer_declares_the_new_products():
    """Обе стороны манифеста должны сходиться: артефакт называет продюсера, продюсер —
    артефакт. Односторонняя запись — это дрейф, который B1/B5 обязаны видеть."""
    m = _manifest()
    agent = next(a for a in m["agents"] if a["label"] == DAILY_CYCLE)
    produced = {p["artifact"] for p in agent["produces"]}
    assert {C1_PRODUCT, C2_PRODUCT} <= produced
    assert "ADR-066" in agent["governed_by"]


def test_orchestrator_step_zero_consumes_both_reports():
    """Шаг 0-офис ведом манифестом: артефакт с потребителем `orchestrator_protocol`
    попадает в контекст сессии и получает квитанцию. Без этого мы бы построили ещё
    один продукт без обязательного читателя — то самое, ради чего затеян ADR-066."""
    m = _manifest()
    by_path = {a["path"]: a for a in m["artifacts"]}
    for path in (C1_PRODUCT, C2_PRODUCT):
        assert "orchestrator_protocol" in by_path[path]["consumers"]


def test_step_zero_script_summarizes_both_reports():
    """Мало прочитать файл — сессия должна увидеть СУТЬ: вердикт и находки, а не
    строку «статус: ok». Generic-ветка спрятала бы расхождения в тишину."""
    src = (_REPO_ROOT / "scripts" / "consume_office_reports.py").read_text(encoding="utf-8")
    assert 'name == "house_view_gap.json"' in src
    assert 'name == "findings_bridge.json"' in src
