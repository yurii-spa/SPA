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
        if abs(arts[path] - hours) > tolerance_hours:
            findings.append({"label": label, "verdict": THRESHOLD_MISMATCH, "artifact": path,
                             "manifest_hours": arts[path], "monitor_hours": hours,
                             "note": "один файл, два разных срока годности"})
    return {
        "manifest_agents": len(man),
        "monitor_agents": len(mon),
        "compared": compared,
        "findings": findings,
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
