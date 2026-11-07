#!/usr/bin/env python3
"""Защитные отсечки, охраняющие СЕКРЕТЫ, обязаны краснеть от своей пустоты.

# LLM_FORBIDDEN

**Чем это НЕ является.** Это не проверка состава перечней — состав назначает автор
модуля. Это ПРОТИВОЯДИЕ класса ADR-939…945: вопрос о непустоте, у которого есть
НАСТОЯЩИЙ читатель, — то есть проба, которая краснеет, когда перечень опустел.

**Почему именно эти три.** Ось направления вреда (ADR-945) разложила 391 кандидата
класса на роды, и в роде `more` («сквозь отсечку проходит БОЛЬШЕ») оказались не
только отсечки шума, но и три защитных: два редактора ПУБЛИЧНОГО ответа и чистильщик
учёток в памяти компании. Мутация «опустошить» на НАСТОЯЩЕМ наборе ввозящих тестов
(ADR-945) дала:

====================================================  ==========================
перечень                                              исход мутации до этой пробы
====================================================  ==========================
``rates_desk._REFUSAL_REDACT_KEY_SUBSTRINGS``         **ВЫЖИЛ** — 39 passed,
                                                      3 skipped: пустоту не заметил
                                                      ни один из ДВУХ тестов,
                                                      которые модуль ввозят
``underwriting._REDACT_KEY_SUBSTRINGS``               **НЕ ИЗМЕРЕНО** — модуль не
                                                      ввозит ни один тест дерева
``memory.sources.SECRET_RES``                         **НЕ ИЗМЕРЕНО** — то же
====================================================  ==========================

Собственный docstring `rates_desk._redact_public` называет себя «defense-in-depth …
even if an upstream field were renamed to carry a secret/token/key/pat/raw-wallet-address
it can never reach the public payload». Пустым перечнем эта гарантия отменяется
МОЛЧА — и именно молчание, а не состав, здесь предмет (инв. #7).

**У каждой пробы сосед с ПРОТИВОПОЛОЖНЫМ ответом:** безобидный ключ обязан ВЫЖИТЬ, а
безобидная строка — остаться. Иначе проба зеленела бы и у редактора, который выбрасывает
ВСЁ, то есть доказывала бы не то, о чём говорит.

**Ни один байт охраняемого кода этой пробой не правится.** Состав перечней, публичные
числа и формулировки — предмет №2 границы ADR-285.
"""

from __future__ import annotations

import unittest

from spa_core.api.routers import rates_desk, underwriting
from spa_core.studio_os.memory import sources

#: Редакторы публичного ответа: (имя для отчёта, перечень-отсечка, функция-редактор).
REDACTORS = (
    ("rates_desk", rates_desk._REFUSAL_REDACT_KEY_SUBSTRINGS, rates_desk._redact_public),
    ("underwriting", underwriting._REDACT_KEY_SUBSTRINGS, underwriting._redact_public),
)

#: Ключ, который обязан пережить редактирование. Если его не станет, проба ниже
#: доказывала бы «редактор выбрасывает всё», а не «редактор выбрасывает опасное».
BENIGN_KEY = "nav_usd"


