#!/bin/bash
# scripts/agent_director_build.sh — launchd-обёртка для com.spa.director_build.
#
# ЧТО ЭТО. Один детерминированный шаг: принятые снимки → web-safe проекция → оболочка →
# атомарная подстановка комплекта в локальную раздачу. Наружу шаг не ходит: выкладки в
# смысле Pages здесь нет вовсе — туннель раздаёт ТОТ каталог, который этот шаг обновил.
#
# ЧЕГО ЭТО НЕ ДЕЛАЕТ. Ни Claude, ни LLM, ни коммита сгенерированных данных, ни пуша.
# Права на это у шага отсутствуют по построению: `director_publish.py` не содержит ветки
# «запушить», а сгенерированные данные не попадают в набор доставки (сторож в тестах).
#
# ПОЧЕМУ ОБЁРТКА, А НЕ ПРЯМОЙ python. launchd не может exec'нуть miniconda-python
# напрямую (exit 78 EX_CONFIG). Канонический путь — `agent_template.sh`, который заодно
# сам подтягивает свежий код из origin (метка свежести 10 минут).
#
# КОД ВОЗВРАТА НЕСЁТ ВЕРДИКТ и не гасится: 0 — смысл изменился и комплект подставлен,
# 3 — менять было нечего, 2 — сравнить не с чем. Смешивать «сломалось» с «не изменилось»
# запрещено: тогда оба ответа теряются.
#
# Лог: /tmp/spa_director_build.log
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    director_build \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/cartographer/director_publish.py
