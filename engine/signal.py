"""
JEDNOTNÝ dátový model "signal" — spoločný kontrakt pre všetky 3 nohy appky:
  - value       : jeden výber, jedna kniha, kladná EV z ostrého trhu (dnešný flow)
  - prediction  : model-predikcia (Elo+Poisson+xG), NEoverená value, len odhad
  - arb         : surebet — kombinácia 2–3 výberov naprieč knihami so Σ(1/kurz) < 1

Web číta `data/signals.json` (zoznam týchto objektov) a filtruje podľa aktívneho tabu (`type`).
Value/prediction = `legs` má 1 prvok. Arb = `legs` má 2–3 prvky (rôzne knihy).

Iba stdlib. Bez závislostí.
"""
from __future__ import annotations

# Povolené typy nôh
TYPE_VALUE = "value"
TYPE_PREDICTION = "prediction"
TYPE_ARB = "arb"

# Ľudské labely (web ich zobrazí, nech je jasné čo je overené a čo len odhad)
LABELS = {
    TYPE_VALUE: "overená value",
    TYPE_PREDICTION: "predikcia (neoverená value)",
    TYPE_ARB: "surebet",
}

# Metriky "edge" podľa typu
EDGE_METRIC = {
    TYPE_VALUE: "ev_pct",          # očakávaný výnos na stávku v %
    TYPE_PREDICTION: "model_prob", # pravdepodobnosť výberu podľa modelu (0–1)
    TYPE_ARB: "arb_profit_pct",    # garantovaný zisk surebetu v %
}


def make_leg(selection, book, odds, stake_pct=None, fair_prob=None):
    """Jedna noha signálu (jeden výber u jednej knihy)."""
    leg = {
        "selection": selection,
        "book": book,
        "odds": round(odds, 3) if odds is not None else None,
    }
    if stake_pct is not None:
        leg["stake_pct"] = round(stake_pct, 2)
    if fair_prob is not None:
        leg["fair_prob"] = round(fair_prob, 4)
    return leg


def make_signal(stype, sport, home, away, commence, market, legs,
                edge_value, confidence=None, league="", expires_hint=None,
                extra=None):
    """
    Zostaví jeden signál v jednotnom tvare.

    stype       : "value" | "prediction" | "arb"
    legs        : list dictov z make_leg()
    edge_value  : číslo podľa EDGE_METRIC[stype]
    extra       : voliteľné polia navyše (napr. fair_odds, score predikcie)
    """
    sig = {
        "type": stype,
        "sport": sport,
        "league": league,
        "event": {"home": home, "away": away, "commence": commence},
        "market": market,
        "legs": legs,
        "edge": {"metric": EDGE_METRIC.get(stype, "edge"), "value": round(edge_value, 3)},
        "confidence": round(confidence, 3) if confidence is not None else None,
        "label": LABELS.get(stype, stype),
        "expires_hint": expires_hint,
    }
    if extra:
        sig.update(extra)
    return sig


def signal_key(sig):
    """
    Stabilný kľúč signálu (na dedup, párovanie výsledkov, tip_results PK).
    Konzistentný s dnešným tip_key formátom: "commence|home|away|market|selection".
    Pre arb (viac nôh) zreťazí výbery.
    """
    ev = sig["event"]
    sels = "+".join(leg["selection"] for leg in sig["legs"])
    return f"{ev['commence']}|{ev['home']}|{ev['away']}|{sig['market']}|{sels}"


def value_pick_to_signal(pick):
    """
    Most z DNEŠNÉHO value pick formátu (engine/blend.py) na jednotný signál.
    Nemení výpočty — len prebalí existujúci záznam, aby ho vedel čítať nový web.
    """
    leg = make_leg(
        selection=pick["selection"],
        book=pick.get("bookmaker", ""),
        odds=pick["best_odds"],
        stake_pct=pick.get("stake_pct"),
        fair_prob=pick.get("fair_prob"),
    )
    return make_signal(
        stype=TYPE_VALUE,
        sport=pick.get("sport_key", ""),
        home=pick["home"],
        away=pick["away"],
        commence=pick["commence"],
        market=pick.get("market", "h2h"),
        legs=[leg],
        edge_value=pick.get("ev_pct", 0.0),
        confidence=pick.get("confidence"),
        league=pick.get("league", ""),
        extra={
            "fair_odds": pick.get("fair_odds"),
            "stake_amount": pick.get("stake_amount"),
            "n_books": pick.get("n_books"),
        },
    )


if __name__ == "__main__":
    import json
    demo_pick = {
        "league": "EPL", "sport_key": "soccer_epl", "home": "Arsenal", "away": "Chelsea",
        "commence": "2026-08-01T16:00:00Z", "market": "h2h", "selection": "Arsenal",
        "best_odds": 2.10, "bookmaker": "bet365", "fair_prob": 0.52, "fair_odds": 1.92,
        "ev_pct": 4.2, "stake_pct": 1.8, "stake_amount": 18.0, "confidence": 0.71, "n_books": 9,
    }
    sig = value_pick_to_signal(demo_pick)
    print(json.dumps(sig, ensure_ascii=False, indent=2))
    print("key:", signal_key(sig))
