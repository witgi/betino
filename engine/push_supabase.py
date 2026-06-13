"""
Posle vysledky vsetkych tipov (history.jsonl) do Supabase tabulky `tip_results`.
Web podla nej pocita osobne aj globalne statistiky (join s user_bets).

Bezi v dennom cron (GitHub Actions). Pouziva SERVICE kluc (obchadza RLS) -> len server.
Env:
  SUPABASE_URL          napr. https://xxxx.supabase.co
  SUPABASE_SERVICE_KEY  tajny service_role / sb_secret_... kluc (len v GitHub secrets!)

Iba stdlib (urllib).
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
import urllib.error

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
HISTORY = os.path.join(ROOT, "data", "history.jsonl")


def _rows():
    out = []
    if not os.path.exists(HISTORY):
        return out
    with open(HISTORY, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            tip_key = f"{r.get('commence')}|{r.get('home')}|{r.get('away')}|{r.get('market')}|{r.get('selection')}"
            out.append({
                "tip_key": tip_key,
                "league": r.get("league"),
                "home": r.get("home"),
                "away": r.get("away"),
                "commence": r.get("commence"),
                "market": r.get("market"),
                "selection": r.get("selection"),
                "best_odds": r.get("best_odds"),
                "result": r.get("result", "pending"),
                "settled_at": r.get("settled_at"),
            })
    return out


def push():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("[supabase] chyba SUPABASE_URL / SUPABASE_SERVICE_KEY -> preskocene.")
        return 0
    rows = _rows()
    if not rows:
        print("[supabase] ziadne tipy na poslanie.")
        return 0

    endpoint = f"{url}/rest/v1/tip_results?on_conflict=tip_key"
    body = json.dumps(rows).encode("utf-8")
    req = urllib.request.Request(endpoint, data=body, method="POST", headers={
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"[supabase] upsert OK: {len(rows)} tipov (HTTP {r.status})")
            return len(rows)
    except urllib.error.HTTPError as e:
        print(f"[supabase] HTTP chyba {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}")
        return 0
    except urllib.error.URLError as e:
        print(f"[supabase] sietova chyba: {e.reason}")
        return 0


if __name__ == "__main__":
    sys.exit(0 if push() >= 0 else 1)
