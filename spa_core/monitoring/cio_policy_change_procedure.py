"""§48 ТЗ «Portfolio CIO» — исполняется ли процедура изменения Risk Policy.

Требование владельца дословно (карточка `inbox-100-zapuskov-na-odnom-snapshot`,
шард одного длинного ТЗ; целое — `inbox-task-portfolio-cio-dynamic-capital-alloc`):

    48. Изменения Risk Policy
    Если investigation покажет, что существующая Risk Policy блокирует разумную
    работу allocator: не ослаблять policy молча. Сформировать отдельный proposal:
    CURRENT RULE …

Текст ТЗ на этом обрывается — сообщение Telegram кончилось, продолжения списка
полей proposal'а в репозитории НЕТ (проверено по всем шардам). Поэтому меряется
то, что сказано ЦЕЛИКОМ, а недосказанное не додумывается: (1) «не ослаблять
молча» и (2) «сформировать отдельный proposal», где слово `CURRENT RULE` задаёт
единственное измеримое свойство — у правки обязано быть предъявимое **текущее
правило**, то есть ссылка, по которой его находят.

Предпосылка §48 сегодня ВЫПОЛНЕНА, и это не гипотеза: `shadow_trigger_evaluation`
третью неделю печатает `UNREACHABLE_UNTIL_CHANGED` — гейт `week_turnover_ok`
отказал на 20 из 20 существенных дней, «ожидание не изменит этого никогда».
То есть развилка §48 наступила, и вопрос «а как у нас вообще проходит правка
политики» перестал быть теоретическим.

Заказ цикла #515 назвал и ловушку: **«процедура описана» ≠ «процедура
исполняется»**, мерить по следам исполнения, а не по тексту документа. Поэтому
здесь нет ни одной проверки вида «в файле написано, что нужен ADR». Меряются
три следа, оставленные РЕАЛЬНЫМИ правками:

1. **Что фактически изменилось** — значения полей `RiskConfig` против
   замороженного снимка v1.0 (`spa_core/risk/versions/v1_0_passive.py`).
   Не проза `changelog`, а значения: `changelog` — ЗАЯВЛЕНИЕ, и расхождение
   заявления с замером само является находкой.
2. **Ослабление это или ужесточение** — по ОБЪЯВЛЕННОЙ полярности поля
   (`KNOB_POLARITY`). §48 запрещает молчаливое ОСЛАБЛЕНИЕ; новый потолок
   ужесточает и находкой не является. Полярность не выводится из имени:
   контракт ОБЪЯВЛЯЮТ, а не угадывают, и незнакомое поле даёт `UNMEASURED`,
   а не догадку.
3. **Есть ли proposal и находят ли его** — документ считается proposal'ом
   правки, только если он НАЗЫВАЕТ идентификатор поля (`max_total_t2_allocation`).
   Совпадение номера («ADR-019 упомянут в changelog») провенансом НЕ является:
   структурный признак ≠ провенанс. Дальше — вопрос достижимости: числится ли
   документ в каноническом реестре, по которому инструкция велит его искать.

## Что нашёл замер (07.09, цикл #516)

Домов у решений ДВА (`docs/adr/` 56 файлов и `docs/decisions/` 210), у каждого
свой индекс, и канонический индекс `docs/decisions/INDEX.md` называет себя
«единственным индексом, по которому находят ADR» (ADR-215, 02.09). Из 56
решений старого дома в каноническом реестре названо **одно**. Сторож
уникальности номера (`scripts/adr_number.py`) читает `DECISIONS_DIR` — то есть
ОДИН дом из двух, — поэтому номера 29/30/48/50/53 заняты дважды разными
решениями.

Бьёт это ровно по риск-контуру: единственное ОСЛАБЛЕНИЕ за всю историю политики
(`max_total_t2_allocation` 0.35 → 0.50) имеет настоящий proposal — ADR-019, он
называет поле дословно, — и этот proposal лежит в доме, которого нет в
каноническом реестре. А `docs/adr/ADR-053-tvl-floor-fail-closed.md` (решение о
`min_tvl_usd`, на которое ссылается `.claude/rules/risk-engine.md`) носит номер,
уже занятый принятым `docs/decisions/ADR-053-rtmr-sense-loop.md`.

ADVISORY. Модуль ничего не чинит и не двигает: ни один порог не меняется, ни
один файл решений не переносится. Перенос дома решений и правка порога — разные
вещи, и вторая — money-path и решение владельца.
"""

