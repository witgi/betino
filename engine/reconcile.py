"""
Vyhodnotenie tipov: logovanie + dopocet vysledkov do data/history.jsonl.

Dva kroky (vola sa typicky denne z routine, po predict.py):
  1. log_new_picks(): zoberie aktualne predictions.json a prida este nezalogovane tipy
     do history.jsonl ako "pending" (s kurzom a casom, kedy sme tip videli).
  2. settle(): cez The Odds API /scores zisti dohrane zapasy a doplni vysledok (win/loss/push)
     + P/L. Sumar (ROI, uspesnost) potom zobrazi web cez predict.load_performance().

Pozn. k CLV: presne live CLV vyzaduje zachytit ZAVERECNU linku ~par minut pred vykopom
(samostatny mini-fetch). Historicky je CLV overeny v backteste; live CLV je pripravene
ako rozsirenie (capture_closing()). Bez neho ostava clv_beat = null.

Pouzitie:
  python engine/reconcile.py            # log + settle
  python engine/reconcile.py --log-only
  python engine/reconcile.py --settle-only

Iba stdlib.
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
HISTORY = os.path.join(ROOT, "data", "history.jsonl")
PREDICTIONS = os.path.join(ROOT, "data", "predictions.json")
API_BASE = "https://api.the-odds-api.com/v4"


def _config():
    try:
        return json.load(open(os.path.join(ROOT, "config.json"), encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def settle_footystats():
    """Vyhodnotí pending tipy cez FootyStats výsledok (keď value zdroj = footystats)."""
    import footystats as fs
    rows = _load_history()
    settled = 0
    for r in rows:
        if r.get("result") != "pending":
            continue
        mid = r.get("match_id")
        if not mid:
            continue
        try:
            det = (fs.match_detail(mid) or {}).get("data") or {}
        except Exception:   # noqa: BLE001 - jeden zápas nesmie zhodiť settling
            continue
        if det.get("status") != "complete":
            continue
        gh, ga = det.get("homeGoalCount"), det.get("awayGoalCount")
        if gh is None or ga is None:
            continue
        score_event = {"scores": [{"name": r["home"], "score": gh}, {"name": r["away"], "score": ga}]}
        res = _result_for_pick(r, score_event)
        if res:
            r["result"] = res
            r["settled_at"] = datetime.now(timezone.utc).isoformat()
            settled += 1
    _write_history(rows)
    print(f"[reconcile] (FootyStats) vyhodnotenych tipov: {settled}")
    return settled


def _pick_key(p):
    return f"{p['commence']}|{p['home']}|{p['away']}|{p['market']}|{p['selection']}"


def _load_history():
    rows = []
    if os.path.exists(HISTORY):
        with open(HISTORY, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def _write_history(rows):
    with open(HISTORY, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def log_new_picks():
    """Prida nove tipy z predictions.json do history.jsonl (dedup podla kluca)."""
    if not os.path.exists(PREDICTIONS):
        print("[reconcile] predictions.json neexistuje, nic na logovanie.")
        return 0
    with open(PREDICTIONS, "r", encoding="utf-8") as f:
        pred = json.load(f)
    rows = _load_history()
    seen = {_pick_key(r) for r in rows}
    added = 0
    for p in pred.get("picks", []):
        k = _pick_key(p)
        if k in seen:
            continue
        rows.append({
            **p,
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "result": "pending",
            "clv_beat": None,
        })
        seen.add(k)
        added += 1
    _write_history(rows)
    print(f"[reconcile] zalogovanych novych tipov: {added}")
    return added


def _fetch_scores(sport, api_key, days_from=3):
    params = {"apiKey": api_key, "daysFrom": days_from, "dateFormat": "iso"}
    url = f"{API_BASE}/sports/{sport}/scores/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "value-bets/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _result_for_pick(pick, score_event):
    """Z dohraneho zapasu urci win/loss/push pre dany tip."""
    scores = {s["name"]: int(s["score"]) for s in (score_event.get("scores") or [])
              if s.get("score") is not None}
    if pick["home"] not in scores or pick["away"] not in scores:
        return None
    hs, as_ = scores[pick["home"]], scores[pick["away"]]
    sel = pick["selection"]
    market = pick.get("market", "h2h")

    if market == "h2h":
        if sel == pick["home"]:
            return "win" if hs > as_ else "loss"
        if sel == pick["away"]:
            return "win" if as_ > hs else "loss"
        if sel == "Draw":
            return "win" if hs == as_ else "loss"
    elif market == "totals":
        total = hs + as_
        parts = sel.split()
        try:
            line = float(parts[-1])
        except (ValueError, IndexError):
            line = 2.5
        if sel.lower().startswith("over"):
            return "push" if total == line else ("win" if total > line else "loss")
        if sel.lower().startswith("under"):
            return "push" if total == line else ("win" if total < line else "loss")
    return None


def settle(api_key=None):
    """Doplni vysledky pending tipom cez /scores."""
    api_key = api_key or os.environ.get("ODDS_API_KEY")
    if not api_key:
        print("[reconcile] chyba ODDS_API_KEY -> settle preskoceny.")
        return 0
    rows = _load_history()
    pending = [r for r in rows if r.get("result") == "pending"]
    if not pending:
        print("[reconcile] ziadne pending tipy.")
        return 0

    sports = sorted({r.get("sport_key") for r in pending if r.get("sport_key")})
    score_index = {}
    for sport in sports:
        if not sport:
            continue
        try:
            for ev in _fetch_scores(sport, api_key):
                if ev.get("completed"):
                    key = f"{ev.get('home_team')}|{ev.get('away_team')}"
                    score_index[key] = ev
        except Exception as e:
            print(f"[reconcile] scores chyba pre {sport}: {e}")

    settled = 0
    for r in rows:
        if r.get("result") != "pending":
            continue
        ev = score_index.get(f"{r['home']}|{r['away']}")
        if not ev:
            continue
        res = _result_for_pick(r, ev)
        if res:
            r["result"] = res
            r["settled_at"] = datetime.now(timezone.utc).isoformat()
            settled += 1
    _write_history(rows)
    print(f"[reconcile] vyhodnotenych tipov: {settled}")
    return settled


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-only", action="store_true")
    ap.add_argument("--settle-only", action="store_true")
    args = ap.parse_args()
    if not args.settle_only:
        log_new_picks()
    if not args.log_only:
        try:
            if _config().get("value_source") == "footystats":
                settle_footystats()
            else:
                settle()
        except RuntimeError as e:
            print(e)
            sys.exit(1)
