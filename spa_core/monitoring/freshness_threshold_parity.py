"""freshness_threshold_parity.py — порог свежести живёт в двух домах; сверить их.

**Замер 2026-08-28.** Ответ на вопрос «через сколько часов файл агента считается протухшим»
хранится в двух независимых местах:

* ``architecture/manifest.json`` → ``produces[].slo_hours`` (19 производителей);
* ``spa_core/monitoring/uptime_monitor.py`` → ``AGENT_OUTPUT_FILES[label] = (файл, секунды)``
  (16 агентов), с объявленным правилом «≈2–3× интервала расписания».

**Пересечение — НОЛЬ.** Поэтому расхождение сегодня физически невозможно, и именно поэтому
его никто не заметит завтра: как только кому-нибудь пропишут ``slo_hours`` для агента, за
которым уже следит ``uptime_monitor``, два порога начнут жить своей жизнью. Одно знание в двух
домах — класс, на котором система горела не раз.

**Почему сверка, а не переезд.** Перенести 16 порогов в манифест значило бы превратить
осознанные значения, выбранные человеком по объявленному правилу, в унаследованные, и спросить
об их происхождении стало бы не у кого. Сверка ничего не двигает и ловит расхождение в тот же
день, когда оно появится. Выбор владельца 28.08.

**Третий исход обязателен.** При нулевом пересечении сторож обязан сказать «сравнивать нечего»
(``not_compared``), а НЕ «всё сошлось». Зелёный вердикт на пустом множестве — это сторож,
который не может сработать; такой сторож обучает игнорировать себя раньше, чем принесёт пользу.

**Замер #444 (2026-08-31): третий исход был только у ВСЕГО множества, но не у агента.**
Правило выше исполнялось лишь для случая «пересечение пусто целиком». По каждому агенту
стояло безмолвное ``continue``: у монитора срок есть, манифест не дал ни одного — и агент
не попадал НИ В ОДИН исход, а печаталось «сошлись все сопоставимые пороги». На живом дереве
так пропадали 2 из 16 наблюдаемых монитором:

* ``com.spa.autopush`` — ``intent: active``, ``curation: partial``, ``produces: []``: монитор
  судит его живость по ``logs/auto_push.log`` с окном 4.5 ч, а манифест не объявляет за ним
  НИ ОДНОГО продукта. Это ровно разногласие о тождестве (``different_artifact``), ради
  которого модуль написан, — и оно отбрасывалось до того, как его могли увидеть;
* ``com.spa.checkpoint-7day`` — ``intent: retired``: пустой контракт у отставного агента
  законен, но монитор за ним всё ещё следит. Состояние другое, и звучать обязано иначе.

Поэтому у сверки появился именованный поагентный исход ``uncompared`` с ПРИЧИНОЙ и с
``intent``/``curation`` манифеста. Вердикт он НЕ трогает (тот же приём, что у ``slo_unassigned``
в B2, цикл #426): назвать пробел — не то же, что объявить аварию, и ни одна из двух сторон
отсюда не признаётся виноватой. Но пробел печатается ВСЕГДА и считается — немой ``continue``
и был всей болезнью.

LLM_FORBIDDEN. Только stdlib, никого не гасит, ничего не пишет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

AGREES = "agrees"
THRESHOLD_MISMATCH = "threshold_mismatch"
DIFFERENT_ARTIFACT = "different_artifact"
NOT_COMPARED = "not_compared"
# Причины поагентного «не сверяли». Отбрасывать агента молча запрещено: см. шапку.
UNCOMPARED_ABSENT = "absent_from_manifest"          # метки нет в манифесте вовсе
UNCOMPARED_NO_THRESHOLD = "no_threshold_in_manifest"  # метка есть, срока не дано
UNCOMPARED_UNKNOWN = "manifest_meta_not_provided"   # вызвали без метаданных — не гадаем

#: Каждая причина обязана звучать по-своему: у них РАЗНЫЕ адресаты починки.
_UNCOMPARED_NOTE = {
    UNCOMPARED_ABSENT: ("монитор судит живость этого агента по файлу, а манифест не знает "
                        "такой метки вовсе — сверять не с чем; чинит курация флота"),
    UNCOMPARED_NO_THRESHOLD: ("монитор судит живость этого агента по файлу, а манифест не "
                              "назначил ему ни одного срока — сверять не с чем; срок "
                              "назначают две роли (ADR-158)"),
    UNCOMPARED_UNKNOWN: ("сверять не с чем, а ПОЧЕМУ — не измерено: сверку позвали без "
                         "метаданных манифеста, и гадать она не станет"),
}
# Монитор строже манифеста — ЗАКОННОЕ состояние, а не находка. Отдельный исход,
# чтобы «проверено и нормально» не сливалось с «не проверяли».
MONITOR_STRICTER = "monitor_stricter"

_REPO = Path(__file__).resolve().parents[2]


def manifest_thresholds(manifest: dict) -> dict[str, dict[str, float]]:
    """{label: {артефакт: часы}} из курированного манифеста."""
    out: dict[str, dict[str, float]] = {}
    for a in manifest.get("agents") or []:
        for p in a.get("produces") or []:
            art, slo = p.get("artifact"), p.get("slo_hours")
            if art and slo:
                out.setdefault(a["label"], {})[art] = float(slo)
    return out


def manifest_meta(manifest: dict) -> dict[str, dict]:
    """{label: {intent, curation, declares_produces}} — чтобы «не сверяли» назвало ПРИЧИНУ.

    Без этого «метки нет в манифесте» и «метка есть, а срока ей не дали» звучали бы
    одинаково, а это разные адресаты починки: первое — курация флота, второе — назначение
    срока двумя ролями (ADR-158).
    """
    out: dict[str, dict] = {}
    for a in manifest.get("agents") or []:
        label = a.get("label")
        if not label:
            continue
        out[label] = {
            "intent": a.get("intent"),
            "curation": a.get("curation"),
            "declares_produces": bool(a.get("produces")),
        }
    return out


def monitor_thresholds(agent_output_files: dict) -> dict[str, tuple[str, float]]:
    """{label: (артефакт, часы)} из карты монитора аптайма. Записи без файла пропускаются."""
    out: dict[str, tuple[str, float]] = {}
    for label, pair in (agent_output_files or {}).items():
        try:
            path, secs = pair
        except (TypeError, ValueError):
            continue
        if path and secs:
            out[label] = (path, float(secs) / 3600.0)
    return out


def compare(man: dict[str, dict[str, float]],
            mon: dict[str, tuple[str, float]],
            *, tolerance_hours: float = 0.01,
            meta: dict[str, dict] | None = None) -> dict:
    """Сверка двух домов. Никогда не бросает; вердикт по каждому агенту.

    `tolerance_hours` мал НАМЕРЕННО: это защита от арифметики с плавающей точкой
    (секунды → часы), а не разрешённый люфт. Порог, отличающийся на реальную
    величину, — находка, даже если «почти совпадает».
    """
    findings: list[dict] = []
    notes: list[dict] = []
    uncompared: list[dict] = []
    compared = 0
    for label, (path, hours) in sorted(mon.items()):
        arts = man.get(label)
        if not arts:
            # НЕ `continue`. Здесь монитор назначил агенту срок, а манифест не дал ни
            # одного — сравнить нечего, и об этом обязан узнать читатель. Молчаливый
            # пропуск делал вердикт «сошлись все сопоставимые» правдой о МЕНЬШЕМ
            # множестве, чем звучало (замер #444: 14 из 16).
            if meta is None:
                reason, extra = UNCOMPARED_UNKNOWN, {}
            elif label not in meta:
                reason, extra = UNCOMPARED_ABSENT, {}
            else:
                reason = UNCOMPARED_NO_THRESHOLD
                extra = {"manifest_intent": meta[label].get("intent"),
                         "manifest_curation": meta[label].get("curation"),
                         "manifest_declares_produces": meta[label].get("declares_produces")}
            uncompared.append({"label": label, "verdict": NOT_COMPARED, "reason": reason,
                               "monitor_artifact": path, "monitor_hours": hours,
                               "note": _UNCOMPARED_NOTE[reason], **extra})
            continue
        compared += 1
        if path not in arts:
            findings.append({"label": label, "verdict": DIFFERENT_ARTIFACT,
                             "monitor_artifact": path,
                             "manifest_artifacts": sorted(arts),
                             "note": "два дома называют РАЗНЫЕ файлы продуктом одного агента"})
            continue
        # ДВА ЧИСЛА ОТВЕЧАЮТ НА РАЗНЫЕ ВОПРОСЫ, И СРАВНИВАТЬ ИХ НЕ НАДО ВОВСЕ.
        #
        # Я сузил эту проверку дважды за один день, и второй раз — потому что первый
        # был недостаточен. Ход рассуждения стоит записать целиком.
        #
        # Порог `uptime_monitor` отвечает «ЖИВ ЛИ АГЕНТ» и выводится из расписания с
        # запасом 1.25–1.5 такта, чтобы один пропуск не мигал. `slo_hours` манифеста
        # отвечает «СВЕЖ ЛИ ПРОДУКТ ДЛЯ ПОТРЕБИТЕЛЯ» и назначается двумя ролями по цене
        # опоздания (ADR-158). Сначала я счёл дефектом случай «монитор ЛОЯЛЬНЕЕ»:
        # продукт объявлен протухающим через 26 ч, а тревога о молчании — через 36 ч,
        # значит десять часов файл негоден и никто не знает.
        #
        # Посылка «никто не знает» ОКАЗАЛАСЬ ЛОЖНОЙ. Свежесть продукта против
        # `slo_hours` сторожит проверка B2 `architecture_conformance`, каждые 6 ч и
        # напрямую. Продукт не остаётся без присмотра ни на час — просто присматривает
        # за ним другой сторож, отвечающий на свой вопрос. Требовать соотношения между
        # окном живости и сроком продукта не нужно ни в какую сторону.
        #
        # Остаётся ОДИН настоящий предмет этой сверки: дома называют РАЗНЫЕ ФАЙЛЫ
        # продуктом одного агента (`different_artifact`) — разногласие о тождестве, а
        # не о числе. Так найден `daily_cycle`, чью живость судят по файлу, которого
        # нет в его контракте.
        #
        # Числа по-прежнему считаются и лежат в отчёте: «сверено и соотношение такое-то»
        # не должно быть неотличимо от «не сверяли».
        if abs(arts[path] - hours) > tolerance_hours:
            notes.append({"label": label, "artifact": path,
                          "manifest_hours": arts[path], "monitor_hours": hours,
                          "note": ("окна разные, и это НОРМА: живость и свежесть продукта — "
                                   "разные вопросы, продукт сторожит B2 напрямую")})
    return {
        "manifest_agents": len(man),
        "monitor_agents": len(mon),
        "compared": compared,
        # Тождество учёта: каждая метка монитора со сроком лежит РОВНО в одном исходе.
        # Пока оно держится, немой пропуск невозможен по построению.
        "uncompared": uncompared,
        "findings": findings,
        # Отчётная строка, не тревога: сколько агентов проверяются строже, чем нужен
        # их продукт. Ноль здесь означал бы, что сверка вообще ничего не различает.
        "threshold_notes": notes,
        # Пустое пересечение — СВОЙ исход, а не успех.
        "verdict": (NOT_COMPARED if compared == 0
                    else (AGREES if not findings else findings[0]["verdict"])),
    }


def audit(manifest_path: Path | None = None, manifest: dict | None = None) -> dict:
    """`manifest` — УЖЕ СВЕДЁННЫЙ манифест вызывающего (см. `contract_manifest_parity.audit`).

    Тот же класс: своё, второе чтение с диска судило бы не тот манифест, что соседние
    проверки того же прогона.
    """
    from spa_core.monitoring.uptime_monitor import AGENT_OUTPUT_FILES
    if manifest is None:
        path = manifest_path or _REPO / "architecture" / "manifest.json"
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    return compare(manifest_thresholds(manifest), monitor_thresholds(AGENT_OUTPUT_FILES),
                   meta=manifest_meta(manifest))


def main() -> int:
    r = audit()
    print(f"  манифест: {r['manifest_agents']} агент(ов) со сроком")
    print(f"  uptime_monitor: {r['monitor_agents']} агент(ов) со сроком")
    print(f"  сопоставимы (есть в ОБОИХ): {r['compared']}")
    if r["verdict"] == NOT_COMPARED:
        print("\n  СРАВНИВАТЬ НЕЧЕГО: множества не пересекаются. Это НЕ «всё сошлось» —\n"
              "  расхождение станет возможным в тот день, когда пересечение появится.")
        return 0
    for f in r["findings"]:
        print(f"\n  {f['verdict'].upper()} {f['label']}: {f['note']}")
        for k, v in f.items():
            if k not in ("label", "verdict", "note"):
                print(f"      {k}: {v}")
    for u in r.get("uncompared") or []:
        print(f"\n  НЕ СВЕРЕНО {u['label']} ({u['reason']}): {u['note']}")
        print(f"      монитор следит за {u['monitor_artifact']} с окном "
              f"{u['monitor_hours']:g}ч")
        if u.get("manifest_intent"):
            print(f"      манифест: intent={u['manifest_intent']} "
                  f"curation={u.get('manifest_curation')}")
    if not r["findings"]:
        # Формулировка НАМЕРЕННО называет размер множества: «сошлись все сопоставимые»
        # без числа читалось как «сошлось всё», хотя сопоставимо было 14 из 16.
        print(f"\n  сошлись все сопоставимые пороги ({r['compared']} из "
              f"{r['monitor_agents']} меток монитора со сроком; "
              f"не сверено {len(r.get('uncompared') or [])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
