"""
Globalne sledovanie vykonnosti VSETKYCH tipov (telo 5 a 6 zo zadania).

Cita data/history.jsonl (zalogovane tipy + vysledky z reconcile.py) a pocita:
  - kolko tipov, vyhodnotenych, cakajucich
  - uspesnost, zisk v jednotkach, ROI (yield)
  - VIRTUALNY BANKROLL: ako by vyzeral bank, keby si dal KAZDY oficialny tip
    odporucanym vkladom (compounding Kelly = stake z aktualneho banku)
  - rovnica banku v case (equity) pre graf
  - CLV beat %

Vysledok -> data/stats.json (cita ho web pre globalny panel).
Osobne sledovanie (co si REALNE podal) bezi cez Supabase a doplni sa, ked bude login.

Iba stdlib.
"""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
HISTORY = os.path.join(ROOT, "data", "history.jsonl")
STATS = os.path.join(ROOT, "data", "stats.json")


def _load_history():
    rows = []
    if os.path.exists(HISTORY):
        with open(HISTORY, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def _settle_order(r):
    """Triedenie podla casu vykopu (chronologicky pre equity krivku)."""
    return r.get("commence", "") or r.get("logged_at", "")


def compute_stats(start_bankroll):
    rows = _load_history()
    logged = len(rows)
    settled_rows = [r for r in rows if r.get("result") in ("win", "loss", "push")]
    pending = sum(1 for r in rows if r.get("result") == "pending")

    wins = sum(1 for r in settled_rows if r["result"] == "win")
    losses = sum(1 for r in settled_rows if r["result"] == "loss")
    pushes = sum(1 for r in settled_rows if r["result"] == "push")

    # virtualny bankroll s compounding Kelly (stake = % aktualneho banku)
    bankroll = float(start_bankroll)
    equity = [{"date": None, "bankroll": round(bankroll, 2)}]
    staked_total = 0.0
    profit_total = 0.0
    for r in sorted(settled_rows, key=_settle_order):
        stake_pct = r.get("stake_pct", 0) / 100.0
        stake = bankroll * stake_pct
        odds = r.get("best_odds", 1.0)
        if r["result"] == "win":
            pnl = stake * (odds - 1.0)
        elif r["result"] == "loss":
            pnl = -stake
        else:  # push
            pnl = 0.0
        bankroll += pnl
        staked_total += stake
        profit_total += pnl
        equity.append({"date": (r.get("commence") or "")[:10], "bankroll": round(bankroll, 2)})

    clv = [r["clv_beat"] for r in rows if r.get("clv_beat") is not None]
    clv_beat_pct = round(sum(1 for x in clv if x) / len(clv) * 100.0, 1) if clv else None

    roi = round(profit_total / staked_total * 100.0, 2) if staked_total > 0 else None
    win_rate = round(wins / len(settled_rows) * 100.0, 1) if settled_rows else None

    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "start_bankroll": start_bankroll,
        "logged": logged,
        "settled": len(settled_rows),
        "pending": pending,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "win_rate_pct": win_rate,
        "staked_units": round(staked_total, 2),
        "profit_units": round(profit_total, 2),
        "roi_pct": roi,
        "virtual_bankroll": round(bankroll, 2),
        "clv_beat_pct": clv_beat_pct,
        "equity": equity,
    }


def build_stats(start_bankroll):
    s = compute_stats(start_bankroll)
    with open(STATS, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    print(f"[stats] vyhodnotenych: {s['settled']} | zisk: {s['profit_units']} j "
          f"| ROI: {s['roi_pct']} | virt. bank: {s['virtual_bankroll']} -> {STATS}")
    return s


if __name__ == "__main__":
    cfg = json.load(open(os.path.join(ROOT, "config.json")))
    build_stats(cfg["bankroll"])
