#!/bin/bash
# Run the mining job inside the deployed app

# Go to the app root
cd /home/site/wwwroot || exit 1

# Try to activate the virtualenv if it exists (Oryx usually creates 'antenv')
if [ -d "antenv" ]; then
  . antenv/bin/activate
fi

# Run your mining script (the same you use locally)
python -m app.jobs.mine_location
