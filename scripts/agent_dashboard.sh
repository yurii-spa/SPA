#!/bin/bash
# scripts/agent_dashboard.sh - launchd wrapper for com.spa.dashboard
# Generated from scripts/agent_template.sh (canonical bash-wrapper pattern).
# launchd CANNOT exec miniconda-python directly (exit 78 EX_CONFIG); this
# bash wrapper runs it correctly. Log: /tmp/spa_dashboard.log
# Plist must call: ProgramArguments = [/bin/bash, <abs path to this file>]
# ЦЕЛЬ: отдаёт файлы проекта по HTTP на 127.0.0.1:8767 — локальная витрина для
# просмотра артефактов с этого же компьютера; единственный измеренный потребитель —
# сторож самолечения (self_heal.py), для которого ответ 200 = признак жизни агента.
#
# ПРИМЕЧАНИЕ (не цель): --bind 127.0.0.1 ОБЯЗАТЕЛЕН: http.server по умолчанию слушает ВСЕ интерфейсы.
# Замер 30.08: порт 8767 отдавал корень репозитория всей локальной сети —
# в листинге были `.git/` и `.github_pat` (режим 600 не спасает: сервер
# работает от того же пользователя и отдаёт файл по HTTP). Соседи по
# флоту слушают петлю: api 8765 и кабинет 8766 — оба 127.0.0.1.
# Единственный потребитель — self_heal.py, он стучится ровно в петлю.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh dashboard http.server 8767 --bind 127.0.0.1 --directory /Users/yuriikulieshov/Documents/SPA_Claude
