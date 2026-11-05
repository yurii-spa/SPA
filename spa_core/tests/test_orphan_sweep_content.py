#!/usr/bin/env python3
"""Четвёртая дверь переписи сирот: «содержимое доставлено ИНЫМ путём» (ADR-926).

Предмет батареи — живой дефект, найденный самим прибором. Замер #1038 поднял
`~/Documents/SPA_worktrees/yield01` ФАЙЛАМИ (21 файл, 1646 строк, только
добавления), а не `cherry-pick`: байты уехали на `origin/main`, коммиты дерева
— нет и не уедут никогда. Прибор #1039 назвал то же дерево кандидатом СНОВА и
был прав по своей мерке и неверен по предмету.

Сцены строятся на ЖИВОМ `git`, а не на подменённом словаре: контроль,
собравший себе словарь, мерит свой словарь, а не проводку (урок #944/#945).
**Имя ветки объявлено входом сцены** (`git init -b main`) — `init.defaultBranch`
у Apple Git `main`, у git на `ubuntu-latest` `master`, и фикстура без `-b`
зелена здесь и красна там (`.claude/rules/deployment.md`, § «GIT-ОКРУЖЕНИЕ»).

Часов в приборе нет вовсе, поэтому замороженных дат здесь нет и быть не может.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from spa_core.monitoring import orphan_sweep as osw  # noqa: E402

BRANCH = "main"


def git(repo, *args):
    out = subprocess.run(["git", "-C", str(repo), *args],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} в {repo}: {out.stderr.strip()}")
    return out.stdout.strip()


def commit(repo, name, text="x", message=None):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    git(repo, "add", name)
    git(repo, "commit", "-m", message or f"touch {name}")
    return git(repo, "rev-parse", "HEAD")


class ContentDoorScenes(unittest.TestCase):
    """upstream (роль origin) + ПОЛНЫЙ клон (отвечает о родословной) + рабочий."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.up = base / "upstream"
        self.up.mkdir()
        git(self.up, "init", "-b", BRANCH, "--quiet")
        git(self.up, "config", "user.email", "t@t")
        git(self.up, "config", "user.name", "t")
        for i in range(2):
            commit(self.up, f"f{i}.txt")

        self.full = base / "full"
        git(base, "clone", "--quiet", f"file://{self.up}", str(self.full))

        self.work = base / "work"
        git(base, "clone", "--quiet", f"file://{self.up}", str(self.work))
        git(self.work, "config", "user.email", "t@t")
        git(self.work, "config", "user.name", "t")
        self.base = base

    def tearDown(self):
        self.tmp.cleanup()

    # ── помощники сцены ──────────────────────────────────────────────────────
    def _upstream_gets(self, name, text):
        """Тот же путь уезжает на `ref` ДРУГИМ путём (так и было у #1038).

        Сообщение коммита НАМЕРЕННО другое. Без этого сцена ломалась неочевидно:
        sha коммита складывается из дерева, родителя, подписи, СООБЩЕНИЯ и
        секунды, — и «те же байты, тот же родитель, то же сообщение, та же
        секунда» давали ОДИН И ТОТ ЖЕ коммит в обоих клонах, то есть сцена
        воспроизводила `cherry-pick`, а не доставку файлами.
        """
        commit(self.up, name, text, message=f"доставка файлами: {name}")
        git(self.full, "fetch", "--quiet", "origin", BRANCH)
        git(self.full, "update-ref", f"refs/remotes/origin/{BRANCH}",
            git(self.up, "rev-parse", BRANCH))

    def sweep(self):
        return osw.sweep(self.work, ref=f"origin/{BRANCH}",
                         lineage_candidates=[str(self.full)])

    def _candidate(self, doc):
        self.assertEqual(doc["state"], "measured", doc.get("reason"))
        self.assertEqual(len(doc["candidates"]), 1, doc["tally"])
        return doc["candidates"][0]

    # ── сцена 1: БАЙТЫ совпали — дерево не сирота ───────────────────────────
    def test_identical_bytes_on_ref_mean_delivered_not_a_candidate(self):
        commit(self.work, "evidence/report.md", "ровно эти байты")
        self._upstream_gets("evidence/report.md", "ровно эти байты")
        doc = self.sweep()
        row = self._candidate(doc)
        self.assertEqual(row["verdict"], "never_pushed")
        self.assertEqual(row["content"], "delivered", row.get("content_reason"))
        self.assertEqual(row["content_paths"]["same"], 1)
        self.assertEqual(doc["fresh_delivered"], [row])
        self.assertEqual(doc["fresh_to_raise"], [])

    def test_delivered_candidate_turns_the_exit_code_from_one_to_zero(self):
        # ПРОМАХ-половина проводки: мало решить — решение обязано дойти до кода
        # возврата, иначе следующий цикл по-прежнему зовут поднимать пустоту.
        commit(self.work, "evidence/report.md", "ровно эти байты")
        self._upstream_gets("evidence/report.md", "ровно эти байты")
        code = osw.main(["--repo-root", str(self.work), "--ref", f"origin/{BRANCH}",
                         "--lineage", str(self.full), "--no-write"])
        self.assertEqual(code, 0)

    def test_report_says_delivered_in_words_not_only_in_a_field(self):
        commit(self.work, "evidence/report.md", "ровно эти байты")
        self._upstream_gets("evidence/report.md", "ровно эти байты")
        doc = self.sweep()
        text = "\n".join(osw.report(doc))
        self.assertIn("СОДЕРЖИМОЕ УЖЕ ДОСТАВЛЕНО", text)
        self.assertIn("поднимать нечего", text)
        self.assertNotIn("🔶 ПОДНЯТЬ", text)
        # ОТДЕЛЬНОЕ утверждение, и его отсутствие пережило мутацию: мало
        # сменить заголовок строки — ПРИЧИНА вердикта обязана быть НАПЕЧАТАНА,
        # иначе она живёт только полем в json и читателю недоступна.
        self.assertIn("содержимое (delivered)", text)
        self.assertIn(doc["candidates"][0]["content_reason"], text)

    def test_report_prints_the_content_reason_for_a_real_candidate_too(self):
        # Обратная сторона: у НАСТОЯЩЕГО кандидата причина тоже печатается —
        # иначе строка появлялась бы только в «хорошем» исходе.
        commit(self.work, "evidence/brand_new.md", "работа")
        doc = self.sweep()
        text = "\n".join(osw.report(doc))
        self.assertIn("содержимое (pending)", text)
        self.assertIn(doc["candidates"][0]["content_reason"], text)

    def test_content_tally_is_printed_in_words_not_only_in_the_doc(self):
        commit(self.work, "evidence/brand_new.md", "работа")
        text = "\n".join(osw.report(self.sweep()))
        self.assertIn("содержимое у кандидатов:", text)
        self.assertIn("«НЕ ИЗМЕРЕНО» доставленным не считается", text)

    # ── сцена 2: байты РАЗОШЛИСЬ — кандидат настоящий ───────────────────────
    def test_different_bytes_on_ref_keep_the_candidate_real(self):
        commit(self.work, "evidence/report.md", "моя версия")
        self._upstream_gets("evidence/report.md", "ЧУЖАЯ версия")
        doc = self.sweep()
        row = self._candidate(doc)
        self.assertEqual(row["content"], "pending", row.get("content_reason"))
        self.assertEqual(row["content_paths"]["differs"], 1)
        self.assertEqual(doc["fresh_to_raise"], [row])
        self.assertEqual(osw.main(["--repo-root", str(self.work),
                                   "--ref", f"origin/{BRANCH}",
                                   "--lineage", str(self.full), "--no-write"]), 1)

    # ── сцена 3: пути на `ref` НЕТ ВОВСЕ — самый частый вид сироты ──────────
    def test_a_path_absent_on_ref_is_its_own_state_not_merged_with_differs(self):
        commit(self.work, "evidence/brand_new.md", "работа, которой нигде нет")
        doc = self.sweep()
        row = self._candidate(doc)
        self.assertEqual(row["content"], "pending")
        self.assertEqual(row["content_paths"]["absent_on_ref"], 1)
        self.assertEqual(row["content_paths"]["differs"], 0)
        self.assertEqual(doc["fresh_to_raise"], [row])

    # ── сцена 4: СМЕШАННАЯ — один путь совпал, другой нет ───────────────────
    def test_one_divergent_path_is_enough_to_keep_the_candidate(self):
        commit(self.work, "evidence/same.md", "одинаково")
        commit(self.work, "evidence/other.md", "по-своему")
        self._upstream_gets("evidence/same.md", "одинаково")
        doc = self.sweep()
        row = self._candidate(doc)
        self.assertEqual(row["content"], "pending", row.get("content_reason"))
        self.assertEqual(row["content_paths"]["same"], 1)
        self.assertEqual(row["content_paths"]["absent_on_ref"], 1)

    # ── сцена 5: третий исход, и он НЕ «доставлено» ─────────────────────────
    def test_commits_touching_no_path_are_unmeasured_not_delivered(self):
        git(self.work, "commit", "--allow-empty", "-m", "пустой коммит")
        doc = self.sweep()
        row = self._candidate(doc)
        self.assertEqual(row["content"], "unmeasured", row.get("content_reason"))
        self.assertIn("не следует", row["content_reason"])
        # Самое важное: третий исход НЕ снимает кандидата с подъёма.
        self.assertEqual(doc["fresh_to_raise"], [row])

    def test_a_path_whose_bytes_are_unreadable_blocks_delivered(self):
        # ДЫРА, найденная мутацией (выжила мутация «НЕ ИЗМЕРЕНО идёт за
        # доставку»): у батареи не было НИ ОДНОЙ сцены, где `content_door`
        # видит непрочитанный путь ВНУТРИ настоящего замера. Без неё fail-OPEN
        # жил бы молча: differs=0, absent=0 ⇒ «все совпали» при same=0.
        # Сцена настоящая, без подмен: клон родословной — НЕ репозиторий.
        commit(self.work, "evidence/report.md", "байты")
        head = git(self.work, "rev-parse", "HEAD")
        base = git(self.work, "rev-parse", "HEAD~1")
        not_a_repo = self.base / "просто-каталог"
        not_a_repo.mkdir()
        got = osw.content_door(str(self.work), not_a_repo, f"origin/{BRANCH}",
                               base=base, head=head)
        self.assertEqual(got["state"], "unmeasured", got.get("reason"))
        self.assertEqual(got["paths"]["unmeasured"], 1)
        self.assertEqual(got["paths"]["same"], 0)
        self.assertIn("НЕ", got["reason"])

    def test_one_unreadable_path_among_matching_ones_is_still_unmeasured(self):
        # Смешанная форма той же дыры и самая опасная: большинство путей
        # совпало, один НЕ ПРОЧИТАН. «Почти доставлено» доставкой не является.
        commit(self.work, "evidence/same.md", "одинаково")
        commit(self.work, "evidence/second.md", "тоже одинаково")
        self._upstream_gets("evidence/same.md", "одинаково")
        self._upstream_gets("evidence/second.md", "тоже одинаково")
        head = git(self.work, "rev-parse", "HEAD")
        base = git(self.work, "rev-parse", "HEAD~2")
        real_blob = osw._blob

        def one_path_is_silent(repo, rev, path):
            if path.endswith("second.md") and Path(repo) == self.full:
                return None, "git не ответил (сцена)"
            return real_blob(repo, rev, path)

        with mock.patch.object(osw, "_blob", one_path_is_silent):
            got = osw.content_door(str(self.work), self.full, f"origin/{BRANCH}",
                                   base=base, head=head)
        self.assertEqual(got["state"], "unmeasured", got.get("reason"))
        self.assertEqual(got["paths"]["same"], 1)
        self.assertEqual(got["paths"]["unmeasured"], 1)

    def test_missing_base_is_unmeasured_with_a_named_reason(self):
        got = osw.content_door(str(self.work), self.full, f"origin/{BRANCH}",
                               base=None, head="deadbeef")
        self.assertEqual(got["state"], "unmeasured")
        self.assertIn("НЕ ИЗМЕРЕНА", got["reason"])
        self.assertIn("НЕ «доставлено»", got["reason"])

    def test_git_silence_about_a_path_is_unmeasured_not_absent(self):
        # `_blob` обязан различать ОТВЕТ git'а «такого пути нет» (код 128) от
        # «git не ответил»: склеив их, дверь объявила бы недочитанное дерево
        # доставленным. Проверяется на несуществующем клоне.
        sha, why = osw._blob(self.base / "нет-такого-клона", "HEAD", "x.txt")
        self.assertIsNone(sha)
        self.assertNotEqual(why, "absent")
        self.assertIn("не ответил", why)

    def test_an_absent_path_is_reported_as_absent_exactly(self):
        sha, why = osw._blob(self.work, f"origin/{BRANCH}", "нет-такого-файла.md")
        self.assertIsNone(sha)
        self.assertEqual(why, "absent")

    # ── учёт и замкнутость перечней ─────────────────────────────────────────
    def test_tally_is_closed_and_adds_up(self):
        commit(self.work, "evidence/brand_new.md", "работа")
        doc = self.sweep()
        ct = doc["content_tally"]
        self.assertEqual(set(ct), set(osw.CONTENT_STATES))
        self.assertEqual(sum(ct.values()), len(doc["candidates"]))
        self.assertNotIn("abandoned", osw.CONTENT_STATES)

    def test_path_states_are_all_accounted_for_in_every_scene(self):
        commit(self.work, "evidence/brand_new.md", "работа")
        row = self._candidate(self.sweep())
        self.assertEqual(set(row["content_paths"]), set(osw.PATH_STATES))

    def test_content_door_is_asked_of_the_full_clone_not_the_work_tree(self):
        # ADR-918: о `ref` спрашивает ПОЛНЫЙ клон. Сцена: путь есть на `ref`
        # только у полного клона (рабочий свой `origin/main` не обновлял) —
        # ответ «доставлено» возможен ТОЛЬКО если спрошен полный.
        commit(self.work, "evidence/report.md", "ровно эти байты")
        self._upstream_gets("evidence/report.md", "ровно эти байты")
        stale = git(self.work, "rev-parse", f"origin/{BRANCH}")
        fresh = git(self.full, "rev-parse", f"origin/{BRANCH}")
        self.assertNotEqual(stale, fresh, "сцена не воспроизвела отставание клона")
        self.assertEqual(self._candidate(self.sweep())["content"], "delivered")


if __name__ == "__main__":
    unittest.main()
