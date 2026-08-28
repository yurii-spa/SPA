"""card_delivery.py — доставка карточек, рождённых В РАНТАЙМЕ, до `origin/main`.

**Зачем.** Мост находок ADR-066 (`findings_bridge.py`) заводит карточку в том
дереве, из которого запущен, — то есть в прод-дереве `~/Documents/SPA_Claude`.
Пуша в мосте нет ни одной строкой, а доставка в это дерево не заглядывает
никогда: пуши идут ПРЯМО на origin, хост-копия дрейфует по построению.

Замер 2026-08-08 (цикл #170), карточка
`inbox-kartochki-mosta-nahodok-rozhdayutsya-v-p`:

* карточек с `finding_key:` в прод-дереве — **11**, на `origin/main` — **7**;
* но все семь приземлились ровно потому, что родились 06.08 в worktree
  разработчика фаз ADR-066 и уехали его же пушем (`git log --diff-filter=A`:
  коммиты «ADR-066 Фаза 1/3/4»);
* из рождённых **в рантайме** агентом `com.spa.decision_loop` доставлено
  **0 из 4** — все четыре `needs-owner`, то есть по протоколу ждут владельца.

Карточка `needs-owner`, которой нет на origin, для очереди владельца НЕ
СУЩЕСТВУЕТ (`CLAUDE.md` инв. 13 «источник правды — файлы в git»;
`orchestrator_queue.py list` сверяется с `origin/main` с цикла #147). При этом
Telegram-уведомление мост шлёт — владелец получает тревогу, за которой нет
ничего. Это класс fail-OPEN: инструмент честно сделал свою часть и промолчал о
том, что последний метр не пройден.

**Дисциплина (каждое правило — против конкретного отказа):**

``только карточки``   везём ТОЛЬКО файлы из `nimbalyst-local/tracker/*.md`.
                      Путь вне каталога — отказ ВСЕЙ пачки, а не тихое
                      выбрасывание лишнего (правило «no silent caps»);
``_BOARD.md никогда`` доска — общая память (`push_to_github.SHARED_MEMORY_DOCS`),
                      и из прод-дерева базу пуша установить нечем ⇒ пушер
                      отказывает fail-CLOSED (ADR-070 п.7) и уронил бы всю
                      пачку. Доска регенерится у любой сессии, карточка — нет;
``одна пачка``        все карточки прогона уходят ОДНИМ атомарным коммитом
                      (урок #53: набор файлов пофайлово = N коммитов, любой
                      промежуточный `main` мог быть красным);
``fail-CLOSED``       «не измерено» ≠ «доставлено»: сбой пушера → ``FAILED``,
                      исключение/таймаут → ``UNCHECKED``, выключено флагом →
                      ``DISABLED``. Ни один из этих исходов не молчит и ни один
                      не выглядит успехом; пустой список → ``IDLE``, а не «OK».

**Обновление карточки — отдельная задача от её рождения (замер 2026-08-12, цикл
#200).** Доставка умела только СОЗДАВАТЬ. Пушер сравнивает нашу версию с базой
РАБОЧЕЙ КОПИИ (``HEAD:<путь>``), а карточка, рождённая мостом в прод-дереве, в
HEAD этого дерева не попадает НИКОГДА (прод синкается копированием
``spa_core/``·``scripts/``·``tests/``, не ``git checkout``). Отсюда две разные
судьбы одного и того же файла:

* **создание** — пути нет ни в базе, ни на remote ⇒ ``DIVERGENCE_SAFE``, пуш идёт;
* **любое последующее обновление** — ``absent_in_base`` + файл на remote ЕСТЬ ⇒
  ``DIVERGENCE_DIVERGED`` ⇒ отказ, код возврата 4. И так БУДЕТ ВСЕГДА.

Измерено: ``delivery.status=FAILED`` (rc 4, attempted 3, delivered 0); карточка
``inbox-nahodka-petli-data-investment-os-health`` рождена самой доставкой
(коммит ``64031ee90``) и закрыта в прод-дереве, а на origin висит ``new``.
Пачка атомарна, поэтому два застрявших обновления утащили с собой ЧУЖОЕ
создание (``…docs-system-briefing-md-po`` не попало на origin вовсе).

**Что делаем — ровно то, что советует сам текст отказа пушера:** перечитываем
версию с remote и переносим на неё СВОЮ правку (:func:`rebase_card`). Перенос
разрешён только там, где он ДОКАЗУЕМ: ``set_status`` меняет ровно одну строку
``status:`` во frontmatter и больше ничего (см. ``owner_queue/queue.py``),
поэтому «remote с нашей строкой ``status:``» обязано совпасть с нашим файлом
БАЙТ В БАЙТ. Совпало — перезапись осознанная (``--allow-overwrite``), потому
что содержимое remote прочитано, а наша правка — одна известная строка. Не
совпало — ОТКАЗ по этой карточке с названной причиной; остальные едут.

Побочно закрыт второй дефект того же корня: мост решает «карточку никто не
трогал ⇒ можно закрыть» по СВОЕЙ стухшей копии, которая не видит ни ответа
владельца (``owner_choice``), ни захвата сессией (``claimed_by``), сделанных на
origin. Теперь такое расхождение видно как лишняя строка frontmatter — и
закрытие отменяется, а не стирает ответ владельца (инвариант #14, fail-CLOSED).

**Граница честности.** Между чтением remote и пушем есть окно: одновременная
правка карточки на origin будет перезаписана. Поэтому в квитанцию пишется sha
прочитанного remote — потеря остаётся хотя бы вычислимой. Прочитать remote
нечем (нет пушера/PAT/сети) ⇒ ``rebase_unmeasured``, и дальше решает СОСТАВ
пачки, потому что ``--allow-overwrite`` не выборочный — он действует на всю
команду пушера сразу:

* в пачке переносов НЕТ ⇒ путь едет как раньше, без флага, и решение остаётся
  за пушером — он fail-CLOSED и откажет сам;
* в пачке ЕСТЬ перенос ⇒ путь **придерживается** до следующего прогона
  (``held``): поехав под чужим флагом, он лишился бы единственной защиты,
  какая у него была, и слепая копия могла бы стереть ответ владельца,
  которого она не видела.

«Не измерено» и «придержано» названы в квитанции, а не выглядят проверкой.

Квитанция: `data/card_delivery_status.json` (атомарно) + блок ``delivery`` в
`data/findings_bridge_report.json` — его читает обязательный шаг 0-офис
оркестратора (`scripts/consume_office_reports.py`), поэтому сбой доставки
попадает В КОНТЕКСТ сессии, а не в файл, который никто не обязан открыть.

LLM_FORBIDDEN. Только stdlib.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys

from spa_core.monitoring.architecture_conformance import REPO_ROOT

STATUS_REL = os.path.join("data", "card_delivery_status.json")
#: Долг доставки: пути, которые доставку НЕ прошли и обязаны поехать снова.
#: Отдельный файл, а не поле квитанции: квитанция — рассказ об ОДНОМ прогоне,
#: долг переживает прогоны (в этом вся суть, см. ADR-081).
DEBT_REL = os.path.join("data", "card_delivery_debt.json")
TRACKER_REL = os.path.join("nimbalyst-local", "tracker")
PUSHER_REL = "push_to_github.py"
PUSH_TIMEOUT = 300
REMOTE_TIMEOUT = 30

#: Имена, которые доставка не везёт даже если её попросили прямо.
NEVER_DELIVER = ("_BOARD.md",)

#: Переменная окружения-выключатель (владельцу — одна команда, без правки кода).
ENV_FLAG = "SPA_CARD_DELIVERY"

DELIVERED = "DELIVERED"
FAILED = "FAILED"
REFUSED = "REFUSED"
UNCHECKED = "UNCHECKED"
DISABLED = "DISABLED"
IDLE = "IDLE"
#: Часть пачки уехала, часть — нет. Читается как ОТКАЗ, а не как успех: «сколько
#: получилось» в этом проекте всегда было формой тихой потери.
PARTIAL = "PARTIAL"
#: Своего груза у прогона не было, но долг доставки НЕ ПУСТ. Отдельный вид, а не
#: `IDLE`: «мне нечего везти» и «я кое-что должен» — разные утверждения, и
#: схлопывание их в одно и есть та авария, ради которой заведён долг.
DEBT = "DEBT"

#: Исходы, которые НЕ означают «карточки на origin». Читателю квитанции не надо
#: помнить список статусов, чтобы не принять отказ за успех.
NOT_DELIVERED = (FAILED, REFUSED, UNCHECKED, DISABLED, PARTIAL, DEBT)

#: Сколько прогонов подряд путь может не доезжать, прежде чем его назовут
#: «сам не рассосётся». Не снимает долг (снять может только origin) — поднимает
#: голос: транзиентная сеть лечится повтором, отказ переноса ждёт человека.
DEBT_STALE_ATTEMPTS = 5

#: Состояния версии карточки на origin. ``UNMEASURED`` — отдельный вид, а не
#: «файла нет»: `get_file_sha`/`get_file_content` пушера схлопывают 404 и обрыв
#: сети в один `None`, и именно на таком схлопывании держится класс fail-OPEN.
REMOTE_PRESENT = "present"
REMOTE_ABSENT = "absent"
REMOTE_UNMEASURED = "unmeasured"

#: Поля frontmatter, появление которых на origin означает «карточку уже увидели»:
#: ответ владельца (кнопки ADR-069) или захват сессией (шаг 0b протокола).
#: Нужны не для решения (решает побайтовое сравнение), а чтобы НАЗВАТЬ причину.
SEEN_ON_ORIGIN_FIELDS = (b"owner_choice", b"owner_answered_at", b"owner_answered_by",
                         b"claimed_by", b"claimed_at")

_STATUS_LINE = re.compile(rb"(?m)^status:[^\n]*\n")

#: Ключ следа переходов во frontmatter. Байтовая копия
#: ``spa_core.owner_queue.status_audit.TRAIL_KEY``: здесь карточка ещё БАЙТЫ, до
#: всякого декодирования, а расхождение двух копий закреплено тестом
#: (``test_card_delivery_carries_status_trail.py::test_trail_key_matches_the_writer``).
_TRAIL_KEY = b"status_trail"

#: Разделитель полей ВНУТРИ строки следа. Байтовая копия
#: ``status_audit.TRAIL_SEP`` — по той же причине и с тем же обязательством:
#: расхождение копий закреплено тестом против НАСТОЯЩЕГО писателя
#: (``trail_line``), а не против литерала, переписанного сюда по памяти.
_TRAIL_SEP = " · ".encode("utf-8")

#: Голова строки следа: ``<ts> <old> -> <new>``. Байтовая копия
#: ``status_audit._TRAIL_LINE_RE``; пинится тем же тестом.
_TRAIL_ARROW = re.compile(rb"^(?P<ts>\S+)[ \t]+(?P<old>\S+)[ \t]*->[ \t]*(?P<new>\S+)$")


def _now(now: dt.datetime | None = None) -> dt.datetime:
    return now or dt.datetime.now(dt.timezone.utc)


def _rel(root: str, path: str) -> str:
    try:
        return os.path.relpath(os.path.realpath(path), os.path.realpath(root))
    except Exception:  # noqa: BLE001 — путь на другом томе: показать как есть
        return path


def is_enabled(env=None) -> bool:
    """Выключатель владельца. По умолчанию доставка ВКЛЮЧЕНА."""
    env = os.environ if env is None else env
    return str(env.get(ENV_FLAG, "1")).strip().lower() not in ("0", "off", "false", "no")


def validate(paths, root: str = REPO_ROOT) -> tuple[list, list]:
    """``(годные абсолютные пути, [{path, reason} …])`` — порядок сохранён, дубли сняты.

    Отказ НАЗЫВАЕТСЯ по каждому пути отдельно: «не доставили» без причины —
    ровно та фигура, из-за которой карточки терялись молча.
    """
    tracker = os.path.realpath(os.path.join(root, TRACKER_REL))
    ok: list[str] = []
    bad: list[dict] = []
    seen: set[str] = set()
    for p in paths or []:
        if not p:
            continue
        absolute = os.path.realpath(os.path.join(root, str(p)))
        if absolute in seen:
            continue
        seen.add(absolute)
        parent = os.path.dirname(absolute)
        name = os.path.basename(absolute)
        if parent != tracker:
            bad.append({"path": _rel(root, absolute),
                        "reason": f"путь вне {TRACKER_REL} — доставка возит только карточки"})
        elif not name.endswith(".md"):
            bad.append({"path": _rel(root, absolute), "reason": "не .md — это не карточка"})
        elif name in NEVER_DELIVER:
            bad.append({"path": _rel(root, absolute),
                        "reason": ("общая память (push_to_github.SHARED_MEMORY_DOCS): база пуша "
                                   "из прод-дерева неизмерима ⇒ пушер отказал бы fail-CLOSED "
                                   "и уронил всю пачку; доска регенерится у любой сессии")})
        elif not os.path.isfile(absolute):
            bad.append({"path": _rel(root, absolute), "reason": "файла нет на диске"})
        else:
            ok.append(absolute)
    return ok, bad


# ── перенос нашей правки на свежую версию с origin ───────────────────────────

def card_parts(blob: bytes):
    """``(frontmatter_без_разделителей, тело)`` или ``None`` — это не карточка."""
    if not isinstance(blob, bytes) or not blob.startswith(b"---\n"):
        return None
    end = blob.find(b"\n---\n", 3)
    if end < 0:
        return None
    return blob[4:end + 1], blob[end + 5:]


def blob_sha(content: bytes) -> str:
    """git-sha содержимого — тот же расчёт, что у пушера (для квитанции)."""
    h = hashlib.sha1()
    h.update(b"blob %d\0" % len(content))
    h.update(content)
    return h.hexdigest()


def origin_covers_card(local: bytes, remote: bytes) -> tuple:
    """Версия origin содержит ВСЁ наше и сверх того? → ``(да/нет, [лишние строки])``.

    Отвечает на вопрос «наша правка УЖЕ доехала?», который до 17.08 подменялся
    вопросом «файлы совпали побайтово?» (``plan_batch``: ``remote == local``).
    Это разные вопросы, и расходятся они ровно там, где origin обгоняет нашу
    слепую копию: ``claimed_by`` от шага 0b, ``owner_choice`` от кнопок ADR-069.
    Прод-дерево ``nimbalyst-local/`` не синкает вовсе, значит наша копия эти
    поля не получит НИКОГДА — побайтовое равенство переставало быть достижимым
    навсегда, и закрытие, уже лежащее на origin, каждый прогон записывалось в
    непогасимый долг (ADR-081 запрещает `IDLE` при непустом долге ⇒ красная
    строка шага 0-офис каждый цикл; ложный долг топит настоящий).

    Доказательство узкое и полное: строки нашего frontmatter обязаны лежать в
    frontmatter origin ПОДПОСЛЕДОВАТЕЛЬНОСТЬЮ (порядок сохранён), а тело —
    совпасть побайтово. Тогда содержимое нашего файла целиком содержится в
    версии origin, и везти нечего — не «примерно то же», а буквально ничего.

    Подпоследовательность ловит и подмену: если origin ИЗМЕНИЛ значение строки,
    которая есть у нас (тот же ``status:``, другой статус), нашей строки в нём
    не окажется — покрытия нет, и путь уходит в прежний отказ ``rebase_card``.
    Поэтому ветка не смеет ничего перезаписать: она вообще ничего не пишет.
    """
    lp, rp = card_parts(local), card_parts(remote)
    if lp is None or rp is None:
        return False, []
    l_fm, l_body = lp
    r_fm, r_body = rp
    # Frontmatter и тело сверяются ПОРОЗНЬ: иначе наша строка `status:` могла бы
    # «найтись» в чужом теле (карточки цитируют frontmatter друг друга сплошь и
    # рядом) — и покрытие доказывалось бы совпадением, к делу не относящимся.
    fm_ok, fm_extra = _covered_lines(l_fm, r_fm)
    if not fm_ok:
        return False, []
    body_ok, body_extra = _covered_lines(l_body, r_body)
    if not body_ok:
        return False, []
    return True, fm_extra + ([f"+{len(body_extra)} строк(и) тела"] if body_extra else [])


def _covered_lines(ours: bytes, theirs: bytes) -> tuple:
    """Наши строки лежат в чужих ПОДПОСЛЕДОВАТЕЛЬНОСТЬЮ? → ``(да/нет, лишние)``.

    Пропускает ровно один вид расхождения — ДОПИСАННОЕ на origin. Изменённая
    строка (тот же ``status:``, другой статус) и удалённая строка нашей копии в
    чужой последовательности не найдутся, и покрытия не будет: «origin ушёл
    вперёд» и «origin разошёлся с нами» обязаны решаться по-разному.
    """
    them = theirs.splitlines(keepends=True)
    extra: list = []
    i = 0
    for line in ours.splitlines(keepends=True):
        while i < len(them) and them[i] != line:
            extra.append(them[i].decode("utf-8", "replace").rstrip("\n"))
            i += 1
        if i >= len(them):
            return False, []          # нашей строки на origin нет — покрытия нет
        i += 1
    extra.extend(ln.decode("utf-8", "replace").rstrip("\n") for ln in them[i:])
    return True, [e for e in extra if e.strip()]


def split_trail_block(fm: bytes) -> tuple:
    """frontmatter → ``(без блока status_trail, сам блок)``. Блока нет ⇒ ``(fm, b"")``.

    Блок — строка ключа ``status_trail:`` плюс идущие за ней отступные строки, ровно
    как их пишет ``status_audit.stamp_trail``. Разбор построчный и байтовый: YAML сюда
    тащить нельзя (рантайм — только stdlib), а «примерно распарсить» карточку значило бы
    решать судьбу чужой правки по догадке.
    """
    kept: list = []
    block: list = []
    inside = False
    for line in fm.splitlines(keepends=True):
        if line[:1] not in (b" ", b"\t"):
            inside = line.split(b":", 1)[0].strip() == _TRAIL_KEY if b":" in line else False
            (block if inside else kept).append(line)
            continue
        (block if inside else kept).append(line)
    return b"".join(kept), b"".join(block)


def _trail_items(block: bytes) -> list:
    """Строки-записи следа (отступные ``- …``) в порядке записи."""
    return [ln for ln in block.splitlines(keepends=True) if ln[:1] in (b" ", b"\t")]


def trail_only_appends(ours: bytes, theirs: bytes) -> bool:
    """Наш след — след origin ПЛЮС дописанное? (порядок сохранён)

    След append-only по построению (``stamp_trail`` дописывает в конец). Значит
    законная разница ровно одна: у нас есть записи, которых origin ещё не видел.
    Запись, которая есть на origin и которой нет у нас, означает обратное — мы
    отстали, — и переносить наш след поверх нельзя: он стёр бы чужой переход.
    Fail-CLOSED: сомнение решается отказом, а отказ разбирается руками.
    """
    mine = _trail_items(ours)
    i = 0
    for line in _trail_items(theirs):
        while i < len(mine) and mine[i] != line:
            i += 1
        if i >= len(mine):
            return False
        i += 1
    return True


def trail_arrow(item: bytes):
    """Переход, записанный строкой следа → ``(old, new)`` или ``None``.

    Разбор ровно тот же, что у читателя следа (``status_audit.read_trail``):
    снять отступ и дефис, снять кавычки, взять ДО первого ``·`` (дальше идут
    ``source``/``session`` — они к переходу не относятся) и прочесть стрелку.
    Нечитаемая строка отдаёт ``None``, а не догадку: выдуманный переход здесь
    решал бы судьбу чужой правки.
    """
    raw = item.strip()
    if raw.startswith(b"-"):
        raw = raw[1:].strip()
    if len(raw) >= 2 and raw[:1] == raw[-1:] and raw[:1] in (b'"', b"'"):
        raw = raw[1:-1]
    m = _TRAIL_ARROW.match(raw.split(_TRAIL_SEP)[0].strip())
    return (m.group("old"), m.group("new")) if m else None


def origin_reached_same_outcome(local: bytes, remote: bytes) -> tuple:
    """Origin пришёл к ТОМУ ЖЕ исходу своим путём? → ``(да/нет, причина)``.

    Последний вопрос семьи, и задавать его можно ТОЛЬКО после отказа
    :func:`rebase_card` — иначе он заслонил бы работающий перенос:

    * ``remote == local`` — «файлы совпали побайтово»;
    * :func:`origin_covers_card` — «origin содержит всё наше и сверх того»;
    * :func:`rebase_card` — «нашу правку можно перенести на свежий origin»;
    * здесь — «origin содержит всё наше КРОМЕ следа, а наш след не несёт
      перехода, которого у origin нет», то есть везти вообще нечего.

    **Замер 28.08 (цикл #406).** Пять живых карточек ``inbox-nahodka-petli-*``
    получали отказ ``trail_only_appends`` каждый прогон: на origin лежала запись
    ``new -> done`` от 10:41Z (``cycle-14899``), а в прод-дереве — своя,
    ``new -> done`` от 19:15Z. Отказ верен и остаётся: наш след ЧУЖОЙ не
    дописывает, он с ним разошёлся, и перенос стёр бы чужой переход. Неверен был
    ВЫВОД: путь уходил в долг доставки, долг по ADR-081 запрещает ``IDLE`` ⇒
    красная строка шага 0-офис каждый цикл. А везти было нечего — origin уже
    ``done``, тот же переход, записанный РАНЬШЕ и другой сессией; наша запись —
    повторное закрытие уже закрытой карточки, и доставка добавила бы ВТОРУЮ
    запись об одном переходе. Сойтись копии не могут по построению: прод-дерево
    не синкает ``nimbalyst-local/`` (CLAUDE.md §1) ⇒ ложный долг вечен, а вечный
    ложный долг топит настоящий — ровно та слепота, ради которой ADR-081 заведён.

    Ветка НИЧЕГО НЕ ПИШЕТ и пушер не зовёт — ослабить п.3 ADR-080 («ответ
    владельца отменяет закрытие») она не может по построению.

    Доказательство узкое и полное, каждое условие закрывает свой обход:

    1. вне следа версия origin содержит всё наше (frontmatter и тело — ПОРОЗНЬ,
       той же подпоследовательностью, что :func:`origin_covers_card`). Отсюда же
       следует равенство ``status:``: изменённая на origin строка в нашей не
       найдётся;
    2. КАЖДАЯ наша запись следа, которой на origin нет ДОСЛОВНО, называет
       переход, который на origin УЖЕ записан. Наш ``in-progress -> done`` при
       чужом ``new -> done`` покрытия не даёт: это разные переходы, а не разные
       отметки времени одного;
    3. таких записей есть хотя бы одна — иначе утверждать нечего, и вопрос
       принадлежит вёдрам выше.

    Условий ровно три, и это тоже решение. Первая редакция несла ещё четыре —
    «след есть у нас», «след есть у origin», «следы не совпали», отдельный отказ
    на неразобранную строку, — и НИ ОДНО из них мутация не покрасила: каждое уже
    следовало из правил 2 и 3 (пустой чужой след не даёт ни одной стрелки;
    пустой наш и совпавший не дают ни одной СВОЕЙ записи; мусор не даёт стрелки
    и не совпадает ни с чем). Сторож, который не может сработать, — украшение,
    и держать его значит выдавать длину проверки за её силу.
    """
    lp, rp = card_parts(local), card_parts(remote)
    if lp is None or rp is None:
        return False, ""
    l_fm, l_body = lp
    r_fm, r_body = rp
    l_rest, l_trail = split_trail_block(l_fm)
    r_rest, r_trail = split_trail_block(r_fm)
    if not _covered_lines(l_rest, r_rest)[0] or not _covered_lines(l_body, r_body)[0]:
        return False, ""
    theirs_items = _trail_items(r_trail)
    theirs = {a for a in (trail_arrow(i) for i in theirs_items) if a is not None}
    ours_only: list = []
    for item in _trail_items(l_trail):
        if item in theirs_items:
            continue
        arrow = trail_arrow(item)
        if arrow not in theirs:      # `None` сюда попадает и отказывает вместе с мусором
            return False, ""
        ours_only.append(f"{arrow[0].decode()} -> {arrow[1].decode()}")
    if not ours_only:
        return False, ""
    return True, ("origin пришёл к тому же исходу РАНЬШЕ нас: переход(ы) "
                  + ", ".join(sorted(set(ours_only)))
                  + " уже записаны на origin другой сессией, а наша запись следа — "
                    "повторное закрытие уже закрытой карточки; вне следа версия origin "
                    "содержит всё наше. Везти нечего — доставка добавила бы вторую "
                    "запись об одном переходе")


def rebase_card(local: bytes, remote: bytes) -> tuple:
    """Перенести НАШУ правку карточки на версию с origin → ``(bytes|None, причина)``.

    Правка моста над существующей карточкой — это строка ``status:`` И след
    перехода ``status_trail:``: ``owner_queue.queue.set_status`` пишет обе части
    ОДНОЙ записью (``status_audit.stamp_trail``), иначе падение между двумя
    записями породило бы неатрибутированный переход. Всё остальное сохраняется
    байт в байт. Поэтому перенос доказуем без слияния «по смыслу»: берём remote,
    подставляем НАШУ строку ``status:`` и НАШ блок следа — результат обязан
    совпасть с нашим файлом побайтово. Совпал ⇒ ничего чужого мы не теряем.
    Не совпал ⇒ на origin есть что-то, чего мы не видели, и перезаписывать это
    нельзя.

    **Замер 27.08 (цикл #394).** Прежняя посылка «правка — РОВНО одна строка
    ``status:``» устарела в тот день, когда след поехал вместе с карточкой
    (решение владельца, вариант 1). С тех пор КАЖДОЕ закрытие карточки, сделанное
    ``set_status``, шло мимо переноса: карточка
    ``inbox-nahodka-petli-vozmozhnost-fluid-fusdc-5-2`` получила
    «расхождение … не сводится к одной строке status:» шесть прогонов подряд,
    и шаг 0-офис каждый раз печатал долг доставки. Отказ был честен по своему
    контракту и отвечал не на тот вопрос — тот самый класс, ради которого сторожа
    и разделяют. Отказ здесь по-прежнему не ослаблен: расширена ровно посылка о
    том, ЧТО пишет наш писатель, а доказательство осталось побайтовым.

    Отказ НАЗЫВАЕТ причину: «сделали не то» и «мы ослепли» — разные аварии.
    """
    lp, rp = card_parts(local), card_parts(remote)
    if lp is None:
        return None, "наша копия не карточка (нет frontmatter) — переносить нечего"
    if rp is None:
        return None, "версия на origin не карточка (нет frontmatter) — сравнивать не с чем"
    l_fm, _l_body = lp
    r_fm, _r_body = rp
    ours = _STATUS_LINE.search(l_fm)
    if ours is None:
        return None, "в нашей копии нет строки status: — правка не опознана"
    if _STATUS_LINE.search(r_fm) is None:
        return None, "на origin нет строки status: — карточка другой формы"
    candidate = remote[:4] + _STATUS_LINE.sub(ours.group(0), r_fm, count=1) + remote[4 + len(r_fm):]
    if candidate == local:
        return candidate, ""
    # Вторая попытка — та же правка, но с нашим следом перехода. Порядок именно
    # такой: карточка БЕЗ следа (созданная до решения о следе, правленная руками)
    # обязана переноситься ровно как раньше, и первая ветка это и делает.
    l_rest, l_trail = split_trail_block(l_fm)
    r_rest, r_trail = split_trail_block(r_fm)
    if l_trail and l_trail != r_trail:
        if not trail_only_appends(l_trail, r_trail):
            return None, ("на origin есть записи следа status_trail, которых нет в нашей "
                          "копии — наш след не дописан к чужому, а разошёлся с ним; "
                          "перенос стёр бы чужой переход")
        # Блок следа `stamp_trail` всегда кладёт В КОНЕЦ frontmatter; строим кандидата
        # ровно так же и требуем побайтового совпадения — иначе на origin лежит форма,
        # которой мы не видели, и это снова отказ, а не догадка.
        merged_fm = _STATUS_LINE.sub(ours.group(0), r_rest, count=1) + l_trail
        candidate = remote[:4] + merged_fm + remote[4 + len(r_fm):]
        if candidate == local:
            return candidate, ""
    seen = [f.decode() for f in SEEN_ON_ORIGIN_FIELDS
            if re.search(rb"(?m)^" + f + rb":", r_fm) and not re.search(rb"(?m)^" + f + rb":", l_fm)]
    if seen:
        return None, (f"на origin карточку УЖЕ увидели (поля: {', '.join(seen)}) — "
                      f"наша слепая копия не смеет это стереть; закрытие отменено")
    return None, ("расхождение с origin не сводится к строке status: и следу "
                  "status_trail: — перенести правку автоматически нечем; сделать это "
                  "вручную из worktree на origin/main")


def _load_pusher_module(root: str):
    """Модуль пушера как библиотека (константы REPO/API_BASE + `get_pat`)."""
    import importlib.util
    path = os.path.join(root, PUSHER_REL)
    if not os.path.isfile(path):
        return None
    spec = importlib.util.spec_from_file_location("_spa_pusher_for_delivery", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _default_remote_reader(root: str, repo_path: str) -> tuple:
    """``(состояние, bytes|None, причина)`` — версия карточки на `origin/main`.

    Транспорт берём у пушера (PAT из Keychain, тот же репозиторий), но 404
    отделяем от сбоя САМИ: у пушера обе беды схлопнуты в ``None``, а нам
    «файла на origin нет» и «мы не смогли посмотреть» обязаны дать разные
    решения — иначе слепота выглядела бы как чистое создание.
    """
    import urllib.error
    import urllib.request
    try:
        mod = _load_pusher_module(root)
        if mod is None:
            return REMOTE_UNMEASURED, None, f"инструмента доставки нет: {PUSHER_REL}"
        pat = mod.get_pat()
        url = f"{mod.API_BASE}/repos/{mod.REPO}/contents/{repo_path}?ref=main"
        req = urllib.request.Request(url, headers={
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github.raw+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        with urllib.request.urlopen(req, timeout=REMOTE_TIMEOUT) as resp:
            return REMOTE_PRESENT, resp.read(), ""
    except urllib.error.HTTPError as e:  # noqa: PERF203 — 404 это ОТВЕТ, а не сбой
        if e.code == 404:
            return REMOTE_ABSENT, None, "на origin файла нет — это создание"
        return REMOTE_UNMEASURED, None, f"HTTP {e.code} при чтении origin"
    except Exception as e:  # noqa: BLE001
        return REMOTE_UNMEASURED, None, f"{type(e).__name__}: {e}"


def plan_batch(root: str, paths: list, reader=_default_remote_reader) -> dict:
    """Что делать с каждой карточкой пачки ДО пуша.

    ``{to_push, rebased, refused, already_on_origin, covered_by_origin,
    same_outcome_on_origin, unmeasured, held}`` — ни один путь не исчезает
    молча: он либо в пачке, либо назван в одном из списков.
    """
    plan = {"to_push": [], "rebased": [], "refused": [],
            "already_on_origin": [], "covered_by_origin": [],
            "same_outcome_on_origin": [],
            "unmeasured": [], "held": []}
    for absolute in paths:
        repo_path = _rel(root, absolute).replace(os.sep, "/")
        try:
            with open(absolute, "rb") as f:
                local = f.read()
        except Exception as e:  # noqa: BLE001
            plan["refused"].append({"path": repo_path, "reason": f"файл не прочитан: {e}"})
            continue
        state, remote, why = reader(root, repo_path)
        if state == REMOTE_ABSENT:
            plan["to_push"].append(absolute)
            continue
        if state != REMOTE_PRESENT or remote is None:
            plan["unmeasured"].append({"path": repo_path, "reason": why or "не измерено"})
            plan["to_push"].append(absolute)  # решение остаётся за пушером (он fail-CLOSED)
            continue
        if remote == local:
            plan["already_on_origin"].append(repo_path)
            continue
        # «Наше уже на origin» — ОТДЕЛЬНОЕ ведро, а не побайтовое совпадение:
        # схлопнуть их значило бы объявить файлы одинаковыми, когда они разные.
        # Судьба общая (везти нечего, долга нет), утверждение — разное.
        covered, extra = origin_covers_card(local, remote)
        if covered:
            plan["covered_by_origin"].append(
                {"path": repo_path,
                 "reason": ("наша правка УЖЕ на origin; версия origin содержит всё наше "
                            "и сверх того" + (f" ({', '.join(extra)})" if extra else ""))})
            continue
        merged, reason = rebase_card(local, remote)
        if merged is None:
            # Отказ переноса верен — но он отвечает на вопрос «можно ли перенести
            # НАШУ правку», а не на вопрос «а надо ли её вообще везти». Второй
            # вопрос задаётся ТОЛЬКО здесь, после отказа: до него он заслонил бы
            # работающий перенос. Ведро отдельное от `covered_by_origin` — судьба
            # общая (везти нечего, долга нет), утверждения РАЗНЫЕ: там origin
            # содержит наш след, здесь origin записал тот же переход СВОЕЙ строкой.
            same, why = origin_reached_same_outcome(local, remote)
            if same:
                plan["same_outcome_on_origin"].append({"path": repo_path, "reason": why})
                continue
            plan["refused"].append({"path": repo_path, "reason": reason})
            continue
        plan["rebased"].append({"path": repo_path, "remote_sha": blob_sha(remote)[:8],
                                "status_line": _STATUS_LINE.search(card_parts(local)[0])
                                .group(0).decode().strip()})
        plan["to_push"].append(absolute)

    # ── `--allow-overwrite` НЕ выборочный: он действует на ВСЮ команду пушера ──
    # Перенос доказан только там, где remote ПРОЧИТАН. Непрочитанный путь, уехавший
    # в той же пачке, поехал бы под тем же флагом — и остался бы вообще без защиты:
    # у пушера `guard_overwrite` при `allow_overwrite` отдаёт DIVERGED в перезапись
    # молча (ветка «ПЕРЕЗАПИСЬ РАЗРЕШЕНА ЯВНО»), а заодно снимает стража общей памяти
    # и стража пропадающих записей. Ровно так слепая копия стирает ответ владельца,
    # которого она не видела (инвариант #14) — то самое, что запрещает п.3 ADR-080.
    # Обещание «решает пушер, он fail-CLOSED» верно ТОЛЬКО в пачке без переносов;
    # тест на него это и проверял — в пачке из одной карточки, где оно не могло
    # сломаться. Поэтому непрочитанные придерживаем: мост ходит каждый цикл, а
    # «не измерено» — состояние преходящее. Придержанные названы в квитанции и
    # НЕ выглядят доставленными.
    if plan["rebased"] and plan["unmeasured"]:
        held_paths = {u["path"] for u in plan["unmeasured"]}
        plan["to_push"] = [p for p in plan["to_push"]
                           if _rel(root, p).replace(os.sep, "/") not in held_paths]
        for u in plan["unmeasured"]:
            u["held"] = True
            u["reason"] = (f"{u['reason']} — ПРИДЕРЖАНА: в пачке есть перенос, значит "
                           f"пушер поедет с --allow-overwrite, а он не выборочный — под "
                           f"ним у этого пути не осталось бы ни одного стража. Поедет "
                           f"следующим прогоном, когда origin удастся прочитать")
        plan["held"] = [dict(u) for u in plan["unmeasured"]]
    return plan


# ── долг доставки: провал обязан поехать снова ───────────────────────────────
#
# До ADR-081 список доставки строился ТОЛЬКО из карточек, которых вызывающий
# коснулся В ЭТОМ прогоне (`findings_bridge._deliver_touched`: created + closed).
# Провалившаяся доставка не запоминалась нигде. Замер 12.08: прогон 13:03Z —
# `FAILED, attempted 3, delivered 0`; все три уже помечены `closed` в состоянии
# моста ⇒ следующий прогон 19:03Z вёз бы ПУСТОЙ список, `deliver([])` вернул бы
# `IDLE`, а шаг 0-офис напечатал бы это ЗЕЛЁНОЙ строкой — при трёх карточках,
# которых на origin нет. Провал не просто не лечился: он сам себя заметал.
#
# Долг живёт в ДВУХ источниках, и это не дублирование, а страховка от того же
# класса: файл долга (переживает прогоны) и ПОСЛЕДНЯЯ КВИТАНЦИЯ (переживает
# потерю файла долга и восстанавливает долг задним числом — включая аварию,
# случившуюся до появления самого механизма).

def owed_from_receipt(receipt: dict) -> list:
    """Что осталось должным по квитанции ОДНОГО прогона → список repo-путей.

    Должно всё, что пытались везти и что на origin не оказалось. `delivered`
    заполняется только при нулевом коде возврата, `already_on_origin` — это
    доказанное совпадение с origin; остальное — долг.
    """
    if not isinstance(receipt, dict):
        return []
    attempted = [p for p in (receipt.get("attempted") or []) if p]
    if not attempted:
        return []
    return [p for p in attempted if p not in arrived_paths(receipt)]


def arrived_paths(receipt: dict) -> set:
    """Пути, о которых ДОКАЗАНО, что наше изменение на origin.

    Одно определение на модуль: долг и квитанция обязаны считать «доехало»
    одинаково. Две копии этого списка разошлись бы молча, а расхождение здесь
    стоит либо потерянной карточки, либо вечного ложного долга.
    """
    if not isinstance(receipt, dict):
        return set()
    arrived = (set(receipt.get("delivered") or [])
               | set(receipt.get("already_on_origin") or []))
    for key in ("covered_by_origin", "same_outcome_on_origin"):
        arrived |= {c.get("path") for c in (receipt.get(key) or [])
                    if isinstance(c, dict) and c.get("path")}
    return arrived


def _read_json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 — нет файла/битый JSON: долг просто пуст
        return None


def load_debt(root: str) -> dict:
    """``{repo_path: {since, attempts, last_status, last_reason}}``.

    Объединяет сохранённый долг с долгом ПОСЛЕДНЕЙ квитанции. Второе слагаемое
    нужно ровно для случая, который эту функцию и породил: авария уже случилась,
    файла долга ещё нет — и без восстановления из квитанции три застрявшие
    карточки не поехали бы никогда.
    """
    debt: dict = {}
    stored = _read_json(os.path.join(root, DEBT_REL)) or {}
    for path, entry in (stored.get("debt") or {}).items():
        if isinstance(entry, dict) and path:
            debt[path] = dict(entry)
    receipt = _read_json(os.path.join(root, STATUS_REL)) or {}
    for path in owed_from_receipt(receipt):
        if path not in debt:
            debt[path] = {"since": receipt.get("generated_at") or "",
                          "attempts": 1,
                          "last_status": receipt.get("status"),
                          "last_reason": receipt.get("reason") or "",
                          "recovered_from_receipt": True}
    return debt


def save_debt(root: str, debt: dict, now: dt.datetime) -> None:
    """Записать долг атомарно. Провал записи НЕ роняет доставку, но и не молчит."""
    from spa_core.utils.atomic import atomic_save
    target = os.path.join(root, DEBT_REL)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    atomic_save({"generated_at": now.isoformat(), "adr": "ADR-081", "debt": debt}, target)


def _age_hours(since: str, now: dt.datetime):
    """Возраст долга в часах или ``None`` — «не датируется» ≠ «свежий»."""
    try:
        stamp = dt.datetime.fromisoformat(str(since))
    except Exception:  # noqa: BLE001
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=dt.timezone.utc)
    return round((now - stamp).total_seconds() / 3600.0, 2)


def debt_block(debt: dict, now: dt.datetime, dropped=None, retried=None) -> dict:
    """Блок долга для квитанции: сколько должны, сколько это длится, что застряло."""
    ages = [a for a in (_age_hours(e.get("since", ""), now) for e in debt.values())
            if a is not None]
    stale = sorted(p for p, e in debt.items()
                   if int(e.get("attempts", 0)) >= DEBT_STALE_ATTEMPTS)
    return {"count": len(debt),
            # Порог едет В блоке, а не копируется читателю: две копии одного
            # числа расходятся молча (урок «пакетная правка по имени не видит
            # вписанный цифрой литерал»).
            "stale_after": DEBT_STALE_ATTEMPTS,
            "paths": sorted(debt),
            "oldest_hours": max(ages) if ages else None,
            "undated": sum(1 for e in debt.values()
                           if _age_hours(e.get("since", ""), now) is None),
            "max_attempts": max((int(e.get("attempts", 0)) for e in debt.values()), default=0),
            "stale": stale,
            "retried": sorted(retried or []),
            "dropped": list(dropped or [])}


def _debt_paths(root: str, debt: dict) -> tuple:
    """``(годные абсолютные пути долга, [{path, reason} …] снятых)``.

    Долг проверяется ОТДЕЛЬНО от заказанной пачки. Иначе один исчезнувший с
    диска должник отклонял бы пачку ЦЕЛИКОМ (`validate` отклоняет всю пачку) —
    и долг, заведённый ради доставки, останавливал бы доставку навсегда.

    Снимаем ровно то, что доставить нельзя НИКОГДА (файла нет, путь не карточка),
    и НАЗЫВАЕМ снятое: «не измерено» навсегда — тоже потеря (урок #199).
    """
    if not debt:
        return [], []
    ok, bad = validate(sorted(debt), root)
    dropped = [{"path": b["path"],
                "reason": f"снят с долга — доставить нечем: {b['reason']}"} for b in bad]
    return ok, dropped


def enforce_debt_status(receipt: dict, debt: dict) -> dict:
    """`IDLE` при непустом долге ЗАПРЕЩЁН (страховка, не основной путь).

    Основной путь — долг попадает в пачку и статус получается из её судьбы.
    Но обещание «зелёная строка достижима только пустым долгом» не должно
    зависеть от того, что все ветки выше отработали как задумано: ровно на
    таких «оно и так не случится» этот проект терял находки.
    """
    if debt and receipt.get("status") == IDLE:
        receipt["status"] = DEBT
        receipt["reason"] = (f"везти за прогон было нечего, но НЕ ДОСТАВЛЕНО {len(debt)} "
                             f"карточк(и) прошлых прогонов — долг: {', '.join(sorted(debt))}")
    return receipt


def build_message(root: str, paths: list) -> str:
    names = [os.path.basename(p) for p in paths]
    head = ", ".join(names[:3]) + (f" (+{len(names) - 3})" if len(names) > 3 else "")
    return (f"cards(ADR-066): доставка карточек петли ({len(names)}): {head} — "
            f"рождены агентом в прод-дереве, куда доставка не заглядывает; "
            f"одной пачкой, одним коммитом")


def _default_pusher(root: str, paths: list, message: str,
                    allow_overwrite: bool = False) -> tuple:
    """``(returncode, вывод)``. Единственное место, где доставка ходит наружу.

    ``allow_overwrite`` ставится ТОЛЬКО когда :func:`plan_batch` доказал перенос
    на прочитанный remote. Это не ослабление стража, а исполнение его же
    предписания: «перечитать со свежего origin/main, перенести свою правку и
    запушить снова; осознанная перезапись — ``--allow-overwrite``».
    """
    pusher = os.path.join(root, PUSHER_REL)
    if not os.path.isfile(pusher):
        return None, f"инструмента доставки нет: {pusher}"
    argv = [sys.executable, pusher, "--files", *paths, "--message", message]
    if allow_overwrite:
        argv.append("--allow-overwrite")
    r = subprocess.run(argv, capture_output=True, text=True, timeout=PUSH_TIMEOUT, cwd=root)
    return r.returncode, ((r.stdout or "") + (r.stderr or ""))


def _tail(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def deliver(paths, root: str = REPO_ROOT, now: dt.datetime | None = None,
            pusher=_default_pusher, env=None, write_status: bool = True,
            message: str | None = None, reader=_default_remote_reader,
            use_debt: bool = True) -> dict:
    """Довезти карточки до `origin/main`. Возвращает квитанцию (и пишет её на диск).

    Исключений НЕ бросает: доставка не смеет уронить сторожа, который её позвал.
    Но и не смеет промолчать — любой исход попадает в ``status``.

    К заказанным путям ВСЕГДА добавляется долг прошлых прогонов (ADR-081):
    повтор живёт здесь, а не у вызывающего, — иначе его пришлось бы завести
    каждому вызывающему по отдельности, и забывший остался бы с той же тихой
    потерей. ``use_debt=False`` — только для тестов, измеряющих один прогон.
    """
    ts = _now(now)
    receipt = {"generated_at": ts.isoformat(), "adr": "ADR-066",
               "attempted": [], "delivered": [], "refused": [],
               "rebased": [], "rebase_refused": [], "already_on_origin": [],
               "covered_by_origin": [], "same_outcome_on_origin": [],
               "rebase_unmeasured": [], "held": [],
               "status": UNCHECKED, "reason": "", "returncode": None, "output": ""}
    debt: dict = {}
    dropped: list = []
    retried: list = []
    try:
        if use_debt:
            debt = load_debt(root)
            debt_abs, dropped = _debt_paths(root, debt)
            for d in dropped:
                debt.pop(d["path"], None)
            asked = {os.path.realpath(os.path.join(root, str(p))) for p in (paths or []) if p}
            extra = [p for p in debt_abs if p not in asked]
            retried = [_rel(root, p) for p in extra]
            paths = list(paths or []) + extra
        ok, bad = validate(paths, root)
        receipt["attempted"] = [_rel(root, p) for p in ok]
        receipt["refused"] = bad
        if bad:
            receipt["status"] = REFUSED
            receipt["reason"] = ("пачка отклонена целиком — недопустимые пути: "
                                 + "; ".join(f"{b['path']}: {b['reason']}" for b in bad))
        elif not ok:
            receipt["status"] = IDLE
            receipt["reason"] = "доставлять нечего — карточек за прогон не создано и не закрыто"
        elif not is_enabled(env):
            receipt["status"] = DISABLED
            receipt["reason"] = (f"доставка выключена переменной {ENV_FLAG}; карточки остались "
                                 f"в рабочем дереве и на origin НЕ попали")
        else:
            plan = plan_batch(root, ok, reader=reader)
            receipt["rebased"] = plan["rebased"]
            receipt["rebase_refused"] = plan["refused"]
            receipt["already_on_origin"] = plan["already_on_origin"]
            receipt["covered_by_origin"] = plan["covered_by_origin"]
            receipt["same_outcome_on_origin"] = plan["same_outcome_on_origin"]
            receipt["rebase_unmeasured"] = plan["unmeasured"]
            receipt["held"] = plan["held"]
            # Застряло = не переносится ЛИБО придержано под чужим `--allow-overwrite`.
            # Причины разные, судьба одна: на origin не попало, и успехом это звать нельзя.
            blocked = plan["refused"] + plan["held"]
            stuck = "; ".join(f"{b['path']}: {b['reason']}" for b in blocked)
            if not plan["to_push"]:
                if blocked:
                    receipt["status"] = REFUSED
                    receipt["reason"] = f"переносить нечем, ни одна карточка не поехала — {stuck}"
                else:
                    receipt["status"] = IDLE
                    # Два основания «везти нечего» названы по отдельности: совпали
                    # побайтово и «наше уже там, origin ушёл вперёд» — разные факты.
                    same = len(plan["already_on_origin"])
                    covered = len(plan["covered_by_origin"])
                    outcome = len(plan["same_outcome_on_origin"])
                    receipt["reason"] = ("везти нечего — "
                                         + f"совпадают с нашими: {same}"
                                         + (f"; наша правка уже на origin (origin ушёл "
                                            f"вперёд): {covered}" if covered else "")
                                         + (f"; origin пришёл к тому же исходу раньше нас "
                                            f"(повторное закрытие): {outcome}"
                                            if outcome else ""))
            else:
                msg = message or build_message(root, plan["to_push"])
                receipt["message"] = msg
                rc, out = pusher(root, plan["to_push"], msg,
                                 allow_overwrite=bool(plan["rebased"]))
                receipt["returncode"] = rc
                receipt["output"] = _tail(out)
                if rc == 0 and not blocked:
                    receipt["status"] = DELIVERED
                    receipt["delivered"] = [_rel(root, p) for p in plan["to_push"]]
                    receipt["reason"] = "пушер вернул 0 — карточки на origin"
                elif rc == 0:
                    receipt["status"] = PARTIAL
                    receipt["delivered"] = [_rel(root, p) for p in plan["to_push"]]
                    receipt["reason"] = (f"уехало {len(plan['to_push'])}, ЗАСТРЯЛО "
                                         f"{len(blocked)} — {stuck}")
                elif rc is None:
                    receipt["status"] = UNCHECKED
                    receipt["reason"] = f"доставка не запускалась: {_tail(out, 300)}"
                else:
                    receipt["status"] = FAILED
                    receipt["reason"] = f"пушер вернул {rc} — карточки на origin НЕ попали"
    except Exception as e:  # noqa: BLE001 — «не измерено» честнее, чем падение сторожа
        receipt["status"] = UNCHECKED
        receipt["reason"] = f"доставка не измерена: {type(e).__name__}: {e}"

    # ── долг после прогона: что пытались везти и что на origin так и не попало ──
    if use_debt:
        try:
            for path in arrived_paths(receipt):
                debt.pop(path, None)
            for path in owed_from_receipt(receipt):
                entry = debt.get(path) or {"since": receipt["generated_at"], "attempts": 0}
                entry["attempts"] = int(entry.get("attempts", 0)) + 1
                entry["last_status"] = receipt["status"]
                entry["last_reason"] = receipt.get("reason") or ""
                debt[path] = entry
            receipt["debt"] = debt_block(debt, ts, dropped=dropped, retried=retried)
            enforce_debt_status(receipt, debt)
            if write_status:
                save_debt(root, debt, ts)
        except Exception as e:  # noqa: BLE001 — долг не смеет уронить доставку,
            # но «долг не измерен» обязано быть видно, а не выглядеть пустым долгом.
            receipt["debt"] = {"count": None, "paths": [],
                               "unmeasured": f"{type(e).__name__}: {e}"}

    if write_status:
        try:
            from spa_core.utils.atomic import atomic_save
            target = os.path.join(root, STATUS_REL)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            atomic_save(receipt, target)
        except Exception as e:  # noqa: BLE001 — квитанция не смеет уронить доставку
            receipt["receipt_write_error"] = f"{type(e).__name__}: {e}"
    return receipt


def render_debt(receipt: dict) -> str:
    """Хвост строки про долг. Пустой ТОЛЬКО когда долг измерен и равен нулю."""
    d = receipt.get("debt")
    if d is None:
        return " · долг доставки НЕ ИЗМЕРЕН (квитанция старого образца)"
    if d.get("unmeasured"):
        return f" · долг доставки НЕ ИЗМЕРЕН: {d['unmeasured']}"
    n = d.get("count")
    if n is None:
        return " · долг доставки НЕ ИЗМЕРЕН"
    if not n:
        return ""
    age = d.get("oldest_hours")
    age_s = f", старшему {age}ч" if age is not None else ", возраст не датируется"
    stale = f", НЕ РАССАСЫВАЕТСЯ: {len(d['stale'])}" if d.get("stale") else ""
    return f" · ДОЛГ {n} карточк(и){age_s}{stale}"


def render(receipt: dict) -> str:
    """Одна строка для лога/отчёта. Отказ виден без чтения JSON."""
    st = receipt.get("status")
    n_try = len(receipt.get("attempted") or [])
    n_reb = len(receipt.get("rebased") or [])
    tail = f" · перенесено на свежий origin: {n_reb}" if n_reb else ""
    tail += render_debt(receipt)
    if st == DELIVERED:
        return f"card_delivery: ✅ DELIVERED {n_try} карточк(и) → origin/main{tail}"
    if st == IDLE:
        return f"card_delivery: — доставлять нечего{tail}"
    return (f"card_delivery: ⚠️ {st} (пыталось {n_try}){tail} — {receipt.get('reason', '')}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", help="карточки nimbalyst-local/tracker/*.md")
    ap.add_argument("--root", default=REPO_ROOT)
    ap.add_argument("--show", action="store_true", help="показать последнюю квитанцию")
    args = ap.parse_args(argv)
    if args.show:
        try:
            print(json.dumps(json.load(open(os.path.join(args.root, STATUS_REL))),
                             ensure_ascii=False, indent=2))
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"квитанции нет: {e}")
            return 2
    if not args.paths:
        ap.print_help()
        return 0
    r = deliver(args.paths, root=args.root)
    print(render(r))
    return 0 if r["status"] in (DELIVERED, IDLE) else 1


if __name__ == "__main__":
    sys.exit(main())