class PublicRedactionDenylist(unittest.TestCase):
    """Редактор публичного ответа. Пустой перечень обязан КРАСНИТЬ, а не молчать."""

    def test_the_denylist_is_not_empty(self):
        """ГРОМКИЙ вопрос о непустоте. `not any(…)` над пустым перечнем ИСТИНЕН для
        КАЖДОГО ключа — редактирования не происходит вовсе, и это самый тихий из
        возможных отказов защиты.

        **Каждое имя спрошено ДОСЛОВНО, а не через переменную цикла.** Перепись
        класса (ADR-940…943) привязывает чтение к ОБЪЯВЛЕНИЮ по ИМЕНИ, и вопрос,
        заданный переменной `denylist`, объявлению не зачитывается вовсе.

        **И даже дословный вопрос перепись зачтёт оси `other`, а не `empty`** —
        замерено 07.11: `assertTrue(NAME)` для неё передача аргументом, а не
        `assert NAME`. Из предмета перечень при этом ВЫХОДИТ (по ADR-943 `empty` и
        `other` суть две половины ОДНОГО вопроса), но утверждать «прибор видит
        вопрос о непустоте» было бы неверно. Что противоядие РАБОТАЕТ, доказывает не
        перепись, а мутация: 5 из 5 убито, включая обратную (ADR-945).
        """
        self.assertTrue(rates_desk._REFUSAL_REDACT_KEY_SUBSTRINGS,
                        "rates_desk: перечень-отсечка ПУСТ — редактирование "
                        "публичного отказного ответа отключено")
        self.assertTrue(underwriting._REDACT_KEY_SUBSTRINGS,
                        "underwriting: перечень-отсечка ПУСТ — редактирование "
                        "публичного ответа отключено")
        self.assertEqual(len(REDACTORS), 2,
                         "спрошены обязаны быть ВСЕ редакторы перечня REDACTORS: "
                         "появился третий — ему нужен свой дословный вопрос")

    def test_every_declared_substring_actually_drops_a_key(self):
        """Положительный контроль на КАЖДЫЙ объявленный член: ключ, несущий подстроку,
        обязан ИСЧЕЗНУТЬ. Проба краснеет и от опустошения перечня, и от удаления
        любого ОДНОГО его члена — то есть мерит состав по ИСХОДУ, а не по длине."""
        for label, denylist, redact in REDACTORS:
            for mark in denylist:
                key = f"upstream_{mark}_field"
                with self.subTest(redactor=label, mark=mark):
                    out = redact({key: "ghp" + "_" + "0" * 36,
                                  BENIGN_KEY: 101973.32})
                    self.assertNotIn(key, out, f"{label}: ключ с «{mark}» уцелел в "
                                               f"публичном ответе")

    def test_a_benign_key_survives(self):
        """СОСЕД предыдущей с ПРОТИВОПОЛОЖНЫМ ответом: редактор, выбрасывающий всё,
        прошёл бы проверку выше и не был бы редактором."""
        for label, _denylist, redact in REDACTORS:
            with self.subTest(redactor=label):
                out = redact({BENIGN_KEY: 101973.32, "days": 137})
                self.assertEqual({BENIGN_KEY: 101973.32, "days": 137}, out,
                                 f"{label}: безобидные ключи не должны редактироваться")

    def test_nesting_is_walked_in_dicts_and_lists(self):
        """Отсечка обязана действовать и в глубине: публичный ответ — дерево, а не
        плоская запись."""
        for label, _denylist, redact in REDACTORS:
            with self.subTest(redactor=label):
                out = redact({"books": [{"api_token": "x", BENIGN_KEY: 1}],
                              "inner": {"wallet": "0xabc", "days": 137}})
                self.assertNotIn("api_token", out["books"][0])
                self.assertEqual(1, out["books"][0][BENIGN_KEY])
                self.assertNotIn("wallet", out["inner"])
                self.assertEqual(137, out["inner"]["days"])


class MemorySecretSanitizer(unittest.TestCase):
    """Чистильщик учёток в памяти компании. `dropped == 0` обязано означать «чистить
    было нечего», а не «чистить было нечем»."""

    def test_the_pattern_list_is_not_empty(self):
        self.assertTrue(sources.SECRET_RES,
                        "перечень признаков учётки ПУСТ — sanitize() ничего не вычищает, "
                        "и `dropped=0` становится неотличим от чистого входа")

    def test_every_declared_pattern_drops_its_line(self):
        """Положительный контроль на КАЖДЫЙ объявленный признак: строка, которую он
        описывает, обязана быть выброшена, а счётчик — вырасти. Образцы заведомо
        поддельные (это ЗНАЧЕНИЯ пробы, а не секреты, инв. #7)."""
        samples = (
            # Образцы СОБРАНЫ ИЗ ЧАСТЕЙ намеренно: литеральная строка, похожая на
            # секрет, в файле репозитория лежать не должна ни одной — инв. #7, и
            # сканер секретов GitHub такой коммит ОТКЛОНЯЕТ (замер 07.11: правило
            # `SLACK` отвергло набор с кодом 422). Поддельность значения этим не
            # меняется; меняется только то, что собирается оно в рантайме.
            "ghp" + "_" + "0" * 36,
            "github" + "_pat_" + "0" * 40,
            "gho" + "_" + "0" * 24,
            "sk" + "-ant-api03-" + "A" * 40,
            "xox" + "b-" + "0" * 10 + "-" + "0" * 10 + "-" + "a" * 24,
            "12345678" + ":" + "A" * 35,
            "AKIA" + "0" * 16,
            "-----BEGIN " + "RSA PRIVATE KEY" + "-----",
            "seed phrase" + ": zero zero zero",
            "api" + "_key=" + "z" * 12,
        )
        self.assertEqual(len(sources.SECRET_RES), len(samples),
                         "образцов обязано быть столько, сколько объявленных признаков: "
                         "иначе новый признак пришёл бы без положительного контроля")
        for sample in samples:
            with self.subTest(sample=sample[:24]):
                clean, dropped = sources.sanitize(f"nav = 101973.32\n{sample}\nday = 137\n")
                self.assertEqual(1, dropped, "строка с признаком учётки не выброшена")
                self.assertNotIn(sample, clean)

    def test_a_benign_text_is_kept_whole(self):
        """СОСЕД с ПРОТИВОПОЛОЖНЫМ ответом: чистильщик, выбрасывающий всё, прошёл бы
        проверку выше."""
        text = "nav = 101973.32\nday = 137\napproved = True\n"
        clean, dropped = sources.sanitize(text)
        self.assertEqual(0, dropped)
        self.assertEqual(text.strip("\n"), clean)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
