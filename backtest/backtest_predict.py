"""
Backtest / KALIBRÁCIA predikčnej nohy (PLAN_V2 Fáza 1).

Otázka: predikuje náš model (FootyStats prematch xG -> Poisson) naozaj dobre?
Meriame na dohratých zápasoch (máme predikciu aj skutočný výsledok):
  - Brier score + log-loss + presnosť pre 1X2, Over/Under 2.5, BTTS
  - kalibračná tabuľka (keď model povie 70 %, stane sa to ~70 %?)
  - ROI: keby stávkujeme na pick modelu trhovým kurzom (všetko vs len value model_ev>0)
  - porovnanie s TRHOM (implied z odds_ft) — bije náš model trhové kvóty?

Default dáta: FootyStats key=example -> EPL 2018/19 (season_id 1625), zadarmo.
Pri platenom kľúči: --season <id> (napr. iná liga) -> reálna validácia.

Použitie:
  python3 backtest/backtest_predict.py
  python3 backtest/backtest_predict.py --season 1625 --min-ev 2

Iba stdlib.
"""
from __future__ import annotations
import os
import sys
import math
import argparse

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "engine"))

import footystats as fs    # noqa: E402
import model as model_mod  # noqa: E402


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def implied_1x2(o1, ox, o2):
    """Normalizované implied pravdepodobnosti trhu z 1X2 kvót (odstránená marža)."""
    inv = [1.0 / o for o in (o1, ox, o2) if o and o > 1.0]
    if len(inv) != 3:
        return None
    s = sum(inv)
    return [v / s for v in inv]


def brier_multiclass(probs, actual_idx):
    """Σ(p_i - o_i)^2 cez triedy. 0 = perfektné, horšie = vyššie."""
    return sum((p - (1.0 if i == actual_idx else 0.0)) ** 2 for i, p in enumerate(probs))


def logloss(p_actual):
    return -math.log(max(min(p_actual, 1 - 1e-12), 1e-12))


def calibration_table(pairs, bins=10):
    """pairs = [(pred_prob, hit 0/1)]. Vráti riadky (rozsah, n, priemer_pred, skutočná_freq)."""
    buckets = [[] for _ in range(bins)]
    for p, hit in pairs:
        idx = min(bins - 1, int(p * bins))
        buckets[idx].append((p, hit))
    rows = []
    for i, b in enumerate(buckets):
        if not b:
            continue
        n = len(b)
        avg_p = sum(p for p, _ in b) / n
        freq = sum(h for _, h in b) / n
        rows.append((f"{i*100//bins:>2}-{(i+1)*100//bins:>3}%", n, round(avg_p, 3), round(freq, 3)))
    return rows


