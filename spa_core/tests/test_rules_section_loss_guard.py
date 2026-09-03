"""Раздел правила не исчезает молча у двери доставки (карточка
`inbox-u-failov-claude-rules-net-ni-odnogo-stor`, цикл #456).

**Положительный контроль — настоящая авария, побайтово.** `ba66e1bd3` (30.08.2026)
принёс свой пункт 8 в `.claude/rules/deployment.md` поверх УСТАРЕВШЕЙ копии файла и
унёс с собой 104 строки: «Четыре вопроса — четыре разных сторожа» (файл откатился к
редакции «Три вопроса»), «Долгоживущий агент держит код с момента старта», «Проверка
долгожителя НЕ ИМЕЕТ ПРАВА его запускать» и «ЛИЧНОСТЬ ПРОЦЕССА в тестах». Шесть дней
этих правил не существовало, а карточка, `docs/STATE.md` и журнал хором числили класс
закрытым «ПРАВИЛОМ». Пропажу нашёл не сторож, а случайность (#453).

Обе редакции лежат в `fixtures/rules_section_loss/` байт в байт из истории — не
выкачиваются `git show`, потому что CI клонирует на глубину 1, а скип превращает «не
измерено» в неотличимое от «прошло» (запрещено `.claude/rules/deployment.md`).

Цена ошибки самой проверки ИЗМЕРЕНА, а не предположена, и ПЕРЕМЕРЕНА при подъёме #467
(вся история `.claude/rules/`: 29 коммитов, 22 пары «коммит+файл», где файл существовал
и в родителе — у #456 было 16, население выросло вместе с историей): отказов 3 — одна настоящая авария и
два законных переписывания заголовка ВМЕСТЕ с телом («Три вопроса» → «Четыре вопроса»,
`7ed5b3da4` и `2828e2ac5`). Такое переименование неотличимо от пропажи по построению,
поэтому оно не гасится молча, а разрешается человеком по трём уликам в тексте отказа:
что пропало, что появилось взамен, куда поехал объём. Ниже это закреплено тестом —
чтобы улики не отвалились вместе с рефакторингом сообщения.

Времени в тестах нет: сравнение чисто содержательное, литеральных дат в фикстурах-байтах
нет (даты внутри исторических редакций — предмет, а не окружение).
"""
import importlib.util
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FIX = Path(__file__).resolve().parent / "fixtures" / "rules_section_loss"
_spec = importlib.util.spec_from_file_location(
    "_pusher_under_test", _ROOT / "push_to_github.py")
pusher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pusher)

RULE = ".claude/rules/deployment.md"
SHA = "ba66e1bd3aa"


def _fixture(name: str) -> bytes:
    return (_FIX / name).read_bytes()


BEFORE = _fixture("deployment_637b55bbb_before.md")
AFTER = _fixture("deployment_ba66e1bd3_after.md")


def rule(*sections: str) -> bytes:
    """Файл правила из перечисленных разделов; тело раздела зависит от заголовка."""
    out = [b"# Rule\n\n"]
    for s in sections:
        out.append(f"## {s}\n\nтело раздела {s}.\n\n".encode())
    return b"".join(out)


