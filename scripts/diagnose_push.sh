#!/bin/bash
# diagnose_push.sh — Диагностика проблем с пушем
echo "=== SPA Push Diagnostics ==="
echo ""

# 1. Check PAT
echo "1. Checking PAT..."
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
if [ -z "$PAT" ]; then
    echo "   ❌ PAT NOT FOUND in Keychain (service: GITHUB_PAT_SPA)"
else
    echo "   ✅ PAT found in Keychain: ${PAT:0:10}..."
    
    # Test PAT validity
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $PAT" \
        -H "Accept: application/vnd.github+json" \
        "https://api.github.com/repos/yurii-spa/SPA")
    
    if [ "$STATUS" = "200" ]; then
        echo "   ✅ PAT is VALID (HTTP 200)"
    elif [ "$STATUS" = "401" ]; then
        echo "   ❌ PAT is INVALID/EXPIRED (HTTP 401)"
        echo "   → Нужно обновить PAT: Settings → Developer settings → Personal access tokens"
        echo "   → После получения нового токена запусти:"
        echo "      security add-generic-password -U -s GITHUB_PAT_SPA -a GITHUB_PAT_SPA -w ghp_NEW_TOKEN"
    else
        echo "   ⚠️  Unexpected HTTP $STATUS"
    fi
fi

echo ""

# 2. Check pending scripts
echo "2. Checking pending push scripts..."
LOG="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )/.push_log"
PENDING=0
for f in $(ls "$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"/push_v*.sh 2>/dev/null | sort -V); do
    name=$(basename "$f")
    if ! grep -qxF "$name" "$LOG" 2>/dev/null; then
        echo "   📦 PENDING: $name"
        PENDING=$((PENDING+1))
    fi
done
echo "   → Total pending: $PENDING scripts"

echo ""
echo "=== Done ==="
