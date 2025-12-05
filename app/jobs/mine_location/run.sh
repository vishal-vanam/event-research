#!/usr/bin/env bash
set -e

cd /home/site/wwwroot
# Activate venv if App Service created one named antenv
if [ -d "antenv" ]; then
  source antenv/bin/activate
fi

python -m app.jobs.mine_location
