"""Перепись списков БЕЗ личности в ответах питоньих читателей.

Заказ **G34, п. 1** приказа владельца «Portfolio CIO» (хвост ADR-409).

## Вопрос, на который прибор отвечает

`element_identity` (ADR-409, `run_identity_key_price`) выбирает поле, которым
элементы списка называют СЕБЯ, и имеет три исхода. Третий — «годного поля нет»
— честно оставляет обход позиционным: координата вида ``.findings[8].severity``
заговорит о ДРУГОЙ находке, стоит набору сменить длину, не изменив ни буквы в
своём имени. Заказ спрашивает ЗАМЕР, а не догадку:

1. сколько списков в ответах читателей попадают СЕЙЧАС в третий исход;
2. у скольких из них есть **годное** поле-кандидат, которого нет в
   ``_IDENTITY_FIELDS``.

Второе число и есть цена нынешнего списка имён: список назван на глаз, и
дописывать в него имена дальше на глаз — ровно та догадка, против которой
написан сам приём. Перепись превращает «кажется, надо добавить `label`» в
«`label` годен у N списков из M, и вот они поимённо».

## Чего перепись НЕ доказывает

* **Годность ≠ верность.** Поле, уникальное на сегодняшнем ответе, завтра может
  повториться. Прибор меряет СОСТАВ одного наблюдённого ответа, а не обещание
  писателя; поэтому вывод односторонний: «годного поля нет» — свойство, «поле
  годно» — наблюдение.
* **Список из ОДНОГО элемента годен тривиально**: любое скалярное поле в нём
  уникально по построению — это совпадение, а не свойство (тот же довод, по
  которому `element_identity` исключает ``bool``). Поэтому синглтоны считаются
  ОТДЕЛЬНО и в число-находку не входят.
* Читатель, которого нельзя позвать, уходит в **не измерено** с названной
  причиной, а не в ноль (инв. #17).
* Обход упёрся в потолок узлов ⇒ строка читателя помечается усечённой и в
  знаменатель находки не идёт: «не досмотрели» не имеет права читаться как
  «не нашли».

Прибор только ЧИТАЕТ: капитал не двигается, живой трек и ``data/`` не
трогаются, зов идёт против КОПИИ-стенда, ``write=False`` проводится там, где
параметр есть (правилом ``module_driver``, а не своей копией правила).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import _list_identity_probe as probe  # noqa: E402
from spa_core.monitoring.python_reader_clock_doors import (  # noqa: E402
    measurement_due, population,
)
from spa_core.monitoring.run_identity_key_price import build_stands  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402

SCHEMA = "list_identity_census.v1"
ARTIFACT = "list_identity_census.json"

#: Такт переписи. Зов каждого читателя стоит секунды, всё население — минуты;
#: ответ на вопрос «как устроены списки» меняется со скоростью кода, а не дня,
#: поэтому такт недельный и срок решает ФАЙЛ (тот же приём, что у соседа G33).
MEASUREMENT_TACT_DAYS = 7

#: Потолок времени на зов всего населения. Превышен ⇒ НЕ ИЗМЕРЕНО с причиной.
PROBE_TIMEOUT_S = 1800

#: Исходы, у которых вопрос заказа ОСМЫСЛЕН: элементы — словари, а значит могли
#: бы назвать себя полем. Список скаляров сюда не входит: он не назван полем не
#: оттого, что списку имён недостаёт имени.
_DICT_OUTCOMES = ("unnamed_candidate_outside", "unnamed_no_candidate")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def run_probe(names: Sequence[str], stand: Path, tree_root: Path,
              moment: dt.datetime) -> Tuple[Optional[dict], str]:
    """Один зов населения — отдельным процессом.

    Отдельный процесс здесь не ради пина часов (его нет вовсе), а ради импорта:
    перепись втягивает под сотню читателей, и побочные эффекты их импорта не
    имеют права оседать в процессе, который потом пишет артефакт.
    """
    with tempfile.TemporaryDirectory(prefix="spa_g34_") as tmp:
        mods = Path(tmp) / "modules.json"
        out = Path(tmp) / "answer.json"
        mods.write_text(json.dumps(list(names)), encoding="utf-8")
        env = dict(os.environ)
        env[probe.STAND_ENV] = str(stand)
        env[probe.CLOCK_ENV] = moment.isoformat()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(tree_root)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "spa_core.monitoring._list_identity_probe",
                 str(mods), str(out)],
                cwd=str(tree_root), env=env, capture_output=True,
                timeout=PROBE_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return None, f"зов населения не уложился в {PROBE_TIMEOUT_S} с"
        if proc.returncode != 0 or not out.exists():
            tail = (proc.stderr or b"").decode("utf-8", "replace").strip()[-300:]
            return None, f"зонд вышел кодом {proc.returncode}: {tail}"
        try:
            return json.loads(out.read_text(encoding="utf-8")), ""
        except (OSError, ValueError) as exc:
            return None, f"ответ зонда не прочитан: {type(exc).__name__}"


def tally(rows: Dict[str, dict]) -> dict:
    """Свод по СПИСКАМ, а не по читателям: предмет заказа — список.

    Знаменатель находки назван явно и он УЖЕ полного населения: из него
    вычтены синглтоны (годность в них тривиальна) и списки не-словарей (полем
    себя не называют по построению). Складывать их в один знаменатель значило
    бы развести находку водой.
    """
    outcomes: Dict[str, int] = {}
    candidate_fields: Dict[str, int] = {}
    strength: Dict[str, int] = {}
    named_fields: Dict[str, int] = {}
    singletons = 0
    truncated_readers: List[str] = []
    finding_rows: List[dict] = []
    total_lists = 0
    readers_measured = 0
    unmeasured: Dict[str, int] = {}

    for module, row in sorted(rows.items()):
        cause = row.get("cause")
        if cause:
            unmeasured[str(cause)] = unmeasured.get(str(cause), 0) + 1
            continue
        readers_measured += 1
        if row.get("truncated"):
            truncated_readers.append(module)
        for item in (row.get("lists") or []):
            total_lists += 1
            outcome = str(item.get("outcome"))
            outcomes[outcome] = outcomes.get(outcome, 0) + 1
            if int(item.get("n") or 0) == 1:
                singletons += 1
            if outcome == "named":
                named_fields[str(item.get("field"))] = (
                    named_fields.get(str(item.get("field")), 0) + 1)
            if outcome == "unnamed_candidate_outside" and int(item.get("n") or 0) > 1:
                for field in (item.get("candidates") or []):
                    candidate_fields[str(field)] = candidate_fields.get(str(field), 0) + 1
                    # Сила свидетельства — ДЛИНА списка, на котором поле
                    # оказалось уникальным. На двух элементах уникальность
                    # почти неизбежна и потому мало что говорит; на сорока
                    # трёх — говорит много. Хранится максимум: он и есть
                    # лучшее наблюдение в пользу поля.
                    prev = strength.get(str(field), 0)
                    strength[str(field)] = max(prev, int(item.get("n") or 0))
                finding_rows.append({"module": module,
                                     "coord": item.get("coord"),
                                     "n": item.get("n"),
                                     "candidates": item.get("candidates")})

    # Знаменатель считается ТОЛЬКО по читателям, чей обход дошёл до конца.
    # Усечённый обход даёт находки (они наблюдены), но не даёт знаменателя:
    # доля, посчитанная от недосмотренного населения, есть «не измерено»,
    # выданное за ответ.
    #
    # И только по СЛОВАРЯМ длиннее одного. Первая редакция брала сюда всякий
    # исход, начинающийся на `unnamed_`, — то есть и списки СКАЛЯРОВ, которых
    # в населении большинство. Знаменатель раздувался вчетверо, а подпись под
    # ним говорила «словари»: ровно то расхождение имени с населением, ради
    # которого весь этот прибор и написан.
    unnamed_dicts_multi = sum(
        1 for row in rows.values()
        if not row.get("cause") and not row.get("truncated")
        for item in (row.get("lists") or [])
        if int(item.get("n") or 0) > 1
        and str(item.get("outcome")) in _DICT_OUTCOMES)
    # Списки СКАЛЯРОВ длиннее одного — не предмет заказа, но и не ноль:
    # обходятся они позиционно, а элемент в них называет себя СВОИМ ЗНАЧЕНИЕМ.
    # Число печатается рядом, чтобы «полем себя не называют» не прочиталось как
    # «личности у них быть не может».
    scalar_lists_multi = sum(
        1 for row in rows.values()
        if not row.get("cause") and not row.get("truncated")
        for item in (row.get("lists") or [])
        if int(item.get("n") or 0) > 1
        and str(item.get("outcome")) == "unnamed_not_dicts")
    return {
        "scalar_lists_multi": scalar_lists_multi,
        "lists_total": total_lists,
        "outcomes": outcomes,
        "singletons": singletons,
        "readers_measured": readers_measured,
        "unmeasured_causes": unmeasured,
        "truncated_readers": sorted(truncated_readers),
        "named_fields": named_fields,
        "candidate_fields_outside": candidate_fields,
        "candidate_field_strength": strength,
        "denominator_of_finding": unnamed_dicts_multi,
        "finding_rows": finding_rows,
    }


def measure(data_dir: Path, tree_root: Path, *,
            now: Optional[dt.datetime] = None) -> dict:
    """Перепись целиком. Любое незакрытое звено ⇒ ``UNMEASURED`` с причиной."""
    moment = now if now is not None else _utcnow()
    doc: dict = {
        "schema": SCHEMA,
        "generated_at": moment.isoformat(),
        "question": ("сколько списков в ответах питоньих читателей не называют "
                     "себя полем (третий исход element_identity) и у скольких "
                     "есть годное поле-кандидат вне _IDENTITY_FIELDS"),
        "what_it_does_not_prove": [
            "годность поля наблюдена на ОДНОМ ответе — это не обещание писателя",
            "синглтон годен тривиально: уникальность в списке из одного элемента "
            "есть совпадение, а не свойство — синглтоны вынесены из знаменателя",
            "усечённый обход в знаменатель находки не идёт: «не досмотрели» не "
            "есть «не нашли»",
            "перепись НЕ дописывает имена в _IDENTITY_FIELDS и не меняет ни одной "
            "координаты — она только называет цену нынешнего списка",
        ],
        "advisory": ("_IDENTITY_FIELDS, element_identity, координаты соседних "
                     "приборов, пороги RiskPolicy v1.0, стоп-кран и живой трек "
                     "НЕ трогаются — прибор только ЧИТАЕТ"),
        "identity_fields_today": list(probe.IDENTITY_FIELDS),
    }

    names, pop_stats = population(Path(tree_root))
    doc["population"] = pop_stats
    if not names:
        doc["status"] = "UNMEASURED"
        doc["reason"] = "питонья ветвь населения переписи пуста — звать некого"
        return doc

    with tempfile.TemporaryDirectory(prefix="spa_g34_stand_") as tmp:
        stands, why = build_stands(Path(data_dir), Path(tmp))
        if stands is None:
            doc["status"] = "UNMEASURED"
            doc["reason"] = f"стенд не построен: {why}"
            return doc
        doc["stand"] = {"day": stands.get("day"), "donor_day": stands.get("donor_day")}
        answer, why = run_probe(names, Path(stands["s1"]), Path(tree_root), moment)
        if answer is None:
            doc["status"] = "UNMEASURED"
            doc["reason"] = f"население не позвано: {why}"
            return doc

    rows = answer.get("__modules__") or {}
    doc["readers"] = rows
    doc["counts"] = tally(rows)
    if not doc["counts"]["readers_measured"]:
        doc["status"] = "UNMEASURED"
        doc["reason"] = ("ни один читатель не позван — знаменателя нет, и ноль "
                         "находок читался бы как ответ")
        return doc
    finding = len(doc["counts"]["finding_rows"])
    doc["status"] = "FINDING" if finding else "CLEAN"
    doc["reason"] = (
        f"списков без личности с годным полем ВНЕ списка имён: {finding}"
        if finding else
        "ни один список без личности не имеет годного поля вне _IDENTITY_FIELDS")
    return doc


def report(doc: dict) -> List[str]:
    """Отчёт. Знаменатель печатается рядом с числителем — всегда."""
    out = [f"Перепись личности списков (G34 п. 1) — {doc.get('status')}"]
    if doc.get("status") == "UNMEASURED":
        out.append(f"[НЕ ИЗМЕРЕНО] {doc.get('reason')}")
        return out
    c = doc.get("counts") or {}
    named = int((c.get("outcomes") or {}).get("named") or 0)
    out.append(f"[ОТВЕТ] списков в ответах: {c.get('lists_total')} · "
               f"называют себя полем: {named} · "
               f"третий исход (личности нет): {c.get('lists_total', 0) - named}")
    out.append(f"[ЗНАМЕНАТЕЛЬ] списков без личности, где вопрос ОСМЫСЛЕН "
               f"(словари, длина > 1): {c.get('denominator_of_finding')}; "
               f"синглтонов всего {c.get('singletons')} — их годность тривиальна "
               f"и в знаменатель не входит")
    out.append(f"[РЯДОМ, НЕ В ЗНАМЕНАТЕЛЕ] списков СКАЛЯРОВ длиннее одного: "
               f"{c.get('scalar_lists_multi')} — полем себя не называют по "
               f"построению, но обходятся позиционно, а элемент в них назван "
               f"своим значением; это соседний вопрос, не этот")
    for key in sorted(c.get("outcomes") or {}):
        out.append(f"[ПО ИСХОДАМ] {key}: {(c.get('outcomes') or {})[key]}")
    fields = c.get("candidate_fields_outside") or {}
    if fields:
        strength = c.get("candidate_field_strength") or {}
        named_fields = ", ".join(
            f"{k}×{v} (макс. длина {strength.get(k, '?')})" for k, v in
            sorted(fields.items(), key=lambda kv: (-kv[1], kv[0])))
        out.append(f"[НАХОДКА] годные поля ВНЕ _IDENTITY_FIELDS: {named_fields}")
        out.append("[СИЛА СВИДЕТЕЛЬСТВА] «макс. длина» — длиннейший список, на "
                   "котором поле оказалось уникальным. На двух элементах "
                   "уникальность почти неизбежна и свидетельствует слабо; "
                   "дописывать имя в список по строке с длиной 2 значило бы "
                   "вернуть ту самую догадку")
        for row in (c.get("finding_rows") or [])[:20]:
            out.append(f"   {row.get('module')} {row.get('coord')} "
                       f"(элементов {row.get('n')}): {', '.join(row.get('candidates') or [])}")
    else:
        out.append("[ОПОРА] годных полей вне списка имён не нашлось — нынешний "
                   "список имён не занижает личность ни у одного списка населения")
    if c.get("truncated_readers"):
        out.append(f"[НЕ ДОСМОТРЕНО] обход упёрся в потолок у читателей: "
                   f"{', '.join(c['truncated_readers'])} — их списки в знаменатель "
                   f"находки не включены")
    for cause, num in sorted((c.get("unmeasured_causes") or {}).items()):
        out.append(f"[НЕ ИЗМЕРЕНО] {cause}: {num} читател(ей)")
    out.append(f"ADVISORY: {doc.get('advisory')}")
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="перепись списков без личности в ответах питоньих читателей (G34 п. 1)")
    ap.add_argument("--data-dir", default=str(_ROOT / "data"),
                    help="каталог data/, с которого строится стенд (КОПИЯ, не правится)")
    ap.add_argument("--tree-root", default=str(_ROOT))
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--if-due", action="store_true",
                    help=f"мерить, только если со дня прошлого замера прошло "
                         f"{MEASUREMENT_TACT_DAYS} дн")
    args = ap.parse_args(argv)

    dest = Path(args.out) if args.out else Path(args.data_dir) / ARTIFACT
    if args.if_due:
        due, why = measurement_due(dest, tact_days=MEASUREMENT_TACT_DAYS)
        if not due:
            print(f"замер не назначен: {why}")
            return 0
    doc = measure(Path(args.data_dir), Path(args.tree_root))
    for line in report(doc):
        print(line)
    if not args.no_write:
        atomic_save(doc, str(dest))
    return {"UNMEASURED": 2, "FINDING": 1}.get(str(doc.get("status")), 0)


if __name__ == "__main__":
    raise SystemExit(main())