from __future__ import annotations

import ast
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPORT_REL = "data/cio_policy_change_procedure.json"

#: Файл действующей политики и её замороженный снимок.
POLICY_REL = "spa_core/risk/policy.py"
POLICY_CLASS = "RiskConfig"
SNAPSHOT_REL = "spa_core/risk/versions/v1_0_passive.py"
SNAPSHOT_CLASS = "_V1_0_RiskConfig"

#: Канонический реестр решений — тот, на который указывает CLAUDE.md.
CANON_INDEX_REL = "docs/decisions/INDEX.md"
#: Сторож уникальности номера решения.
NUMBER_GUARD_REL = "scripts/adr_number.py"

#: **Полярность порога ОБЪЯВЛЕНА, а не выведена.**
#:
#: «Больше — свободнее?» нельзя угадать по имени: у `max_concentration_t1`
#: рост потолка ослабляет, у `min_cash_pct` ослабляет СНИЖЕНИЕ, а
#: `var_horizon_days` не является ограничением вовсе. Ошибка здесь стоила бы
#: ложного «молчаливого ослабления» на ужесточении — то есть уверенного
#: неверного ответа, а не отказа. Незнакомое поле ⇒ `UNMEASURED`.
LOOSER_WHEN_HIGHER = "higher_is_looser"
LOOSER_WHEN_LOWER = "lower_is_looser"
NOT_A_LIMIT = "not_a_limit"

KNOB_POLARITY: dict[str, str] = {
    # потолки: поднять = пустить больше риска
    "max_concentration_t1": LOOSER_WHEN_HIGHER,
    "max_concentration_t2": LOOSER_WHEN_HIGHER,
    "max_single_protocol": LOOSER_WHEN_HIGHER,
    "max_apy_for_new_position": LOOSER_WHEN_HIGHER,
    "max_drawdown_stop": LOOSER_WHEN_HIGHER,
    "max_single_position_drawdown": LOOSER_WHEN_HIGHER,
    "max_var_pct": LOOSER_WHEN_HIGHER,
    "max_single_chain_allocation": LOOSER_WHEN_HIGHER,
    "max_l2_total_allocation": LOOSER_WHEN_HIGHER,
    "max_total_t2_allocation": LOOSER_WHEN_HIGHER,
    "max_total_t3_allocation": LOOSER_WHEN_HIGHER,
    "BASE_CHAIN_CAP": LOOSER_WHEN_HIGHER,
    "max_protocols": LOOSER_WHEN_HIGHER,
    # полы: опустить = пустить больше риска
    "min_apy_for_new_position": LOOSER_WHEN_LOWER,
    "min_tvl_usd": LOOSER_WHEN_LOWER,
    "min_cash_pct": LOOSER_WHEN_LOWER,
    "var_confidence": LOOSER_WHEN_LOWER,
    # не ограничения
    "version": NOT_A_LIMIT,
    "version_date": NOT_A_LIMIT,
    "changelog": NOT_A_LIMIT,
    "preferred_chains": NOT_A_LIMIT,
    "var_horizon_days": NOT_A_LIMIT,
}

_REF_RE = re.compile(r"\b(?:ADR|MP)[-_ ]?(\d{1,4})\b")


# ─── разбор объявленных порогов ──────────────────────────────────────────────

