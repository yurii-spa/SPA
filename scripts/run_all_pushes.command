#!/bin/bash
# run_all_pushes.command — запуск всех pending пушей (фиксы + v840-v869)
# Двойной клик в Finder или: bash ~/Documents/SPA_Claude/scripts/run_all_pushes.command

set -uo pipefail
cd ~/Documents/SPA_Claude

LOG="logs/run_all_pushes_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs
exec > >(tee -a "$LOG") 2>&1

echo "════════════════════════════════════════════════════"
echo " SPA — Run All Pending Pushes (v8.09 → v8.69)"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════════"

# PAT один раз
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || true)
PAT=${PAT:-${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}}
if [ -z "$PAT" ] && [ -f ~/.github_pat ]; then PAT=$(cat ~/.github_pat); fi
if [ -z "$PAT" ]; then
  echo "❌ PAT не найден — проверь Keychain (security add-generic-password -s GITHUB_PAT_SPA -a github -w YOUR_PAT)"
  read -rp "Нажми Enter для выхода..." && exit 1
fi
echo "✅ PAT найден"
echo ""

PASSED=(); FAILED=(); SKIPPED=()

run_push() {
  local script="$1"
  local name; name=$(basename "$script")
  if [ ! -f "$script" ]; then
    echo "⏭  SKIP  $name"
    SKIPPED+=("$name"); return
  fi
  echo "──────────────────────────────────────────────────"
  echo "▶  $name"
  if bash "$script" 2>&1; then
    echo "✅ OK    $name"
    PASSED+=("$name")
  else
    echo "❌ FAIL  $name"
    FAILED+=("$name")
  fi
  sleep 1
}

# ── Фикс-скрипты ──────────────────────────────────────────────────────────
echo "═══ Фиксы ═══"
run_push scripts/push_tg_dedup_fix.sh
run_push scripts/push_agent_fixes.sh
run_push scripts/push_tg_bot_fix.sh
run_push scripts/push_tg_menu.sh
run_push scripts/push_tools_integration.sh

# ── Версионные спринты v809–v869 (все существующие) ──────────────────────
echo ""
echo "═══ Спринты v8.09 → v8.71 ═══"
for N in 809 810 811 812 813 814 815 816 817 818 819 820 821 822 823 824 826 827 828 829 830 831 832 833 834 835 836 837 838 839 840 841 842 843 844 845 846 847 848 849 850 851 852 853 854 855 856 857 858 859 860 861 862 863 864 865 866 867 868 869 870 871 872 873 874 875 876; do
  run_push "scripts/push_v${N}.sh"
done

# ── Итог ──────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════"
echo " Готово — $(date '+%H:%M:%S')"
printf " ✅ OK:   %d\n" "${#PASSED[@]}"
printf " ❌ FAIL: %d\n" "${#FAILED[@]}"
printf " ⏭  SKIP: %d\n" "${#SKIPPED[@]}"
if [ "${#FAILED[@]}" -gt 0 ]; then
  echo " Упали: ${FAILED[*]}"
fi
echo " Лог: $LOG"
echo "════════════════════════════════════════════════════"

read -rp "Нажми Enter для закрытия..."
