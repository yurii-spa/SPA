"""N1 (ADR-580 §C8 REVIEW_2, 2026-10-05) — положительный контроль, реплей находки.

Независимый ре-ревьюер нашёл: `ensure_faithful_stand` симлинкала КАЖДЫЙ не-`data`
верхнеуровневый узел `tree_root`, а в проде `tree_root` РАВЕН живому дереву
(`com.spa.decision_loop` → findings_bridge, ADR-414). Ребёнок, получивший
`SPA_LIVE_ROOT=<стенд>`, резолвил `<стенд>/nimbalyst-local/tracker` ПРЯМО в
прод-трекер: `owner_queue.queue.TRACKER_DIR` указывал бы туда же, что живой флот,
и писатель (не знающий о стенде) писал бы в прод.

Два звена починки, и у каждого свой контроль ниже:

* (a) `ensure_faithful_stand` — мутабельные узлы (`nimbalyst-local/`,
  `landing/src/data`, `spa_core/database/spa.db`) теперь КОПИРУЮТСЯ, а не
  симлинкаются; `.git` ОМИТАЕТСЯ.
* (b) `live_paths.assert_not_prod_realpath` / broadened
  `_refuse_if_leaking_to_prod` — ДАЖЕ если где-то останется симлинк на
  прод-подкаталог, резолвящийся путь ВНУТРИ `DEFAULT_LIVE_ROOT` (не только
  РАВНЫЙ ему) теперь тоже отказ.

Каждый тест ниже красен на СВОЁМ звене, если его откатить — см. докстринг
теста для того, как это проверено.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from spa_core.monitoring import run_identity_key_price as g16
from spa_core.owner_queue import queue as Q
from spa_core.utils import live_paths as LP

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _fake_prod_with_tracker(tmp_path: Path, name: str) -> tuple[Path, Path, bytes]:
    """Фальшивый «прод»: `<home>/Documents/SPA_Claude` с живым трекером внутри."""
    fake_home = tmp_path / name
    fake_prod = fake_home / "Documents" / "SPA_Claude"
    tracker = fake_prod / "nimbalyst-local" / "tracker"
    tracker.mkdir(parents=True)
    card = tracker / "own-живой-вопрос.md"
    card.write_text("---\nstatus: needs-owner\n---\n\nЖивой след владельца.\n",
                    encoding="utf-8")
    (fake_prod / "data").mkdir()
    return fake_home, fake_prod, card.read_bytes()


# ===========================================================================
# (a) ensure_faithful_stand — мутабельный узел КОПИРУЕТСЯ, а не симлинкается
# ===========================================================================


class TestStandCopiesMutableStateInsteadOfSymlinking:

    def test_nimbalyst_local_lands_as_a_real_copy_not_a_symlink(self, tmp_path):
        """Прямой контроль звена (a). ДО фикса `stand / "nimbalyst-local"` был
        бы `is_symlink() == True`, указывающим прямо в `fake_prod` — именно
        это и воспроизводит реплей ниже. Проверено откатом: временный возврат
        тела `ensure_faithful_stand` к безусловному
        `link.symlink_to(entry, ...)` для КАЖДОГО не-`data` узла делает эту
        строку красной (`is_symlink()` становится `True`), подтверждая, что
        тест действительно меряет звено (a), а не случайную деталь."""
        _, fake_prod, card_bytes = _fake_prod_with_tracker(tmp_path, "prod_a1")
        stand = tmp_path / "stand"
        (stand / "data").mkdir(parents=True)

        g16.ensure_faithful_stand(stand, fake_prod)

        linked = stand / "nimbalyst-local"
        assert linked.exists()
        assert not linked.is_symlink(), (
            "N1: nimbalyst-local остался симлинком на прод-дерево — утечка (a) не закрыта")
        card = linked / "tracker" / "own-живой-вопрос.md"
        assert card.read_bytes() == card_bytes, "копия обязана быть ЧИТАЕМОЙ, как и ссылка"

    def test_writing_into_the_stand_copy_never_touches_the_real_tracker(self, tmp_path):
        """Обратная сторона: раз копия — запись в СТЕНД не долетает до прод-файла,
        в отличие от того, что происходило бы со ссылкой."""
        _, fake_prod, _ = _fake_prod_with_tracker(tmp_path, "prod_a2")
        stand = tmp_path / "stand"
        (stand / "data").mkdir(parents=True)
        g16.ensure_faithful_stand(stand, fake_prod)

        leak_attempt = stand / "nimbalyst-local" / "tracker" / "leak.md"
        leak_attempt.write_text("утечка", encoding="utf-8")

        assert not (fake_prod / "nimbalyst-local" / "tracker" / "leak.md").exists(), (
            "запись в копию стенда долетела до прод-дерева — это и есть N1")

    def test_git_is_omitted_not_copied_not_linked(self, tmp_path):
        """`.git` слишком объёмен для копии (REVIEW_2) — честное «отсутствует»,
        не симлинк и не копия."""
        fake_home = tmp_path / "prod_a3"
        fake_prod = fake_home / "Documents" / "SPA_Claude"
        (fake_prod / ".git").mkdir(parents=True)
        (fake_prod / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
        (fake_prod / "data").mkdir()
        stand = tmp_path / "stand"
        (stand / "data").mkdir(parents=True)

        g16.ensure_faithful_stand(stand, fake_prod)

        assert not (stand / ".git").exists()
        assert not (stand / ".git").is_symlink()


# ===========================================================================
# (b) live_paths — REALPATH внутри прод-дерева тоже отказ, не только равенство
# ===========================================================================


class TestDestinationGuardCatchesNestedLeaksToo:

    def test_a_symlink_into_a_prod_subdir_is_refused_even_though_it_is_not_equal(
            self, tmp_path, monkeypatch):
        """Независимый контроль звена (b): даже если КТО-ТО (новый харнесс,
        забытый код) оставит симлинк на подкаталог прод-дерева — не на сам
        `DEFAULT_LIVE_ROOT`, а на его ПОТОМКА — `assert_not_prod_realpath`
        обязан поймать это. Сцена строится РУКАМИ (не через
        `ensure_faithful_stand`, которая теперь это закрывает сама), чтобы
        проверить ИМЕННО приёмник, а не звено (a)."""
        fake_prod = tmp_path / "prod_b1"
        (fake_prod / "nimbalyst-local" / "tracker").mkdir(parents=True)
        monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", fake_prod)
        monkeypatch.setenv(LP.SANDBOX_ENV, "1")

        stand = tmp_path / "stand_b1"
        stand.mkdir()
        # Форма ДО фикса (a): стенд держит симлинк прямо на прод-подкаталог.
        (stand / "nimbalyst-local").symlink_to(fake_prod / "nimbalyst-local",
                                               target_is_directory=True)
        candidate = stand / "nimbalyst-local" / "tracker"

        with pytest.raises(LP.SandboxLeakError):
            LP.assert_not_prod_realpath(candidate, who="test")

    def test_without_the_broadened_check_the_same_scene_would_not_be_caught(
            self, tmp_path, monkeypatch):
        """Контроль «метка нашла бы находку, если бы проверки не было» (тот же
        приём, что у `test_without_the_destination_guard_the_scene_would_have_leaked`
        в `test_sandbox_prod_leak_inc1.py`): откатываем ТОЛЬКО расширение —
        чистым равенством (как было ДО REVIEW_2) — и подтверждаем, что
        именно ОНО не видит потомка. Без этого контроля первый тест мог бы
        быть зелёным по случайности."""
        fake_prod = tmp_path / "prod_b2"
        (fake_prod / "nimbalyst-local" / "tracker").mkdir(parents=True)
        monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", fake_prod)
        monkeypatch.setenv(LP.SANDBOX_ENV, "1")
        # Откат (b): равенство, а не «совпадает ИЛИ лежит внутри» — ровно
        # форма ДО этой правки.
        monkeypatch.setattr(LP, "_is_same_or_within", lambda c, p: c == p)

        stand = tmp_path / "stand_b2"
        stand.mkdir()
        (stand / "nimbalyst-local").symlink_to(fake_prod / "nimbalyst-local",
                                               target_is_directory=True)
        candidate = stand / "nimbalyst-local" / "tracker"

        # С откатом (b) отказа НЕТ — именно это чистое равенство не видит;
        # без этого контроля падение первого теста недоказательно.
        LP.assert_not_prod_realpath(candidate, who="test")  # не поднимает

    def test_no_leak_no_marker_resolves_normally(self, tmp_path, monkeypatch):
        """Нулевой побочный эффект: обычный путь, не лежащий в прод-дереве,
        под маркером не отказывает."""
        fake_prod = tmp_path / "prod_b3"
        fake_prod.mkdir()
        monkeypatch.setattr(LP, "DEFAULT_LIVE_ROOT", fake_prod)
        monkeypatch.setenv(LP.SANDBOX_ENV, "1")
        safe = tmp_path / "sandbox" / "nimbalyst-local" / "tracker"
        LP.assert_not_prod_realpath(safe, who="test")  # не поднимает


# ===========================================================================
# Сквозной реплей: субпроцесс, маркер, TRACKER_DIR — ровно сцена ревьюера
# ===========================================================================


def _run_tracker_probe(env: dict, *, timeout: int = 60) -> subprocess.CompletedProcess:
    code = (
        "import json\n"
        "from spa_core.owner_queue.queue import TRACKER_DIR\n"
        "TRACKER_DIR.mkdir(parents=True, exist_ok=True)\n"
        "(TRACKER_DIR / 'leak-attempt.md').write_text('утечка', encoding='utf-8')\n"
        "print(json.dumps({'tracker_dir': str(TRACKER_DIR)}))\n"
    )
    return subprocess.run([sys.executable, "-c", code], env=env,
                          capture_output=True, text=True, timeout=timeout)


def test_reviewer_scenario_end_to_end_prod_tracker_stays_byte_identical(tmp_path):
    """Сквозной реплей сцены ревьюера: `ensure_faithful_stand` строит стенд из
    фальшивого «прода» КАК tree_root (ровно форма INC-1/N1 — в проде
    `tree_root` и есть живое дерево), ребёнок получает `SPA_SANDBOX=1` +
    `SPA_LIVE_ROOT=<стенд>` (ровно так, как это делают `run_arm`/`run_probe`/
    `_run_http_probe`) и пытается ПИСАТЬ через `owner_queue.queue.TRACKER_DIR`.

    Ожидание (дизъюнкция из заказа): либо отказ (`SandboxLeakError`), либо
    запись уходит ТОЛЬКО в копию стенда — в обоих случаях прод-трекер
    остаётся байт-в-байт тем же, чем был.
    """
    fake_home, fake_prod, card_bytes = _fake_prod_with_tracker(tmp_path, "prod_e2e")
    card_path = fake_prod / "nimbalyst-local" / "tracker" / "own-живой-вопрос.md"

    stand = tmp_path / "stand_e2e"
    (stand / "data").mkdir(parents=True)
    g16.ensure_faithful_stand(stand, fake_prod)

    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["PYTHONPATH"] = str(_REPO_ROOT)
    env.pop("SPA_TRACKER_DIR", None)
    env[LP.SANDBOX_ENV] = "1"
    env[LP.LIVE_ROOT_ENV] = str(stand)
    env[LP.DATA_DIR_ENV] = str(stand / "data")

    proc = _run_tracker_probe(env)

    # Прод-трекер — неизменный, что бы ни случилось внутри ребёнка.
    assert card_path.read_bytes() == card_bytes, (
        "прод-трекер изменился — это ровно N1, защита не сработала")
    assert not (fake_prod / "nimbalyst-local" / "tracker" / "leak-attempt.md").exists(), (
        "новый файл утечки появился В ПРОД-трекере")

    if proc.returncode == 0:
        # Запись удалась — она ОБЯЗАНА была уйти в копию стенда, не в прод.
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        resolved = Path(out["tracker_dir"]).resolve()
        assert fake_prod.resolve() not in (resolved, *resolved.parents), (
            "TRACKER_DIR резолвится в прод-дерево — утечка")
        assert (stand / "nimbalyst-local" / "tracker" / "leak-attempt.md").exists(), (
            "процесс завершился успехом, но файл не найден даже в копии стенда"
        )
    else:
        assert "SandboxLeakError" in proc.stderr, proc.stderr[-800:]
