"""
BACKTEST value-betting metody na realnych historickych datach.

Zdroj: football-data.co.uk (zadarmo, CSV s kurzami vratane Pinnacle + vysledky).
Princip = presne ten isty ako live:
  1. Pinnacle (ostra kniha) -> devig (Shin) -> fer pravdepodobnost vysledku.
  2. Najlepsi kurz medzi SOFT knihami (B365, BW, WH, ...) na ten isty vyber.
  3. Ak EV > prah a kurz v zone -> "stavime" (frakcny Kelly / flat) a vyhodnotime vs realny vysledok.
  4. Vyratame ROI, yield, pocet stavok, max drawdown a CLV (porazili sme zaverecnu Pinnacle linku?).

POZOR: backtest pouziva Pinnacle ako "pravdu" a stavi do inych knih -> ukazuje, ci v historickych
datach existoval realny rozdiel. Vysledok byva SKROMNY (trh je efektivny). To je cielom — uprimne
zmerat ocakavanie, nie nahuckat.

Pouzitie:
  python backtest/backtest.py                       # default: PL 3 sezony
  python backtest/backtest.py E0 SP1 D1 --seasons 2122 2223 2324
  python backtest/backtest.py --flat                # flat staking namiesto Kelly

Iba stdlib (urllib, csv, math).
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "engine"))
import devig as devig_mod   # noqa: E402
import blend as blend_mod   # noqa: E402

BASE_URL = "https://www.football-data.co.uk/mmz4281"
CACHE_DIR = os.path.join(HERE, "csv")

# Soft knihy (kam by sme realne stavili) – pouzijeme tie stlpce, ktore su v CSV pritomne.
SOFT_PREFIXES = ["B365", "BW", "IW", "WH", "VC", "BF", "PS"]  # PS sa pri devigu vynima
# Max (najlepsi trhovy kurz) ak je k dispozicii:
MAX_PREFIXES = ["Max", "BbMx"]


def load_config():
    with open(os.path.join(ROOT, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def download_csv(season, div):
    """Stiahne (a nacachuje) jeden CSV. season napr. '2324', div napr. 'E0'."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{season}_{div}.csv")
    if os.path.exists(path) and os.path.getsize(path) > 0:
        with open(path, "r", encoding="latin-1") as f:
            return f.read()
    url = f"{BASE_URL}/{season}/{div}.csv"
    req = urllib.request.Request(url, headers={"User-Agent": "value-bets-backtest/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("latin-1")
    with open(path, "w", encoding="latin-1") as f:
        f.write(raw)
    return raw


def _f(row, key):
    """Bezpecne float z CSV bunky."""
    v = row.get(key, "")
    if v is None or v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def sharp_triplet(row, prefix):
    h = _f(row, prefix + "H")
    d = _f(row, prefix + "D")
    a = _f(row, prefix + "A")
    if h and d and a:
        return [h, d, a]
    return None


def best_soft_odds(row):
    """Pre kazdy vyber [H,D,A] vrati najlepsi kurz medzi soft knihami (+ Max ak je)."""
    best = [None, None, None]
    book = [None, None, None]
    for pref in SOFT_PREFIXES:
        if pref == "PS":   # Pinnacle je ostra kniha, nestavame do nej
            continue
        trip = sharp_triplet(row, pref)
        if not trip:
            continue
        for i in range(3):
            if best[i] is None or trip[i] > best[i]:
                best[i] = trip[i]
                book[i] = pref
    for pref in MAX_PREFIXES:
        trip = sharp_triplet(row, pref)
        if trip:
            for i in range(3):
                if best[i] is None or trip[i] > best[i]:
                    best[i] = trip[i]
                    book[i] = pref
    return best, book


def run_backtest(divs, seasons, cfg, flat=False, stake_unit=10.0):
    th = cfg["thresholds"]
    kf = cfg["kelly_fraction"]
    bankroll = cfg["bankroll"]

    n_matches = 0
    bets = []          # zoznam {pnl, stake, taken, clv_beat}
    missing_pinnacle = 0

    for season in seasons:
        for div in divs:
            try:
                raw = download_csv(season, div)
            except Exception as e:
                print(f"[backtest] nepodarilo sa stiahnut {season}/{div}: {e}")
                continue
            reader = csv.DictReader(io.StringIO(raw))
            for row in reader:
                ftr = row.get("FTR", "")
                if ftr not in ("H", "D", "A"):
                    continue
                n_matches += 1

                pin = sharp_triplet(row, "PS")          # Pinnacle (na devig)
                if not pin:
                    missing_pinnacle += 1
                    continue
                fair = devig_mod.fair_probs(pin, method="shin")
                pin_close = sharp_triplet(row, "PSC")    # Pinnacle Closing (na CLV)

                best, book = best_soft_odds(row)
                outcome_idx = {"H": 0, "D": 1, "A": 2}[ftr]

                for i in range(3):
                    odds = best[i]
                    if odds is None:
                        continue
                    if not (th["min_odds"] <= odds <= th["max_odds"]):
                        continue
                    p = fair[i]
                    ev = blend_mod.ev(p, odds) * 100.0
                    if ev < th["min_ev_pct"] or ev > th["max_ev_pct"]:
                        continue

                    # velkost stavky
                    if flat:
                        stake = stake_unit
                    else:
                        fullk = blend_mod.kelly_fraction(p, odds)
                        stake_pct = min(fullk * kf * 100.0, cfg["max_stake_pct"])
                        stake = bankroll * stake_pct / 100.0
                    if stake <= 0:
                        continue

                    won = (i == outcome_idx)
                    pnl = stake * (odds - 1.0) if won else -stake

                    # CLV: porazili sme zaverecnu Pinnacle fer linku?
                    clv_beat = None
                    if pin_close:
                        fair_close = devig_mod.fair_probs(pin_close, method="shin")
                        fair_close_odds = 1.0 / fair_close[i] if fair_close[i] > 0 else None
                        if fair_close_odds:
                            clv_beat = odds > fair_close_odds

                    bets.append({"pnl": pnl, "stake": stake, "taken": odds,
                                 "won": won, "clv_beat": clv_beat})

    return summarize(bets, n_matches, missing_pinnacle)


def summarize(bets, n_matches, missing_pinnacle):
    n = len(bets)
    if n == 0:
        return {"n_matches": n_matches, "n_bets": 0, "note": "ziadne stavky neprosli filtrami"}

    staked = sum(b["stake"] for b in bets)
    profit = sum(b["pnl"] for b in bets)
    wins = sum(1 for b in bets if b["won"])

    # equity krivka + max drawdown
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for b in bets:
        equity += b["pnl"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    clv = [b["clv_beat"] for b in bets if b["clv_beat"] is not None]
    clv_beat_pct = (sum(1 for x in clv if x) / len(clv) * 100.0) if clv else None

    return {
        "n_matches": n_matches,
        "n_bets": n,
        "bet_rate_pct": round(n / n_matches * 100.0, 1) if n_matches else 0,
        "missing_pinnacle": missing_pinnacle,
        "win_rate_pct": round(wins / n * 100.0, 1),
        "total_staked": round(staked, 2),
        "profit": round(profit, 2),
        "roi_yield_pct": round(profit / staked * 100.0, 2) if staked else 0,
        "final_equity": round(equity, 2),
        "max_drawdown": round(max_dd, 2),
        "clv_beat_pct": round(clv_beat_pct, 1) if clv_beat_pct is not None else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("divs", nargs="*", default=["E0"], help="ligy: E0 SP1 D1 I1 F1 ...")
    ap.add_argument("--seasons", nargs="*", default=["2122", "2223", "2324"])
    ap.add_argument("--flat", action="store_true", help="flat staking namiesto Kelly")
    args = ap.parse_args()
    divs = args.divs if args.divs else ["E0"]

    cfg = load_config()
    print(f"Backtest | ligy={divs} sezony={args.seasons} | "
          f"prahy: EV {cfg['thresholds']['min_ev_pct']}–{cfg['thresholds']['max_ev_pct']} %, "
          f"kurz {cfg['thresholds']['min_odds']}–{cfg['thresholds']['max_odds']}, "
          f"staking={'flat' if args.flat else 'Kelly'}")
    res = run_backtest(divs, args.seasons, cfg, flat=args.flat)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    if res.get("n_bets"):
        y = res["roi_yield_pct"]
        verdict = ("KLADNY yield – metoda mala v tychto datach vyhodu (over na viac datach!)"
                   if y > 0 else
                   "ZAPORNY/nulovy yield – takto NEnasadzovat, doladit prahy alebo zmenit trh/ligu")
        print("\nZAVER:", verdict)
        if res.get("clv_beat_pct") is not None:
            print(f"CLV: v {res['clv_beat_pct']} % stavok sme porazili zaverecnu Pinnacle linku "
                  "(>50 % = dobre znamenie do buducna).")


if __name__ == "__main__":
    main()
