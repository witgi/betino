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
from datetime import datetime, timezone, timedelta


def _week_of(commence):
    """Pondelok týždňa výkopu (ISO) — kľúč pre týždennú agregáciu. None ak sa nedá."""
    try:
        d = datetime.fromisoformat((commence or "").replace("Z", "+00:00")).date()
    except ValueError:
        return None
    return (d - timedelta(days=d.weekday())).isoformat()


def weekly_breakdown(settled_rows, start_bankroll):
    """Týždenná ziskovosť (compounding Kelly). Vráti chronologicky [{week, profit, roi, wins, losses, n, bank}]."""
    weeks = {}
    order = []
    bank = float(start_bankroll)
    for r in sorted(settled_rows, key=lambda x: x.get("commence", "") or x.get("logged_at", "")):
        wk = _week_of(r.get("commence"))
        if wk is None:
            continue
        if wk not in weeks:
            weeks[wk] = {"week": wk, "staked": 0.0, "profit": 0.0, "wins": 0, "losses": 0, "n": 0}
            order.append(wk)
        stake = bank * (r.get("stake_pct", 0) / 100.0)
        odds = r.get("best_odds", 1.0)
        if r["result"] == "win":
            pnl = stake * (odds - 1.0); weeks[wk]["wins"] += 1
        elif r["result"] == "loss":
            pnl = -stake; weeks[wk]["losses"] += 1
        else:
            pnl = 0.0
        bank += pnl
        w = weeks[wk]
        w["staked"] += stake; w["profit"] += pnl; w["n"] += 1
        w["bank"] = round(bank, 2)
    out = []
    for wk in order:
        w = weeks[wk]
        out.append({
            "week": wk, "n": w["n"], "wins": w["wins"], "losses": w["losses"],
            "profit": round(w["profit"], 2),
            "roi": round(w["profit"] / w["staked"] * 100.0, 1) if w["staked"] else 0.0,
            "bank": w.get("bank"),
        })
    return out

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
    all_settled = [r for r in rows if r.get("result") in ("win", "loss", "push")]
    # globalny bank rata LEN oficialne tipy (stare riadky bez priznaku = official)
    settled_rows = [r for r in all_settled if r.get("official", True)]
    pending = sum(1 for r in rows if r.get("result") == "pending")

    # kompaktny zoznam VSETKYCH vyhodnotenych tipov -> web ho pouzije na "bank podla rizika"
    tips = [{
        "ev": r.get("ev_pct"), "odds": r.get("best_odds"), "books": r.get("n_books"),
        "stake": r.get("stake_pct"), "res": r.get("result"),
        "t": (r.get("commence") or "")[:10], "off": bool(r.get("official", True)),
    } for r in sorted(all_settled, key=_settle_order)
        if r.get("ev_pct") is not None and r.get("best_odds")]

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
        "tips": tips,   # pre "bank podľa miery rizika" vo webe
        "weekly": weekly_breakdown(settled_rows, start_bankroll),
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
