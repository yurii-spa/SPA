"""Батарея прибора «проводка упоминанием сироты» (ADR-1026).

# LLM_FORBIDDEN

Каждая сцена — положительный контроль одной стороны вердикта, и у каждой есть
обратное плечо: прибор, который ВСЁ называет находкой, и прибор, который не
называет НИЧЕГО, одинаково бесполезны, а различить их можно только парой сцен
с ПРОТИВОПОЛОЖНЫМИ ответами.

Сцены идут на ОДНОРАЗОВОМ дереве — живое дерево ни одна из них не трогает.
Отдельно стоя́т два утверждения о ЖИВОМ дереве: паритет с храповиком (правило
«что считается упоминанием» живёт в одном месте) и само население замера.
"""
from __future__ import annotations

import pathlib

import pytest

from spa_core.tests import _mention_wiring as mw
from spa_core.tests import test_unwired_guard_modules_ratchet as ratchet

_ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Замер 2026-11-16 (цикл #1165) на `origin/main` 8225f7dea: население ПОЛА
#: класса. Может только УМЕНЬШАТЬСЯ — член либо подключают к достижимому
#: вызывающему, либо выводят карточкой. Дописывать сюда, чтобы погасить
#: падение, ЗАПРЕЩЕНО (тот же порядок, что у `KNOWN_UNWIRED`).
POPULATION_2026_11_16 = {
    # ← edition_cause (сам в переписи) и producer_input_awareness (сам член класса)
    "spa_core/monitoring/edition_remeasure.py",
    # ← findings_bridge_c125, который стои́т в KNOWN_UNWIRED с самой базы
    "spa_core/monitoring/house_view_gap_c125.py",
    # ← shared_read_door_leverage (сам в переписи) — случай, названный #1163
    "spa_core/monitoring/producer_input_awareness.py",
}


def _mk(root: pathlib.Path, rel: str, body: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _subject(name: str) -> str:
    return (f'"""Сторож {name}."""\n'
            "def main():\n    return 0\n"
            'if __name__ == "__main__":\n    raise SystemExit(main())\n')


def _scene(tmp_path: pathlib.Path) -> pathlib.Path:
    root = tmp_path / "tree"
    (root / "spa_core" / "monitoring").mkdir(parents=True)
    return root


class TestSyntheticScenes:
    def test_a_mention_from_a_declared_root_is_wiring(self, tmp_path):
        """НУЛЕВАЯ ПРОБА: настоящий вызывающий ⇒ население ПУСТО.

        Без неё «население 3» нельзя отличить от «прибор всё зовёт находкой».
        """
        root = _scene(tmp_path)
        _mk(root, "spa_core/monitoring/alpha.py", _subject("alpha"))
        _mk(root, "scripts/caller.py",
            "from spa_core.monitoring import alpha\nalpha.main()\n")
        rep = mw.measure(root, min_subjects=1)
        assert rep["orphan_chain"] == [], rep["orphan_chain"]
        assert rep["status"]["spa_core/monitoring/alpha.py"] == mw.REACHABLE
        assert mw.main(["--root", str(root), "--min-subjects", "1"]) == 0

    def test_a_mention_from_an_orphan_is_not_wiring(self, tmp_path):
        """Предмет класса: упоминающего САМОГО не зовёт никто."""
        root = _scene(tmp_path)
        _mk(root, "spa_core/monitoring/alpha.py", _subject("alpha"))
        _mk(root, "spa_core/monitoring/beta.py",
            _subject("beta") + "from spa_core.monitoring import alpha\n")
        rep = mw.measure(root, min_subjects=1)
        assert [i["module"] for i in rep["orphan_chain"]] == [
            "spa_core/monitoring/alpha.py"]
        assert rep["status"]["spa_core/monitoring/beta.py"] == mw.CENSUS, (
            "упоминающий обязан остаться в переписи храповика — иначе прибор "
            "назвал бы находкой того, кто и так на учёте")
        assert rep["orphan_chain"][0]["mentioned_by"] == [
            {"path": "spa_core/monitoring/beta.py", "status": mw.CENSUS}]
        assert mw.main(["--root", str(root), "--min-subjects", "1"]) == 1

    def test_the_chain_is_followed_to_its_root_not_one_step(self, tmp_path):
        """Обратное плечо фикспойнта: достижимость идёт ВПЕРЁД, а не на шаг.

        Цепь выложена ПРОТИВ порядка обхода (обход сортированный: alpha, beta,
        gamma — а зовут в обратную сторону, корень → gamma → beta → alpha).
        Без этого сцена была бы зелена и у прибора, считающего один шаг:
        прямой порядок разрешается за один проход случайно, по сортировке.
        Прибор, считающий только соседа, объявил бы находками alpha и beta —
        то есть ВЫДУМАЛ бы две.
        """
        root = _scene(tmp_path)
        _mk(root, "scripts/caller.py",
            "from spa_core.monitoring import gamma\ngamma.main()\n")
        _mk(root, "spa_core/monitoring/gamma.py",
            _subject("gamma") + "from spa_core.monitoring import beta\n")
        _mk(root, "spa_core/monitoring/beta.py",
            _subject("beta") + "from spa_core.monitoring import alpha\n")
        _mk(root, "spa_core/monitoring/alpha.py", _subject("alpha"))
        rep = mw.measure(root, min_subjects=1)
        assert rep["orphan_chain"] == [], rep["orphan_chain"]
        assert all(v == mw.REACHABLE for v in rep["status"].values()), rep["status"]
        assert rep["fixpoint_rounds"] >= 3, (
            "цепь из трёх, выложенная против порядка обхода, обязана потребовать "
            f"больше двух проходов; вышло {rep['fixpoint_rounds']} — "
            "утверждение о транзитивности ничем не проверено")

    def test_two_orphans_mentioning_each_other_do_not_wire_themselves(self, tmp_path):
        """Взаимное упоминание — не проводка, и именно его храповик не видит.

        depth-1 назвал бы ОБОИХ подключёнными: у каждого есть упоминающий.
        """
        root = _scene(tmp_path)
        _mk(root, "spa_core/monitoring/alpha.py",
            _subject("alpha") + "from spa_core.monitoring import beta\n")
        _mk(root, "spa_core/monitoring/beta.py",
            _subject("beta") + "from spa_core.monitoring import alpha\n")
        rep = mw.measure(root, min_subjects=1)
        assert sorted(i["module"] for i in rep["orphan_chain"]) == [
            "spa_core/monitoring/alpha.py", "spa_core/monitoring/beta.py"]
        assert rep["census_depth1"] == [], (
            "у обоих есть упоминающий, поэтому в переписи храповика их нет — "
            "на этом и стои́т весь класс")

    def test_prose_is_judged_by_the_ratchets_door_not_a_second_copy(self, tmp_path):
        """Упоминание в докстроке ⇒ субъект падает в ПЕРЕПИСЬ, а не в класс.

        Срез прозы здесь не свой: его делают функции храповика. Сцена ловит
        появление второй копии правила.
        """
        root = _scene(tmp_path)
        _mk(root, "spa_core/monitoring/alpha.py", _subject("alpha"))
        _mk(root, "scripts/caller.py", '"""Аналог alpha.py для Engine B."""\nx = 1\n')
        rep = mw.measure(root, min_subjects=1)
        assert rep["census_depth1"] == ["spa_core/monitoring/alpha.py"]
        assert rep["orphan_chain"] == [], (
            "сирота depth-1 не является членом ЭТОГО класса: он уже на учёте")


class TestNotMeasuredIsItsOwnOutcome:
    def test_a_thin_surface_is_not_zero_findings(self, tmp_path):
        root = _scene(tmp_path)
        _mk(root, "spa_core/monitoring/alpha.py", _subject("alpha"))
        with pytest.raises(mw.Unmeasured) as e:
            mw.measure(root)
        assert "скан сузился" in str(e.value)
        assert mw.main(["--root", str(root)]) == 2, "НЕ ИЗМЕРЕНО обязано дать код 2"

    def test_an_unreadable_file_is_not_zero_findings(self, tmp_path):
        """Нечитаемый файл мог быть настоящим вызывающим ⇒ fail-CLOSED."""
        root = _scene(tmp_path)
        for i in range(60):
            _mk(root, f"spa_core/monitoring/m{i}.py", _subject(f"m{i}"))
        blind = root / "scripts" / "blind.py"
        _mk(root, "scripts/blind.py", "x = 1\n")
        blind.chmod(0o000)
        try:
            try:
                blind.read_text(encoding="utf-8")
            except OSError:
                pass
            else:
                pytest.fail(
                    "предпосылка НЕ ОБЕСПЕЧЕНА: файл с режимом 000 всё равно "
                    "читается (прогон от root?) — судить о слепом файле нечем")
            with pytest.raises(mw.Unmeasured) as e:
                mw.measure(root, min_subjects=1)
            assert "scripts/blind.py" in str(e.value)
        finally:
            blind.chmod(0o644)

    def test_the_two_refusals_do_not_look_like_a_clean_pass(self, tmp_path):
        """Код 2 отличается и от 0, и от 1 — три исхода различимы (инв. #17)."""
        root = _scene(tmp_path)
        _mk(root, "spa_core/monitoring/alpha.py", _subject("alpha"))
        _mk(root, "scripts/caller.py",
            "from spa_core.monitoring import alpha\nalpha.main()\n")
        assert mw.main(["--root", str(root)]) == 2, (
            "пол непустоты снят умолчанием — «чисто» стало неотличимо от "
            "«мерить было нечем»")


class TestTheLiveTree:
    def test_the_depth1_census_matches_the_ratchet(self):
        """ОДНА дверь: прибор и храповик обязаны видеть одну перепись.

        Разойдись они — прибор судил бы о чужом дереве, а не о том, которое
        сторожит храповик, и число населения ничего бы не значило.
        """
        rep = mw.measure(_ROOT)
        assert set(rep["census_depth1"]) == ratchet._census(), (
            "перепись прибора разошлась с переписью храповика: "
            f"только у прибора {sorted(set(rep['census_depth1']) - ratchet._census())}, "
            f"только у храповика {sorted(ratchet._census() - set(rep['census_depth1']))}")

    def test_the_measurement_is_not_vacuous(self):
        rep = mw.measure(_ROOT)
        assert rep["subjects"] >= mw.MIN_SUBJECTS
        assert rep["deemed_wired_depth1"] >= 150, (
            f"подключённых всего {rep['deemed_wired_depth1']} — поверхность "
            "класса сузилась, и ноль находок значил бы «мерить нечем»")

    def test_no_new_member_joins_the_class(self):
        rep = mw.measure(_ROOT)
        new = sorted({i["module"] for i in rep["orphan_chain"]}
                     - POPULATION_2026_11_16)
        assert not new, (
            f"новый сторож подключён УПОМИНАНИЕМ сироты: {new}. Упоминание от "
            "того, кого самого никто не зовёт, проводкой не является — "
            "подключить к достижимому вызывающему или вывести карточкой. "
            "В POPULATION_2026_11_16 НЕ дописывать (инв. #16).")

    def test_a_fixed_member_leaves_the_declared_set(self):
        rep = mw.measure(_ROOT)
        gone = sorted(POPULATION_2026_11_16
                      - {i["module"] for i in rep["orphan_chain"]})
        assert not gone, (
            f"эти модули больше не члены класса: {gone} — убери их из "
            "POPULATION_2026_11_16, иначе список перестанет что-либо значить.")

    def test_every_declared_member_still_names_a_real_module(self):
        missing = sorted(m for m in POPULATION_2026_11_16
                         if not (_ROOT / m).exists())
        assert not missing, f"в объявлении призраки: {missing}"

    def test_the_claim_is_about_mentioners_not_just_counts(self):
        """Утверждение класса проверяется ПОИМЁННО, а не числом.

        Число совпало бы и при другом составе; предмет же в том, что у
        КАЖДОГО члена ни один упоминающий сам не достижим.
        """
        rep = mw.measure(_ROOT)
        for item in rep["orphan_chain"]:
            assert item["mentioned_by"], (
                f"{item['module']} попал в класс без упоминающих — это сирота "
                "depth-1, её место в переписи храповика")
            bad = [m for m in item["mentioned_by"]
                   if m["status"] not in (mw.CENSUS, mw.ORPHAN_CHAIN)]
            assert not bad, (
                f"{item['module']}: упоминающий достижим, значит член назван "
                f"ошибочно: {bad}")
