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

import argparse
import ast
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spa_core.utils.observation import observed

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


# ─── вторая ось §48 (ADR-993): отказ политики обходят СТУПЕНЬЮ, не порогом ──
#
# ADR-254 мерил §48 по ПОРОГАМ: что изменилось в `RiskConfig` против снимка v1.0
# и есть ли у ослабления предъявимое решение. «Не ослаблять policy молча» можно
# нарушить, не тронув ни одного порога: гейт отказал (или одобрил ОДНУ книгу),
# а ступень после гейта — трим ADR-850, запасная книга ADR-108 (ступень ADR-002),
# перераздача ADR-072 — исполнила ДРУГУЮ. ADR-991/992 нашли эти ступени на
# носителе цели и показали на СЦЕНАХ, что отказ они переживают не всегда. Эта
# ось задаёт тот же вопрос ЖИВЫМ записям §43 (заказ G981 п. 1 карточки приказа):
# трейлу `audit_trail.jsonl` (деньги) и теневым журналам ADR-060 (переспрос).
#
# Что считается обходом (и что — НЕ считается):
#   * отказ первого гейта (`risk_verdict.approved == False`) и в той же цепочке
#     `trade_executed` — отказ ОБОЙДЁН;
#   * исполненная книга несёт по протоколу БОЛЬШЕ, чем max(одобрено, удержано),
#     — свежий капитал, которого первый гейт не судил (`record_divergence`
#     ADR-992 на живой записи); протокол, не названный ни одобренной книгой,
#     ни удержанным, — введён без суда (`introduced_unjudged`);
#   * книга НИЖЕ одобренной (срез гейта к буферу кэша, трим вниз) обходом НЕ
#     является: меньшая продажа не есть свежий капитал (ADR-992).
# Трейл НЕ подписывает ступень (ADR-989: девять переписчиков цели невидимы
# ему по построению), поэтому виновник у живой записи остаётся неназванным, а
# ступени ниже — КАНДИДАТЫ, не вердикт.
TRAIL_REL = "data/audit_trail.jsonl"
TRAIL_FILE = "audit_trail.jsonl"
SHADOW_HISTORY_FILES: dict[str, str] = {
    "conservative": "allocation_rationale_history.jsonl",
    "balanced": "allocation_rationale_history_balanced.jsonl",
    "aggressive": "allocation_rationale_history_aggressive.jsonl",
}
BYPASS_WINDOW_SINCE = "2026-09-06"
BYPASS_WINDOW_PROVENANCE = (
    "заказ G981 п. 1 карточки приказа «Portfolio CIO»: «сколько раз с 06.09 отказ "
    "RiskPolicy был „обойдён“ не правкой порога, а ступенью»")
