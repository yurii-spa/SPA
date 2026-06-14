#!/bin/bash
# SPA_Claude Cleanup Script — run from Mac Terminal
# Created 2026-06-13 by Claude
# Removes obsolete files that accumulated during early development

SPA="$HOME/Documents/SPA_Claude"
echo "🧹 SPA Cleanup starting..."
echo ""

# 1. Delete 26 old .command files in root
echo "Removing old .command files..."
rm -f "$SPA"/*.command
echo "  ✅ .command files removed"

# 2. Delete KANBAN backup files
echo "Removing KANBAN backup files..."
rm -f "$SPA"/KANBAN.json.bak*
rm -f "$SPA"/KANBAN_backup*.json
echo "  ✅ KANBAN backups removed"

# 3. Delete httpserver.log (6.9MB from May)
echo "Removing httpserver.log..."
rm -f "$SPA"/httpserver.log
echo "  ✅ httpserver.log removed"

# 4. Delete empty strategies/ directory
echo "Removing empty strategies/..."
rmdir "$SPA"/strategies/ 2>/dev/null && echo "  ✅ strategies/ removed" || echo "  ℹ️  strategies/ not empty or already gone"

# 5. Delete old tmp/result files in root
echo "Removing tmp/result files..."
rm -f "$SPA"/_tmp_kanban_inspect.txt
rm -f "$SPA"/_v327_final_*.txt "$SPA"/_v327_results.txt "$SPA"/_v327_runner.sh "$SPA"/_v327_runner_stdout.txt
rm -f "$SPA"/_v360_result.txt "$SPA"/_v363_a.txt "$SPA"/_v363_b.txt "$SPA"/_v363_probe.txt
echo "  ✅ Tmp files removed"

# 6. Delete old root-level tests/ (superseded by spa_core/tests/)
echo "Checking root tests/ directory..."
ROOT_TEST_COUNT=$(ls "$SPA"/tests/*.py 2>/dev/null | wc -l)
SPA_CORE_TEST_COUNT=$(ls "$SPA"/spa_core/tests/*.py 2>/dev/null | wc -l)
echo "  Root tests: $ROOT_TEST_COUNT files | spa_core/tests: $SPA_CORE_TEST_COUNT files"
if [ "$ROOT_TEST_COUNT" -lt "$SPA_CORE_TEST_COUNT" ]; then
    rm -rf "$SPA"/tests/
    echo "  ✅ Root tests/ removed (spa_core/tests/ has $SPA_CORE_TEST_COUNT files)"
else
    echo "  ⚠️  Skipping root tests/ — needs manual review"
fi

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "Files remaining in root (should be clean):"
ls "$SPA"/*.command 2>/dev/null && echo "WARNING: .command files still present" || echo "  No .command files ✅"
ls "$SPA"/httpserver.log 2>/dev/null && echo "WARNING: log still present" || echo "  No httpserver.log ✅"