class IncidentBa66e1bd3(unittest.TestCase):
    """Та самая доставка 30.08 — она обязана НЕ пройти."""

    def test_fixtures_are_the_incident(self):
        """Предпосылка контроля: фикстуры и правда несут ту самую потерю.

        `git show --stat ba66e1bd3` — 10 вставок против 104 удалений, то есть
        НЕТТО −94 строки. Проверяем нетто (его и считает сторож) и исчезновение
        заголовка, по которому авария опознаётся.
        """
        self.assertEqual(BEFORE.count(b"\n") - AFTER.count(b"\n"), 94)
        head = "## Четыре вопроса".encode()
        self.assertIn(head, BEFORE)
        self.assertNotIn(head, AFTER)

    def test_incident_is_refused(self):
        with self.assertRaises(pusher.RulesSectionLossRefused) as ctx:
            pusher.guard_rules_section_loss(RULE, BEFORE, AFTER, SHA)
        msg = str(ctx.exception)
        for lost in ("Четыре вопроса",
                     "Долгоживущий агент держит код с момента старта",
                     "Проверка долгожителя НЕ ИМЕЕТ ПРАВА его запускать",
                     "ЛИЧНОСТЬ ПРОЦЕССА в тестах"):
            self.assertIn(lost, msg, f"отказ не назвал пропавший раздел: {lost}")

    def test_refusal_carries_the_three_clues(self):
        """Пропало / появилось взамен / куда поехал объём — иначе человек не рассудит."""
        with self.assertRaises(pusher.RulesSectionLossRefused) as ctx:
            pusher.guard_rules_section_loss(RULE, BEFORE, AFTER, SHA)
        msg = str(ctx.exception)
        self.assertIn("Появилось взамен", msg)
        self.assertIn("Три вопроса", msg)          # улика переименования
        self.assertIn("-94", msg)                  # улика усадки (нетто)

    def test_restoration_is_refused_too_and_the_clues_tell_it_apart(self):
        """Честная цена сторожа: ВОССТАНОВЛЕНИЕ он тоже останавливает — и это верно.

        Возврат файла к полной редакции переименовывает «Три вопроса» обратно в
        «Четыре вопроса» вместе с телом, а такое переименование неотличимо от
        пропажи ПО ПОСТРОЕНИЮ. Именно так `2828e2ac5` (#453, восстановление 104
        строк) попал в измеренные 3 отказа на 16 коммитов истории правил.

        Сторож поэтому обязан не «угадать намерение», а выдать улики: пропал ОДИН
        заголовок, взамен появились ЧЕТЫРЕ, файл ВЫРОС на 94 строки. Человек
        рассуждает по ним за один взгляд и проходит через `--allow-overwrite`.
        Если этот тест позеленеет «сам собой» — значит кто-то научил сторожа
        молчать на потере раздела, а это ослабление (инвариант #16).
        """
        with self.assertRaises(pusher.RulesSectionLossRefused) as ctx:
            pusher.guard_rules_section_loss(RULE, AFTER, BEFORE, SHA)
        msg = str(ctx.exception)
        self.assertIn("стёр бы 1 раздел", msg)
        self.assertIn("! ## Три вопроса", msg)
        self.assertIn("+ ## Четыре вопроса", msg)
        self.assertIn("+94", msg)


class Boundaries(unittest.TestCase):
    """Границы: где сторож обязан молчать и где обязан кричать."""

    def test_only_rules_files_are_watched(self):
        shrunk = rule("A")
        for path in ("docs/OWNER_GATE.md", "spa_core/risk/policy.py", ".claude/rules/x.txt"):
            self.assertEqual(
                pusher.guard_rules_section_loss(path, rule("A", "B"), shrunk, SHA), "",
                f"{path} не файл правил, а сторож про него что-то сказал")
        with self.assertRaises(pusher.RulesSectionLossRefused):
            pusher.guard_rules_section_loss(".claude/rules/site-copy.md",
                                            rule("A", "B"), shrunk, SHA)

    def test_new_file_on_remote_has_nothing_to_lose(self):
        self.assertEqual(
            pusher.guard_rules_section_loss(RULE, None, rule("A"), None), "")

    def test_unread_remote_is_refusal_not_silence(self):
        """Файл на remote ЕСТЬ, содержимое не прочитано — это не «всё в порядке»."""
        with self.assertRaises(pusher.RulesSectionLossRefused):
            pusher.guard_rules_section_loss(RULE, None, rule("A"), SHA)

    def test_allow_overwrite_is_the_conscious_door(self):
        self.assertEqual(
            pusher.guard_rules_section_loss(RULE, rule("A", "B"), rule("A"), SHA,
                                            allow_overwrite=True), "")

    def test_pure_rename_is_named_not_refused(self):
        """Заголовок другой, тело побайтово то же — это переименование, а не потеря."""
        before = "# Rule\n\n## Три вопроса\n\nодно и то же тело.\n".encode()
        after = "# Rule\n\n## Четыре вопроса\n\nодно и то же тело.\n".encode()
        note = pusher.guard_rules_section_loss(RULE, before, after, SHA)
        self.assertIn("переименован", note)
        self.assertIn("Три вопроса", note)

    def test_body_edit_alone_is_not_a_loss(self):
        before = rule("A", "B")
        after = before.replace("тело раздела A.".encode(),
                               "тело раздела A, переписанное.".encode())
        self.assertEqual(pusher.guard_rules_section_loss(RULE, before, after, SHA), "")

    def test_third_level_sections_count(self):
        """`###` — тоже раздел: в аварии пропал именно такой."""
        before = "# R\n\n## A\n\nтело A\n\n### A.1\n\nтело A.1\n".encode()
        after = "# R\n\n## A\n\nтело A\n".encode()
        with self.assertRaises(pusher.RulesSectionLossRefused) as ctx:
            pusher.guard_rules_section_loss(RULE, before, after, SHA)
        self.assertIn("### A.1", str(ctx.exception))


