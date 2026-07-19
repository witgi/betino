"""
Hlavny orchestrator: stiahne kurzy -> devig -> model -> blend -> value tipy -> predictions.json

Pouzitie:
  export ODDS_API_KEY=...        # live rezim
  python engine/predict.py

  python engine/predict.py --cache data/cache/sample_raw.json   # offline z ulozenej odpovede

Vystup: data/predictions.json (cita ho web).
Iba stdlib.
"""
from __future__ import annotations
import json
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(__file__)
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)

import fetch as fetch_mod          # noqa: E402
import devig as devig_mod          # noqa: E402
import model as model_mod          # noqa: E402
import blend as blend_mod          # noqa: E402
import signal as signal_mod        # noqa: E402
import predict_model as predmodel  # noqa: E402
import betburger as betburger_mod  # noqa: E402
import arb as arb_mod              # noqa: E402
import footystats as fs_mod        # noqa: E402


def load_config():
    with open(os.path.join(ROOT, "config.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def within_horizon(commence_iso, horizon_hours):
    """True ak vykop je v buducnosti a do horizon_hours od teraz."""
    if not commence_iso:
        return True
    try:
        t = datetime.fromisoformat(commence_iso.replace("Z", "+00:00"))
    except ValueError:
        return True
    now = datetime.now(timezone.utc)
    return now <= t <= now + timedelta(hours=horizon_hours)


def market_fair_probs(event):
    """
    Fer pravdepodobnosti z OSTREJ knihy (devig Shin). Vrati list v poradi outcomes,
    alebo None ak ostra kniha nepokryva vsetky vybery.
    """
    sharp = [oc.get("sharp_odds") for oc in event["outcomes"]]
    if any(s is None or s <= 1.0 for s in sharp):
        return None
    return devig_mod.fair_probs(sharp, method="shin")


def load_performance():
    """Sumar z history.jsonl (ROI, CLV, pocet tipov) pre zobrazenie vo webe."""
    path = os.path.join(ROOT, "data", "history.jsonl")
    if not os.path.exists(path):
        return None
    settled, wins, staked, returned, clv_beats, clv_count = 0, 0, 0.0, 0.0, 0, 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                if r.get("result") in ("win", "loss", "push"):
                    settled += 1
                    stake = r.get("stake_amount", 0)
                    staked += stake
                    if r.get("result") == "win":
                        wins += 1
                        returned += stake * r.get("best_odds", 1)
                    elif r.get("result") == "push":
                        returned += stake
                if r.get("clv_beat") is not None:
                    clv_count += 1
                    if r["clv_beat"]:
                        clv_beats += 1
    except (OSError, json.JSONDecodeError):
        return None
    if settled == 0:
        return None
    roi = (returned - staked) / staked * 100.0 if staked > 0 else 0.0
    return {
        "settled_bets": settled,
        "win_rate_pct": round(wins / settled * 100.0, 1),
        "roi_pct": round(roi, 2),
        "clv_beat_pct": round(clv_beats / clv_count * 100.0, 1) if clv_count else None,
    }


def run(cache_path=None):
    cfg = load_config()
    notes = []

    value_source = cfg.get("value_source", "odds_api")
    if cache_path:
        raw = fetch_mod.load_cached(cache_path)
        info = {"requests_remaining": "n/a (cache)"}
        notes.append(f"Offline rezim z cache: {cache_path}")
        events = fetch_mod.normalize(raw, cfg)
    elif value_source == "footystats":
        # value zdroj = FootyStats (kurzy po knihách vrátane Pinnacle) — bez limitu líg
        events, vinfo = fs_mod.value_events(cfg)
        info = {"requests_remaining": f"FS:{vinfo.get('remaining')}"}
        if vinfo.get("error"):
            notes.append(f"value zdroj FootyStats CHYBA: {vinfo['error']}")
        else:
            notes.append(f"value zdroj: FootyStats — {vinfo.get('matches')} zápasov, {vinfo.get('seasons')} líg")
    else:
        raw, info = fetch_mod.fetch_odds(cfg)
        events = fetch_mod.normalize(raw, cfg)
    ratings = model_mod.load_ratings()
    if not ratings:
        notes.append("ratings.json chyba -> model preskoceny, pouziva sa cisty trh (OK pre MS).")

    considered, skipped_no_sharp, all_picks, all_candidates = 0, 0, [], []
    for ev in events:
        if not within_horizon(ev["commence"], cfg.get("horizon_hours", 36)):
            continue
        considered += 1

        p_market = market_fair_probs(ev)
        if p_market is None:
            skipped_no_sharp += 1
            continue

        p_model = model_mod.model_probs_for_event(ev, ratings)
        p_final = blend_mod.blend_probs(p_market, p_model, cfg["blend"]["market_weight"])

        all_picks.extend(blend_mod.find_value_picks(ev, p_final, p_market, p_model, cfg))
        all_candidates.extend(blend_mod.build_candidates(ev, p_final, p_market, p_model, cfg))

    all_picks.sort(key=lambda p: (p["confidence"], p["ev_pct"]), reverse=True)
    all_candidates.sort(key=lambda p: p["ev_pct"], reverse=True)

    if skipped_no_sharp:
        notes.append(f"{skipped_no_sharp} zapasov preskocenych (ostra kniha nepokryva vsetky vybery).")

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bankroll": cfg["bankroll"],
        "kelly_fraction": cfg["kelly_fraction"],
        "sports": cfg["sports"],
        "thresholds": cfg["thresholds"],
        "requests_remaining": info.get("requests_remaining"),
        "n_events_considered": considered,
        "n_picks": len(all_picks),
        "performance": load_performance(),
        "picks": all_picks,
        "candidates": all_candidates,
        "staking": {
            "bankroll": cfg["bankroll"],
            "kelly_fraction": cfg["kelly_fraction"],
            "max_stake_pct": cfg["max_stake_pct"],
        },
        "default_thresholds": cfg["thresholds"],
        "notes": notes,
    }

    out_path = os.path.join(ROOT, "data", "predictions.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # --- Jednotný výstup signals.json (PLAN_V2: spoločný formát pre 3 nohy) ---
    # Value noha: kandidáti (širší zoznam pre posuvník) prebalené na signály;
    # tie, čo prešli oficiálnymi prahmi, dostanú "official": true.
    official_keys = {
        f"{p['commence']}|{p['home']}|{p['away']}|{p.get('market','h2h')}|{p['selection']}"
        for p in all_picks
    }
    value_signals = []
    for c in all_candidates:
        sig = signal_mod.value_pick_to_signal(c)
        sig["official"] = signal_mod.signal_key(sig) in official_keys
        value_signals.append(sig)

    all_signals = list(value_signals)
    legs_enabled = ["value"]

    # --- Predikčná noha (FootyStats → Poisson) — nesmie zhodiť value nohu ---
    pred_cfg = (cfg.get("legs", {}) or {}).get("prediction", {}) or {}
    if pred_cfg.get("enabled"):
        try:
            pred_signals, pred_notes = predmodel.build_prediction_signals(cfg)
            all_signals.extend(pred_signals)
            legs_enabled.append("prediction")
            notes.extend(f"[predikcie] {n}" for n in pred_notes)
            print(f"[predict] prediction signálov: {len(pred_signals)}")
        except Exception as e:   # noqa: BLE001 - izolácia nohy
            notes.append(f"[predikcie] CHYBA (noha preskočená): {e}")
            print(f"[predict] predikčná noha zlyhala: {e}")

    # --- Arbitrážna noha — dva zdroje: The Odds API (medzinár.) + BetBurger (vrátane SK kníh) ---
    arb_cfg = (cfg.get("legs", {}) or {}).get("arb", {}) or {}
    if arb_cfg.get("enabled"):
        arb_total = 0
        # zdroj A: surebety z The Odds API kurzov (len keď value zdroj = odds_api; potrebuje per-book dáta)
        if value_source == "odds_api":
            try:
                horizon_events = [e for e in events
                                  if within_horizon(e["commence"], cfg.get("horizon_hours", 72))]
                a = arb_mod.find_arbs(horizon_events, cfg)
                all_signals.extend(a); arb_total += len(a)
                notes.append(f"[arb] OddsAPI: {len(a)} surebetov z {len(horizon_events)} trhov")
            except Exception as e:   # noqa: BLE001 - izolácia zdroja
                notes.append(f"[arb] OddsAPI CHYBA: {e}")
                print(f"[predict] arb (OddsAPI) zlyhal: {e}")
        # zdroj B: BetBurger (SK knihy ako Tipsport; capped ~1 % bez plateného plánu)
        if (arb_cfg.get("betburger", {}) or {}).get("filter_ids"):
            try:
                bb_cfg = {"legs": {"arb": {"enabled": True, **arb_cfg["betburger"]}}}
                b, bb_notes = betburger_mod.build_arb_signals(bb_cfg)
                all_signals.extend(b); arb_total += len(b)
                notes.extend(f"[arb] {n}" for n in bb_notes)
            except Exception as e:   # noqa: BLE001
                notes.append(f"[arb] BetBurger CHYBA: {e}")
                print(f"[predict] arb (BetBurger) zlyhal: {e}")
        if arb_total or True:
            legs_enabled.append("arb")
        print(f"[predict] arb signálov spolu: {arb_total}")

    # zoznam všetkých kníh pre filter v arb tabe (aj tie, čo práve nemajú arb) =
    # známe BetBurger knihy + knihy z aktuálnych arbov (vrátane OddsAPI)
    arb_leg_books = {l["book"] for s in all_signals if s.get("type") == "arb"
                     for l in (s.get("legs") or s.get("stake_split") or []) if l.get("book")}
    all_books = sorted(set(betburger_mod.BOOKMAKER_NAMES.values()) | arb_leg_books,
                       key=lambda b: b.lower())

    signals_out = {
        "generated_at": out["generated_at"],
        "legs_enabled": legs_enabled,
        "sports": cfg["sports"],
        "staking": out["staking"],
        "performance": out["performance"],
        "all_books": all_books,
        "signals": all_signals,
    }
    signals_path = os.path.join(ROOT, "data", "signals.json")
    with open(signals_path, "w", encoding="utf-8") as f:
        json.dump(signals_out, f, ensure_ascii=False, indent=2)

    print(f"[predict] zapasov zvazenych: {considered} | value tipov: {len(all_picks)}")
    print(f"[predict] requests_remaining: {info.get('requests_remaining')}")
    for n in notes:
        print(f"[predict] pozn.: {n}")
    print(f"[predict] zapisane -> {out_path}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", help="cesta k ulozenej JSON odpovedi API (offline test)")
    args = ap.parse_args()
    try:
        run(cache_path=args.cache)
    except RuntimeError as e:
        print(e)
        sys.exit(1)
