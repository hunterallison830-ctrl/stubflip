#!/bin/bash
# Runs on the box: the MLB The Show API returns 403 to GitHub Actions runners, so scan here and push data.json every 5 min.
cd /workspace/stubflip-pages
while true; do
  if OUT=web python3 scan.py >> publish.log 2>&1; then
    git add web/data.json && git -c user.name=stubflip-bot -c user.email=hunterallison830-ctrl@users.noreply.github.com commit -qm "data $(date '+%F %T %Z')" && git push -q origin main >> publish.log 2>&1
  fi
  sleep 300
done
