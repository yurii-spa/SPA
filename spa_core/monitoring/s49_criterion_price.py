"""Цена НЕИЗМЕРЕННОГО критерия §49 приказа владельца «Portfolio CIO» — по одному.

Заказ G93 п. 1 (хвост ADR-505) дословно:

    «Десять критериев без мерки — назвать цену по одному. Не "написать десять
     проб" (это перепись, а ряд G-nn ровно так себя и кормит), а спросить у
     КАЖДОГО: что именно наблюдается по исходу, и существует ли сегодня
     артефакт, у которого это можно спросить. Критерий, у которого наблюдать
     НЕЧЕГО, — находка об архитектуре, а не о нехватке кода.»

Сводка ADR-505 сказала «НЕ ИЗМЕРЕНО 10 из 13» и на этом кончилась. Десять
одинаковых `НЕ ИЗМЕРЕНО` читаются как десять одинаковых дыр — а это неверно, и
разница между ними и есть ответ на заказ. У одних артефакт уже живёт, свеж и
объявлен в конституции: не хватает ОДНОГО поля. У других артефакта нет вовсе:
не хватает РЕШЕНИЯ, какой артефакт есть мера. Это чинится разным, и слить их в
одно слово значило бы повторить дефект, против которого написан инв. #17 —
только этажом выше.

## Где прибор берёт привязку «критерий → артефакт»

**Не у себя.** Список адресов, набранный в этом файле, был бы третьим местом для
чисел (`.claude/rules/site-numbers.md`) и молча разъехался бы с системой.
Привязка уже СУЩЕСТВУЕТ — в `architecture/manifest.json`, где у артефакта есть
производитель, потребители и `slo_hours`, а поле `notes` прозой говорит, меру
какого критерия §49 этот артефакт несёт.

И вот в этом всё дело: **привязка живёт ПРОЗОЙ**. Проза вердиктом не становится
(ADR-504): читатель сводки — машина, и она читает поле. Прибор поэтому разбирает
заметку СТРОГО — тремя объявленными формулировками, и упоминание `§49`, не
подошедшее ни к одной, обрывает замер с адресом, а не пропускается молча.

## Пять исходов, и каждый есть РАЗНАЯ цена

===================  ==========================================================
`TRANSCRIPTION`      привязка есть в канонической форме, артефакт жив и свеж по
                     СВОЕМУ ЖЕ `slo_hours` ⇒ цена = перенести привязку из прозы
                     в поле (`s49_criterion` у пробы над уже живым артефактом)
`WORDING`            привязка есть, но ДРУГОЙ формулировкой ⇒ цена та же плюс
                     приведение к одной форме; само существование двух
                     формулировок и есть находка — читатель обязан угадывать
`PRODUCER`           привязка есть, а артефакта в живом каталоге НЕТ или он
                     протух ⇒ цена = вернуть производителя в такт; объявлять
                     пока нечего, спрашивать не у чего
`DECISION`           конституция не называет мерой этого критерия НИ ОДНОГО
                     артефакта ⇒ цена = РЕШИТЬ, какой артефакт есть мера. Это
                     решение, а не перепись, и находка здесь об архитектуре
`UNMEASURED`         третий исход с названной причиной: манифест не прочитан,
                     каталог артефактов не назван, привязка столкнулась у
                     нескольких артефактов, `§49` упомянут неразобранной формой
===================  ==========================================================

Порядок разрешения намеренно таков, что **живость доминирует над формой**:
артефакт, которого нет, не становится дешевле оттого, что о нём красиво
написано.

## Чего прибор НЕ докладывает (назвать слепоту — часть замера)

* **Верность привязки.** `notes` говорит «этот артефакт объявлен мерой такого-то
  критерия». Мерит ли он его на самом деле, решает контроль пробы в обе стороны
  (`.claude/rules/acceptance.md`, п. 3), а не этот прибор.
* **Наблюдения ВНЕ конституции.** Прибор читает объявления, а не дерево. Артефакт,
  который что-то наблюдает, но не объявил себя ничьей мерой, для прибора не
  существует — и `DECISION` говорит ровно это: «объявленного наблюдателя нет»,
  а не «наблюдать нечего нигде». Необъявленное неотличимо от несуществующего, и
  это не оговорка прибора, а свойство системы.
* **Ничего не чинит.** ADVISORY: ни строки risk-логики, стоп-крана, аллокатора,
  живого трека или `landing/**`.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime as dt
import json
import os
import re

from spa_core.utils.observation import observed

#: Конституция: где объявлены артефакты, их производители и сроки годности.
MANIFEST_REL = "architecture/manifest.json"

#: Поле, которым артефакт называет собственное время производства. Перебирать
#: «хоть какое-нибудь похожее» ЗАПРЕЩЕНО (урок #467, `consume_office_reports`
#: `_TS_FIELD`): угаданное поле сделало бы возраст уверенно НЕВЕРНЫМ — хуже, чем
#: честно неизмеренным. Отклонения объявляются там, а здесь отсутствие поля —
#: третий исход.
TS_FIELD = "generated_at"

TRANSCRIPTION = "TRANSCRIPTION"
WORDING = "WORDING"
PRODUCER = "PRODUCER"
DECISION = "DECISION"
UNMEASURED = "UNMEASURED"

#: Человекочитаемая цена каждого исхода — ОДНОЙ строкой, для печати рядом.
PRICE_RU = {
    TRANSCRIPTION: "перенести привязку из прозы в поле",
    WORDING: "привести формулировку к канонической и перенести в поле",
    PRODUCER: "вернуть производителя в такт — спрашивать пока не у чего",
    DECISION: "РЕШИТЬ, какой артефакт есть мера этого критерия",
    UNMEASURED: "цена НЕ НАЗВАНА — сначала снять причину",
}

#: Как конституция СЕГОДНЯ связывает артефакт с критерием §49. Перечень ЗАКРЫТ
#: намеренно: открытый («возьмём что-нибудь после §49») превратил бы любую
#: соседнюю фразу в привязку, и население бесшумно выросло бы.
#:
#: Держит перечень **ЯКОРЬ** (`\A` + `match`): форма обязана начаться сразу за
#: `§49`. Без него «§49 — подробности в ADR, см. `Economics` ниже» объявило бы
#: мерой критерия первый попавшийся термин в кавычках, то есть привязка родилась
#: бы из фона.
#:
#: **Порядок форм безразличен, и это ИЗМЕРЕНО, а не предположено.** Первая
#: редакция этого комментария утверждала обратное — будто `paren` обязана стоять
#: впереди, иначе `quoted` вытащит «Portfolio CIO». Мутация «переставить формы»
#: выжила и была права: формы взаимоисключительны по первому значащему символу
#: (`ТЗ`, обратная кавычка, ёлочка), и при якоре пересечься не могут
#: (`spa_core/tests/test_s49_criterion_price.py::FormsAreAnchored`).
_BINDING_FORMS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("paren", re.compile(r"\A\s*ТЗ\s+«[^»]{1,40}»\s*\(\s*(?P<criterion>[^:)]{1,40}?)\s*[:)]")),
    ("backtick", re.compile(r"\A\s*`(?P<criterion>[^`]{1,40})`")),
    ("quoted", re.compile(r"\A\s*«(?P<criterion>[^»]{1,40})»")),
)

#: Каноническая формулировка — та, которой конституция пользуется чаще и которая
#: называет критерий БЕЗ обрамляющего текста. Выбор объявлен здесь, а не выведен
#: из большинства в момент замера: «канон = кого сегодня больше» менялся бы от
#: одной дописанной заметки и делал бы вердикт прибора функцией населения.
CANONICAL_FORM = "backtick"

#: Хвост заметки, который прибор показывает у неразобранного `§49`.
_SNIPPET = 70


class Unmeasured(Exception):
    """Цены нет вовсе. Несёт причину, которую обязан напечатать вызывающий."""


def _iter_mentions(note: str):
    """Позиции всех упоминаний `§49` в заметке."""
    for match in re.finditer("§49", note):
        yield match.end()


def parse_bindings(manifest: dict) -> dict:
    """Разобрать привязки «критерий → артефакт» из `notes` конституции.

    Возврат::

        {"bindings": {criterion: [{"path", "slo_hours", "status", "form"}, …]},
         "unparsed": [{"path", "snippet"}, …]}

    Упоминание `§49`, не подошедшее ни к одной объявленной формулировке, попадает
    в `unparsed` С АДРЕСОМ и делает соответствующий критерий НЕ ИЗМЕРЕННЫМ, а не
    пропускается: разбор, умеющий пропустить непонятное, врал бы тихо — привязка
    молча перестала бы существовать.
    """
    artifacts = observed(manifest, "artifacts", kind=list)
    if artifacts is None:
        raise Unmeasured(f"в {MANIFEST_REL} нет списка `artifacts` — привязок "
                         f"взять неоткуда, и это НЕ «привязок ноль»")

    bindings: dict[str, list[dict]] = {}
    unparsed: list[dict] = []
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise Unmeasured(f"в {MANIFEST_REL} член `artifacts` не словарь "
                             f"({type(entry).__name__}) — список разобран НЕ БЫЛ")
        path = observed(entry, "path", kind=str)
        note = observed(entry, "notes", kind=str)
        if path is None:
            raise Unmeasured(f"в {MANIFEST_REL} у артефакта нет поля `path` — "
                             f"адрес привязки НЕИЗВЕСТЕН")
        if note is None:
            continue
        for pos in _iter_mentions(note):
            tail = note[pos:pos + 160]
            for form, pattern in _BINDING_FORMS:
                found = pattern.match(tail)
                if found:
                    name = found.group("criterion").strip()
                    bindings.setdefault(name, []).append(
                        {"path": path, "form": form,
                         "slo_hours": observed(entry, "slo_hours", kind=(int, float)),
                         "status": observed(entry, "status", kind=str)})
                    break
            else:
                unparsed.append({"path": path,
                                 "snippet": "§49" + tail[:_SNIPPET]})
    return {"bindings": bindings, "unparsed": unparsed}


def read_manifest(repo_root: str) -> dict:
    """Прочитать конституцию. Непрочитанная конституция — `Unmeasured`, не пустота."""
    path = os.path.join(repo_root, MANIFEST_REL)
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise Unmeasured(f"{MANIFEST_REL} не прочитан ({exc}) — о привязках НЕ "
                         f"СКАЗАНО НИЧЕГО") from None
    if not isinstance(data, dict):
        raise Unmeasured(f"{MANIFEST_REL} — не объект ({type(data).__name__})")
    return data


def _parse_ts(value) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        stamp = dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def _liveness(data_dir: str | None, rel_path: str, slo_hours,
              now: dt.datetime) -> dict:
    """Жив ли артефакт в ЖИВОМ каталоге.

    Возврат — ``{"outcome", "why", "age_hours"}``; пустой ``outcome`` значит
    «жив», а НЕ «нечего сказать»: причина и возраст печатаются в любом случае.
    ``age_hours`` остаётся ``None``, когда возраст НЕ ИЗМЕРЕН, — ноль сюда не
    подставляется никогда (инв. #17).
    """
    if data_dir is None:
        return {"outcome": UNMEASURED, "age_hours": None,
                "why": ("каталог артефактов не назван (--data-dir) — жив ли "
                        "артефакт, НЕ СПРОШЕНО")}
    if not os.path.isdir(data_dir):
        # «Каталога нет» и «артефакта нет» чинятся разным: первое — не то дерево
        # или не тот путь, второе — молчащий производитель. Слить их значило бы
        # объявить молчащими ВСЕХ производителей разом.
        return {"outcome": UNMEASURED, "age_hours": None,
                "why": (f"каталога артефактов {data_dir} НЕ СУЩЕСТВУЕТ — это не "
                        f"«артефактов нет», а «спросили не у того дерева»")}
    name = os.path.basename(rel_path)
    full = os.path.join(data_dir, name)
    if not os.path.isfile(full):
        return {"outcome": PRODUCER, "age_hours": None,
                "why": f"артефакта {name} в {data_dir} НЕТ"}
    try:
        with open(full, encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError) as exc:
        return {"outcome": UNMEASURED, "age_hours": None,
                "why": f"{name} не прочитан ({exc}) — возраст НЕ ИЗМЕРЕН"}
    stamp = _parse_ts(observed(doc, TS_FIELD, kind=str))
    if stamp is None:
        return {"outcome": UNMEASURED, "age_hours": None,
                "why": (f"{name} не пишет разбираемый `{TS_FIELD}` — возраст НЕ "
                        f"ИЗМЕРЕН по построению, и `slo_hours` при нём украшение")}
    age = (now - stamp).total_seconds() / 3600.0
    if slo_hours is None:
        return {"outcome": UNMEASURED, "age_hours": age,
                "why": (f"{name}: возраст {age:.1f}ч, но `slo_hours` в "
                        f"{MANIFEST_REL} не объявлен — сравнивать НЕ С ЧЕМ")}
    if age > float(slo_hours):
        return {"outcome": PRODUCER, "age_hours": age,
                "why": (f"{name} протух: {age:.1f}ч при объявленном пределе "
                        f"{float(slo_hours):g}ч")}
    return {"outcome": "", "age_hours": age,
            "why": f"{name} жив: {age:.1f}ч при пределе {float(slo_hours):g}ч"}


def price_of(criterion: str, parsed: dict, *, data_dir: str | None,
             now: dt.datetime | None = None) -> dict:
    """Цена ОДНОГО неизмеренного критерия. `now` — вход, а не стенные часы."""
    now = now or dt.datetime.now(dt.timezone.utc)
    bound = parsed["bindings"].get(criterion) or []
    blind = [u for u in parsed["unparsed"]]

    if len(bound) > 1:
        where = ", ".join(sorted(b["path"] for b in bound))
        return {"criterion": criterion, "price": UNMEASURED, "artifact": None,
                "form": None, "slo_hours": None, "age_hours": None,
                "detail": (f"мерой критерия объявлены СРАЗУ {len(bound)} артефакта "
                           f"({where}) — выбрать молча значило бы спрятать "
                           f"столкновение объявлений")}
    if not bound:
        if blind:
            where = ", ".join(sorted({u['path'] for u in blind}))
            return {"criterion": criterion, "price": UNMEASURED, "artifact": None,
                    "form": None, "slo_hours": None, "age_hours": None,
                    "detail": (f"объявленной привязки нет, но §49 упомянут "
                               f"НЕРАЗОБРАННОЙ формой у {len(blind)} артефакт(ов) "
                               f"({where}) — «привязки нет» и «спросили не той "
                               f"формой» здесь НЕРАЗЛИЧИМЫ")}
        return {"criterion": criterion, "price": DECISION, "artifact": None,
                "form": None, "slo_hours": None, "age_hours": None,
                "detail": ("конституция не называет мерой этого критерия НИ ОДНОГО "
                           "артефакта — объявленного наблюдателя нет, и первым "
                           "шагом нужен не код, а решение, какой артефакт есть мера")}

    entry = bound[0]
    live = _liveness(data_dir, entry["path"], entry["slo_hours"], now)
    row = {"criterion": criterion, "artifact": entry["path"],
           "form": entry["form"], "slo_hours": entry["slo_hours"],
           "age_hours": live["age_hours"]}
    if live["outcome"]:
        return {**row, "price": live["outcome"], "detail": live["why"]}
    price = TRANSCRIPTION if entry["form"] == CANONICAL_FORM else WORDING
    form_note = ("" if price == TRANSCRIPTION else
                 f"; привязка записана формой `{entry['form']}`, а не канонической "
                 f"`{CANONICAL_FORM}` — читатель обязан угадывать")
    return {**row, "price": price, "detail": f"{live['why']}{form_note}"}


def measure(criteria, *, repo_root: str, data_dir: str | None,
            population=None, now: dt.datetime | None = None) -> dict:
    """Цена каждого критерия из `criteria` + находки о самих привязках.

    `criteria` — те критерии, у которых мерки нет; население, ИЗМЕРЕННОЕ
    вызывающим (разбор §49 карточки), а не список в этом файле: «десять» здесь
    нигде не зашито.

    `population` — ПОЛНОЕ население §49; по нему и только по нему решается,
    является ли привязка сиротой. Считать сиротой всё, что вне `criteria`, было
    бы неверно вдвойне: привязка критерия, у которого мерка УЖЕ есть, попала бы
    в находку, а настоящая сирота потерялась бы среди них.
    """
    known = set(population if population is not None else criteria)
    manifest = read_manifest(repo_root)
    parsed = parse_bindings(manifest)
    rows = [price_of(name, parsed, data_dir=data_dir, now=now) for name in criteria]
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["price"]] = counts.get(row["price"], 0) + 1
    orphan = {name: sorted(e["path"] for e in entries)
              for name, entries in parsed["bindings"].items()
              if name not in known}
    return {"rows": rows, "counts": counts, "orphan_bindings": orphan,
            "unparsed_mentions": parsed["unparsed"],
            "declared_bindings": sum(len(v) for v in parsed["bindings"].values())}
