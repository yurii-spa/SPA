#!/usr/bin/env bash
FILE=~/Documents/SPA_Claude/data/tmp8vy8_nbk.tmp
if [ -f "$FILE" ]; then
    rm -f "$FILE"
    echo "✅ Deleted: $FILE"
else
    echo "✅ Already gone: $FILE"
fi

# Создаём push скрипт для pendle_pt_adapter fix
echo "---"
echo "Creating push script for pendle_pt_adapter fix..."
