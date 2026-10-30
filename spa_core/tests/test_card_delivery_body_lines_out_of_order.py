"""Ручное сведение карточки сделало долг доставки НЕПОГАСИМЫМ.

# FROZEN-DATE-OK: injected-clock — часы здесь ВХОД (`deliver(now=…)`), а
# литеральные отметки внутри байтов карточки воспроизводят аварию 2026-10-30
# дословно: обе стороны закреплены, календарь на вердикт не влияет.

**Авария, которую повторяет каждый положительный контроль ниже** (замер цикла
#985, `data/findings_bridge_report.json` 2026-10-29 10:18:11Z, прод-дерево
против `origin/main` b6a091cea):

    attempted: 3  delivered: 1  rebase_refused: 2
    status: PARTIAL · ДОЛГ ДОСТАВКИ: 2 карточк(и) НЕ на origin (старшему 91.4ч)
    ⛔ не рассасывается повтором (≥5 попыток), нужен человек: …

Человек там УЖЕ был. Цикл #971 (`a78c38f56`, 28.10 23:46) свёл долг моста
**8 → 2** ВРУЧНУЮ и оставил в обеих карточках свою пометку «перенесено ВРУЧНУЮ
из прод-дерева». Именно эта починка и сделала остаток непогасимым: руками текст
кладут туда, где он ЧИТАЕТСЯ, а не туда, где доказуемо порядкосохраняющее
вложение. Замер прод-копий:

* frontmatter покрыт СТРОГОЙ мерой у обеих карточек;
* наших непустых строк тела 32 и 40, у origin 36 и 60;
* наших строк, которых на origin НЕТ ВОВСЕ, — **0** и **0**;
* вложения всё равно НЕ СУЩЕСТВУЕТ, и это не жадность матчера (жадное левое
  соответствие для подпоследовательности оптимально): у первой карточки наша
  строка «Прибор … (ADR-328) назвал этот» есть на origin ТОЛЬКО в дописанном
  блоке (позиция 50), а её продолжение — ТОЛЬКО на позиции 19, то есть ПОЗАДИ.

Население класса измерено по всему трекеру (1524 карточки на `origin/main`):
ровно **2**, и это те самые две. Ветка написана не «на будущее».

Пушер здесь ВСЕГДА инъектируется, и главное утверждение положительных контролей
двойное: исход стал `IDLE` **и** пушер не позван. По отдельности второе зелено и
на неисправленном модуле (там путь молчит по отказу) — тест, проверяющий только
его, был бы украшением.

**Обратные контроли держат слабую меру в обе стороны:** пропала наша строка ⇒
отказ; тот же набор строк в другом порядке (переписывание, а не обгон) ⇒ отказ;
разошёлся frontmatter ⇒ отказ, и слабую меру тела никто не спрашивает.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile

import pytest

from spa_core.monitoring import card_delivery as cd


NOW = dt.datetime(2030, 3, 1, 12, 0, tzinfo=dt.timezone.utc)  # FROZEN-DATE-OK: injected-clock

CARD_NAME = "inbox-spisok-shagov-ci-vyveden-cherez-shest-li.md"
REL = f"{cd.TRACKER_REL.replace(os.sep, '/')}/{CARD_NAME}"

_HEAD = """---
trackerStatus:
  type: inbox
title: Список шагов CI выведен через ШЕСТЬ литеральных пробелов — сдвинется отступ, проверка замолчит
status: done
source: nimbalyst
created: 2026-09-11
status_trail:
  - "2026-09-17T15:03:12.780611+00:00 new -> done · queue.set_status"
---
"""

#: Общий хвост абзаца. Он ОДИН и тот же в обеих копиях — ровно поэтому ручное
#: сведение и переплело текст: заново хвост никто не переписывал.
_SHARED_TAIL = """сайт признаком `pins-literal-indentation`, но **измерить** его не смог: законное
смещение отступа от незаконного он не отличает ничем.
"""

#: Прод-дерево: абзац про прибор ссылается на ADR-328 и стои́т НА СВОЁМ МЕСТЕ.
LOCAL = (_HEAD + """
## Что случилось и почему это важно

Проверка `tests/test_mypy_gate.py:191` строит список шагов CI из файла
`.github/workflows/ci-lite.yml` выражением, прибитым к шести литеральным
пробелам отступа.

