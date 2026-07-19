#!/usr/bin/env bash
# Denny beh (vola ho cloud routine / lokalny cron):
#   1. vyhodnoti vcerajsie tipy (vysledky + ROI)
#   2. zaloguje uz hotove tipy
#   3. vygeneruje nove tipy na zajtra
#   4. commitne a (volitelne) pushne -> web sa obnovi
#
# Vyzaduje: export ODDS_API_KEY=...   (live rezim)
set -euo pipefail
cd "$(dirname "$0")"

echo "=== value-bets daily $(date -u +%FT%TZ) ==="

# 1: nove predikcie na zajtra
python3 engine/predict.py

# 2: vyhodnotenie predoslych + logovanie cerstvych tipov
python3 engine/reconcile.py || echo "reconcile preskoceny"

# 4: prepocitaj globalne statistiky + virtualny bankroll
python3 engine/stats.py || echo "stats preskocene"

# 4c: per-noha sledovanie (predikcie + arby) -> stats_legs.json
python3 engine/reconcile_legs.py || echo "reconcile_legs preskocene"

# 4b: posli vysledky do Supabase (ak su nastavene kluce)
python3 engine/push_supabase.py || echo "supabase push preskoceny"

# 5: ulozit do gitu (predictions.json + history.jsonl + stats.json)
if [ -d .git ]; then
  git add data/predictions.json data/history.jsonl data/stats.json
  if ! git diff --cached --quiet; then
    git commit -q -m "predikcie $(date -u +%F)" || true
    if git remote | grep -q origin; then
      git push -q origin HEAD || echo "push zlyhal (skontroluj token/remote)"
    fi
  else
    echo "ziadne zmeny na commit"
  fi
fi
echo "=== hotovo ==="
