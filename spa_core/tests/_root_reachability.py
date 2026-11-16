"""Корень, объявленный корнем, сам может быть сиротой — тогда «3» есть ПОЛ.

# LLM_FORBIDDEN

Прибор `_mention_wiring` (ADR-1026) измерил население класса «проводка
упоминанием сироты»: **3 из 213**. В его докстроке честно сказано, чем это
число является:

    Корнем объявлен КАЖДЫЙ остальной файл скана: обёртка, plist, манифест,
    `scripts/**` и модуль-библиотека без точки входа. Про их собственную
    достижимость этот прибор не спрашивает — у `scripts/` на тот вопрос есть
    свой храповик, а у библиотек его нет вовсе.
    Отсюда знак ошибки: объявление корнем может только ПРИБАВИТЬ достижимости,
    значит найденное население — ПОЛ класса, а не его потолок.

Заказ G1015 п. 4 требует это объявление ЗАМЕРИТЬ. Прибор здесь задаёт ровно
тот вопрос, который ADR-1026 не задавал: **достижим ли сам объявленный
корень** — и считает население класса второй раз, от УЗКОГО набора корней.

## Почему это даёт ПОТОЛОК, а не «настоящее число»

Узкий набор корней объявлен поимённо и состоит только из того, что зовут
ИЗВНЕ репозитория:

* `*.plist` — зовёт launchd;
* `.github/workflows/*.y*ml` — зовёт GitHub Actions.

Всё остальное обязано достижимость ЗАРАБОТАТЬ — быть упомянутым файлом,
который сам достижим. Знак ошибки у этого замера **обратный** замеру
ADR-1026: зовущих извне больше, чем названо (cron, рука владельца, промпт
оркестратора в `docs/ORCHESTRATOR_PROTOCOL.md`, Telegram), а поверхность
скана их не содержит. Значит найденное здесь население — **ПОТОЛОК**.

Два числа вместе и есть честный ответ: класс лежит в вилке
`[пол ADR-1026, потолок этого прибора]`, и ни один конец не выдаётся за
другой. Утверждать по потолку «столько членов есть» запрещено ровно так же,
как по полу — «больше членов нет».

## Поверхность CI объявлена ДОБАВЛЕНИЕМ, и это не удобство

`.github/workflows/**` в поверхность `_mention_wiring` не входит вовсе.
Оставить её вне узкого замера значило бы ВЫДУМАТЬ сирот: скрипт, который
зовёт только воркфлоу, стал бы недостижимым из-за слепоты прибора, а не из-за
состояния дерева. Поэтому файлы воркфлоу добавлены в поверхность как
УПОМИНАЮЩИЕ и объявлены корнями; добавление ПЕЧАТАЕТСЯ.

## Три исхода (инвариант #17)

* измерено — вилка названа, оба конца напечатаны;
* измерено и равно нулю — потолок пуст, и это печатается отдельной строкой;
* **НЕ ИЗМЕРЕНО** (`Unmeasured`, код 2) — нечитаемая поверхность, тонкая
  поверхность субъектов, ни одного корня-извне. Ноль таким исходом не
  является: «корней не нашлось» значило бы, что недостижимо ВСЁ, то есть
  прибор доложил бы о себе, а не о дереве.

## Чего прибор НЕ знает и говорит это вслух

1. **Отношение «упоминает» взято у `_mention_wiring`** (а тот берёт его у
   храповика): подстрока стема в срезанном от прозы тексте. Второй копии
   правила здесь нет НАМЕРЕННО.
2. **Коллизия стемов** (`fluid_usdc` против `fluid_usdc_adapter` и прочие
   одноимённые в разных каталогах) может подарить достижимость не тому файлу.
   Число коллизий ИЗМЕРЯЕТСЯ и печатается — это не оговорка, а величина.
3. **«Достижим» ≠ «зовётся»**: упоминание стема не есть вызов. Тот вопрос —
   предмет G1015 п. 3 и здесь не задаётся.
"""
from __future__ import annotations

import argparse
import collections
import datetime as _dt
import json
import pathlib
import sys
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from spa_core.tests import _mention_wiring as _mw

#: Добавление к поверхности `_mention_wiring`: без него прибор выдумал бы сирот
#: среди скриптов, которых зовёт только CI. Объявление ПЕЧАТАЕТСЯ.
CI_SURFACE_DIR = ".github/workflows"
CI_SUFFIXES = (".yml", ".yaml")

#: Пол непустоты поверхности субъектов — то же число и тот же вопрос, что у
#: `_mention_wiring` и у храповика: «сирот нет» не имеет права значить
#: «мерить было нечем».
MIN_SUBJECTS = _mw.MIN_SUBJECTS

REACHABLE = _mw.REACHABLE
ORPHAN_CHAIN = _mw.ORPHAN_CHAIN
CENSUS = _mw.CENSUS

_ROOT = pathlib.Path(__file__).resolve().parents[2]


class Unmeasured(RuntimeError):
    """Поверхность не прочитана, тонка или без корней — это НЕ ноль находок."""


