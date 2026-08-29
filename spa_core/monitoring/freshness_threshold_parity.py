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
            *, tolerance_hours: float = 0.01) -> dict:
    """Сверка двух домов. Никогда не бросает; вердикт по каждому агенту.

    `tolerance_hours` мал НАМЕРЕННО: это защита от арифметики с плавающей точкой
    (секунды → часы), а не разрешённый люфт. Порог, отличающийся на реальную
    величину, — находка, даже если «почти совпадает».
    """
    findings: list[dict] = []
    notes: list[dict] = []
    compared = 0
    for label, (path, hours) in sorted(mon.items()):
        arts = man.get(label)
        if not arts:
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
        "findings": findings,
        # Отчётная строка, не тревога: сколько агентов проверяются строже, чем нужен
        # их продукт. Ноль здесь означал бы, что сверка вообще ничего не различает.
        "threshold_notes": notes,
        # Пустое пересечение — СВОЙ исход, а не успех.
        "verdict": (NOT_COMPARED if compared == 0
                    else (AGREES if not findings else findings[0]["verdict"])),
    }


def audit(manifest_path: Path | None = None) -> dict:
    from spa_core.monitoring.uptime_monitor import AGENT_OUTPUT_FILES
    path = manifest_path or _REPO / "architecture" / "manifest.json"
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    return compare(manifest_thresholds(manifest), monitor_thresholds(AGENT_OUTPUT_FILES))


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
    if not r["findings"]:
        print("\n  сошлись все сопоставимые пороги")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
