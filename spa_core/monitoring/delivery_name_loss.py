"""Доставка уносит ИМЯ, которого автор никогда не видел: «я удалил» ≠ «я не видел».

Заказ #570 (стоячая карточка CIO `inbox-task-portfolio-cio-dynamic-capital-alloc`)
поставлен находкой, а не вопросом: 11.09 в 23:52 коммит `2a1e32187` (ADR-343) завёл
проводку прибора `haystack_origin_census` в мост находок — запись в ``PRODUCES``,
запись в ``CENSUS_STAGE``, запись в ``CENSUS_PRODUCT`` и саму ступень в ``main()``.
Через **42 минуты** коммит `6322d0d56` (спринт ADR-344, «файлы 14–18») правил тот же
файл ОДНОЙ строкой по своему делу — и унёс все двадцать строк проводки. Сообщение
коммита о них не говорит ни слова: автор их не удалял, он их НЕ ВИДЕЛ — его копия
файла была снята до 23:52.

Это ТРЕТИЙ случай класса за две недели, и первый — в КОДЕ, а не в документе:

* `ba66e1bd3` (30.08) унёс 104 строки `.claude/rules/deployment.md` (найдено #453);
* `e1044b907` (27.08) унёс инвариант #17 из `CLAUDE.md` (найдено ADR-344);
* `6322d0d56` (12.09) унёс проводку ADR-343 — **тем самым спринтом, который чинил
  предыдущий случай**.

## Почему существующий страж молчал

У двери доставки страж перезаписи ЕСТЬ (`push_to_github.guard_overwrite`) и он
устроен верно — но проверка ПОТЕРИ СОДЕРЖИМОГО включена только для документов::

    if allow_overwrite or not is_rules_doc(repo_path):   # guard_content_loss
        return ""
    watched = is_append_only_doc(repo_path) or is_rules_doc(repo_path)

``.py`` не входит ни в один класс, поэтому о коде страж не говорит НИЧЕГО. Замер по
рефлогу `refs/remotes/origin/main` показывает, что в момент того пуша (00:34:50) голова
стояла на `e116ae03c`, база автора — на `b1d15bc8e`, blob-и файла различались
(`0d5a0624` против `84887948`), то есть вердикт был ``DIVERGENCE_DIVERGED`` и путь без
обхода ОТКАЗАЛ БЫ. Отсюда следует, что обход был (`--allow-overwrite` либо
`SPA_PUSH_ALLOW_OVERWRITE=1`); самой командной строки в истории нет, и это сказано как
третий исход, а не додумано. Но вывод от неё не зависит: **ни одна из трёх веток
стража не называет, ЧТО именно теряется.** Ветка явной перезаписи печатает имя файла и
причину расхождения — и ни одного утраченного байта.

## Единица смысла: имя, исчезнувшее ЦЕЛИКОМ, а не строка

Первый замер этого заказа брал единицей ЛЮБОЙ идентификатор и дал 90 исчезнувших имён
за неделю — почти сплошь локальные переменные (`amount`, `canon`, `dates`, `market`),
которые пропадают при любой правке. Считать это классом значило бы получить сторожа,
который кричит шесть раз в день и которого поэтому выключат.

Поэтому единица здесь — имя, которое файл может потерять ЗНАЧИМО:

``imports``       имя импортируемого модуля (`haystack_origin_census`);
``defs``          имя функции или класса верхнего уровня;
``module_names``  имя, связанное на уровне модуля (константа-реестр);
``entries``       строковый элемент коллекции-литерала верхнего уровня
                  (`"data/haystack_origin_census.json"` в ``PRODUCES``).

Локальные имена внутри функций НЕ считаются вовсе. Ступень в ``main()`` из аварии
ловится не как «блок кода», а через имя импортируемого модуля, которое в ней живёт:
на remote `haystack_origin_census` встречается 9 раз, у автора — 0. Это и есть признак,
не требующий понимать смысл правки.

## Разделение — ТРЁХСТОРОННЕЕ, и в этом всё дело

Само по себе «имя исчезло» дефектом НЕ является: замер по `origin/main` с 05.09 даёт
**57 исчезновений, сделанных автором осознанно** (`4bea832d1` — объявленный ОТКАТ
ADR-331, и сообщение коммита прямо это говорит). Разделяет не факт исчезновения, а
ответ на вопрос, БЫЛО ЛИ имя в копии автора:

``deleted_by_author``     имя есть в БАЗЕ автора и нет в его версии ⇒ он его видел и
                          убрал. Дефекта нет, страж молчит.
``never_seen_by_author``  имени нет НИ в базе автора, НИ в его версии, а на remote оно
                          ЕСТЬ ⇒ удалить его автор не мог по построению: он его не
                          видел. Ровно это и произошло 12.09.
``unmeasured``            базу установить нечем. НЕ складывается ни с одной долей и
                          никогда не читается как «чисто» (инвариант #17).

Три версии файла у двери доставки уже есть — база (`HEAD:путь` рабочей копии),
наша (то, что пушим) и remote. Ничего дополнительно читать не надо.

## Почему «доказать аддитивность difflib'ом» не спасало

Заведённый порядок работы с неизмеримой базой («докажи аддитивность, потом
`--allow-overwrite`») сравнивает нашу версию с НАШЕЙ ЖЕ базой. Аддитивность при этом
честно доказывается — и ничего не говорит о remote, который тем временем ушёл вперёд.
Проверка отвечает на свой вопрос, а нужный остаётся незаданным: ровно та форма ошибки,
против которой написаны «четыре вопроса» правила доставки.

## Чего прибор НЕ утверждает

НЕ говорит, верна ли правка по существу; НЕ различает переименование от удаления (имя
`foo` → `bar` он назовёт потерей `foo`, и это верно по его вопросу — на remote имени
больше нет); НЕ смотрит на строки внутри функций; и НЕ судит о файлах, которые не
разбираются как Python, — для них третий исход с названной причиной.

ADVISORY. Ни один тест не правится. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
from typing import Optional

#: Исходы разделения. Третий НИКОГДА не складывается с первыми двумя.
DELETED_BY_AUTHOR = "deleted_by_author"
NEVER_SEEN_BY_AUTHOR = "never_seen_by_author"
UNMEASURED = "unmeasured"


def _module_level_names(tree: ast.Module) -> set:
    """Имена, которые файл может потерять ЗНАЧИМО (см. «единица смысла»)."""
    names: set = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
            if node.value is not None:
                names |= _collection_entries(node.value)

    # Импорты ищутся по ВСЕМУ дереву намеренно: ступень моста из аварии 12.09 живёт
    # внутри `main()`, и её импорт — единственное имя, по которому она опознаётся.
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[-1])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                names.add(a.asname or a.name)

    return {n for n in names if isinstance(n, str) and n}


def _collection_entries(value: ast.AST) -> set:
    """Строковые элементы коллекции-литерала (и ключи словаря) верхнего уровня."""
    out: set = set()
    if isinstance(value, (ast.Tuple, ast.List, ast.Set)):
        for e in value.elts:
            if isinstance(e, ast.Constant) and isinstance(e.value, str) and e.value.strip():
                out.add(e.value)
    elif isinstance(value, ast.Dict):
        for k in value.keys:
            if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value.strip():
                out.add(k.value)
    return out


def significant_names(blob: Optional[bytes]) -> Optional[set]:
    """Значимые имена файла — или ``None``, если файл не разобран.

    ``None`` здесь значит ровно «не измерено»: пустое множество означало бы «имён
    нет», и склеивать эти два исхода нельзя (инвариант #17).
    """
    if blob is None:
        return None
    try:
        tree = ast.parse(blob.decode("utf-8", "replace"))
    except (SyntaxError, ValueError):
        return None
    return _module_level_names(tree)


def classify_loss(base: Optional[bytes], local: Optional[bytes],
                  remote: Optional[bytes]) -> dict:
    """Что теряет пуш ``local`` поверх ``remote`` при базе ``base``.

    Возвращает словарь с тремя долями и НАЗВАННОЙ причиной, если мерить нечем.
    """
    n_local, n_remote = significant_names(local), significant_names(remote)

    if n_remote is None:
        return {"status": UNMEASURED, "reason": "версия на remote не прочитана или не разбирается",
                DELETED_BY_AUTHOR: [], NEVER_SEEN_BY_AUTHOR: []}
    if n_local is None:
        return {"status": UNMEASURED, "reason": "наша версия не разбирается как Python",
                DELETED_BY_AUTHOR: [], NEVER_SEEN_BY_AUTHOR: []}

    gone = n_remote - n_local
    if not gone:
        return {"status": "clean", "reason": "", DELETED_BY_AUTHOR: [], NEVER_SEEN_BY_AUTHOR: []}

    n_base = significant_names(base)
    if n_base is None:
        # Имена ТЕРЯЮТСЯ, но сказать, видел ли их автор, нечем. Это не «чисто».
        return {"status": UNMEASURED,
                "reason": ("база рабочей копии не установлена — «я удалил» и «я не видел» "
                           "неразличимы"),
                DELETED_BY_AUTHOR: [], NEVER_SEEN_BY_AUTHOR: [], "lost_unattributed": sorted(gone)}

    never_seen = sorted(g for g in gone if g not in n_base)
    deleted = sorted(g for g in gone if g in n_base)
    return {"status": NEVER_SEEN_BY_AUTHOR if never_seen else DELETED_BY_AUTHOR,
            "reason": "", DELETED_BY_AUTHOR: deleted, NEVER_SEEN_BY_AUTHOR: never_seen}


def refusal_text(repo_path: str, verdict: dict) -> str:
    """Текст отказа — НАЗЫВАЕТ утраченное поимённо. Пусто, если терять нечего."""
    never = verdict.get(NEVER_SEEN_BY_AUTHOR) or []
    if never:
        return (
            f"❌ {repo_path}: пуш унёс бы {len(never)} имя(ён), которых НЕТ в вашей базе — "
            f"значит, вы их не удаляли, вы их не видели: {', '.join(never[:12])}"
            f"{' …' if len(never) > 12 else ''}\n"
            f"Так 12.09 коммит 6322d0d56 унёс проводку ADR-343 из моста находок (20 строк, "
            f"о которых сообщение коммита не говорило).\n"
            f"Что делать: перечитать {repo_path} со свежего origin, перенести свою правку на "
            f"него и запушить снова. Осознанная перезапись — `--allow-overwrite`.")
    unattributed = verdict.get("lost_unattributed") or []
    if unattributed:
        return (f"⚠️  {repo_path}: пуш теряет имена ({', '.join(unattributed[:12])}), а базу "
                f"рабочей копии установить нечем — сказать, ваши это удаления или чужие "
                f"правки, НЕЧЕМ: {verdict.get('reason')}")
    return ""