def _class_fields(path: Path, cls: str) -> tuple[dict[str, Any], str | None]:
    """Поля-с-умолчанием датакласса → (значения, причина отказа).

    Отказ разбора — ТРЕТИЙ исход с названной причиной, а не пустой словарь:
    пустота неотличима от «класса нет», и обе читались бы как «изменений нет».
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError) as exc:
        return {}, f"{path}: {exc.__class__.__name__}: {exc}"
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls:
            out: dict[str, Any] = {}
            for st in node.body:
                if (isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)
                        and st.value is not None):
                    try:
                        out[st.target.id] = ast.literal_eval(st.value)
                    except (ValueError, SyntaxError):
                        out[st.target.id] = "<expr>"
            if not out:
                return {}, f"{path}: класс `{cls}` найден, но полей с умолчанием нет"
            return out, None
    return {}, f"{path}: класс `{cls}` не найден"


def measure_knobs(root: Path) -> dict[str, Any]:
    """Что фактически изменилось в политике против замороженного снимка v1.0."""
    cur, cur_err = _class_fields(root / POLICY_REL, POLICY_CLASS)
    snap, snap_err = _class_fields(root / SNAPSHOT_REL, SNAPSHOT_CLASS)
    err = cur_err or snap_err

    knobs: dict[str, dict[str, Any]] = {}
    for name, now_val in cur.items():
        polarity = KNOB_POLARITY.get(name)
        entry: dict[str, Any] = {
            "current": now_val,
            "v1_0": snap.get(name, None),
            "in_snapshot": name in snap,
            "polarity": polarity,
        }
        if err:
            entry["verdict"] = "UNMEASURED"
            entry["why"] = f"разбор не удался: {err}"
        elif polarity is None:
            entry["verdict"] = "UNMEASURED"
            entry["why"] = (f"полярность поля `{name}` не объявлена в KNOB_POLARITY — "
                            "направление правки не измерено (догадка запрещена)")
        elif polarity == NOT_A_LIMIT:
            entry["verdict"] = "NOT_A_LIMIT"
        elif name not in snap:
            entry["verdict"] = "ADDED"
        elif snap[name] == now_val:
            entry["verdict"] = "UNCHANGED"
        else:
            try:
                higher = float(now_val) > float(snap[name])
            except (TypeError, ValueError):
                entry["verdict"] = "UNMEASURED"
                entry["why"] = "значения не сравнимы как числа"
                knobs[name] = entry
                continue
            looser = higher if polarity == LOOSER_WHEN_HIGHER else not higher
            entry["verdict"] = "RELAXED" if looser else "TIGHTENED"
        knobs[name] = entry

    return {"knobs": knobs, "error": err,
            "changelog": str(cur.get("changelog", "")),
            "snapshot_fields": len(snap), "current_fields": len(cur)}


# ─── дома решений и достижимость proposal'а ──────────────────────────────────

def find_homes(root: Path) -> list[str]:
    """Каталоги под `docs/`, в которых лежат файлы решений. Дом ищется, а не задан.

    Задать список домов константой значило бы ответить на вопрос замера
    заранее: ровно наличие ВТОРОГО дома и есть предмет.
    """
    homes: list[str] = []
    docs = root / "docs"
    if not docs.is_dir():
        return homes
    for d in sorted([docs] + [p for p in docs.iterdir() if p.is_dir()]):
        if any(p.name.startswith("ADR") and p.suffix == ".md" for p in d.iterdir()):
            homes.append(str(d.relative_to(root)))
    return homes


def _adr_files(root: Path, home: str) -> list[Path]:
    return sorted(p for p in (root / home).glob("ADR*.md") if p.is_file())


def _number_of(name: str) -> int | None:
    m = re.match(r"ADR[-_]0*(\d+)", name)
    return int(m.group(1)) if m else None


def measure_homes(root: Path) -> dict[str, Any]:
    """Дома решений, канонический реестр и коллизии номеров между домами."""
    homes = find_homes(root)
    canon_txt = ""
    canon_path = root / CANON_INDEX_REL
    if canon_path.is_file():
        canon_txt = canon_path.read_text(encoding="utf-8", errors="replace")

    per_home: dict[str, Any] = {}
    numbers: dict[str, set[int]] = {}
    for home in homes:
        files = _adr_files(root, home)
        listed = sum(1 for p in files if p.name in canon_txt)
        nums = {n for n in (_number_of(p.name) for p in files) if n is not None}
        numbers[home] = nums
        per_home[home] = {
            "files": len(files),
            "listed_in_canon_index": listed,
            "unlisted": len(files) - listed,
            "has_own_index": any((root / home).glob("*INDEX*.md")),
        }

    collisions: list[dict[str, Any]] = []
    hs = list(numbers)
    for i, a in enumerate(hs):
        for b in hs[i + 1:]:
            for n in sorted(numbers[a] & numbers[b]):
                collisions.append({
                    "number": n,
                    a: [p.name for p in _adr_files(root, a) if _number_of(p.name) == n],
                    b: [p.name for p in _adr_files(root, b) if _number_of(p.name) == n],
                })

    # какие дома читает сторож уникальности номера
    guard = root / NUMBER_GUARD_REL
    guard_homes, guard_why = [], None
    if guard.is_file():
        gtxt = guard.read_text(encoding="utf-8", errors="replace")
        for home in homes:
            if re.search(rf'["\']{re.escape(home)}["\']', gtxt):
                guard_homes.append(home)
        if not guard_homes:
            guard_why = (f"{NUMBER_GUARD_REL}: ни один дом не назван литералом — "
                         "охват сторожа не измерен")
    else:
        guard_why = f"{NUMBER_GUARD_REL} отсутствует — охват сторожа не измерен"

    return {"homes": per_home, "canon_index": CANON_INDEX_REL,
            "canon_index_present": canon_path.is_file(),
            "collisions": collisions,
            "number_guard": {"path": NUMBER_GUARD_REL, "reads_homes": guard_homes,
                             "homes_total": len(homes), "why": guard_why}}


def documents_naming(root: Path, field: str, homes: list[str],
                     canon_txt: str) -> list[dict[str, Any]]:
    """Документы, НАЗЫВАЮЩИЕ поле дословно. Это упоминание, а НЕ провенанс.

    Первая редакция этого модуля объявляла такой документ «proposal'ом» и на
    живом дереве выдала уверенный НЕВЕРНЫЙ ответ: у единственного ослабления
    (`max_total_t2_allocation`) нашлись два документа в каноническом реестре —
    ADR-131 и ADR-144, — и вердикт стал «proposal достижим». Оба поле лишь
    ЦИТИРУЮТ; правку 0.35 → 0.50 решал ADR-019, которого в реестре нет.
    Оба к тому же содержат и старое, и новое значение, поэтому «предъявляет
    переход» их тоже не отделяет. Структурный признак ≠ провенанс.

    Поэтому упоминания остаются в отчёте как справка, а вердикт §48 строится на
    СОБСТВЕННОМ признании политики — ссылках `RiskConfig.changelog`.
    """
    hits: list[dict[str, Any]] = []
    pat = re.compile(rf"\b{re.escape(field)}\b")
    for home in homes:
        for p in _adr_files(root, home):
            try:
                txt = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if pat.search(txt):
                hits.append({"home": home, "file": p.name,
                             "in_canon_index": p.name in canon_txt})
    return hits


def resolve_ref(root: Path, ref: str, homes: list[str],
                canon_txt: str) -> dict[str, Any]:
    """Куда разрешается ссылка вида ``ADR-019`` — по ВСЕМ домам решений."""
    num = re.match(r"(?:ADR|MP)[-_ ]?0*(\d+)", ref)
    n = int(num.group(1)) if num else None
    docs: list[dict[str, Any]] = []
    if n is not None and ref.upper().startswith("ADR"):
        for home in homes:
            for p in _adr_files(root, home):
                if _number_of(p.name) == n:
                    docs.append({"home": home, "file": p.name,
                                 "in_canon_index": p.name in canon_txt})
    reachable = [d for d in docs if d["in_canon_index"]]
    if not docs:
        verdict = "UNRESOLVED"
    elif reachable:
        verdict = "IN_CANON_INDEX"
    else:
        verdict = "OUTSIDE_CANON_INDEX"
    return {"ref": ref, "documents": docs, "verdict": verdict}


def changelog_refs(changelog: str) -> list[str]:
    """Ссылки, которыми политика САМА объясняет свои правки."""
    out: list[str] = []
    for m in re.finditer(r"\b(ADR|MP)[-_ ]?(\d{1,4})\b", changelog):
        ref = f"{m.group(1).upper()}-{int(m.group(2)):03d}"
        if ref not in out:
            out.append(ref)
    return out


def measure_proposals(root: Path, knobs: dict[str, Any],
                      homes_report: dict[str, Any],
                      changelog: str) -> dict[str, Any]:
    """Для каждой изменённой ручки — признаётся ли правка и находят ли её proposal.

    Вердикт строится на ссылках `changelog` (собственное признание политики),
    а не на том, кто поле упоминает: чью правку решал документ, по факту
    упоминания не установить.
    """
    homes = list(homes_report["homes"])
    canon_txt = ""
    canon = root / CANON_INDEX_REL
    if canon.is_file():
        canon_txt = canon.read_text(encoding="utf-8", errors="replace")

    refs = changelog_refs(changelog)
    resolved = {r: resolve_ref(root, r, homes, canon_txt) for r in refs}

    out: dict[str, Any] = {}
    for field, k in knobs.items():
        if k["verdict"] not in ("RELAXED", "TIGHTENED", "ADDED"):
            continue
        mentions = documents_naming(root, field, homes, canon_txt)
        if not refs:
            verdict = "NO_RECORD"
        elif any(resolved[r]["verdict"] == "IN_CANON_INDEX" for r in refs):
            verdict = "PROPOSAL_IN_CANON_INDEX"
        elif any(resolved[r]["verdict"] == "OUTSIDE_CANON_INDEX" for r in refs):
            verdict = "PROPOSAL_OUTSIDE_CANON_INDEX"
        else:
            verdict = "PROPOSAL_UNRESOLVED"
        out[field] = {"change": k["verdict"],
                      "declared_refs": refs,
                      "refs_resolved": resolved,
                      "mentioned_in": mentions,
                      "verdict": verdict}
    return out


# ─── положительный контроль ──────────────────────────────────────────────────

_CTRL_POLICY = (
    "from dataclasses import dataclass\n"
    "@dataclass\n"
    "class RiskConfig:\n"
    "    changelog: str = {changelog!r}\n"
    "    min_cash_pct: float = {cash}\n"
    "    max_concentration_t1: float = 0.40\n"
)
_CTRL_SNAP = (
    "from dataclasses import dataclass\n"
    "@dataclass\n"
    "class _V1_0_RiskConfig:\n"
    "    min_cash_pct: float = 0.05\n"
    "    max_concentration_t1: float = 0.40\n"
)


def _control_tree(base: Path, cash: float, proposal: str | None,
                  changelog: str = "") -> Path:
    (base / "spa_core/risk/versions").mkdir(parents=True, exist_ok=True)
    (base / "docs/decisions").mkdir(parents=True, exist_ok=True)
    (base / POLICY_REL).write_text(
        _CTRL_POLICY.format(cash=cash, changelog=changelog), encoding="utf-8")
    (base / SNAPSHOT_REL).write_text(_CTRL_SNAP, encoding="utf-8")
    idx = "# INDEX\n"
    if proposal:
        (base / "docs/decisions" / proposal).write_text(
            "# proposal\n\nСнижаем `min_cash_pct` с 0.05 до 0.01.\n", encoding="utf-8")
        idx += f"| ADR-900 | тест | Accepted | [x]({proposal}) |\n"
    (base / CANON_INDEX_REL).write_text(idx, encoding="utf-8")
    return base


def positive_control() -> dict[str, Any]:
    """Прибор ОБЯЗАН увидеть молчаливое ослабление — и НЕ увидеть его там, где решение достижимо.

    Половин три, и каждая управляет своим ответом. Одна половина была бы
    украшением: проверка, которая только «находит», проходит и у сторожа,
    который находит ВСЕГДА. Обратные половины отличаются ровно тем, чем должны:
    наличием разрешимой ссылки и направлением правки.
    """
    checks: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)

        def verdict(tree: Path) -> tuple[str | None, str]:
            m = measure_knobs(tree)
            h = measure_homes(tree)
            pr = measure_proposals(tree, m["knobs"], h, m["knobs"] and m["changelog"])
            return (pr.get("min_cash_pct", {}).get("verdict"),
                    m["knobs"]["min_cash_pct"]["verdict"])

        silent = _control_tree(base / "silent", 0.01, None, changelog="")
        got, change = verdict(silent)
        checks.append({"name": "ослабление без единой ссылки видно",
                       "expected": "NO_RECORD/RELAXED", "got": f"{got}/{change}",
                       "passed": got == "NO_RECORD" and change == "RELAXED"})

        reachable = _control_tree(base / "reachable", 0.01, "ADR-900-cash-buffer.md",
                                  changelog="ADR-900 (2026-01-01): снижен буфер")
        got, change = verdict(reachable)
        checks.append({"name": "ослабление с решением В РЕЕСТРЕ находкой НЕ является",
                       "expected": "PROPOSAL_IN_CANON_INDEX/RELAXED",
                       "got": f"{got}/{change}",
                       "passed": got == "PROPOSAL_IN_CANON_INDEX" and change == "RELAXED"})

        outside = _control_tree(base / "outside", 0.01, None,
                                changelog="ADR-900 (2026-01-01): снижен буфер")
        (outside / "docs/adr").mkdir(parents=True, exist_ok=True)
        (outside / "docs/adr/ADR-900-cash-buffer.md").write_text(
            "# proposal\n\nСнижаем `min_cash_pct`.\n", encoding="utf-8")
        got, change = verdict(outside)
        checks.append({"name": "решение ВНЕ реестра отличается от решения в реестре",
                       "expected": "PROPOSAL_OUTSIDE_CANON_INDEX/RELAXED",
                       "got": f"{got}/{change}",
                       "passed": got == "PROPOSAL_OUTSIDE_CANON_INDEX"
                       and change == "RELAXED"})

        tight = _control_tree(base / "tight", 0.20, None, changelog="")
        m3 = measure_knobs(tight)
        checks.append({"name": "ужесточение не объявляется ослаблением",
                       "expected": "TIGHTENED",
                       "got": m3["knobs"]["min_cash_pct"]["verdict"],
                       "passed": m3["knobs"]["min_cash_pct"]["verdict"] == "TIGHTENED"})

    return {"passed": all(c["passed"] for c in checks), "checks": checks}


# ─── находки ─────────────────────────────────────────────────────────────────

def _findings(meas: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    knobs = meas["knobs"]["knobs"]
    props = meas["proposals"]
    homes = meas["homes"]

    for field, p in sorted(props.items()):
        if p["change"] != "RELAXED":
            continue
        old, now = knobs[field]["v1_0"], knobs[field]["current"]
        if p["verdict"] in ("NO_RECORD", "PROPOSAL_UNRESOLVED"):
            out.append({"severity": "critical", "field": field,
                        "text": (f"`{field}` ОСЛАБЛЕН против снимка v1.0 "
                                 f"({old} → {now}), и политика не предъявляет ни "
                                 "одной разрешимой ссылки на решение — ровно то "
                                 "молчаливое ослабление, которое запрещает §48")})
        elif p["verdict"] == "PROPOSAL_OUTSIDE_CANON_INDEX":
            outside = sorted({f"{d['home']}/{d['file']}"
                              for r in p["refs_resolved"].values()
                              for d in r["documents"] if not d["in_canon_index"]})
            out.append({"severity": "warn", "field": field,
                        "text": (f"`{field}` ОСЛАБЛЕН ({old} → {now}); решение "
                                 f"существует ({', '.join(outside)}), но в "
                                 f"каноническом реестре `{CANON_INDEX_REL}` его НЕТ — "
                                 "CURRENT RULE не предъявить по пути, который "
                                 "называет инструкция")})

    for field, k in sorted(knobs.items()):
        if k["verdict"] == "UNMEASURED":
            out.append({"severity": "unchecked", "field": field,
                        "text": f"`{field}`: {k.get('why', 'не измерено')}"})

    guard = homes["number_guard"]
    if guard["why"]:
        out.append({"severity": "unchecked", "field": None, "text": guard["why"]})
    elif len(guard["reads_homes"]) < guard["homes_total"]:
        missed = [h for h in homes["homes"] if h not in guard["reads_homes"]]
        out.append({"severity": "warn", "field": None,
                    "text": (f"сторож уникальности номера читает "
                             f"{len(guard['reads_homes'])} дом(а) из "
                             f"{guard['homes_total']}: не читает {', '.join(missed)} — "
                             "номер решения выдаётся по одному дому из нескольких")})

    if homes["collisions"]:
        nums = ", ".join(f"ADR-{c['number']:03d}" for c in homes["collisions"])
        out.append({"severity": "warn", "field": None,
                    "text": (f"{len(homes['collisions'])} номер(ов) заняты дважды "
                             f"разными решениями ({nums}) — ссылка proposal'а "
                             "не разрешается однозначно")})

    for home, h in sorted(homes["homes"].items()):
        if h["unlisted"] and home != "docs/decisions":
            out.append({"severity": "warn", "field": None,
                        "text": (f"дом `{home}`: {h['unlisted']} из {h['files']} решений "
                                 f"не названы в `{CANON_INDEX_REL}` — по канону их "
                                 "не находят")})

    declared = meas["knobs"]["changelog"]
    changed = sorted(f for f, k in knobs.items()
                     if k["verdict"] in ("RELAXED", "TIGHTENED", "ADDED"))
    unnamed = [f for f in changed if f not in declared]
    if unnamed:
        out.append({"severity": "info", "field": None,
                    "text": (f"{len(unnamed)} из {len(changed)} изменённых полей не "
                             f"названы в `RiskConfig.changelog` ИДЕНТИФИКАТОРОМ "
                             f"({', '.join(unnamed)}); часть описана прозой "
                             "(«T2 cap 35%→50%»), поэтому это не «правка скрыта», а "
                             "«запись нельзя сверить с полем машинно»")})
    return out


def measure(root: Path) -> dict[str, Any]:
    knobs = measure_knobs(root)
    homes = measure_homes(root)
    props = measure_proposals(root, knobs["knobs"], homes, knobs["changelog"])
    return {"knobs": knobs, "homes": homes, "proposals": props}


def run(root: str | Path | None = None, *, write: bool = True,
        now: datetime | None = None) -> dict[str, Any]:
    """Собрать отчёт §48. ``now`` — ВХОД (правило о времени в тестах)."""
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    ts = (now or datetime.now(timezone.utc)).isoformat()

    control = positive_control()
    meas = measure(root)
    findings = _findings(meas)

    counts = {
        "critical": sum(1 for f in findings if f["severity"] == "critical"),
        "warn": sum(1 for f in findings if f["severity"] == "warn"),
        "info": sum(1 for f in findings if f["severity"] == "info"),
        "unchecked": sum(1 for f in findings if f["severity"] == "unchecked"),
    }
    if not control["passed"]:
        overall = "UNCHECKED"
    elif counts["critical"]:
        overall = "CRITICAL"
    elif counts["unchecked"]:
        overall = "UNCHECKED"
    elif counts["warn"]:
        overall = "WARN"
    else:
        overall = "OK"

    knobs = meas["knobs"]["knobs"]
    doc = {
        "schema": "cio_policy_change_procedure/v1",
        "generated_at": ts,
        "overall": overall,
        "counts": counts,
        "positive_control": control,
        "knobs": knobs,
        "knobs_total": len(knobs),
        "knobs_relaxed": sorted(f for f, k in knobs.items() if k["verdict"] == "RELAXED"),
        "knobs_tightened": sorted(f for f, k in knobs.items() if k["verdict"] == "TIGHTENED"),
        "knobs_added": sorted(f for f, k in knobs.items() if k["verdict"] == "ADDED"),
        "knobs_unchanged": sum(1 for k in knobs.values() if k["verdict"] == "UNCHANGED"),
        "proposals": meas["proposals"],
        "homes": meas["homes"],
        "findings": findings,
        "advisory": ("ADVISORY: ни один порог не изменён и ни одно решение не "
                     "перенесено. Перенос дома решений — отдельная работа; правка "
                     "порога RiskPolicy — money-path и решение владельца."),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(root) / REPORT_REL))
    return doc


def main() -> int:
    doc = run(root=os.environ.get("SPA_ROOT") or None)
    print(f"cio_policy_change_procedure: {doc['overall']} "
          f"(critical={doc['counts']['critical']} warn={doc['counts']['warn']} "
          f"unchecked={doc['counts']['unchecked']}) · "
          f"ослаблено {len(doc['knobs_relaxed'])}, ужесточено "
          f"{len(doc['knobs_tightened'])}, добавлено {len(doc['knobs_added'])}, "
          f"не менялось {doc['knobs_unchanged']} из {doc['knobs_total']}")
    for f in doc["findings"]:
        print(f"  [{f['severity'].upper()}] {f['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