class Wiring(unittest.TestCase):
    """Сторож, до которого не доходит вызов, не существует — проверяем ФОРМУ вызова."""

    def test_dispatcher_runs_both_guards(self):
        """`guard_content_loss` — одна дверь: и запись тетради, и раздел правила."""
        with self.assertRaises(pusher.RulesSectionLossRefused):
            pusher.guard_content_loss(RULE, BEFORE, AFTER, SHA)
        with self.assertRaises(pusher.EntryLossRefused):
            pusher.guard_content_loss("docs/journal/2026-W36.md",
                                      "## запись\n\ntext\n".encode(),
                                      b"# j\n", SHA)

    def test_guard_overwrite_calls_the_dispatcher_on_a_safe_base(self):
        """DIVERGENCE_SAFE: база == remote, и сокращение правила всё равно отказ."""
        real = pusher.divergence_verdict
        try:
            pusher.divergence_verdict = lambda *a, **k: {
                "state": pusher.DIVERGENCE_SAFE, "base": BEFORE, "reason": "test"}
            with self.assertRaises(pusher.RulesSectionLossRefused):
                pusher.guard_overwrite("pat", "repo", "main", RULE, "/dev/null",
                                       AFTER, SHA)
        finally:
            pusher.divergence_verdict = real

    def test_unmeasured_base_still_checks_a_rules_file(self):
        """Дыра, которую закрываем: базы нет ⇒ раньше правило уехало бы как есть."""
        real_verdict, real_get = pusher.divergence_verdict, pusher.get_file_content
        try:
            pusher.divergence_verdict = lambda *a, **k: {
                "state": pusher.DIVERGENCE_UNMEASURED, "base": None,
                "reason": "копия не основана на ветке доставки"}
            pusher.get_file_content = lambda *a, **k: BEFORE
            with self.assertRaises(pusher.RulesSectionLossRefused):
                pusher.guard_overwrite("pat", "repo", "main", RULE, "/dev/null",
                                       AFTER, SHA)
        finally:
            pusher.divergence_verdict, pusher.get_file_content = real_verdict, real_get

    def test_the_rebase_door_reaches_the_guard_too(self):
        """ТРЕТЬЯ дверь: `DIVERGENCE_DIVERGED` → пере-база. Найдено ПОДЪЁМОМ #467.

        Замер мутациями по координате: из семи подмен шесть краснели, а «вернуть в
        ветке пере-базы `guard_entry_loss` вместо диспетчера» проходила ЗЕЛЁНОЙ —
        то есть у третьей двери сторожа не было, хотя вызов в коде стоял. Ровно тот
        способ, которым сторож перестаёт существовать, оставаясь в тексте (это и
        сказано в docstring самого диспетчера — и не было проверено).

        Пере-база сохраняет remote ПО ПОСТРОЕНИЮ, поэтому проверка тут ловит не
        нашу правку, а РЕГРЕССИЮ `rebase_append`. Её и воспроизводим: подменяем
        `rebase_append` так, чтобы он вернул усечённый файл, — диспетчер обязан
        отказать. Обратный контроль (честная пере-база проходит) — рядом, иначе
        тест не отличает «сторож на месте» от «отказывает всегда».
        """
        real_verdict = pusher.divergence_verdict
        real_get = pusher.get_file_content
        real_rebase = pusher.rebase_append
        try:
            pusher.divergence_verdict = lambda *a, **k: {
                "state": pusher.DIVERGENCE_DIVERGED, "base": BEFORE,
                "reason": "разошлись"}
            pusher.get_file_content = lambda *a, **k: BEFORE

            # регрессия пере-базы: вернула копию, потерявшую разделы
            pusher.rebase_append = lambda *a, **k: AFTER
            with self.assertRaises(pusher.RulesSectionLossRefused):
                pusher.guard_overwrite("pat", "repo", "main", RULE, "/dev/null",
                                       AFTER, SHA)

            # обратный контроль: честная пере-база (remote + наша добавка) проходит
            addition = "\n## новый раздел\n\nтело.\n".encode()
            pusher.rebase_append = lambda *a, **k: BEFORE + addition
            body, note = pusher.guard_overwrite("pat", "repo", "main", RULE,
                                                "/dev/null", AFTER, SHA)
            self.assertIn(addition, body)
            self.assertIn("пере-база", note)
        finally:
            pusher.divergence_verdict = real_verdict
            pusher.get_file_content = real_get
            pusher.rebase_append = real_rebase

    def test_the_batch_door_reaches_the_same_guard(self):
        """`push_to_github_batch.py` — дверь, которой правила и доставляются на самом деле.

        Многофайловая доставка (N файлов = ОДИН коммит) идёт через batch, и `ba66e1bd3`
        приехал именно ею. Проверяем не «есть ли имя», а ФОРМУ связи: batch обязан звать
        ТОТ ЖЕ объект `guard_overwrite`, а не свою копию — иначе сторож существует в коде
        и отсутствует у двери. `build_entries` перечислен рядом: он собирает список
        отправляемого, и подмена одного из двух даёт молчание там, где ждали отказ.
        """
        spec = importlib.util.spec_from_file_location(
            "_batch_under_test", _ROOT / "push_to_github_batch.py")
        batch = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(batch)
        root = getattr(batch, "_root_push", None)
        self.assertIsNotNone(root, "batch больше не держит ссылку на корневой пушер")
        for name in ("guard_overwrite", "build_entries"):
            fn = getattr(batch, name)
            self.assertIs(fn, getattr(root, name),
                          f"batch.{name} — не объект корневого пушера, а своя копия")
            self.assertTrue(
                fn.__code__.co_filename.endswith("push_to_github.py"),
                f"batch.{name} собран не из push_to_github.py: "
                f"{fn.__code__.co_filename}")

    def test_is_rules_doc_matches_every_rule_in_the_tree(self):
        """Ни один живой файл правил не остаётся вне присмотра по имени."""
        rules_dir = _ROOT / ".claude" / "rules"
        # Скипа здесь НЕТ намеренно (`.claude/rules/deployment.md` § «не измерено»,
        # рецидивы #465/#466): каталог ГИТ-ТРЕКАЕМЫЙ — он есть на `origin/main` и в
        # любом worktree от него. Его отсутствие поэтому не «в этой копии предмета
        # нет», а находка; скип же сделал бы её неотличимой от зелёного прогона.
        self.assertTrue(rules_dir.is_dir(),
                        f"{rules_dir} нет, хотя каталог git-трекаемый: сторож правил "
                        f"остался БЕЗ ПРЕДМЕТА, и это находка, а не повод молчать")
        found = sorted(p.name for p in rules_dir.glob("*.md"))
        self.assertTrue(found, ".claude/rules есть, но пуст — это само по себе находка")
        for name in found:
            self.assertTrue(pusher.is_rules_doc(f".claude/rules/{name}"),
                            f"{name} не признан файлом правил")


if __name__ == "__main__":
    unittest.main()
