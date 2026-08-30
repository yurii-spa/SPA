"""contract_manifest_parity.py — контракт в КОДЕ против контракта в МАНИФЕСТЕ.

Объявляя `PRODUCES` в модулях агентов (ADR-158), мы завели ТРЕТИЙ дом для одного факта
«что этот агент производит»: он теперь записан и в коде, и в `architecture/manifest.json`
(`produces[].artifact`). Ровно за это — «одно знание в двух домах» — 28.08 заведена карточка
про сроки свежести; было бы нечестно завести ту же болезнь самим и не поставить сверку.

**Она окупилась в первый запуск и первой находкой поймала АВТОРА этих объявлений:** декларация
`com.spa.daily_cycle`, выписанная утром из манифеста, к вечеру отстала от него на три артефакта —
манифест докурировали параллельные сессии. Дом разошёлся с домом за часы, а не за месяцы.

Сравнение идёт по ПОЛНЫМ путям, а не по базовым именам: обе стороны хранят путь целиком, и
двусмысленности `data/market_regime.json` против `data/investment_os/market_regime.json`
здесь нет (в `artifact_contract` она есть и там названа — сверка с КОДОМ имени каталога не знает).

Исходы:

* ``agrees``               — множества совпали;
* ``declared_not_in_manifest`` — код объявляет то, чего манифест не знает: артефакт живёт без
  SLO и без объявленного потребителя, то есть его никто не сторожит;
* ``manifest_not_declared``    — манифест знает то, чего код не объявляет: объявление отстало
  (случай `daily_cycle`) либо продукт производит не тот модуль, что считается точкой входа;
* ``not_compared``         — сопоставлять нечего (агент есть только в одном доме). Это СВОЙ
  исход, а не согласие: зелёный вердикт на пустом множестве — сторож, который не может сработать.

Ничего не пишет и никого не гасит. LLM_FORBIDDEN, только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

AGREES = "agrees"
DECLARED_NOT_IN_MANIFEST = "declared_not_in_manifest"
MANIFEST_NOT_DECLARED = "manifest_not_declared"
NOT_COMPARED = "not_compared"

_REPO = Path(__file__).resolve().parents[2]


def manifest_produces(manifest: dict) -> dict[str, set[str]]:
    """Что манифест считает продуктом каждого агента. ПУСТО — тоже ответ.

    Раньше агент без `produces` сюда не попадал вовсе, и пересечение домов его
    выбрасывало: объявление в коде оставалось НЕ СВЕРЕННЫМ НИ С ЧЕМ. Замер 29.08 —
    четыре таких (`apiserver`, `familyfund`, `rtmr_sense`, `telegram_bot`): все
    объявляют артефакты кодом, манифест о них не знает, и сверка молчала. Это в
    точности та находка, ради которой она написана («артефакт объявлен кодом, но
    манифест его не знает — он без SLO и без объявленного потребителя»), и фильтр
    её же и гасил. Агент, которого нет в манифесте ВООБЩЕ, по-прежнему не
    сопоставим — про него решения не принимали.
    """
    out: dict[str, set[str]] = {}
    for a in manifest.get("agents") or []:
        if not a.get("label"):
            continue
        out[a["label"]] = {p.get("artifact") for p in (a.get("produces") or [])
                           if p.get("artifact")}
    return out


def compare(declared: dict[str, set[str]], manifest: dict[str, set[str]]) -> dict:
    """Сверка двух домов. Агент, живущий лишь в одном, НЕ сопоставим — и так и сказано."""
    findings: list[dict] = []
    compared = 0
    for label in sorted(set(declared) & set(manifest)):
        compared += 1
        d, m = declared[label], manifest[label]
        if d == m:
            continue
        row: dict = {"label": label}
        only_d, only_m = sorted(d - m), sorted(m - d)
        if only_d:
            row["declared_only"] = only_d
        if only_m:
            row["manifest_only"] = only_m
        row["verdict"] = (DECLARED_NOT_IN_MANIFEST if only_d and not only_m
                          else MANIFEST_NOT_DECLARED if only_m and not only_d
                          else DECLARED_NOT_IN_MANIFEST)
        row["note"] = ("артефакт объявлен кодом, но манифест его не знает — он без SLO и без "
                       "объявленного потребителя" if only_d and not only_m else
                       "манифест знает продукт, которого нет в объявлении — объявление отстало "
                       "или пишет не точка входа" if only_m and not only_d else
                       "дома расходятся в обе стороны")
        findings.append(row)
    return {"compared": compared, "findings": findings,
            "verdict": (NOT_COMPARED if compared == 0
                        else AGREES if not findings else findings[0]["verdict"])}


def audit(manifest_path: Path | None = None, manifest: dict | None = None) -> dict:
    """`manifest` — УЖЕ СВЕДЁННЫЙ манифест вызывающего; читать свою копию с диска нельзя.

    Замер #431: курация (в т.ч. `produces`) живёт в git и берётся с `origin/main` —
    прод-дерево каталог `architecture/` при синхронизации НЕ получает, о чём сам сторож
    и предупреждает строкой B6. Но эта сверка читала манифест С ДИСКА вторым, независимым
    чтением, и потому судила ДРУГОЙ манифест, чем соседние B1/B2/B5 в том же прогоне.
    Следствие измерено на живой системе: курация четырёх агентов, доставленная на origin,
    не гасила находку в проде вовсе — «доставлено» и «работает» разошлись ровно на этом
    втором чтении.
    """
    from spa_core.monitoring.artifact_contract import _entry_modules, declared_produces
    if manifest is None:
        path = manifest_path or _REPO / "architecture" / "manifest.json"
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    decl: dict[str, set[str]] = {}
    for label, module in _entry_modules(_REPO).items():
        f = _REPO / (module.replace(".", "/") + ".py")
        d = declared_produces(f) if f.is_file() else None
        if d:
            decl[label] = set(d)
    return compare(decl, manifest_produces(manifest))


def main() -> int:
    r = audit()
    print(f"  сопоставимо (объявлено И есть в манифесте): {r['compared']}")
    if r["verdict"] == NOT_COMPARED:
        print("  СОПОСТАВЛЯТЬ НЕЧЕГО — это не «всё сошлось».")
        return 0
    if not r["findings"]:
        print("  дома сошлись полностью")
        return 0
    print(f"  РАСХОДЯТСЯ: {len(r['findings'])}")
    for f in r["findings"]:
        print(f"\n  {f['label']} — {f['note']}")
        for k in ("declared_only", "manifest_only"):
            if k in f:
                print(f"      {k}: {f[k]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
