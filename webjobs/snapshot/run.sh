#!/usr/bin/env bash
set -euo pipefail

echo "[snapshot] Starting snapshot job..."

# 1) Go to the site root
cd /home/site/wwwroot
echo "[snapshot] CWD: $(pwd)"
echo "[snapshot] Listing:"
ls

# 2) Extract the built app if output.tar.gz is present
if [ -f output.tar.gz ]; then
  echo "[snapshot] Found output.tar.gz, extracting into _job_app..."
  rm -rf _job_app
  mkdir -p _job_app
  tar -xzf output.tar.gz -C _job_app
  cd _job_app
  echo "[snapshot] Now in extracted app dir: $(pwd)"
else
  echo "[snapshot] WARNING: output.tar.gz not found; assuming code already present here."
fi

# 3) Make sure current dir is on PYTHONPATH so `import app` works
export PYTHONPATH="$PWD:${PYTHONPATH:-}"
echo "[snapshot] PYTHONPATH: $PYTHONPATH"

# 4) Run the mining job
echo "[snapshot] Python version: $(python --version 2>&1)"
echo "[snapshot] Running: python -m app.jobs.mine_location"
python -m app.jobs.mine_location

echo "[snapshot] Job finished successfully."