# --------------------------------------------------------------------------- #
# поиск множества подстрок за один проход (Aho — Corasick, только stdlib)
# --------------------------------------------------------------------------- #
class _Multi:
    """Словарь подстрок: `found(text)` отдаёт встретившиеся слова за один проход.

    Наивное `for stem in stems: stem in body` даёт произведение
    «стемы × объём дерева» и на живом дереве не доходит до конца. Отношение
    при этом ТО ЖЕ САМОЕ — подстрока; меняется только цена ответа.
    """

    __slots__ = ("goto", "fail", "out")

    def __init__(self, words: Iterable[str]) -> None:
        self.goto: List[Dict[str, int]] = [{}]
        self.out: List[List[str]] = [[]]
        self.fail: List[int] = [0]
        for w in words:
            if not w:
                continue
            node = 0
            for ch in w:
                nxt = self.goto[node].get(ch)
                if nxt is None:
                    nxt = len(self.goto)
                    self.goto.append({})
                    self.out.append([])
                    self.fail.append(0)
                    self.goto[node][ch] = nxt
                node = nxt
            self.out[node].append(w)
        queue = collections.deque()
        for ch, nxt in self.goto[0].items():
            self.fail[nxt] = 0
            queue.append(nxt)
        while queue:
            node = queue.popleft()
            for ch, nxt in self.goto[node].items():
                queue.append(nxt)
                f = self.fail[node]
                while f and ch not in self.goto[f]:
                    f = self.fail[f]
                cand = self.goto[f].get(ch, 0)
                self.fail[nxt] = 0 if cand == nxt else cand
                self.out[nxt] = self.out[nxt] + self.out[self.fail[nxt]]

    def found(self, text: str) -> Set[str]:
        hits: Set[str] = set()
        node = 0
        goto, fail, out = self.goto, self.fail, self.out
        for ch in text:
            while node and ch not in goto[node]:
                node = fail[node]
            node = goto[node].get(ch, 0)
            if out[node]:
                hits.update(out[node])
        return hits


# --------------------------------------------------------------------------- #
# поверхность
# --------------------------------------------------------------------------- #
def surface(root: pathlib.Path) -> Tuple[Dict[str, str], List[str]]:
    """{путь: текст} поверхности `_mention_wiring` ПЛЮС объявленная поверхность CI.

    Возвращает ещё и список добавленных путей — чтобы добавление можно было
    напечатать, а не держать в уме.
    """
    try:
        texts = dict(_mw.tree_texts(root))
    except _mw.Unmeasured as exc:
        raise Unmeasured(str(exc)) from exc
    added: List[str] = []
    ci = root / CI_SURFACE_DIR
    if ci.is_dir():
        for f in sorted(ci.iterdir()):
            if not f.is_file() or f.suffix not in CI_SUFFIXES:
                continue
            rel = f"{CI_SURFACE_DIR}/{f.name}"
            try:
                body = f.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise Unmeasured(
                    f"файл поверхности CI не прочитан, а он мог быть зовущим: "
                    f"{rel} — {exc}") from exc
            texts[rel] = _mw._ratchet._without_test_paths(body)
            added.append(rel)
    return texts, added


def outside_roots(texts: Dict[str, str]) -> Dict[str, str]:
    """Корни, которые зовут ИЗВНЕ репозитория — поимённо и с причиной."""
    roots: Dict[str, str] = {}
    for p in sorted(texts):
        if p.endswith(".plist"):
            roots[p] = "launchd"
        elif p.startswith(CI_SURFACE_DIR + "/"):
            roots[p] = "github-actions"
    return roots


def _kind(path: str) -> str:
    """Род объявленного корня — тем же делением, что названо в ADR-1026."""
    if path.endswith(".plist"):
        return "plist"
    if path.endswith(".sh"):
        return "обёртка"
    if path.endswith(".json"):
        return "манифест"
    if path.startswith("scripts/"):
        return "scripts (свой храповик)"
    return "библиотека без точки входа (сторожа нет)"


def _reach(mentions: Dict[str, Set[str]], seed: Iterable[str]) -> Tuple[Set[str], int]:
    """Достижимость вперёд по «A упоминает B» от набора `seed`, до фикспойнта."""
    reach: Set[str] = set(seed)
    frontier: Set[str] = set(reach)
    rounds = 0
    while frontier:
        rounds += 1
        nxt: Set[str] = set()
        for p in frontier:
            for q in mentions.get(p, ()):
                if q not in reach:
                    reach.add(q)
                    nxt.add(q)
        frontier = nxt
    return reach, rounds


