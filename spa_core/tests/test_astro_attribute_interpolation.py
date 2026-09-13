#!/usr/bin/env python3
"""`{имя}` в КАВЫЧКАХ атрибута Astro не вычисляется — и уезжает в заголовок страницы.

Замер 13.09. Страница `/annual-contrast` публиковала в `<title>` и в мета-описании
буквальный текст `{realizedNumEn}` вместо числа — то есть ровно в тех двух местах,
которые читают поисковик и превью ссылки. Ещё три страницы делали то же самое, всего
шесть атрибутов.

**Почему это не ловилось.** В Astro подстановка работает в ТЕКСТЕ элемента и в
атрибуте-выражении (`data-ru={\\`…${x}…\\`}`), но НЕ внутри обычной строки в кавычках
(`title="…{x}…"`). На одной и той же странице обе формы стоят рядом: `data-ru` рендерил
`5,0%`, а `title` печатал `{realizedNumEn}`. Глазами это неразличимо, а сборка не
жалуется — для неё это просто текст.

**Мера статическая и точная.** Ложное срабатывание здесь дороже пропуска: `{`
встречается в CSS внутри `style="…"`, в JSON-LD и в скриптах. Поэтому подозрением
считается только имя, которое страница САМА объявила в своём frontmatter
(`const имя = …`): текст `{foo}` без такого объявления — не подстановка, а просто текст.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES = ROOT / "landing" / "src" / "pages"
COMPONENTS = ROOT / "landing" / "src" / "components"

#: Объявление во frontmatter страницы.
_DECL = re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=", re.M)

#: Атрибут вида `name="… {имя} …"` — строка в кавычках, подстановка НЕ работает.
_ATTR = re.compile(r'\s[a-zA-Z_:][\w:.-]*="([^"]*\{[A-Za-z_$][\w$]*\}[^"]*)"')

#: Имя в фигурных скобках.
_PLACEHOLDER = re.compile(r"\{([A-Za-z_$][\w$]*)\}")


def offenders() -> list[tuple[str, list[str]]]:
    """Страницы, у которых объявленное имя стои́т в КАВЫЧКАХ атрибута."""
    out: list[tuple[str, list[str]]] = []
    for base in (PAGES, COMPONENTS):
        if not base.is_dir():
            continue
        for f in sorted(base.rglob("*.astro")):
            src = f.read_text(encoding="utf-8")
            names = set(_DECL.findall(src))
            if not names:
                continue
            bad: set[str] = set()
            for value in _ATTR.findall(src):
                bad |= {n for n in _PLACEHOLDER.findall(value) if n in names}
            if bad:
                out.append((str(f.relative_to(ROOT)), sorted(bad)))
    return out


class NoAstroAttributeSwallowsAnExpression(unittest.TestCase):
    def test_no_page_prints_its_own_variable_literally(self):
        found = offenders()
        self.assertEqual(found, [], (
            "подстановка в кавычках атрибута НЕ вычисляется — страница напечатает "
            f"`{{имя}}` буквально (замер 13.09: так в <title> уехало `{{realizedNumEn}}`): "
            f"{found}. Чинить формой `attr={{`…${{имя}}…`}}`, а не удалением переменной."))

    def test_the_detector_sees_the_real_accident(self):
        """Положительный контроль формой настоящей аварии.

        Без него проверка была бы истинна и у детектора, который не видит НИЧЕГО.
        """
        src = ('---\nconst realizedNumEn = "5.0%";\n---\n'
               '<Layout title="steady {realizedNumEn} | earn-defi.com" />\n')
        names = set(_DECL.findall(src))
        bad = {n for v in _ATTR.findall(src) for n in _PLACEHOLDER.findall(v) if n in names}
        self.assertEqual(bad, {"realizedNumEn"})

    def test_the_working_form_is_not_flagged(self):
        """Обратная сторона: `attr={`…${имя}…`}` работает и обвиняться не должна."""
        src = ('---\nconst x = "5,0%";\n---\n'
               '<h1 data-ru={`стабильных ${x} деска`}>text</h1>\n')
        names = set(_DECL.findall(src))
        bad = {n for v in _ATTR.findall(src) for n in _PLACEHOLDER.findall(v) if n in names}
        self.assertEqual(bad, set(), "рабочая форма объявлена дефектом")

    def test_a_brace_that_is_not_a_declared_name_is_not_flagged(self):
        """Ложное срабатывание дороже пропуска: `{` есть в CSS, JSON-LD и скриптах."""
        src = ('---\nconst x = 1;\n---\n'
               '<div style="color:var(--t)" data-json="{foo: 1}">t</div>\n')
        names = set(_DECL.findall(src))
        bad = {n for v in _ATTR.findall(src) for n in _PLACEHOLDER.findall(v) if n in names}
        self.assertEqual(bad, set())


if __name__ == "__main__":
    unittest.main()
