"""slo_proposal.py — две роли называют срок годности артефакта, каждая со своего вопроса.

Исполнение ADR-158 (решение владельца 28.08): срок назначают **Head of Investment** и
**Архитектор**, СОГЛАСОВЫВАЯ. Здесь обе роли выражены кодом, у каждой свой вопрос и свой
довод; модуль ничего не пишет в манифест — он готовит предложение человеку.

**Архитектор — «что физически возможно».** Агент не может держать файл свежее собственного
такта: просыпается раз в 6 часов — свежее 6 часов файл не бывает никогда. Отсюда НИЖНЯЯ
граница: такт × 2, то есть один пропущенный запуск не поднимает тревогу. Это ровно то правило,
по которому уже живёт `AGENT_OUTPUT_FILES` в `uptime_monitor.py` («≈2–3× интервала»), и оно
взято оттуда, а не придумано заново.

**Head of Investment — «через сколько молчание становится опасным».** Вопрос не про расписание,
а про цену опоздания, и она разная у файла с деньгами и у справочной таблички:

* артефакт читает money-path (`risk` / `governance` / `paper_trading` / стоп-кран) — ВЕРХНЯЯ
  граница жёсткая: устаревшие данные там двигают книгу;
* результат уезжает владельцу тревогой — сутки с запасом: молчание сторожа заметит человек;
* исследовательский контур — неделя: опоздание не стоит ничего.

**Согласование.** Годится любой срок между «возможно» (пол Архитектора) и «допустимо» (потолок
HoI). Берётся ПОТОЛОК: он реже поднимает ложную тревогу, а нижняя граница всё равно соблюдена.

**Несогласие — не повод усреднить.** Если пол выше потолка, значит агент физически не может
обеспечить свежесть, которой требует цена опоздания. Это НАХОДКА («расписание против цены»), а
не задача на арифметику: поле остаётся пустым, причина называется. Прямо по ADR-158.

LLM_FORBIDDEN. Только stdlib, ничего не пишет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]

AGREED = "agreed"
ALREADY = "already_curated"
CONTRADICTION = "schedule_vs_cost"
UNMEASURED = "unmeasured"

#: Модули, чтение которых означает money-path.
_MONEY = ("spa_core.risk", "spa_core.governance", "spa_core.paper_trading", "spa_core.execution")
_CADENCE = re.compile(r"interval:(\d+)s")


def cadence_hours(schedule: str | None) -> float | None:
    """Такт агента в часах. `None` — такта нет (демон/событие), судить нельзя."""
    if not schedule:
        return None
    m = _CADENCE.search(schedule)
    if m:
        return max(int(m.group(1)) / 3600.0, 0.0834)      # не мельче 5 минут
    if schedule.startswith("calendar:"):
        # Несколько отметок в сутки → такт = сутки / число отметок.
        marks = [t for t in schedule[len("calendar:"):].split(",") if t]
        return 24.0 / max(len(marks), 1)
    return None


#: Запас поверх такта. ВЫВЕДЕН, а не выбран: правило проверено на 35 парах
#: «такт → курированный человеком slo_hours» из манифеста. «такт + 2 ч» попадает ТОЧНО
#: в 19 из 35 (средняя ошибка 30 ч), «такт × 2» — НИ В ОДНО (ошибка 44 ч). Оно же
#: воспроизводит оба известных якоря: часовой агент → 3 ч (`agent_health`), суточный → 26 ч.
#: То есть у правила есть автор — люди, проставившие эти 35 значений; я его восстановил.
_MARGIN_HOURS = 2.0


def architect_floor(schedule: str | None) -> tuple[float | None, str]:
    """Нижняя граница: свежее собственного такта агент физически не бывает."""
    c = cadence_hours(schedule)
    if c is None:
        return None, f"такт не выводится из расписания {schedule!r} — судить не о чем"
    floor = round(max(c + _MARGIN_HOURS, 1.0), 2)
    return floor, (f"такт {c:g} ч ⇒ пол {floor:g} ч (такт + запас {_MARGIN_HOURS:g} ч на один "
                   f"пропуск; правило восстановлено по 35 курированным срокам, точных совпадений 19)")


def observed_floor(median_hours: float | None) -> tuple[float | None, str]:
    """Тот же пол, но от НАБЛЮДЁННОГО такта, а не от объявленного расписания.

    ``architect_floor`` выше спрашивает расписание — и расписание про такт ВРЁТ, что
    измерено: ADR-506 нашёл у ``com.spa.decision_loop`` объявленные ``interval:21600s``
    (6 ч) против наблюдённого такта 7,6 ч, потому что launchd отсчитывает
    ``StartInterval`` от ЗАВЕРШЕНИЯ прогона, а прогон идёт ~1 ч 40 мин. Пол, выведенный
    из объявления, в такой паре НИЖЕ физически возможного — то есть ровно та ошибка, от
    которой пол и должен защищать.

    **Запас тот же самый и взят отсюда же**, не выбран заново: меняется БАЗА (наблюдение
    вместо объявления), а не правило. Калибровка ``_MARGIN_HOURS`` шла по объявленным
    тактам, и это сказано вслух: запас есть запас, его переносимость на наблюдённую базу —
    допущение, а не замер.

    **Третий исход (инв. #17).** Такта не наблюдали ⇒ ``None`` с названной причиной.
    Подставить сюда объявленное расписание значило бы вернуть тот самый дефект, а ноль —
    соврать о скорости.
    """
    if median_hours is None:
        return None, ("наблюдённого такта нет — пол из объявленного расписания здесь НЕ "
                      "подставляется (ADR-506: объявление про такт врёт)")
    # `float()` здесь был бы МОЛЧАЛИВЫМ приведением: строка «7.3» прошла бы как
    # замер, то есть разбор чужой формы случился бы в месте, которое за разбор не
    # отвечает. Такт обязан прийти числом ОТ ПРИБОРА.
    if isinstance(median_hours, bool) or not isinstance(median_hours, (int, float)):
        return None, f"наблюдённый такт не число ({median_hours!r}) — судить не о чем"
    middle = float(median_hours)
    if middle <= 0:
        return None, f"наблюдённый такт не положителен ({middle:g} ч) — судить не о чем"
    floor = round(max(middle + _MARGIN_HOURS, 1.0), 2)
    return floor, (f"наблюдённая МЕДИАНА такта {middle:g} ч ⇒ пол {floor:g} ч "
                   f"(медиана + тот же запас {_MARGIN_HOURS:g} ч; база — наблюдение, не "
                   f"расписание, ADR-506)")


#: Вердикты вопроса «а курированный срок — выше пола?» (ADR-814). Это НЕ вердикты
#: `propose`: тот отвечает «какой срок назначить», этот — «не ниже ли уже назначенный
#: того, что физически возможно».
CURATED_ABOVE = "curated_above_floor"
CURATED_BELOW = "curated_below_floor_and_tact_breaks_it"
CURATED_MARGIN_ONLY = "curated_below_floor_but_tact_keeps_it"
CURATED_UNMEASURED = "curated_floor_unmeasured"


def audit_curated(declared_hours, floor: float | None,
                  median_hours: float | None = None) -> tuple[str, str]:
    """Вопрос, которого у :func:`propose` НЕТ ПО ПОСТРОЕНИЮ.

    ``propose`` при уже проставленном человеком сроке возвращает ``already_curated`` и
    **роли его не переназначают** — для СВОЕГО вопроса («какой срок назначить, если его
    нет») это верно и остаётся. Но из этого следует, что курированный срок НИЖЕ
    собственного пола модуля не может быть назван ни одной его строкой: пол считается,
    сравнивать его не с чем.

    Замер 26.10 на живой конституции: курированных пар «агент × артефакт» со сроком —
    **231**, из них **82** ниже пола, который даёт ``architect_floor`` по ОБЪЯВЛЕННОМУ
    расписанию. Ни об одной `propose` не сказал ничего — и это не промах реализации, а
    предел вопроса.

    **«Ниже пола» — ДВА разных состояния, и путать их значило бы повторить ADR-813
    на один этаж выше.** Запас ``_MARGIN_HOURS`` — КОНСТАНТА (2 ч), а такты агентов
    различаются на два порядка: у пятиминутного агента пол 2,08 ч требует срока в 25
    тактов, и ``data/resource_health.json`` (срок 0,5 ч, медиана 0,083 ч) оказывается
    «ниже пола», хотя обещание ДЕРЖИТ с запасом ×6. Это предел правила запаса, а не
    дефект срока, и лечится оно НЕ сроком. Поэтому состояния названы раздельно:

    ``CURATED_BELOW``
        срок ниже пола И наблюдённая медиана его ПРЕВЫШАЕТ — производитель
        демонстративно не способен держать обещание. Класс ADR-506, лечится сроком
        либо расписанием. Замер 26.10: **69** пар, все одна семья
        ``com.spa.decision_loop``.
    ``CURATED_MARGIN_ONLY``
        срок ниже пола, но медиана ВНУТРИ срока — такт обещание держит. Находка здесь
        принадлежит правилу запаса, не сроку. Замер 26.10: **9** пар.
    ``CURATED_ABOVE``
        срок не ниже пола.
    ``CURATED_UNMEASURED``
        третий исход (инв. #17): пол не выведен, и причина названа.

    Медиана не передана ⇒ различить два состояния НЕЧЕМ, и это ``CURATED_UNMEASURED``,
    а не «превышает»: подставить сюда «да» значило бы выдумать замер.
    """
    if floor is None:
        return CURATED_UNMEASURED, "пол не выведен — сравнивать не с чем"
    if isinstance(declared_hours, bool) or not isinstance(declared_hours, (int, float)):
        return CURATED_UNMEASURED, f"курированный срок не число ({declared_hours!r})"
    declared = float(declared_hours)
    if declared >= floor:
        return CURATED_ABOVE, f"курированный срок {declared:g} ч не ниже пола {floor:g} ч"
    if median_hours is None:
        return CURATED_UNMEASURED, (
            f"курированный срок {declared:g} ч ниже пола {floor:g} ч, но медианы такта "
            f"нет — «обещание нарушено» от «запас правила велик» отличить НЕЧЕМ")
    if isinstance(median_hours, bool) or not isinstance(median_hours, (int, float)):
        return CURATED_UNMEASURED, f"наблюдённая медиана не число ({median_hours!r})"
    middle = float(median_hours)
    if middle > declared:
        return CURATED_BELOW, (f"курированный срок {declared:g} ч НИЖЕ пола {floor:g} ч, и "
                               f"медиана такта {middle:g} ч его ПРЕВЫШАЕТ — производитель "
                               f"обещание не держит")
    return CURATED_MARGIN_ONLY, (
        f"курированный срок {declared:g} ч ниже пола {floor:g} ч, но медиана такта "
        f"{middle:g} ч ВНУТРИ срока — обещание держится; ниже пола он из-за "
        f"КОНСТАНТНОГО запаса {_MARGIN_HOURS:g} ч, и сроком это не лечится")


def hoi_ceiling(readers: set[str], reaches_owner: bool) -> tuple[float | None, str]:
    """Верхняя граница: через сколько молчание становится опасным."""
    money = sorted(m for m in readers if m.startswith(_MONEY))
    if money:
        # ВНИМАНИЕ, проверено на двух случаях 29.08: близость к money-path — ПОДСКАЗКА,
        # а не приговор. Правило судит по тому, КТО читает, но срочность определяет то,
        # ЧТО читатель с этим делает, и это надо ПРОЧИТАТЬ:
        #   · `risk.scoring_engine` имеет СВОЙ TTL 2 ч и при устаревании уходит в нейтраль
        #     (`ANALYTICS_TTL_S`) — то есть деградирует безопасно, 3 ч ему не требуются;
        #   · `golive_checker` спрашивает «дайджест ушёл СЕГОДНЯ?» — вопрос по природе
        #     суточный, и 3 ч там бессмысленны.
        # Оба выглядели «расхождением ролей», пока читателя не прочитали. Поэтому потолок
        # money-path — повод ОТКРЫТЬ читателя, а не готовое число.
        return 3.0, (f"читает money-path ({', '.join(money[:2])}) — ПОДСКАЗКА, что данные "
                     f"срочные; подтвердить чтением потребителя (у него может быть свой TTL "
                     f"или суточный по природе вопрос)")
    if reaches_owner:
        return 26.0, "результат уезжает владельцу тревогой — молчание заметит человек за сутки"
    if readers:
        return 26.0, "продукт читает код вне money-path — сутки с запасом"
    return 168.0, "исследовательский контур, потребителя нет — опоздание не стоит ничего"


def reconcile(floor: float | None, ceiling: float | None) -> tuple[float | None, str]:
    if floor is None or ceiling is None:
        return None, UNMEASURED
    if floor > ceiling:
        return None, CONTRADICTION
    return ceiling, AGREED


def propose(label: str, repo: Path | None = None) -> dict:
    """Предложение по одному агенту. Никогда не бросает."""
    repo = repo or _REPO
    out = {"label": label, "verdict": UNMEASURED, "slo_hours": None,
           "architect": "", "head_of_investment": "", "artifacts": []}
    try:
        from spa_core.monitoring.artifact_consumers import code_readers, reaches_owner
        from spa_core.monitoring.artifact_contract import _entry_modules, declared_produces
        manifest = json.loads((repo / "architecture" / "manifest.json").read_text(encoding="utf-8"))
        entry = next((a for a in manifest["agents"] if a["label"] == label), None)
        module = _entry_modules(repo).get(label)
        if not entry or not module:
            out["note"] = "агента или его точки входа нет — судить не о чем"
            return out
        f = repo / (module.replace(".", "/") + ".py")
        declared = declared_produces(f) if f.is_file() else None
        if not declared:
            out["note"] = ("агент ничего не объявил (или объявил «ничего») — сроку не к чему "
                           "прикрепиться")
            return out
        arts = set(declared)
        curated = {p["artifact"]: p.get("slo_hours") for p in (entry.get("produces") or [])
                   if p.get("artifact") and p.get("slo_hours")}
        if curated and set(curated) >= arts:
            out.update(verdict="already_curated", artifacts=sorted(arts),
                       note=f"срок уже проставлен человеком ({curated}) — роли его НЕ переназначают")
            return out
        floor, why_a = architect_floor(entry.get("schedule"))
        readers = code_readers(arts, repo, exclude_module=module)
        ceiling, why_h = hoi_ceiling(readers, reaches_owner(module, repo))
        slo, verdict = reconcile(floor, ceiling)
        out.update(artifacts=sorted(arts), architect=why_a, head_of_investment=why_h,
                   floor=floor, ceiling=ceiling, slo_hours=slo, verdict=verdict)
        if verdict == CONTRADICTION:
            out["note"] = (f"РАСХОЖДЕНИЕ РОЛЕЙ: агент способен на {floor:g} ч, а цена опоздания "
                           f"требует {ceiling:g} ч. Это находка «расписание против цены», а не "
                           f"задача на среднее: поле остаётся пустым")
        return out
    except Exception as exc:                                # noqa: BLE001
        out["note"] = f"замер не состоялся: {exc}"
        return out


def main() -> int:
    import sys
    repo = _REPO
    manifest = json.loads((repo / "architecture" / "manifest.json").read_text(encoding="utf-8"))
    rows = [propose(a["label"], repo) for a in manifest["agents"]]
    agreed = [r for r in rows if r["verdict"] == AGREED]
    already = [r for r in rows if r["verdict"] == ALREADY]
    contra = [r for r in rows if r["verdict"] == CONTRADICTION]
    print(f"  агентов: {len(rows)}")
    print(f"  роли СОШЛИСЬ:        {len(agreed)}")
    print(f"  срок уже курирован:  {len(already)} (не переназначаем)")
    print(f"  роли РАЗОШЛИСЬ:      {len(contra)}")
    print(f"  судить не о чем:     {len(rows) - len(agreed) - len(contra) - len(already)}")
    if "--verbose" in sys.argv:
        for r in sorted(agreed, key=lambda x: x["slo_hours"]):
            print(f"\n  {r['label']}  →  {r['slo_hours']:g} ч")
            print(f"      архитектор: {r['architect']}")
            print(f"      HoI:        {r['head_of_investment']}")
        for r in contra:
            print(f"\n  ! {r['label']}: {r['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
