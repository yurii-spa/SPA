#!/bin/bash
cd ~/Documents/SPA_Claude
bash scripts/run_cpa_wave6_pushes.sh 2>&1 | tee /tmp/wave6_push.log
echo "Done. Press Enter to close."
read