def measure(root: Optional[pathlib.Path] = None,
            min_subjects: int = MIN_SUBJECTS) -> dict:
    """Замер: достижимость объявленных корней и ПОТОЛОК населения класса."""
    base = (pathlib.Path(root) if root is not None else _ROOT).resolve()
    try:
        subj = _mw.subjects(base)
    except _mw.Unmeasured as exc:
        raise Unmeasured(str(exc)) from exc
    if len(subj) < min_subjects:
        raise Unmeasured(
            f"субъектов всего {len(subj)} при поле {min_subjects} — скан сузился, "
            "и «корни достижимы» значило бы «мерить было нечем»")
    texts, ci_added = surface(base)
    seeds = outside_roots(texts)
    if not seeds:
        raise Unmeasured(
            "ни одного корня-извне (plist, воркфлоу CI) в поверхности — "
            "недостижимым оказалось бы ВСЁ, и прибор доложил бы о себе, "
            "а не о дереве")

    stem_of = {p: pathlib.Path(p).stem for p in texts}
    by_stem: Dict[str, List[str]] = collections.defaultdict(list)
    for p, s in stem_of.items():
        by_stem[s].append(p)
    collisions = {s: sorted(ps) for s, ps in by_stem.items() if len(ps) > 1}

    finder = _Multi(sorted(by_stem))
    mentions: Dict[str, Set[str]] = {}
    for p, body in texts.items():
        tgt: Set[str] = set()
        for s in finder.found(body):
            for q in by_stem[s]:
                if q != p:
                    tgt.add(q)
        mentions[p] = tgt

    subj_set = set(subj)
    mentioned_by = {m: sorted(p for p in texts if p != m and m in mentions[p])
                    for m in subj}

    # ── замер ADR-1026: корнем объявлен каждый не-субъект ──────────────────
    declared_roots = sorted(p for p in texts if p not in subj_set)
    reach_declared, rounds_declared = _reach(mentions, declared_roots)
    floor = sorted(m for m in subj
                   if mentioned_by[m] and m not in reach_declared)

    # ── замер этого прибора: корень обязан достижимость ЗАРАБОТАТЬ ─────────
    reach_narrow, rounds_narrow = _reach(mentions, seeds)
    ceiling = sorted(m for m in subj
                     if mentioned_by[m] and m not in reach_narrow)
    dead_roots = sorted(p for p in declared_roots if p not in reach_narrow)
    by_kind = collections.Counter(_kind(p) for p in dead_roots)

    return {
        "measured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "root": str(base),
        "subjects": len(subj),
        "surface_files": len(texts),
        "ci_surface_added": ci_added,
        "outside_roots": seeds,
        "declared_roots": len(declared_roots),
        "declared_roots_unreachable": dead_roots,
        "declared_roots_unreachable_by_kind": dict(sorted(by_kind.items())),
        "population_floor": floor,
        "population_ceiling": ceiling,
        "fixpoint_rounds_declared": rounds_declared,
        "fixpoint_rounds_narrow": rounds_narrow,
        "stem_collisions": len(collisions),
        "bracket_not_a_number": True,
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="достижимость ОБЪЯВЛЕННЫХ корней + потолок класса (ADVISORY)")
    ap.add_argument("--root", default=None, help="дерево замера; умолчание ПЕЧАТАЕТСЯ")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--min-subjects", type=int, default=MIN_SUBJECTS,
                    help="пол непустоты поверхности; сдвиг ПЕЧАТАЕТСЯ")
    a = ap.parse_args(argv)
    if a.root is None:
        print(f"[дерево] умолчание: {_ROOT}", file=sys.stderr)
    if a.min_subjects != MIN_SUBJECTS:
        print(f"[пол] объявлен {a.min_subjects} вместо {MIN_SUBJECTS} — "
              "осознанный сдвиг", file=sys.stderr)
    try:
        rep = measure(pathlib.Path(a.root) if a.root else None,
                      min_subjects=a.min_subjects)
    except Unmeasured as exc:
        print(f"НЕ ИЗМЕРЕНО: {exc}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if rep["declared_roots_unreachable"] else 0
    print(f"дерево: {rep['root']}")
    print(f"[поверхность CI ДОБАВЛЕНА] файлов {len(rep['ci_surface_added'])} — "
          "без них прибор выдумал бы сирот среди скриптов, которых зовёт только CI")
    print(f"файлов поверхности: {rep['surface_files']} · субъектов: {rep['subjects']}"
          f" · коллизий стемов: {rep['stem_collisions']}")
    print(f"корней-извне названо: {len(rep['outside_roots'])}"
          f" (plist + {CI_SURFACE_DIR})")
    print(f"ОБЪЯВЛЕННЫХ корней: {rep['declared_roots']}"
          f" · из них САМИ НЕДОСТИЖИМЫ: {len(rep['declared_roots_unreachable'])}")
    for kind, n in rep["declared_roots_unreachable_by_kind"].items():
        print(f"      {kind}: {n}")
    print(f"ВИЛКА класса «проводка упоминанием сироты»: "
          f"пол {len(rep['population_floor'])} … потолок {len(rep['population_ceiling'])}"
          f" (раундов фикспойнта: объявленный {rep['fixpoint_rounds_declared']},"
          f" узкий {rep['fixpoint_rounds_narrow']})")
    if not rep["population_ceiling"]:
        print("   потолок ИЗМЕРЕН И РАВЕН НУЛЮ — не то же, что «не измерен»")
    for m in rep["population_ceiling"]:
        mark = " [и в полу]" if m in rep["population_floor"] else ""
        print(f"   • {m}{mark}")
    if not rep["declared_roots_unreachable"]:
        print("✅ каждый объявленный корень достижим — пол ADR-1026 совпал с потолком")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
