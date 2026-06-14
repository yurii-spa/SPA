#!/bin/bash
pkill -f "http.server 8765" 2>/dev/null
cd /Users/yuriikulieshov/Documents/SPA_Claude
python3 -m http.server 8765
