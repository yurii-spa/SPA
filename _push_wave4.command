#!/bin/bash
cd ~/Documents/SPA_Claude
bash scripts/run_cpa_wave4_pushes.sh 2>&1 | tee /tmp/wave4_push.log
echo "Done. Press Enter to close."
read
