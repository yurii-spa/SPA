"""Очередь владельца живёт в ЖИВОМ дереве, а не в дереве вызывающего.

Карточка-призрак (замер на владельце 2026-08-22): автономный цикл в
/tmp-worktree создал owner-decision, задал вопрос в Telegram и умер вместе
с worktree — файла карточки не существовало нигде, ответ владельца «2»
реплаем упёрся в «не знаю такого вопроса». Вопрос, на который нельзя
ответить по построению. Тот же класс, что журнал пушей и дедуп-реестр
owner-gate: состояние, обязанное переживать worktree, обязано жить в
живом дереве.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib
from pathlib import Path

from spa_core.owner_queue import queue as Q


def _resolve(monkeypatch, *, tracker_env=None, live_root_env=None,
             default_live_exists=False, tmp_path=None):
    monkeypatch.delenv("SPA_TRACKER_DIR", raising=False)
    monkeypatch.delenv("SPA_LIVE_ROOT", raising=False)
    if tracker_env is not None:
        monkeypatch.setenv("SPA_TRACKER_DIR", str(tracker_env))
    if live_root_env is not None:
        monkeypatch.setenv("SPA_LIVE_ROOT", str(live_root_env))
    from spa_core.utils import live_paths
    if not default_live_exists:
        # В облаке/CI ~/Documents/SPA_Claude и так нет; закрепляем герметично.
        monkeypatch.setattr(live_paths, "DEFAULT_LIVE_ROOT",
                            (tmp_path / "no-such-prod-tree"), raising=True)
    return Q._resolve_tracker_dir()


def test_explicit_env_seam_wins(tmp_path, monkeypatch):
    d = tmp_path / "sandbox-tracker"
    assert _resolve(monkeypatch, tracker_env=d, tmp_path=tmp_path) == d


def test_live_root_beats_own_tree(tmp_path, monkeypatch):
    """Суть починки: из worktree карточка едет в ЖИВОЕ дерево — переживает
    worktree, и бот может записать в неё ответ владельца."""
    live = tmp_path / "prod-tree"
    got = _resolve(monkeypatch, live_root_env=live, tmp_path=tmp_path)
    assert got == live / "nimbalyst-local" / "tracker"


def test_cloud_without_live_tree_falls_back_to_own_repo(tmp_path, monkeypatch):
    got = _resolve(monkeypatch, tmp_path=tmp_path)
    assert got == Q._REPO_ROOT / "nimbalyst-local" / "tracker"


def test_gate_sandbox_env_does_not_hijack_the_owner_queue(tmp_path, monkeypatch):
    """SPA_DATA_DIR — песочница data/ для гейта; вопрос владельцу не data и
    не имеет права испаряться вместе с песочницей."""
    monkeypatch.setenv("SPA_DATA_DIR", str(tmp_path / "sandbox-data"))
    live = tmp_path / "prod-tree"
    got = _resolve(monkeypatch, live_root_env=live, tmp_path=tmp_path)
    assert got == live / "nimbalyst-local" / "tracker"


def test_create_card_lands_in_the_live_tracker(tmp_path, monkeypatch):
    """Сквозной контроль: create_card с дефолтным разрешением кладёт файл в
    живой трекер (через перезагрузку модуля с SPA_LIVE_ROOT)."""
    live = tmp_path / "prod-tree"
    (live / "nimbalyst-local" / "tracker").mkdir(parents=True)
    monkeypatch.delenv("SPA_TRACKER_DIR", raising=False)
    monkeypatch.setenv("SPA_LIVE_ROOT", str(live))
    mod = importlib.reload(Q)
    try:
        path = mod.create_card(tracker_type="owner-decision",
                               title="Тест: призрак не рождается",
                               body="## Что случилось и почему это важно\nтест\n")
        assert Path(path).parent == live / "nimbalyst-local" / "tracker"
        assert Path(path).exists()
    finally:
        monkeypatch.delenv("SPA_LIVE_ROOT", raising=False)
        importlib.reload(Q)
