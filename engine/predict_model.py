"""
PREDIKČNÁ noha (BETEGY-style) — model-predikcie, NIE overená value.

Tok: FootyStats prematch xG  ->  Poisson model (model.py)  ->  pravdepodobnosti
     1X2 / Over-Under 2.5 / BTTS / top presné skóre  ->  prediction-signály.

Predikcie sú jasne označené ("predikcia (neoverená value)"). Pre informáciu pripájame
aj trhové kvóty z FootyStats a "model_ev_pct" (či model vidí na danom výbere value voči trhu).

Výstup: zoznam signálov (signal.py, type=prediction). Orchestruje ho predict.py do signals.json.
Iba stdlib.
"""
from __future__ import annotations
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

import footystats as fs_mod    # noqa: E402
import model as model_mod      # noqa: E402
import signal as signal_mod    # noqa: E402
import blend as blend_mod      # noqa: E402


def _implied(odd):
    try:
        o = float(odd)
        return 1.0 / o if o > 1.0 else None
    except (TypeError, ValueError):
        return None


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def build_signal_for_match(m):
    """Z jedného FootyStats zápasu (s prematch xG) vyrobí jeden prediction-signál, alebo None."""
    xg = fs_mod.match_xg(m)
    if not xg:
        return None
    lam_h, lam_a = xg
    home = m.get("home_name", "")
    away = m.get("away_name", "")

    p1x2 = model_mod.h2h_probs(lam_h, lam_a)
    ou = model_mod.totals_probs(lam_h, lam_a, 2.5)
    btts = model_mod.btts_probs(lam_h, lam_a)
    tops = model_mod.top_scorelines(lam_h, lam_a, 5)

    # 1X2 výber modelu (headline) + kvóta trhu naň
    sides = [("home", home, p1x2["home"], _f(m.get("odds_ft_1"))),
             ("draw", "Draw", p1x2["draw"], _f(m.get("odds_ft_x"))),
             ("away", away, p1x2["away"], _f(m.get("odds_ft_2")))]
    sides.sort(key=lambda s: s[2], reverse=True)
    pick_code, pick_name, pick_prob, pick_odds = sides[0]
    second_prob = sides[1][2]

    # confidence: ako rozhodný je výber (rozdiel top dvoch) + strop
    margin = pick_prob - second_prob
    conf = round(min(1.0, 0.40 + margin * 2.0), 3)

    # model EV voči trhu (ak je kvóta) — most predikcia -> value
    model_ev_pct = None
    if pick_odds:
        model_ev_pct = round(blend_mod.ev(pick_prob, pick_odds) * 100.0, 2)

    commence = _unix_to_iso(m.get("date_unix"))
    leg = signal_mod.make_leg(selection=pick_name, book="(trh)", odds=pick_odds, fair_prob=pick_prob)
    sig = signal_mod.make_signal(
        stype=signal_mod.TYPE_PREDICTION,
        sport="soccer",
        home=home, away=away, commence=commence,
        market="h2h",
        legs=[leg],
        edge_value=pick_prob,          # metrika = model_prob
        confidence=conf,
        league=m.get("competition_name") or m.get("league_name") or "",
        expires_hint=commence,
        extra={
            "source": "footystats",
            "match_id": m.get("id"),
            "xg": {"home": round(lam_h, 2), "away": round(lam_a, 2)},
            "pick": pick_code,
            "model_ev_pct": model_ev_pct,
            "probs_1x2": {k: round(v, 3) for k, v in p1x2.items()},
            "ou25": {k: round(v, 3) for k, v in ou.items()},
            "btts": {k: round(v, 3) for k, v in btts.items()},
            "top_scores": [[f"{i}-{j}", round(p, 3)] for i, j, p in tops],
            "market_odds": {
                "1": _f(m.get("odds_ft_1")), "x": _f(m.get("odds_ft_x")), "2": _f(m.get("odds_ft_2")),
                "over25": _f(m.get("odds_ft_over25")), "btts_yes": _f(m.get("odds_btts_yes")),
            },
            # FootyStats vlastné predikčné % (nezávislý druhý názor na náš Poisson)
            "fs_potential": {"o25": m.get("o25_potential"), "btts": m.get("btts_potential")},
        },
    )
    return sig


def _unix_to_iso(unix):
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(unix), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def build_prediction_signals(cfg, force_all=False):
    """
    Postaví prediction-signály podľa config['legs']['prediction'].
    force_all=True ignoruje filter 'only_upcoming' (na testovanie s historickými dátami).
    Vráti (signals, notes).
    """
    leg_cfg = (cfg.get("legs", {}) or {}).get("prediction", {}) or {}
    notes = []
    if not leg_cfg.get("enabled"):
        return [], ["predikčná noha vypnutá (config.legs.prediction.enabled=false)"]

    season_ids = leg_cfg.get("season_ids", [])
    if not season_ids:
        return [], ["predikčná noha: chýbajú season_ids v configu"]

    only_upcoming = leg_cfg.get("only_upcoming", True) and not force_all
    max_matches = leg_cfg.get("max_matches", 100)

    signals = []
    for sid in season_ids:
        matches, meta = fs_mod.league_matches(sid)
        if meta.get("error"):
            notes.append(f"season {sid}: {meta['error']}")
            continue
        if only_upcoming:
            matches = fs_mod.upcoming_matches(matches)
        for m in matches:
            sig = build_signal_for_match(m)
            if sig:
                signals.append(sig)
        notes.append(f"season {sid}: {len(matches)} zápasov | request_remaining={meta.get('request_remaining')}")

    # najpravdepodobnejšie/najsebavedomejšie predikcie hore
    signals.sort(key=lambda s: (s.get("confidence") or 0, s["edge"]["value"]), reverse=True)
    if max_matches:
        signals = signals[:max_matches]
    return signals, notes


if __name__ == "__main__":
    # test cez example kľúč (EPL 2018/19), force_all lebo sú to dohraté zápasy
    import json
    test_cfg = {"legs": {"prediction": {"enabled": True, "season_ids": [1625],
                                        "only_upcoming": False, "max_matches": 3}}}
    sigs, notes = build_prediction_signals(test_cfg, force_all=True)
    for n in notes:
        print("[predict_model]", n)
    print(f"[predict_model] prediction signálov: {len(sigs)}")
    if sigs:
        print(json.dumps(sigs[0], ensure_ascii=False, indent=2))