BYPASS_STAGE_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("ADR-850", "трим допустимого хода", "apply_admissible_trim"),
    ("ADR-108", "запасная книга при отсутствии снимка (ступень ADR-002)", "_compliant_target"),
    ("ADR-072", "перераздача срезанного гейтом бюджета", "redistribute_freed_budget"),
)
BYPASS_EPS_USD = 0.01
BYPASS_MEASURED = "measured"
BYPASS_UNMEASURED = "UNMEASURED"
#: Трейл пишет ОДИН `risk_verdict` на цепочку (замер 12.11: 615 цепочек, с двумя
#: вердиктами — 0). Переспрос политики ступенью (повторный гейт ADR-072, трим
#: ADR-850) едет в лог и в теневой журнал, не в трейл. Ноль событий здесь —
#: свойство НОСИТЕЛЯ, а не ответ «не переспрашивали».
CARRIER_ONE_VERDICT = "one_verdict_per_chain"
STAGE_NOT_SIGNED = ("ступень не названа: трейл не несёт переписанной цели и не подписывает "
                    "переписчика (ADR-989); кандидаты — " +
                    ", ".join(f"{adr} ({what})" for adr, what, _ in BYPASS_STAGE_CANDIDATES))


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int, str | None]:
    """(записи, нечитаемых строк, причина отказа). Нет файла — ОТКАЗ, не пустой список."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], 0, f"{path}: {exc.__class__.__name__}: {exc}"
    rows: list[dict[str, Any]] = []
    bad = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(obj, dict):
            rows.append(obj)
        else:
            bad += 1
    return rows, bad, None


def _usd(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _book(value: Any) -> dict[str, float] | None:
    """Книга как словарь чисел — либо None: не словарь или нечисло внутри (НЕ ИЗМЕРЕНО)."""
    if not isinstance(value, dict):
        return None
    out: dict[str, float] = {}
    for key, raw in value.items():
        usd = _usd(raw)
        if usd is None:
            return None
        out[str(key)] = usd
    return out


def execution_vs_gate(approved: dict[str, float], held: dict[str, float],
                      executed: dict[str, float]) -> dict[str, Any]:
    """Несёт ли ИСПОЛНЕННАЯ книга капитал, которого первый гейт не судил.

    Потолок свежести у протокола — max(одобрено, удержано) (ADR-992): меньшая
    продажа не есть свежий капитал, и книга НИЖЕ одобренной обходом не является.
    Протокол, которого нет ни в одобренной книге, ни среди удержанного, — введён
    без суда (`introduced_unjudged`).
    """
    fresh = 0.0
    beyond: dict[str, float] = {}
    introduced: list[str] = []
    for proto, usd in executed.items():
        ceiling = max(approved.get(proto, 0.0), held.get(proto, 0.0))
        if usd - ceiling > BYPASS_EPS_USD:
            beyond[proto] = round(usd - ceiling, 2)
            fresh += usd - ceiling
        if proto not in approved and proto not in held and usd > BYPASS_EPS_USD:
            introduced.append(proto)
    equal = all(abs(executed.get(p, 0.0) - approved.get(p, 0.0)) <= BYPASS_EPS_USD
                for p in set(executed) | set(approved))
    return {"fresh_beyond_gate_usd": round(fresh, 2), "beyond_by_protocol": beyond,
            "introduced_unjudged": sorted(introduced), "equal_to_decision": equal}


def _group_chains(rows: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], int]:
    chains: dict[str, list[dict[str, Any]]] = {}
    orphan = 0
    for r in rows:
        cid = observed(r, "correlation_id", kind=str)
        if not cid:
            orphan += 1
            continue
        chains.setdefault(cid, []).append(r)
    return chains, orphan


def _empty_tally() -> dict[str, Any]:
    return {"chains": 0, "chains_without_verdict": 0, "refused": 0,
            "refused_then_executed": [], "refused_then_blocked": 0, "refused_hold": 0,
            "executions": 0, "executions_equal_to_decision": 0,
            "executions_below_decision_only": 0, "executions_fresh_beyond_gate": [],
            "fresh_beyond_gate_usd": 0.0, "executions_unmeasured": 0}


def tally_trail(chains: dict[str, list[dict[str, Any]]], since: str) -> dict[str, Any]:
    """Обход отказа по цепочкам трейла — в окне заказа и за всю историю порознь."""
    window, all_time = _empty_tally(), _empty_tally()
    rejudged_events = 0
    refused_dates: set[str] = set()
    for cid, ev in chains.items():
        ts = next((str(observed(e, "timestamp", kind=str) or "") for e in ev
                   if observed(e, "timestamp", kind=str)), "")
        buckets = [all_time] + ([window] if ts[:10] >= since else [])
        for b in buckets:
            b["chains"] += 1
        verdicts = [e for e in ev if e.get("event_type") == "risk_verdict"]
        if len(verdicts) > 1:
            rejudged_events += 1
        if not verdicts:
            for b in buckets:
                b["chains_without_verdict"] += 1
            continue
        vdata = observed(verdicts[0], "data", kind=dict)
        approved = None if vdata is None else observed(vdata, "approved", kind=bool)
        types = [e.get("event_type") for e in ev]
        execs = [e for e in ev if e.get("event_type") == "trade_executed"]
        if approved is False:
            refused_dates.add(ts[:10])
            for b in buckets:
                b["refused"] += 1
                if execs:
                    b["refused_then_executed"].append({
                        "correlation_id": cid, "timestamp": ts,
                        "violations": observed(vdata, "violations", kind=list),
                        "trade_ids": [observed(observed(e, "data", kind=dict), "trade_id")
                                      for e in execs]})
                elif "trade_blocked" in types:
                    b["refused_then_blocked"] += 1
                else:
                    b["refused_hold"] += 1
        proposal = next((e for e in ev if e.get("event_type") == "allocation_proposal"), None)
        pdata = observed(proposal, "data", kind=dict) if proposal is not None else None
        target = _book(observed(pdata, "target_usd", kind=dict)) if pdata is not None else None
        for e in execs:
            edata = observed(e, "data", kind=dict)
            executed = _book(observed(edata, "to_allocation", kind=dict)) if edata is not None else None
            held = _book(observed(edata, "from_allocation", kind=dict)) if edata is not None else None
            for b in buckets:
                b["executions"] += 1
            if executed is None or held is None or target is None:
                for b in buckets:
                    b["executions_unmeasured"] += 1
                continue
            cmp = execution_vs_gate(target, held, executed)
            if cmp["equal_to_decision"]:
                for b in buckets:
                    b["executions_equal_to_decision"] += 1
            elif cmp["fresh_beyond_gate_usd"] > BYPASS_EPS_USD or cmp["introduced_unjudged"]:
                rec = {"trade_id": observed(edata, "trade_id"), "correlation_id": cid,
                       "timestamp": str(observed(e, "timestamp", kind=str) or ts),
                       "first_gate_approved": approved,
                       "gate_trimmed": observed(vdata, "trimmed", kind=bool),
                       "stage": None, "stage_reason": STAGE_NOT_SIGNED, **cmp}
                for b in buckets:
                    b["executions_fresh_beyond_gate"].append(rec)
                    b["fresh_beyond_gate_usd"] = round(
                        b["fresh_beyond_gate_usd"] + cmp["fresh_beyond_gate_usd"], 2)
            else:
                for b in buckets:
                    b["executions_below_decision_only"] += 1
    if rejudged_events:
        rejudged = {"events": rejudged_events, "verdict": BYPASS_MEASURED, "reason": ""}
    else:
        rejudged = {"events": 0, "verdict": BYPASS_UNMEASURED, "carrier": CARRIER_ONE_VERDICT,
                    "reason": ("трейл несёт один `risk_verdict` на цепочку — переспрос RiskPolicy "
                               "ступенью (повторный гейт ADR-072, трим ADR-850) трейлу невидим по "
                               "построению; свидетель переспроса — поле `admissible_trim.policy` "
                               "теневого журнала ADR-060 (см. `shadow`)")}
    return {"window": window, "all_time": all_time, "rejudged_within_chain": rejudged,
            "refused_dates": sorted(refused_dates)}


def tally_shadow(data_dir: Path, since: str, refused_dates: set[str]) -> dict[str, Any]:
    """Переспрос RiskPolicy тримом ADR-850 по теневым журналам ADR-060 — по книгам.

    Единственное место, где переспрос ЗАПИСАН: `admissible_trim.policy`. Сцена
    «отказ стал одобрением» собирается соединением по ДНЮ (UTC) с отказами
    первого гейта из трейла — основание соединения названо в отчёте.
    """
    books: dict[str, Any] = {}
    for book, fname in SHADOW_HISTORY_FILES.items():
        rows, bad, err = _read_jsonl(data_dir / fname)
        if err:
            books[book] = {"verdict": BYPASS_UNMEASURED, "reason": err}
            continue
        recs = [r for r in rows if str(observed(r, "generated_at", kind=str) or "")[:10] >= since]
        trim_verdicts: Counter = Counter()
        labels: Counter = Counter()
        rejudged = rejudged_approved = on_act = 0
        converted: list[dict[str, Any]] = []
        for r in recs:
            label = observed(r, "policy_version", kind=str)
            if label is not None:
                labels[label] += 1
            trim = observed(r, "admissible_trim", kind=dict)
            if trim is None:
                continue
            trim_verdicts[str(observed(trim, "verdict", kind=str))] += 1
            if str(observed(r, "verdict", kind=str)) != "HOLD":
                on_act += 1
            pol = observed(trim, "policy", kind=dict)
            if pol is None:
                continue
            rejudged += 1
            ok = observed(pol, "approved", kind=bool)
            if ok:
                rejudged_approved += 1
                day = str(observed(r, "cycle_date", kind=str)
                          or observed(r, "generated_at", kind=str) or "")[:10]
                if day in refused_dates:
                    converted.append({"book": book, "day": day,
                                      "decision_id": observed(r, "decision_id"),
                                      "trim_verdict": observed(trim, "verdict")})
        books[book] = {"verdict": BYPASS_MEASURED, "records": len(recs), "unparsable_lines": bad,
                       "trims": sum(trim_verdicts.values()),
                       "trim_verdicts": dict(sorted(trim_verdicts.items())),
                       "rejudged": rejudged, "rejudged_approved": rejudged_approved,
                       "trims_on_act_days": on_act,
                       "refusal_to_approval_same_day": converted,
                       "join_basis": "день UTC: `cycle_date` записи ↔ дата `risk_verdict` трейла",
                       "policy_version_labels": dict(sorted(labels.items()))}
    return books


def measure_bypass(data_dir: Path, *, since: str = BYPASS_WINDOW_SINCE,
                   declared_version: Any = None) -> dict[str, Any]:
    """Вторая ось §48 на живых записях. `data_dir` — ВХОД: из worktree живого `data/` нет."""
    out: dict[str, Any] = {"since": since, "since_provenance": BYPASS_WINDOW_PROVENANCE,
                           "data_dir": str(data_dir), "stage_candidates": [
                               {"adr": a, "what": w, "function": f} for a, w, f in BYPASS_STAGE_CANDIDATES],
                           "declared_version": declared_version}
    rows, bad, err = _read_jsonl(data_dir / TRAIL_FILE)
    if err:
        out.update(verdict=BYPASS_UNMEASURED, reason=err, trail=None, shadow=None,
                   version_labels=None)
        return out
    chains, orphan = _group_chains(rows)
    trail = tally_trail(chains, since)
    trail.update(rows=len(rows), unparsable_lines=bad, rows_without_correlation=orphan,
                 chains_total=len(chains))
    shadow = tally_shadow(data_dir, since, set(trail["refused_dates"]))
    labels: set[str] = set()
    for b in shadow.values():
        if b.get("verdict") == BYPASS_MEASURED:
            labels.update(b["policy_version_labels"])
    if declared_version is None or not isinstance(declared_version, str):
        version_labels = {"verdict": BYPASS_UNMEASURED,
                          "reason": "`RiskConfig.version` не прочитан — сравнивать подписи не с чем",
                          "on_records": sorted(labels), "declared": declared_version}
    else:
        version_labels = {"verdict": BYPASS_MEASURED, "declared": declared_version,
                          "on_records": sorted(labels),
                          "undeclared": sorted(labels - {declared_version})}
    out.update(verdict=BYPASS_MEASURED, reason="", trail=trail, shadow=shadow,
               version_labels=version_labels)
    return out


def _bypass_findings(bp: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if bp.get("verdict") != BYPASS_MEASURED:
        out.append({"severity": "unchecked", "field": None,
                    "text": (f"вторая ось §48 (обход отказа ступенью, ADR-993) НЕ ИЗМЕРЕНА: "
                             f"{bp.get('reason') or 'причина не названа'}")})
        return out
    trail = bp["trail"]
    win, allt = trail["window"], trail["all_time"]
    since = bp["since"]
    for rec in win["refused_then_executed"]:
        out.append({"severity": "critical", "field": None,
                    "text": (f"отказ RiskPolicy ОБОЙДЁН: цепочка {rec['correlation_id']} "
                             f"({rec['timestamp'][:19]}) получила `approved=False` "
                             f"({rec.get('violations')}) и в той же цепочке исполнен ход "
                             f"{rec.get('trade_ids')} — ослабление политики не порогом, а ступенью")})
    fresh = win["executions_fresh_beyond_gate"]
    if fresh:
        protos = sorted({p for r in fresh for p in r["introduced_unjudged"]})
        out.append({"severity": "critical", "field": None,
                    "text": (f"с {since}: у {len(fresh)} из {win['executions']} исполнений книга несёт "
                             f"${win['fresh_beyond_gate_usd']:,.2f} свежего капитала СВЕРХ потолка "
                             f"первого гейта (max(одобрено, удержано)); введены без суда: "
                             f"{protos or '—'}; ступень трейлом не подписана — RiskPolicy судила "
                             "одну книгу, исполнена другая: «ослабить policy молча» другими средствами")})
    if allt["executions_fresh_beyond_gate"]:
        n_all = len(allt["executions_fresh_beyond_gate"])
        out.append({"severity": "warn" if not fresh else "info", "field": None,
                    "text": (f"за всю историю трейла: {n_all} из {allt['executions']} исполнений несут "
                             f"${allt['fresh_beyond_gate_usd']:,.2f} свежего капитала сверх потолка первого "
                             f"гейта; отказов первого гейта {allt['refused']}, из них исполнено "
                             f"{len(allt['refused_then_executed'])}, удержано отказом "
                             f"{allt['refused_then_blocked'] + allt['refused_hold']}")})
    rj = trail["rejudged_within_chain"]
    if rj["verdict"] != BYPASS_MEASURED:
        out.append({"severity": "unchecked", "field": None,
                    "text": f"переспрос RiskPolicy внутри цепочки: НЕ ИЗМЕРЕНО — {rj['reason']}"})
    for book, b in sorted(bp["shadow"].items()):
        if b.get("verdict") != BYPASS_MEASURED:
            out.append({"severity": "unchecked", "field": None,
                        "text": f"теневой журнал «{book}» не прочитан: {b.get('reason')}"})
            continue
        for c in b["refusal_to_approval_same_day"]:
            out.append({"severity": "critical", "field": None,
                        "text": (f"книга «{book}», {c['day']}: первый гейт отказал книге дня, а трим "
                                 f"ADR-850 переспросил RiskPolicy и получил одобрение "
                                 f"({c['trim_verdict']}, {c['decision_id']}) — отказ стал одобрением "
                                 "внутри одного дня")})
        if b["trims_on_act_days"]:
            out.append({"severity": "warn", "field": None,
                        "text": (f"книга «{book}»: {b['trims_on_act_days']} трим(ов) ADR-850 на днях с "
                                 "ходом — урезанная книга дошла до исполнения")})
    measured = [b for b in bp["shadow"].values() if b.get("verdict") == BYPASS_MEASURED]
    if measured:
        out.append({"severity": "info", "field": None,
                    "text": (f"теневые журналы ADR-060 с {since}: трим ADR-850 переспросил RiskPolicy "
                             f"{sum(b['rejudged'] for b in measured)} раз (одобрена "
                             f"{sum(b['rejudged_approved'] for b in measured)}), на днях с ходом "
                             f"{sum(b['trims_on_act_days'] for b in measured)}, «отказ → одобрение» в "
                             f"один день {sum(len(b['refusal_to_approval_same_day']) for b in measured)}")})
    vl = bp["version_labels"]
    if vl["verdict"] != BYPASS_MEASURED:
        out.append({"severity": "unchecked", "field": "version",
                    "text": f"подписи версии политики на записях: НЕ ИЗМЕРЕНО — {vl['reason']}"})
    elif vl["undeclared"]:
        out.append({"severity": "warn", "field": "version",
                    "text": (f"записи теневых журналов подписаны версиями политики "
                             f"{vl['undeclared']}, а `RiskConfig.version` объявляет "
                             f"`{vl['declared']}` — у CURRENT RULE больше одного имени, и по "
                             "подписи записи его правило не найти")})
    return out


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
        now: datetime | None = None, data_dir: str | Path | None = None,
        since: str = BYPASS_WINDOW_SINCE) -> dict[str, Any]:
    """Собрать отчёт §48. ``now`` — ВХОД (правило о времени в тестах).

    ``data_dir`` — каталог живых записей (трейл, теневые журналы); умолчание —
    ``<root>/data``. Из worktree живого ``data/`` нет ПО ПОСТРОЕНИЮ — передавать
    каталог прод-дерева, иначе вторая ось меряет git-замороженный канон.
    ``since`` — окно заказа (дата ISO), печатается с провенансом.
    """
    root = Path(root) if root else Path(__file__).resolve().parents[2]
    data_path = Path(data_dir) if data_dir else root / "data"
    ts = (now or datetime.now(timezone.utc)).isoformat()

    control = positive_control()
    meas = measure(root)
    declared = observed(meas["knobs"]["knobs"].get("version"), "current", kind=str)
    bypass = measure_bypass(data_path, since=since, declared_version=declared)
    findings = _findings(meas) + _bypass_findings(bypass)

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
        "schema": "cio_policy_change_procedure/v2",
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
        # ADR-993: вторая ось §48 — обход отказа ступенью на живых записях.
        # Артефакт без этого поля — схема v1, ось НЕ измерена (офис печатает это вслух).
        "bypass_by_stage": bypass,
        "findings": findings,
        "advisory": ("ADVISORY: ни один порог не изменён и ни одно решение не "
                     "перенесено. Перенос дома решений — отдельная работа; правка "
                     "порога RiskPolicy — money-path и решение владельца."),
    }
    if write:
        from spa_core.utils.atomic import atomic_save
        atomic_save(doc, str(Path(root) / REPORT_REL))
    return doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="§48 ТЗ CIO: процедура изменения Risk Policy "
                                 "(пороги, ADR-254) и обход отказа ступенью (ADR-993)")
    ap.add_argument("--root", default=os.environ.get("SPA_ROOT") or None,
                    help="корень дерева с политикой и реестром решений (умолчание — своё)")
    ap.add_argument("--data-dir", default=None,
                    help="каталог живых записей (трейл, теневые журналы); умолчание <root>/data — "
                         "из worktree живого data/ нет, передавать каталог прод-дерева")
    ap.add_argument("--since", default=BYPASS_WINDOW_SINCE,
                    help=f"окно заказа для второй оси, дата ISO (умолчание {BYPASS_WINDOW_SINCE})")
    args = ap.parse_args(argv)
    doc = run(root=args.root, data_dir=args.data_dir, since=args.since)
    print(f"cio_policy_change_procedure: {doc['overall']} "
          f"(critical={doc['counts']['critical']} warn={doc['counts']['warn']} "
          f"unchecked={doc['counts']['unchecked']}) · "
          f"ослаблено {len(doc['knobs_relaxed'])}, ужесточено "
          f"{len(doc['knobs_tightened'])}, добавлено {len(doc['knobs_added'])}, "
          f"не менялось {doc['knobs_unchanged']} из {doc['knobs_total']}")
    bp = doc["bypass_by_stage"]
    if bp.get("verdict") == BYPASS_MEASURED:
        w = bp["trail"]["window"]
        print(f"  вторая ось (с {bp['since']}, {bp['data_dir']}): цепочек {w['chains']} · "
              f"отказов первого гейта {w['refused']} · из них исполнено "
              f"{len(w['refused_then_executed'])} · исполнений {w['executions']}, со свежим "
              f"капиталом сверх гейта {len(w['executions_fresh_beyond_gate'])} "
              f"(${w['fresh_beyond_gate_usd']:,.2f}) · переспрос в трейле: "
              f"{bp['trail']['rejudged_within_chain']['verdict']}")
    else:
        print(f"  вторая ось: НЕ ИЗМЕРЕНО — {bp.get('reason')}")
    for f in doc["findings"]:
        print(f"  [{f['severity'].upper()}] {f['text']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
