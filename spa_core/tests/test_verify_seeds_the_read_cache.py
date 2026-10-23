"""verify() отдаёт разобранное областному кэшу чтения (ADR-787, цикл #908, заказ G784 п. 1).

ЗАМЕР ДО РАБОТЫ, на живом ``data/research_factory/ledger.jsonl`` (69 101 205 Б, 23 194 записи):
один зов ``research_factory.read.latest()`` разбирал ленту **дважды** — свежий ``verify()``
(кэшу не доверяет НИКОГДА, N3) и ещё один разбор, который делят все помощники вида. Обе
личности файла ``(dev, inode, size, mtime_ns)`` в этих разборах СОВПАЛИ, то есть второй читал
те же байты и был избыточен ПО ЗАМЕРУ, а не по рассуждению.

ЗАМЕР ПОСЛЕ, тем же прибором (``ledger_parse_census``) и на том же файле: разборов за зов
**1**, цена 0.593 с → 0.279 с, запас 1.7× → 3.6×, срок до бюджета 1.00 с — **13.2 → 49.6
суток**. Находка ``growth_margin_below_floor`` при этом СТОИТ: 3.6× всё ещё ниже порога 4.0×.
Лекарство вернуло запас, но не сняло вопрос — и говорить иначе значило бы выдать отсрочку за
решение.

Предмет этой батареи — НЕ ускорение, а то, что ускорение не куплено ни одной снятой проверкой.
Каждый тест ниже — названный способ, которым посев мог бы соврать.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from spa_core.tests._freshness import ts
from spa_core.utils import hash_ledger as hl


@pytest.fixture()
def cache_on(monkeypatch):
    monkeypatch.setattr(hl, "_READ_CACHE_ENABLED", True)
    monkeypatch.setattr(hl, "_READ_CACHE", {})


def _ledger(tmp_path: Path) -> hl.HashLedger:
    return hl.HashLedger(tmp_path, "rf", "rf_anchors")


def _count_parses(monkeypatch) -> dict:
    n = {"parse": 0}
    orig = hl.HashLedger._parse

    def counting(path):
        n["parse"] += 1
        return orig(path)
    monkeypatch.setattr(hl.HashLedger, "_parse", staticmethod(counting))
    return n


def _seeded(led: hl.HashLedger) -> bool:
    return str(led.ledger_path()) in hl._READ_CACHE


# ── предмет: цена зова ───────────────────────────────────────────────────────────────────

def test_verify_then_read_parses_once_not_twice(tmp_path, monkeypatch, cache_on):
    """ИСХОД, ради которого всё: `verify()` + чтение внутри одной области = ОДИН разбор."""
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    n = _count_parses(monkeypatch)
    assert led.verify()["ok"] is True
    rows = led.read_all()
    assert n["parse"] == 1
    assert [r["payload"]["x"] for r in rows] == [1]


def test_without_the_seed_the_same_call_costs_two_parses(tmp_path, monkeypatch, cache_on):
    """ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ: звено снято — и цена возвращается к двум разборам.

    Без него тест выше доказывал бы только, что сегодня разбор один, но не ЧЕМ он один.
    """
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    monkeypatch.setattr(hl.HashLedger, "_seed_read_cache",
                        lambda self, path, entries, ident: False)
    n = _count_parses(monkeypatch)
    led.verify()
    led.read_all()
    assert n["parse"] == 2


def test_the_seeded_rows_are_the_rows_a_reader_would_have_parsed(tmp_path, cache_on):
    """Посев обязан отдавать ТО ЖЕ, что отдал бы честный разбор, — иначе он экономит враньём."""
    led = _ledger(tmp_path)
    for i in range(5):
        led.append("run", [f"r{i}"], {"x": i}, ts(5 - i))
    led.verify()
    seeded = led.read_all()
    hl._READ_CACHE.clear()
    assert seeded == led.read_all()


def test_seeded_rows_carry_the_same_read_only_contract_as_parsed_ones(tmp_path, cache_on):
    """Посеянные строки делят все читатели области, поэтому они обязаны быть ровно так же
    неизменяемы, как строки обычного разбора (ADR-763). Посев, кладущий в кэш ЖИВЫЕ словари,
    отдал бы соседям общий изменяемый объект — экономия ценой порчи."""
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    led.verify()
    rows = led.read_all()
    assert isinstance(rows, list) and not isinstance(rows, hl.FrozenList)   # список СВОЙ
    with pytest.raises(TypeError):
        rows[0]["payload"]["x"] = 2                                        # строка — общая
    assert dict(rows[0])["payload"]["x"] == 1                              # копия — своя
    assert led.read_all()[0]["payload"]["x"] == 1


# ── четыре случая, когда посева НЕ ДОЛЖНО БЫТЬ ───────────────────────────────────────────

def test_a_broken_ledger_is_never_seeded(tmp_path, cache_on):
    """Повод не верить ленте есть повод не верить кэшу: порванная цепь не сеется."""
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    p = led.ledger_path()
    st = p.stat()
    p.write_text(p.read_text().replace('"x":1', '"x":2'))     # та же длина
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert led.verify()["ok"] is False
    assert not _seeded(led)


def test_nothing_is_seeded_outside_a_scope(tmp_path, monkeypatch):
    """Вне области кэша нет вовсе — посев пережил бы читающую секцию (свойство вечного флага,
    снятого ADR-777)."""
    monkeypatch.setattr(hl, "_READ_CACHE", {})
    assert hl._READ_CACHE_ENABLED is False
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    assert led.verify()["ok"] is True
    assert hl._READ_CACHE == {}


def test_the_trusted_writer_is_not_seeded(tmp_path, cache_on):
    """У доверенного писателя СВОЯ память (`self._cache`); вторая копия рядом — тот самый
    класс «одно правило, две копии»."""
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    led.mark_verified()
    assert led._trusted is True
    hl._READ_CACHE.clear()
    assert led.verify()["ok"] is True
    assert hl._READ_CACHE == {}


def test_an_append_landing_while_verify_runs_never_yields_a_stale_answer(tmp_path, monkeypatch, cache_on):
    """Чужая дописка внутри нашего разбора: читатель обязан увидеть ОБЕ записи.

    Что этот тест меряет на самом деле — и почему он НЕ есть контроль сторожа личности файла
    (мутационный замер #908 это и показал: обе мутации сторожа его не трогают). Дописка рвёт
    согласие ленты с якорями, `verify()` отвечает `ledger_truncated`, и посева не случается
    РАНЬШЕ — на ветке «вердикт не ok». До сторожа личности дело просто не доходит.
    Его собственный контроль — тест ниже, где вердикт ОСТАЁТСЯ `ok`.
    """
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(2))
    writer = _ledger(tmp_path)
    orig = hl.HashLedger._parse

    def parse_then_sibling_appends(path):
        out = orig(path)
        if not getattr(parse_then_sibling_appends, "done", False):
            parse_then_sibling_appends.done = True
            writer.append("run", ["r2"], {"x": 2}, ts(1))
        return out
    monkeypatch.setattr(hl.HashLedger, "_parse", staticmethod(parse_then_sibling_appends))
    led.verify()
    monkeypatch.setattr(hl.HashLedger, "_parse", staticmethod(orig))
    # Меряется не «пуст ли кэш» — дописывающий сосед внутри области сеет и СВОЙ verify, и это
    # не предмет. Предмет: под ТЕКУЩЕЙ личностью файла не лежит ни одной устаревшей раскладки,
    # поэтому устаревшим ответить физически нечем (та же мерка, что у соседней батареи).
    now_ident = hl._file_identity(led.ledger_path())
    assert all(ident != now_ident or len(rows) == 2
               for ident, rows in hl._READ_CACHE.values())
    assert [r["payload"]["x"] for r in led.read_all()] == [1, 2]


def test_the_file_changing_under_an_OK_verify_is_not_seeded(tmp_path, monkeypatch, cache_on):
    """СОБСТВЕННЫЙ контроль сторожа личности файла, и он обязан жить там, где вердикт `ok`.

    Сторож отвечает на один вопрос: «те ли байты всё ещё на диске, которые я разобрал?» —
    и единственное свидетельство у него личность файла `(dev, inode, size, mtime_ns)`. Если
    она сменилась, пока шли разбор и обход, посев стал бы утверждением о файле, которого
    прибор не читал. Сцена: цепь НЕ трогаем (вердикт остаётся `ok`), а личность меняем —
    этого достаточно, потому что отличить «сменилась только отметка» от «сменилось
    содержимое» сторож не может по построению и обязан ошибаться в сторону отказа.

    Мутационный замер назвал цену отсутствия этого теста: без него выживают ДВА мутанта —
    снятая перепроверка и личность, снятая ПОСЛЕ разбора вместо «до».
    """
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    path = led.ledger_path()
    orig = hl.HashLedger._parse

    def parse_then_touch(p):
        out = orig(p)
        if not getattr(parse_then_touch, "done", False):
            parse_then_touch.done = True
            st = os.stat(path)
            os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
        return out
    monkeypatch.setattr(hl.HashLedger, "_parse", staticmethod(parse_then_touch))
    assert led.verify()["ok"] is True          # цепь цела — ветка «порвано» тут НЕ работает
    assert not _seeded(led)                    # …и всё же посева нет: байты могли смениться
    monkeypatch.setattr(hl.HashLedger, "_parse", staticmethod(orig))
    assert [r["payload"]["x"] for r in led.read_all()] == [1]


def test_an_append_landing_after_verify_is_still_seen(tmp_path, cache_on):
    """Сторож посева — та же личность файла, что у обычного чтения: дописка меняет размер и
    mtime, поэтому посеянное промахивается, а не отвечает устаревшим."""
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(2))
    assert led.verify()["ok"] is True
    assert _seeded(led)
    _ledger(tmp_path).append("run", ["r2"], {"x": 2}, ts(1))
    assert [r["payload"]["x"] for r in led.read_all()] == [1, 2]


def test_verify_still_never_answers_from_the_cache(tmp_path, cache_on):
    """N3 не тронут: поменялось НАПРАВЛЕНИЕ (verify отдаёт), а не доверие (verify не берёт).

    Подмена той же длины и с тем же mtime — слепое пятно кэша по построению; `verify()`
    обязан его НЕ разделять, иначе посев превратил бы ускорение в снятую проверку.
    """
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    assert led.verify()["ok"] is True
    assert _seeded(led)
    p = led.ledger_path()
    st = p.stat()
    p.write_text(p.read_text().replace('"x":1', '"x":2'))
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert led.read_all()[0]["payload"]["x"] == 1        # кэш слеп — и это задокументировано
    assert led.verify()["ok"] is False                   # verify этой слепоты НЕ разделяет


def test_the_seed_reports_whether_it_happened(tmp_path, cache_on):
    """Исход посева НАБЛЮДАЕМ: «посеял» и «не стал» различимы вызывающим, а не выводятся из
    текста модуля (инв. #17)."""
    led = _ledger(tmp_path)
    led.append("run", ["r1"], {"x": 1}, ts(1))
    path = led.ledger_path()
    ident = hl._file_identity(path)
    entries = led.read_all()
    hl._READ_CACHE.clear()
    assert led._seed_read_cache(path, entries, ident) is True
    hl._READ_CACHE.clear()
    assert led._seed_read_cache(path, entries, None) is False
