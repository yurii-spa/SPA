#!/usr/bin/env python3
"""Заслон от потока обязан быть ОБЩИМ на машину и гасить побуквенный повтор.

Замер 09.08: владелец получал одно и то же сообщение каждые несколько минут всё утро —
«с этим невозможно работать». Разбор дал две причины, обе одного класса:

1. **«Общий межпроцессный лимит» не был общим.** Файл состояния считался от каталога
   ОТПРАВИТЕЛЯ, поэтому у каждого рабочего дерева был свой бюджет 12 сообщений в минуту —
   лимит молча умножался на число деревьев.
2. **История тоже была по-дереву**, поэтому поток из чужого дерева НЕ ВИДЕН в проде, и
   разбор «кто это шлёт» дважды упирался в пустоту.

Плюс: `push_policy` знает только СВОИХ отправителей, а мимо него шлют скрипты и чужие
сессии. Поэтому побуквенный повтор гасится в единственной точке отправки — там, где мимо
не пройдёт никто.

Сети здесь нет: проверяются пути и чистая функция сравнения.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pytest

from spa_core.alerts import telegram_client as tc
from spa_core.tests._freshness import now_utc

NOW = now_utc()


def _history(tmp_path, entries):
    p = tmp_path / "alert_history.json"
    p.write_text(json.dumps({"entries": entries}), encoding="utf-8")
    return p


def _entry(text, *, seconds_ago=0, ok=True):
    return {"ts": (NOW - timedelta(seconds=seconds_ago)).isoformat(),
            "preview": text[:tc._PREVIEW_LEN], "ok": ok}


def test_the_rate_limit_state_lives_in_the_live_tree():
    """Положительный контроль: лимит обязан считаться от ЖИВОГО дерева.

    Пока он считался от дерева отправителя, каждая параллельная сессия получала СВОЙ
    бюджет 12/мин — и «общий» лимит существовал только в докстринге.
    """
    from pathlib import Path

    from spa_core.utils.live_paths import live_data_dir

    # Якорь — дерево САМОГО модуля-отправителя, а не рабочий каталог процесса: 14.08 этот
    # тест краснел в CI (`cd spa_core && pytest tests/`) не потому, что лимит уехал, а
    # потому, что ожидание считалось от cwd. Ожидание, зависящее от cwd, проверяет
    # не то, что написано в его имени.
    live = live_data_dir(Path(tc.__file__).resolve().parents[2])
    assert tc._RATE_STATE.parent == live
    assert tc._HISTORY_STATE.parent == live
    # и то же самое без явного якоря — разрешение обязано быть cwd-независимым
    assert live_data_dir(None) == live


def test_history_and_rate_state_share_one_tree():
    """Разъедься они — «кто шлёт» опять станет неотвечаемым вопросом."""
    assert tc._RATE_STATE.parent == tc._HISTORY_STATE.parent


def test_identical_text_within_the_window_is_a_duplicate(tmp_path, monkeypatch):
    """Побуквенно тот же текст в окне не несёт НИ ОДНОГО нового факта."""
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    monkeypatch.setattr(tc, "_HISTORY_STATE",
                        _history(tmp_path, [_entry("🧑‍⚖️ Нужно твоё решение: сайт", seconds_ago=120)]))
    assert tc._duplicate_recently("🧑‍⚖️ Нужно твоё решение: сайт") is True


def test_a_different_text_always_passes(tmp_path, monkeypatch):
    """Дедуп не имеет права стать глухотой: изменился текст — сообщение уходит."""
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    monkeypatch.setattr(tc, "_HISTORY_STATE",
                        _history(tmp_path, [_entry("Просадка 5%", seconds_ago=60)]))
    assert tc._duplicate_recently("Просадка 9%") is False


def test_the_same_text_after_the_window_passes_again(tmp_path, monkeypatch):
    """Окно, а не вечный запрет: через полчаса то же сообщение снова имеет смысл."""
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    monkeypatch.setattr(tc, "_HISTORY_STATE",
                        _history(tmp_path, [_entry("та же тревога",
                                                   seconds_ago=tc.DUPLICATE_WINDOW_S + 60)]))
    assert tc._duplicate_recently("та же тревога") is False


def test_a_failed_send_does_not_count_as_a_duplicate(tmp_path, monkeypatch):
    """Сообщение, которое НЕ дошло, не имеет права запретить повторную попытку.

    Иначе первая же сетевая ошибка глушила бы тревогу на полчаса — подавление вместо дедупа.
    """
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    monkeypatch.setattr(tc, "_HISTORY_STATE",
                        _history(tmp_path, [_entry("важное", seconds_ago=60, ok=False)]))
    assert tc._duplicate_recently("важное") is False


def test_an_unreadable_history_never_suppresses(tmp_path, monkeypatch):
    """Fail-CLOSED в сторону ДОСТАВКИ: не смогли проверить — шлём.

    Молчание дороже лишнего сообщения: пропущенная тревога стоит больше, чем дубль.
    """
    monkeypatch.setenv("SPA_TELEGRAM_DUP_TEST", "1")
    monkeypatch.setattr(tc, "_HISTORY_STATE", tmp_path / "нет-такого.json")
    assert tc._duplicate_recently("что угодно") is False


def test_preview_length_is_one_constant():
    """Сравнение повтора и запись истории обязаны резать текст ОДИНАКОВО.

    Разъедься они — дедуп сравнивал бы разные вещи и молча перестал бы срабатывать.
    """
    src = (tc.__file__ or "")
    text = open(src, encoding="utf-8").read()
    assert '[:80]' not in text.replace('_PREVIEW_LEN = 80', ''), \
        "длина превью зашита числом в обход константы"
