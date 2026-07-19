"""
Per-noha sledovanie výsledkov (PLAN_V2 Fáza 3) — predikcie + arbitráž.

Loguje denné signály a postupne ich vyhodnocuje, aby appka vedela ukázať reálnu
úspešnosť aj pri PREDIKCIÁCH a ARBITRÁŽI (nielen backtest / aktuálny stav).

  - Predikcie: pre každý tip modelu (1X2) sa po odohratí zápasu zistí výsledok
    (FootyStats), a ráta sa virtuálny bank „keby stavíš flat na každý tip modelu".
  - Arbitráž: garantovaný zisk sa netrackuje ako bank ( efemérne, nevieme čo user vzal);
    ukazujeme súhrn — koľko arbov appka našla, priemerný/najlepší zisk %, podľa kníh.

Výstup: data/stats_legs.json (číta ho web). Iba stdlib + engine/footystats.
Beží v pipeline po stats.py; je izolovaný (chyba nezhodí zvyšok cronu).
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import footystats as fs   # noqa: E402

SIGNALS = os.path.join(ROOT, "data", "signals.json")
HIST_PRED = os.path.join(ROOT, "data", "history_prediction.jsonl")
HIST_ARB = os.path.join(ROOT, "data", "history_arb.jsonl")
OUT = os.path.join(ROOT, "data", "stats_legs.json")

FLAT_STAKE = 10.0        # virtuálny vklad na 1 predikciu (€)
START_BANK = 1000.0


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load_jsonl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return rows


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _past(commence_iso):
    if not commence_iso:
        return False
    try:
        t = datetime.fromisoformat(commence_iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return datetime.now(timezone.utc) > t


def _load_signals():
    if not os.path.exists(SIGNALS):
        return []
    try:
        return json.load(open(SIGNALS, encoding="utf-8")).get("signals", [])
    except (json.JSONDecodeError, OSError):
        return []


# ---------- PREDIKCIE ----------
def log_predictions(signals):
    """Zaloguj nové tipy modelu (dedup podľa kľúča)."""
    rows = _load_jsonl(HIST_PRED)
    seen = {r["key"] for r in rows}
    added = 0
    for s in signals:
        if s.get("type") != "prediction":
            continue
        ev = s.get("event", {})
        leg = (s.get("legs") or [{}])[0]
        key = f"{ev.get('commence')}|{ev.get('home')}|{ev.get('away')}|{s.get('pick')}"
        if key in seen:
            continue
        rows.append({
            "key": key, "home": ev.get("home"), "away": ev.get("away"),
            "commence": ev.get("commence"), "sport": s.get("sport"),
            "pick_code": s.get("pick"), "pick_name": leg.get("selection"),
            "model_prob": (s.get("edge") or {}).get("value"),
            "market_odds": leg.get("odds"), "match_id": s.get("match_id"),
            "result": "pending", "logged_at": _now(), "settled_at": None,
        })
        seen.add(key); added += 1
    _write_jsonl(HIST_PRED, rows)
    return added


def settle_predictions():
    """Vyhodnoť odohraté tipy cez FootyStats výsledok."""
    rows = _load_jsonl(HIST_PRED)
    settled = 0
    for r in rows:
        if r.get("result") != "pending" or not _past(r.get("commence")):
            continue
        mid = r.get("match_id")
        if not mid:
            r["result"] = "void"; r["settled_at"] = _now(); continue
        try:
            resp = fs.match_detail(mid)
            m = resp.get("data") if isinstance(resp, dict) else None
            if not m or m.get("status") != "complete":
                continue
            gh, ga = m.get("homeGoalCount"), m.get("awayGoalCount")
            if gh is None or ga is None:
                continue
            actual = "home" if gh > ga else ("away" if ga > gh else "draw")
            r["result"] = "win" if r.get("pick_code") == actual else "loss"
            r["settled_at"] = _now()
            settled += 1
        except Exception:   # noqa: BLE001 - jeden zápas nesmie zhodiť settling
            continue
    _write_jsonl(HIST_PRED, rows)
    return settled


def prediction_stats():
    """Virtuálny bank keby stavíš flat na každý tip modelu (pri trhovom kurze)."""
    rows = _load_jsonl(HIST_PRED)
    bank = START_BANK
    equity = [{"bankroll": round(bank, 2)}]
    settled = wins = losses = pending = 0
    staked = profit = 0.0
    for r in sorted(rows, key=lambda x: x.get("commence") or ""):
        if r.get("result") in ("win", "loss"):
            odds = r.get("market_odds")
            if not odds or odds <= 1.0:
                continue
            settled += 1
            staked += FLAT_STAKE
            if r["result"] == "win":
                wins += 1; gain = FLAT_STAKE * (odds - 1.0); profit += gain; bank += gain
            else:
                losses += 1; profit -= FLAT_STAKE; bank -= FLAT_STAKE
            equity.append({"bankroll": round(bank, 2)})
        elif r.get("result") == "pending":
            pending += 1
    return {
        "settled": settled, "wins": wins, "losses": losses, "pending": pending,
        "win_rate_pct": round(wins / settled * 100, 1) if settled else 0.0,
        "profit_units": round(profit, 2),
        "roi_pct": round(profit / staked * 100, 2) if staked else 0.0,
        "virtual_bankroll": round(bank, 2), "start_bankroll": START_BANK,
        "flat_stake": FLAT_STAKE, "equity": equity,
    }


# ---------- ARBITRÁŽ ----------
def log_arbs(signals):
    rows = _load_jsonl(HIST_ARB)
    seen = {r["key"] for r in rows}
    added = 0
    for s in signals:
        if s.get("type") != "arb":
            continue
        ev = s.get("event", {})
        legs = s.get("legs") or s.get("stake_split") or []
        key = s.get("arb_id") or f"{ev.get('commence')}|{ev.get('home')}|{ev.get('away')}|{s.get('market')}"
        if key in seen:
            continue
        rows.append({
            "key": key, "home": ev.get("home"), "away": ev.get("away"),
            "commence": ev.get("commence"), "sport": s.get("sport"),
            "profit_pct": (s.get("edge") or {}).get("value"),
            "books": [l.get("book") for l in legs], "logged_at": _now(),
        })
        seen.add(key); added += 1
    _write_jsonl(HIST_ARB, rows)
    return added


def arb_stats(signals):
    """Súhrn (nie bank): koľko arbov appka našla, priemer/max %, podľa kníh + aktuálne."""
    hist = _load_jsonl(HIST_ARB)
    profits = [r.get("profit_pct") or 0 for r in hist]
    by_book = {}
    for r in hist:
        for b in (r.get("books") or []):
            if b:
                by_book[b] = by_book.get(b, 0) + 1
    current = [s for s in signals if s.get("type") == "arb"]
    return {
        "total_seen": len(hist),
        "current": len(current),
        "avg_profit_pct": round(sum(profits) / len(profits), 2) if profits else 0.0,
        "max_profit_pct": round(max(profits), 2) if profits else 0.0,
        "by_book": dict(sorted(by_book.items(), key=lambda x: -x[1])),
    }


def run():
    signals = _load_signals()
    added_p = log_predictions(signals)
    added_a = log_arbs(signals)
    settled_p = settle_predictions()
    out = {
        "generated_at": _now(),
        "prediction": prediction_stats(),
        "arb": arb_stats(signals),
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[reconcile_legs] predikcie: +{added_p} lognuté, {settled_p} vyhodnotené | "
          f"arby: +{added_a} lognuté | zapisane -> {OUT}")
    return out


if __name__ == "__main__":
    run()
