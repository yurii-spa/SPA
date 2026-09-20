#!/bin/bash
# scripts/agent_director_build.sh — launchd-обёртка для com.spa.director_build.
#
# ОДИН детерминированный шаг: канонические источники → улики Cartographer → web-safe
# проекция → оболочка → сравнение дайджеста → атомарная подстановка комплекта в локальную
# раздачу. Наружу шаг не ходит: выкладки в смысле Pages нет, туннель раздаёт ТОТ каталог,
# который этот шаг обновил.
#
# ЧЕГО НЕ ДЕЛАЕТ. Ни Claude, ни LLM, ни коммита сгенерированных данных, ни пуша. Ветки
# «запушить» в director_publish.py нет как кода, а сгенерированные данные не попадают в
# набор доставки — это держит сторож в тестах, а не память автора.
#
# ПОЧЕМУ АРГУМЕНТЫ ЯВНЫЕ. Первая редакция звала цель без них, и канонический гейт отказал
# кодом 2 (argparse): цель требует --rebuild-from/--work-root/--output. Отказ был верным —
# расписанный шаг без аргументов не работал бы каждый час молча.
#
# ПОЧЕМУ КАТАЛОГИ ВНЕ РЕПОЗИТОРИЯ. Репозиторий публичный; сгенерированные владельческие
# данные в него не попадают ни при какой ошибке, и сама цель отказывается писать внутрь
# дерева кода.
#
# КОД ВОЗВРАТА НЕСЁТ ВЕРДИКТ и не гасится: 0 — смысл изменился и комплект подставлен,
# 3 — менять было нечего, 2 — сравнить не с чем. Смешивать «сломалось» с «не изменилось»
# запрещено: тогда оба ответа теряются.
#
# Лог: /tmp/spa_director_build.log
RUN_SCRIPT="/Users/yuriikulieshov/Documents/SPA_Claude/scripts/cartographer/director_publish.py"
PRODUCTION="/Users/yuriikulieshov/Documents/SPA_Claude"
WORK_ROOT="/Users/yuriikulieshov/studio-os-serve/work"
SERVE_ROOT="/Users/yuriikulieshov/studio-os-serve/director"
STATE="/Users/yuriikulieshov/studio-os-serve/freshness_state.json"
STAMP="$(date -u +%Y%m%dT%H%M%S)"

exec /Users/yuriikulieshov/miniconda3/bin/python3 \
    "$RUN_SCRIPT" \
    --rebuild-from "$PRODUCTION" \
    --work-root "$WORK_ROOT" \
    --output "$WORK_ROOT/bundle-$STAMP" \
    --activate-root "$SERVE_ROOT" \
    --state "$STATE" \
    >> /tmp/spa_director_build.log 2>&1
