"""Претензия о CI, не называющая свой прогон, перемерить нечем.

# LLM_FORBIDDEN

**Замер, ради которого прибор написан** (2026-11-27, цикл #1268, подтверждено
#1270). Ежедневный аудит «90 %» доложил владельцу строкой announce-лога:

    CI control RED 140 имён (вчера 58), худший — f-string SyntaxError на py3.11 ×26

Канонический читатель ``scripts/ci_control_verdict.py`` на том же дне даёт
**84** упавших, а не 140; худший файл — ``test_reachability_of_the_rest_wiring.py``
действительно **×26**, но причина, прочитанная в логе шарда, —
``Failed: Timeout (>180.0s) from pytest-timeout`` в ``setUpModule``. Класс
f-string при этом измерен в НОЛЬ двумя приборами. То есть **совпавшее число
×26 сделало ложную причину убедительной** и отправило бы следующий цикл чинить
то, чего нет.

**Предмет прибора — не «верна ли претензия», а «можно ли её вообще
перемерить».** У претензии о прогоне CI есть ровно одна личность, по которой
её перемеряют: НОМЕР ПРОГОНА. Претензия, несущая число или род падения и НЕ
несущая номера, не ошибочна и не верна — она **неопровержима**, и никакой
сторож о ней ничего не скажет. Это тот же класс, что «не измерено, выданное за
ответ» (`.claude/rules/deployment.md`), только с другой стороны: здесь за
ответ выдаётся ПРОЗА.

**Почему номер ищется ТОЛЬКО внутри сегмента претензии.** В той же строке
сводки стоят другие номера и другие sha — например коммит песочницы
(``песочница A/B/C на c5931f41b``) или номер ЗАКАЗАННОГО прогона из соседней
записи. Первая редакция мерки спрашивала «есть ли в строке хоть что-то похожее
на sha» и объявляла претензию 27.11 ПЕРЕМЕРЯЕМОЙ — ошибка в сторону «чисто»,
ровно та, против которой прибор написан. Поэтому личность берётся из
СЕГМЕНТА (от маркера до следующего ``;``), а номер, найденный в строке мимо
сегмента, назван отдельной осью и перемеряемости НЕ даёт.

**Чего прибор НЕ делает.** Он не сверяет РОД падения: род в претензии — проза,
и сверять её с осью причин канонического читателя нечем, кроме чтения лога
шарда. Поэтому у претензии с названным прогоном и названным родом исход свой —
«число сверено, РОД НЕ СВЕРЕН», и он находка: именно совпадение числа делает
непроверенный род убедительным. Выдумать прозаический сравнитель значило бы
завести меру, отвечающую «я не умею» под видом «чисто».
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

#: Маркеры, по которым узнаётся претензия о контрольном прогоне. Перечень
#: ОБЪЯВЛЕН здесь: маркер, которого тут нет, даёт запись «вне населения», а не
#: молчание.
CLAIM_MARKS: tuple[str, ...] = (
    r"CI\s+control",
    r"CI\s+контроль",
    r"контрольн\w*\s+прогон\w*",
    r"автопроверк\w*\s+кода",
)
_MARK_RE = re.compile("|".join(CLAIM_MARKS), re.IGNORECASE)

#: Формы ЧИСЛА упавших. `RED 140 имён`, `RED 68`, `красных 59`, `упавших 84`.
COUNT_FORMS: tuple[str, ...] = (
    r"RED\s+(\d+)",
    r"красн\w*\s+(\d+)",
    r"упавш\w*\s+(\d+)",
    r"failed\s*[=:]?\s*(\d+)",
)
_COUNT_RE = re.compile("|".join(COUNT_FORMS), re.IGNORECASE)

#: Формы РОДА падения с кратностью: `худший — <проза> ×26`, `причина … x13`.
CAUSE_FORMS: tuple[str, ...] = (
    r"худш\w*\s*[—\-:]\s*(?P<cause>[^,;()]{3,120}?)\s*[×x]\s*(?P<mult>\d+)",
    r"причина\w*\s*[—\-:]\s*(?P<cause>[^,;()]{3,120}?)\s*[×x]\s*(?P<mult>\d+)",
)
#: Формы рода компилируются ПООТДЕЛЬНОСТИ: у каждой свои именованные
#: группы, и склейка через `|` их бы переопределила.
_CAUSE_RES = tuple(re.compile(f, re.IGNORECASE) for f in CAUSE_FORMS)


def _search_cause(segment: str) -> re.Match | None:
    for rx in _CAUSE_RES:
        m = rx.search(segment)
        if m is not None:
            return m
    return None

#: Номер прогона GitHub Actions. Замер: живые номера этого репозитория — 11
#: знаков; вилка 10…12 взята с запасом в ОБЕ стороны, чтобы мерка не зависела
#: от того, когда GitHub перешагнёт разряд.
RUN_ID_RE = re.compile(r"\b(\d{10,12})\b")

#: Ширина номера прогона ОБЪЯВЛЕНА, и число ДРУГОЙ ширины в сегменте есть
#: отдельная ось, а не молчание. Замер 27.11: живые номера прогонов этого
#: репозитория — 11 знаков, идентификаторы ВОРКФЛОУ — 9
#: (`387027328 SPA CI control`), и запись аудита 27.10 несла `908015739`,
#: которого среди прогонов нет вовсе (`GET …/actions/runs/908015739` → 404).
#: Промолчи мерка об этом — читатель решил бы, что прогон назван, а прибор его
#: не увидел.
_DIGITS_RE = re.compile(r"\b(\d{4,})\b")

#: Кавычки ЦИТАТЫ. Претензия, попавшая внутрь «…», принадлежит ДРУГОЙ записи:
#: её автор пересказывает чужую сводку, а не утверждает своё. Считать цитату
#: находкой значило бы удваивать население и наказывать разбор — ровно ошибка
#: в сторону НАХОДКИ (замер 27.11: из 22 претензий с числом цитатой является
#: РОВНО одна — запись цикла #1270, разбиравшего сводку аудита).
QUOTE_OPEN, QUOTE_CLOSE = "«", "»"


def quoted_spans(text: str) -> list[tuple[int, int]]:
    """Диапазоны цитат «…» (вложенные считаются как одна внешняя)."""
    out: list[tuple[int, int]] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text or ""):
        if ch == QUOTE_OPEN:
            if depth == 0:
                start = i
            depth += 1
        elif ch == QUOTE_CLOSE and depth:
            depth -= 1
            if depth == 0:
                out.append((start, i))
    return out

# ── исходы (инв. #17: «не измерено» — отдельное значение, а не ноль) ────────
NO_CLAIM = "no_claim"
QUOTED = "quoted_claim_of_another_record"
UNFALSIFIABLE = "unfalsifiable"
COUNT_AGREES = "count_agrees"
COUNT_DIFFERS = "count_differs"
CAUSE_UNVERIFIED = "cause_unverified_number_only"
OUT_OF_WINDOW = "unmeasured_out_of_window"
NO_CANONICAL = "unmeasured_no_canonical"
UNPARSED = "unmeasured_unparsed"

KINDS: tuple[str, ...] = (
    NO_CLAIM, QUOTED, UNFALSIFIABLE, COUNT_AGREES, COUNT_DIFFERS, CAUSE_UNVERIFIED,
    OUT_OF_WINDOW, NO_CANONICAL, UNPARSED,
)

#: Исходы, которые есть НАХОДКА, а не состояние.
FINDING_KINDS: frozenset[str] = frozenset({UNFALSIFIABLE, COUNT_DIFFERS,
                                           CAUSE_UNVERIFIED})

#: Исходы «НЕ ИЗМЕРЕНО»: нулём они не считаются и находкой не являются.
UNMEASURED_KINDS: frozenset[str] = frozenset({OUT_OF_WINDOW, NO_CANONICAL,
                                              UNPARSED})


def claim_segments(summary: str) -> list[dict]:
    """Сегменты претензии: от маркера до следующего ``;`` (или до конца).

    Граница именно ``;``: сводка аудита перечисляет предметы через точку с
    запятой, и «флот 97,8 %» к прогону CI отношения не имеет. Брать строку
    целиком значило бы отдать претензии номер соседнего предмета.
    """
    out: list[dict] = []
    for m in _MARK_RE.finditer(summary or ""):
        tail = summary[m.start():]
        cut = tail.find(";")
        seg = tail if cut < 0 else tail[:cut]
        out.append({"mark": m.group(0), "start": m.start(), "segment": seg})
    return out


def _first_group(m: re.Match | None) -> str | None:
    if m is None:
        return None
    for g in m.groups():
        if g:
            return g
    return None


def read_claim(segment: str) -> dict:
    """Что ОБЪЯВЛЕНО в сегменте: число, род с кратностью, номера прогонов."""
    count = _first_group(_COUNT_RE.search(segment))
    cause_m = _search_cause(segment)
    cause = mult = None
    if cause_m is not None:
        cause = (cause_m.groupdict().get("cause") or "").strip() or None
        mult = cause_m.groupdict().get("mult")
    return {
        "count": int(count) if count is not None else None,
        "cause": cause,
        "cause_mult": int(mult) if mult else None,
        "run_ids": RUN_ID_RE.findall(segment),
        "digits_not_run_id": [d for d in _DIGITS_RE.findall(segment)
                              if not RUN_ID_RE.fullmatch(d)],
    }


def classify_claim(segment: str, *, line: str = "", start: int = -1,
                   canonical: dict | None = None,
                   canonical_reason: str = "") -> dict:
    """Исход ОДНОЙ претензии. Третий исход обязателен и несёт причину.

    ``start`` — положение сегмента в строке; нужно ОСИ ЦИТАТЫ. Без него (−1)
    ось не спрашивается, и это сказано в исходе, а не умолчано.
    """
    got = read_claim(segment)
    row = dict(got)
    row["segment"] = segment
    # Номер в СТРОКЕ мимо сегмента — отдельная ось. Перемеряемости он не даёт:
    # неизвестно, о том ли он прогоне, а догадка здесь была бы ошибкой в
    # сторону «чисто».
    outside = [r for r in RUN_ID_RE.findall(line or "") if r not in got["run_ids"]]
    row["run_id_outside_segment"] = outside

    claims_something = got["count"] is not None or got["cause"] is not None
    if not claims_something:
        row["kind"] = NO_CLAIM
        row["reason"] = "сегмент не несёт ни числа, ни рода — претензии нет"
        return row

    spans = quoted_spans(line) if line else []
    row["quoted"] = any(a <= start <= b for a, b in spans) if start >= 0 else False
    if row["quoted"]:
        row["kind"] = QUOTED
        row["reason"] = ("претензия стоит внутри цитаты «…» — она принадлежит "
                         "ДРУГОЙ записи, и спрашивать её у этого автора значило "
                         "бы удвоить население")
        return row

    if not got["run_ids"]:
        row["kind"] = UNFALSIFIABLE
        extra = (f"; номер(а) в строке мимо сегмента: {', '.join(outside)} — "
                 f"о том ли он прогоне, НЕ ИЗВЕСТНО" if outside else "")
        if got["digits_not_run_id"]:
            extra += ("; числа в сегменте, номером прогона НЕ являющиеся: "
                      + ", ".join(got["digits_not_run_id"])
                      + " (живой номер прогона — 10…12 знаков)")
        row["reason"] = ("претензия несёт "
                         + ("число" if got["count"] is not None else "")
                         + (" и " if got["count"] is not None and got["cause"] else "")
                         + ("род падения" if got["cause"] else "")
                         + " и НЕ называет прогон — перемерить нечем" + extra)
        return row

    row["run_id"] = got["run_ids"][0]
    if canonical is None:
        row["kind"] = NO_CANONICAL
        row["reason"] = ("канонический читатель не ответил: "
                         + (canonical_reason or "причина не названа"))
        return row

    cid = str(((canonical.get("run") or {}).get("id")) or "")
    if cid != row["run_id"]:
        row["kind"] = OUT_OF_WINDOW
        row["reason"] = (f"канонический читатель отвечает о прогоне {cid or '—'}, "
                         f"а претензия о {row['run_id']} — перемерить этим "
                         f"чтением нечем")
        return row

    row["canonical_failed"] = canonical.get("failed")
    if got["count"] is not None and canonical.get("failed") != got["count"]:
        row["kind"] = COUNT_DIFFERS
        row["reason"] = (f"претензия назвала {got['count']}, канонический "
                         f"читатель — {canonical.get('failed')} на том же прогоне")
        return row

    if got["cause"] is not None:
        worst = ((canonical.get("red_census") or {}).get("worst") or [])
        row["canonical_worst"] = worst[0] if worst else None
        row["kind"] = CAUSE_UNVERIFIED
        row["reason"] = ("число сверено, а РОД падения — проза: сверять его "
                         "нечем, кроме чтения лога шарда. Совпавшее число "
                         "делает непроверенный род убедительным")
        return row

    row["kind"] = COUNT_AGREES
    row["reason"] = "число совпало с каноническим читателем на том же прогоне"
    return row


def read_announce(path: Path) -> tuple[list[dict], int, str]:
    """Записи announce-лога. Возврат ``(записи, неразобранных, причина)``.

    Причина непуста ⇒ **НЕ ИЗМЕРЕНО**: «файла нет» и «претензий нет» — разные
    состояния, и схлопывать их в пустой список запрещено (инв. #17).
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [], 0, f"{type(exc).__name__}: {exc}"
    rows: list[dict] = []
    bad = 0
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except ValueError:
            bad += 1
            continue
        if isinstance(doc, dict):
            rows.append(doc)
        else:
            bad += 1
    return rows, bad, ""


def canonical_verdict(repo_root: Path | None = None, *,
                      runner=None) -> tuple[dict | None, str]:
    """Вердикт КАНОНИЧЕСКОГО читателя (``scripts/ci_control_verdict.py``).

    Своей копии разбора у прибора нет намеренно: разойдись она с читателем —
    прибор судил бы претензии по мерке, которой не судит никто другой.
    ``runner`` — точка инъекции для сцен.
    """
    root = Path(repo_root or _ROOT)
    tool = root / "scripts" / "ci_control_verdict.py"
    if runner is None:
        if not tool.exists():
            return None, f"канонического читателя нет в дереве: {tool}"

        def runner():  # noqa: E306 — замыкание вокруг найденного пути
            return subprocess.run(
                [sys.executable, str(tool), "--json"],
                capture_output=True, text=True, timeout=300, cwd=str(root),
            )

    try:
        out = runner()
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    text = getattr(out, "stdout", "") or ""
    if not text.strip():
        return None, (f"канонический читатель не отдал документ "
                      f"(код {getattr(out, 'returncode', '—')})")
    try:
        doc = json.loads(text)
    except ValueError as exc:
        return None, f"документ канонического читателя не разобран: {exc}"
    if not isinstance(doc, dict):
        return None, "документ канонического читателя не объект"
    return doc, ""


def run_census(*, data_dir: str | os.PathLike | None = None,
               repo_root: str | os.PathLike | None = None,
               canonical: dict | None = None,
               canonical_reason: str = "",
               ask_canonical: bool = False,
               runner=None) -> dict:
    """Перепись претензий о CI в announce-логе.

    ``data_dir`` — ВХОД, а не расположение прибора: из worktree живого
    ``data/`` нет по построению, и прибор, молча вернувшийся к своему дереву,
    отвечал бы на СВОЙ вопрос (урок ADR-1107/1108). Выбор ПЕЧАТАЕТСЯ.
    """
    root = Path(repo_root or _ROOT)
    named = data_dir is not None
    ddir = Path(data_dir) if named else root / "data"
    path = ddir / "session_changes.jsonl"

    doc: dict = {
        "status": "OK",
        "data_dir": str(ddir),
        "data_dir_named": named,
        "announce_path": str(path),
        "kinds_declared": list(KINDS),
        "records": 0,
        "unparsed_records": 0,
        "claims": [],
        "by_kind": {k: 0 for k in KINDS},
        "canonical_run": None,
        "canonical_failed": None,
        "canonical_reason": canonical_reason,
        "unmeasured": [],
    }

    rows, bad, why = read_announce(path)
    doc["unparsed_records"] = bad
    if why:
        doc["status"] = "UNMEASURED"
        doc["unmeasured"].append(f"announce-лог не прочитан ({path}): {why}")
        return doc
    doc["records"] = len(rows)

    if canonical is None and ask_canonical:
        canonical, canonical_reason = canonical_verdict(root, runner=runner)
        doc["canonical_reason"] = canonical_reason
    elif canonical is None and not canonical_reason:
        doc["canonical_reason"] = ("канонического читателя не спрашивали "
                                   "(--ask-canonical не передан)")
    if canonical is not None:
        doc["canonical_run"] = str(((canonical.get("run") or {}).get("id")) or "")
        doc["canonical_failed"] = canonical.get("failed")

    for rec in rows:
        line = rec.get("summary") or ""
        for seg in claim_segments(line):
            row = classify_claim(seg["segment"], line=line,
                                 start=seg["start"],
                                 canonical=canonical,
                                 canonical_reason=doc["canonical_reason"])
            row["ts"] = rec.get("ts")
            row["session"] = rec.get("session")
            row["mark"] = seg["mark"]
            doc["claims"].append(row)
            doc["by_kind"][row["kind"]] += 1

    findings = [c for c in doc["claims"] if c["kind"] in FINDING_KINDS]
    # Подось САМОГО ОПАСНОГО вида: претензия без прогона, но с НАЗВАННЫМ родом
    # падения. Именно она отправляет следующий цикл чинить то, чего нет, —
    # число рядом делает род убедительным.
    doc["unfalsifiable_with_cause"] = sum(
        1 for c in doc["claims"]
        if c["kind"] == UNFALSIFIABLE and c.get("cause"))
    unmeas = [c for c in doc["claims"] if c["kind"] in UNMEASURED_KINDS]
    doc["findings"] = findings
    doc["unmeasured_claims"] = len(unmeas)
    if bad:
        doc["unmeasured"].append(
            f"записей announce-лога НЕ РАЗОБРАНО {bad} — это НЕ ноль")
    if findings:
        doc["status"] = "FINDING"
    return doc


def format_report(doc: dict) -> list[str]:
    lines: list[str] = []
    choice = "НАЗВАН" if doc.get("data_dir_named") else "УМОЛЧАНИЕ"
    lines.append(f"провенанс претензий о CI: каталог {doc['data_dir']} ({choice})")
    if doc["status"] == "UNMEASURED":
        for why in doc["unmeasured"]:
            lines.append(f"   [НЕ ИЗМЕРЕНО] {why}")
        return lines
    by = doc["by_kind"]
    lines.append(f"   записей {doc['records']} · претензий о прогоне "
                 f"{len(doc['claims'])} · НЕ РАЗОБРАНО записей "
                 f"{doc['unparsed_records']}")
    lines.append(f"   цитат чужой претензии {by[QUOTED]} (население не "
                 f"удваивается)")
    lines.append(f"   без претензии {by[NO_CLAIM]} · НЕОПРОВЕРЖИМЫХ "
                 f"{by[UNFALSIFIABLE]} · число сверено {by[COUNT_AGREES]} · "
                 f"число РАСХОДИТСЯ {by[COUNT_DIFFERS]} · род НЕ СВЕРЕН "
                 f"{by[CAUSE_UNVERIFIED]}")
    lines.append(f"   из НЕОПРОВЕРЖИМЫХ несут РОД падения: "
                 f"{doc.get('unfalsifiable_with_cause', 0)} — это самый "
                 f"дорогой вид: число рядом делает непроверенный род "
                 f"убедительным")
    lines.append(f"   НЕ ИЗМЕРЕНО: вне окна читателя {by[OUT_OF_WINDOW]} · "
                 f"читатель не спрошен {by[NO_CANONICAL]} · форма не разобрана "
                 f"{by[UNPARSED]} — нулём это не считается")
    if doc.get("canonical_run"):
        lines.append(f"   канонический читатель: прогон {doc['canonical_run']}, "
                     f"упавших {doc['canonical_failed']}")
    elif doc.get("canonical_reason"):
        lines.append(f"   канонический читатель НЕ ОТВЕТИЛ: {doc['canonical_reason']}")
    for c in doc.get("findings", []):
        head = {UNFALSIFIABLE: "НЕОПРОВЕРЖИМО",
                COUNT_DIFFERS: "ЧИСЛО РАСХОДИТСЯ",
                CAUSE_UNVERIFIED: "РОД НЕ СВЕРЕН"}[c["kind"]]
        lines.append(f"   🚨 {head}  {c.get('ts')}: {c['reason']}")
        lines.append(f"        претензия: {c['segment'][:160]}")
    for why in doc.get("unmeasured", []):
        lines.append(f"   [НЕ ИЗМЕРЕНО] {why}")
    if not doc.get("findings"):
        lines.append("   ✅ находок нет: каждая претензия либо называет свой "
                     "прогон, либо ничего не утверждает")
    lines.append("   форма, которой претензия становится перемеряемой: номер "
                 "прогона В СВОЁМ сегменте, а число и род — у "
                 "scripts/ci_control_verdict.py")
    lines.append("   ADVISORY: прибор только ЧИТАЕТ — announce-лог, карточки и "
                 "data/ не меняются")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Провенанс претензии о контрольном прогоне CI: называет ли "
                    "она прогон, которым её можно перемерить.")
    ap.add_argument("--data-dir", help="каталог артефактов (ВХОД, не "
                                       "расположение прибора); выбор печатается")
    ap.add_argument("--repo-root", help="дерево, из которого берётся "
                                        "канонический читатель")
    ap.add_argument("--ask-canonical", action="store_true",
                    help="спросить scripts/ci_control_verdict.py (сеть). Без "
                         "него претензии с НАЗВАННЫМ прогоном получают "
                         "«НЕ ИЗМЕРЕНО» с причиной, а не вердикт")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.data_dir is not None and not Path(args.data_dir).is_dir():
        print(f"[НЕ ИЗМЕРЕНО] названный каталог не читается: {args.data_dir}",
              file=sys.stderr)
        return 2

    doc = run_census(data_dir=args.data_dir, repo_root=args.repo_root,
                     ask_canonical=args.ask_canonical)
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        for line in format_report(doc):
            print(line)
    if doc["status"] == "UNMEASURED":
        return 2
    return 1 if doc.get("findings") else 0


if __name__ == "__main__":
    sys.exit(main())