def run(season_id, min_ev_pct, max_matches=None):
    matches, meta = fs.league_matches(season_id)
    if meta.get("error"):
        print(f"[backtest_predict] season {season_id}: {meta['error']}")
        return
    done = [m for m in matches if m.get("status") == "complete" and fs.match_xg(m)]
    if max_matches:
        done = done[:max_matches]
    print(f"[backtest_predict] season {season_id}: {len(done)} dohratých zápasov s xG\n")

    # akumulátory
    n = 0
    b1x2_model = b1x2_mkt = ll1x2 = acc1x2 = 0.0
    bou = llou = accou = 0.0
    bbtts = llbtts = accbtts = 0.0
    cal_fav = []          # kalibrácia: pravdepodobnosť favorita 1X2 vs trafil
    # ROI simulácia (1X2 pick modelu pri trhovom kurze)
    staked_all = ret_all = 0.0
    staked_val = ret_val = bets_val = 0

    for m in done:
        lam_h, lam_a = fs.match_xg(m)
        gh, ga = m.get("homeGoalCount"), m.get("awayGoalCount")
        if gh is None or ga is None:
            continue
        n += 1

        # --- 1X2 ---
        p = model_mod.h2h_probs(lam_h, lam_a)
        probs = [p["home"], p["draw"], p["away"]]
        s = sum(probs); probs = [x / s for x in probs]
        actual = 0 if gh > ga else (1 if gh == ga else 2)
        b1x2_model += brier_multiclass(probs, actual)
        ll1x2 += logloss(probs[actual])
        pick = max(range(3), key=lambda i: probs[i])
        acc1x2 += 1.0 if pick == actual else 0.0
        cal_fav.append((probs[pick], 1.0 if pick == actual else 0.0))

        o1, ox, o2 = _f(m.get("odds_ft_1")), _f(m.get("odds_ft_x")), _f(m.get("odds_ft_2"))
        mkt = implied_1x2(o1, ox, o2)
        if mkt:
            b1x2_mkt += brier_multiclass(mkt, actual)

        # ROI: stávka 1 jednotka na pick modelu pri trhovom kurze
        pick_odds = (o1, ox, o2)[pick]
        if pick_odds and pick_odds > 1.0:
            staked_all += 1.0
            if pick == actual:
                ret_all += pick_odds
            # value filter: model_ev = p*(odds-1) - (1-p)
            ev = probs[pick] * (pick_odds - 1) - (1 - probs[pick])
            if ev * 100 >= min_ev_pct:
                bets_val += 1
                staked_val += 1.0
                if pick == actual:
                    ret_val += pick_odds

        # --- Over/Under 2.5 ---
        ou = model_mod.totals_probs(lam_h, lam_a, 2.5)
        over_hit = 1.0 if (gh + ga) > 2.5 else 0.0
        bou += (ou["over"] - over_hit) ** 2 + (ou["under"] - (1 - over_hit)) ** 2
        llou += logloss(ou["over"] if over_hit else ou["under"])
        accou += 1.0 if ((ou["over"] >= 0.5) == (over_hit == 1.0)) else 0.0

        # --- BTTS ---
        bt = model_mod.btts_probs(lam_h, lam_a)
        btts_hit = 1.0 if (gh > 0 and ga > 0) else 0.0
        bbtts += (bt["yes"] - btts_hit) ** 2 + (bt["no"] - (1 - btts_hit)) ** 2
        llbtts += logloss(bt["yes"] if btts_hit else bt["no"])
        accbtts += 1.0 if ((bt["yes"] >= 0.5) == (btts_hit == 1.0)) else 0.0

    if n == 0:
        print("[backtest_predict] žiadne použiteľné zápasy."); return

    def r(x): return round(x, 4)
    print("=== PRESNOSŤ PREDIKCIÍ (nižší Brier/log-loss = lepšie) ===")
    print(f"1X2     : Brier {r(b1x2_model/n)} (trh {r(b1x2_mkt/n)})  log-loss {r(ll1x2/n)}  presnosť {r(acc1x2/n*100)}%")
    print(f"O/U 2.5 : Brier {r(bou/n)}  log-loss {r(llou/n)}  presnosť {r(accou/n*100)}%")
    print(f"BTTS    : Brier {r(bbtts/n)}  log-loss {r(llbtts/n)}  presnosť {r(accbtts/n*100)}%")
    verdict = "MODEL BIJE TRH" if b1x2_model < b1x2_mkt else "trh je lepší (model zaostáva)"
    print(f"  -> 1X2 vs trh: {verdict}")

    print("\n=== KALIBRÁCIA (pick modelu): pred. pravdepod. vs skutočná freq ===")
    print("  rozsah        n   pred   real")
    for rng, cnt, ap, fr in calibration_table(cal_fav):
        print(f"  {rng:<10} {cnt:>4}  {ap:>5}  {fr:>5}")

    print("\n=== ROI (stávka na 1X2 pick modelu pri trhovom kurze) ===")
    if staked_all:
        yld_all = (ret_all - staked_all) / staked_all * 100
        print(f"VŠETKY picky: {int(staked_all)} stávok, yield {round(yld_all,2)}%")
    if staked_val:
        yld_val = (ret_val - staked_val) / staked_val * 100
        print(f"Len value (model_ev>={min_ev_pct}%): {bets_val} stávok, yield {round(yld_val,2)}%")
    else:
        print(f"Len value (model_ev>={min_ev_pct}%): 0 stávok")
    print("\nPozn.: trhový kurz tu je predzápasový z FootyStats; reálny ROI value nohy validuje backtest.py (closing linka).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", type=int, default=1625, help="FootyStats season_id (default 1625 = EPL 2018/19, key=example)")
    ap.add_argument("--min-ev", type=float, default=2.0, help="prah model_ev %% pre value filter")
    ap.add_argument("--max", type=int, default=None, help="limit zápasov (debug)")
    args = ap.parse_args()
    run(args.season, args.min_ev, args.max)
