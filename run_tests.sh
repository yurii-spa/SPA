#!/usr/bin/env bash
set -e
cd ~/Documents/SPA_Claude
python3 -m pytest tests/ -v --tb=short "$@"