**Сегодня потери НЕТ** (замер цикла #566): по прибитой форме находится 10
шагов, по свободной — те же 10.

Прибор `spa_core/monitoring/subject_population_census.py` (ADR-328) назвал этот
""" + _SHARED_TAIL).encode("utf-8")

#: `origin/main` b6a091cea: номер ADR в абзаце ПОПРАВЛЕН на месте (328 → 333), а
#: прод-версия того же абзаца ДОПИСАНА в конец вместе с пометкой о сведении.
#: Хвост абзаца при этом НЕ продублирован — он остался на своём месте. Именно
#: это и делает порядкосохраняющее вложение невозможным.
REMOTE = (_HEAD + """
## Что случилось и почему это важно

Проверка `tests/test_mypy_gate.py:191` строит список шагов CI из файла
`.github/workflows/ci-lite.yml` выражением, прибитым к шести литеральным
пробелам отступа.

**Сегодня потери НЕТ** (замер цикла #566): по прибитой форме находится 10
шагов, по свободной — те же 10.

Прибор `spa_core/monitoring/subject_population_census.py` (ADR-333) назвал этот
""" + _SHARED_TAIL + """
<!-- цикл #971: перенесено ВРУЧНУЮ из прод-дерева (мост отказал: расхождение
     не сводится к строке status:). База — origin/main: там позднейшие правки,
     которые прод-копия не несёт. Уникальное прод-копии добавлено ниже без потерь. -->

Прибор `spa_core/monitoring/subject_population_census.py` (ADR-328) назвал этот
""").encode("utf-8")


class _Pusher:
    """Инъектируемый пушер: считает вызовы и НЕ ходит в сеть."""

    def __init__(self):
        self.calls = []

    def __call__(self, root, paths, message, allow_overwrite=False):
        self.calls.append({"paths": list(paths), "allow_overwrite": allow_overwrite})
        return 0, "ok"


def _remote(table):
    def reader(root, repo_path):
        value = table.get(os.path.basename(repo_path))
        if value is None:
            return cd.REMOTE_ABSENT, None, "на origin файла нет"
        return cd.REMOTE_PRESENT, value, ""
    return reader


def _run(tmp, local: bytes, remote: bytes, *, attempts: int = 6):
    """Один прогон доставки в песочнице → ``(квитанция, пушер)``.

    Долг сеется НЕПУСТЫМ и УЖЕ просроченным (попыток больше `stale_after`),
    ровно как в проде: иначе тест мерил бы «долг не появился», а не «вечный
    долг погашен вместе с эскалацией „нужен человек“».
    """
    root = os.path.realpath(tmp)
    tracker = os.path.join(root, cd.TRACKER_REL)
    os.makedirs(tracker, exist_ok=True)
    os.makedirs(os.path.join(root, "data"), exist_ok=True)
    with open(os.path.join(tracker, CARD_NAME), "wb") as f:
        f.write(local)
    with open(os.path.join(root, cd.DEBT_REL), "w", encoding="utf-8") as f:
        json.dump({"generated_at": "2026-10-29T10:18:11+00:00", "adr": "ADR-081",
                   "debt": {REL: {"since": "2026-10-25T14:49:00+00:00",
                                  "attempts": attempts, "last_status": cd.REFUSED,
                                  "last_reason": "расхождение не сводится к строке status:"}}},
                  f)
    pusher = _Pusher()
    receipt = cd.deliver([], root=root, now=NOW, pusher=pusher,
                         reader=_remote({CARD_NAME: remote}), env={cd.ENV_FLAG: "1"})
    return receipt, pusher


# ── сцена воспроизводит аварию: строгие меры ОТКАЗЫВАЮТ ──────────────────────

def test_the_scene_is_the_real_one_every_strict_measure_refuses():
    """Без этого контроля тест мог бы зеленеть на сцене, где хватило бы `covered_by_origin`."""
    assert REMOTE != LOCAL
    assert cd.origin_covers_card(LOCAL, REMOTE)[0] is False
    assert cd.rebase_card(LOCAL, REMOTE)[0] is None
    assert cd.origin_reached_same_outcome(LOCAL, REMOTE)[0] is False


def test_our_body_lines_are_all_on_origin_and_order_is_the_only_difference():
    """Замер, из которого и вырос вердикт: пропавших строк НОЛЬ, а вложения нет."""
    ours = cd._body_line_counts(cd.card_parts(LOCAL)[1])
    theirs = cd._body_line_counts(cd.card_parts(REMOTE)[1])
    missing = sum(max(0, n - theirs.get(line, 0)) for line, n in ours.items())
    assert missing == 0
    assert sum(theirs.values()) > sum(ours.values())


# ── положительные контроли: авария 30.10 ─────────────────────────────────────

def test_the_hand_merged_card_stops_owing():
    """ГЛАВНЫЙ контроль: раньше здесь был PARTIAL/REFUSED и непогасимый долг 1."""
    with tempfile.TemporaryDirectory() as td:
        receipt, pusher = _run(td, LOCAL, REMOTE)
    assert receipt["status"] == cd.IDLE, receipt["reason"]
    assert receipt["debt"]["count"] == 0
    # ДВА факта разом: исход стал IDLE И пушер молчал. Порознь второй зелен и
    # на неисправленном модуле — там путь молчит по отказу, а не по покрытию.
    assert pusher.calls == []


def test_the_escalation_asking_for_a_human_disappears_with_the_debt():
    """«Нужен человек» просило сделать то, что человек уже сделал (#971)."""
    with tempfile.TemporaryDirectory() as td:
        receipt, _pusher = _run(td, LOCAL, REMOTE)
    assert receipt["debt"]["stale"] == []
    assert receipt["debt"]["paths"] == []


def test_the_card_lands_in_its_own_bucket_not_in_the_strict_ones():
    """Судьба общая (везти нечего), утверждения РАЗНЫЕ — и мера разной силы."""
    with tempfile.TemporaryDirectory() as td:
        receipt, _pusher = _run(td, LOCAL, REMOTE)
    assert [c["path"] for c in receipt["body_lines_on_origin_unordered"]] == [REL]
    assert receipt["covered_by_origin"] == []
    assert receipt["already_on_origin"] == []
    assert receipt["same_outcome_on_origin"] == []
    assert receipt["rebase_refused"] == []


def test_the_reason_calls_its_own_proof_weaker():
    """Слабое доказательство, поданное как строгое, и есть дефект этой ветки."""
    with tempfile.TemporaryDirectory() as td:
        receipt, _pusher = _run(td, LOCAL, REMOTE)
    said = receipt["body_lines_on_origin_unordered"][0]["reason"]
    assert "ПОРЯДОК не наш" in said
    assert "слабее" in said
    assert "СТРОКИ, а не" in said


def test_the_run_reason_names_the_fourth_ground_separately():
    """Схлопнуть четвёртое основание с «везти нечего вообще» — тот же класс (#268)."""
    with tempfile.TemporaryDirectory() as td:
        receipt, _pusher = _run(td, LOCAL, REMOTE)
    assert "ПОРЯДОК не наш (слабая мера): 1" in receipt["reason"]


def test_the_path_counts_as_arrived_for_the_one_definition_of_delivered():
    """Долг и квитанция обязаны считать «доехало» ОДНИМ определением."""
    with tempfile.TemporaryDirectory() as td:
        receipt, _pusher = _run(td, LOCAL, REMOTE)
    assert REL in cd.arrived_paths(receipt)
    assert cd.owed_from_receipt(receipt) == []


# ── обратные контроли: слабая мера не смеет прощать расхождение ──────────────

def test_a_lost_body_line_is_still_a_refusal():
    """ПОРВАННОЕ ЗВЕНО: origin потерял нашу строку ⇒ это расхождение, не обгон."""
    lost = REMOTE.replace(
        "**Сегодня потери НЕТ** (замер цикла #566): по прибитой форме находится 10\n".encode(),
        b"")
    assert lost != REMOTE
    ok, why = cd.origin_carries_our_body_lines(LOCAL, lost)
    assert ok is False
    assert "разошёлся с нами" in why
    with tempfile.TemporaryDirectory() as td:
        receipt, pusher = _run(td, LOCAL, lost)
    assert receipt["body_lines_on_origin_unordered"] == []
    assert [c["path"] for c in receipt["rebase_refused"]] == [REL]
    assert receipt["debt"]["count"] == 1
    assert pusher.calls == []


def test_a_pure_permutation_is_a_rewrite_and_is_refused():
    """ПОРВАННОЕ ЗВЕНО: тот же набор строк в другом порядке — не обгон, а переписывание."""
    body = cd.card_parts(LOCAL)[1]
    lines = [ln for ln in body.splitlines(keepends=True)]
    shuffled = b"".join(lines[::-1])
    permuted = LOCAL[:len(LOCAL) - len(body)] + shuffled
    ok, why = cd.origin_carries_our_body_lines(LOCAL, permuted)
    assert ok is False
    assert "ПЕРЕПИСЫВАНИЕ" in why


def test_a_diverged_frontmatter_is_refused_before_the_weak_measure_is_asked():
    """ПОРВАННОЕ ЗВЕНО: машинную часть карточки слабая мера не судит НИКОГДА."""
    other = REMOTE.replace(b"status: done", b"status: new", 1)
    ok, why = cd.origin_carries_our_body_lines(LOCAL, other)
    assert ok is False
    assert "frontmatter" in why
    assert "слабую меру тела" in why


def test_the_old_strict_coverage_still_wins_when_an_embedding_exists():
    """ОБРАТНЫЙ КОНТРОЛЬ починки: вложение есть ⇒ отвечает СТРОГАЯ мера, не эта."""
    ahead = REMOTE.replace(b"(ADR-333)", b"(ADR-328)", 1)
    ahead = ahead[:ahead.index(b"<!-- \xd1\x86\xd0\xb8\xd0\xba\xd0\xbb #971")]
    assert cd.origin_covers_card(LOCAL, ahead)[0] is True
    with tempfile.TemporaryDirectory() as td:
        receipt, pusher = _run(td, LOCAL, ahead)
    assert [c["path"] for c in receipt["covered_by_origin"]] == [REL]
    assert receipt["body_lines_on_origin_unordered"] == []
    assert pusher.calls == []


def _blanks(body: bytes) -> int:
    return sum(1 for ln in body.splitlines() if not ln.strip())


def test_extra_blank_lines_in_our_copy_are_not_a_lost_paragraph():
    """ПОРВАННОЕ ЗВЕНО наоборот: пустая строка содержания не несёт и терять нечего.

    Контроль написан по ВЫЖИВШЕМУ мутанту замера #985 (мутация 6 из 10:
    «пустые строки снова считаются содержанием»). На двух живых карточках
    мутант оказался НЕОТЛИЧИМ — у origin пустых строк и так больше (44/50 и
    56/79 с учётом пустых), то есть он менял поведение на входе, которого в
    населении НЕТ. Поэтому сцена строится ЯВНО: наша копия несёт пустых строк
    БОЛЬШЕ, чем origin, и всё остальное покрыто. Вердикт обязан остаться «везти
    нечего»: иначе лишний перевод строки, поставленный чьей-то рукой, читался бы
    как пропавший абзац — и вечный ложный долг вернулся бы с другой стороны.
    """
    head, body = LOCAL[:LOCAL.index(b"\n---\n") + 5], cd.card_parts(LOCAL)[1]
    need = _blanks(cd.card_parts(REMOTE)[1]) - _blanks(body) + 1
    assert need > 0, "сцена обязана дать НАМ пустых строк больше, чем у origin"
    padded = head + body + b"\n" * need
    assert _blanks(cd.card_parts(padded)[1]) > _blanks(cd.card_parts(REMOTE)[1])
    ok, why = cd.origin_carries_our_body_lines(padded, REMOTE)
    assert ok is True, why
    with tempfile.TemporaryDirectory() as td:
        receipt, pusher = _run(td, padded, REMOTE)
    assert receipt["status"] == cd.IDLE, receipt["reason"]
    assert receipt["debt"]["count"] == 0
    assert [c["path"] for c in receipt["body_lines_on_origin_unordered"]] == [REL]
    assert pusher.calls == []


def test_a_non_card_is_not_judged_by_the_weak_measure():
    """Третий исход вместо догадки: без frontmatter сравнивать нечем."""
    ok, why = cd.origin_carries_our_body_lines(b"no frontmatter here\n", REMOTE)
    assert ok is False
    assert "не карточка" in why
