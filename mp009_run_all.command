#!/bin/bash
# MP-009: Один клик — всё делает сам
# 1. Чинит launchd сервисы (httpserver + autopush)
# 2. Пушит все изменения в GitHub

cd /Users/yuriikulieshov/Documents/SPA_Claude

echo "╔══════════════════════════════════════════════════╗"
echo "║  MP-009: Fix launchd + Push to GitHub (1 click)  ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ────────────── STEP 1: Fix launchd ──────────────
bash /Users/yuriikulieshov/Documents/SPA_Claude/mp009_fix_launchd.command

echo ""
echo "══════════════════════════════════════════════════"
echo "Пушу изменения в GitHub..."
echo ""

# ────────────── STEP 2: Push ──────────────
python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json \
    /Users/yuriikulieshov/Documents/SPA_Claude/com.spa.httpserver.plist \
    /Users/yuriikulieshov/Documents/SPA_Claude/com.spa.autopush.plist \
    /Users/yuriikulieshov/Documents/SPA_Claude/mp009_fix_launchd.command \
    /Users/yuriikulieshov/Documents/SPA_Claude/mp009_run_all.command \
  --message "fix(MP-009): launchd httpserver+autopush exit code fixes ✅"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅ MP-009 Done! Всё исправлено и запушено.      ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "Можно закрыть это окно."
