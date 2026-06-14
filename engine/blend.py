"""
Z fer pravdepodobnosti + dostupnych kurzov vyrobi VALUE TIPY.

Pripomienka filozofie (value betting, NIE arbitraz):
  - Pre kazdy vyber (napr. "vyhra domacich") mame fer p z ostreho trhu (+ model).
  - Najdeme JEDNU kancelariu s najvyssim kurzom na ten vyber.
  - Ak ten kurz dava kladnu EV -> je to tip: TENTO vyber, v TEJTO kancelarii.
  - Nikdy nekombinujeme vybery cez kancelarie (to by bola arbitraz).
"""
from __future__ import annotations


def ev(prob, odds):
    """Expected value na 1 jednotku stavky. 0.05 = +5 % vynos na stavku."""
    return prob * (odds - 1.0) - (1.0 - prob)


def kelly_fraction(prob, odds):
    """Plny Kelly podiel banku. Zaporny -> nestavkovat."""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    f = (prob * b - (1.0 - prob)) / b
    return max(0.0, f)


def blend_probs(p_market, p_model, market_weight):
    """Vahovane spojenie trhu a modelu. Ak model chyba, vrati cisty trh."""
    if p_model is None:
        return list(p_market)
    w = market_weight
    return [w * pm + (1.0 - w) * mo for pm, mo in zip(p_market, p_model)]


def confidence(p_final, p_market, p_model, n_books):
    """
    Hrube confidence skore 0..1 na triedenie tipov:
      - viac kancelarii = spolahlivejsi konsenzus
      - mensia odchylka trh<->model = vyssia zhoda signalov
    """
    book_score = min(1.0, n_books / 8.0)
    if p_model is None:
        agree_score = 0.6  # bez modelu nevieme overit, neutralne
    else:
        # priemerna absolutna odchylka medzi trhom a modelom cez vybery
        diff = sum(abs(a - b) for a, b in zip(p_market, p_model)) / len(p_market)
        agree_score = max(0.0, 1.0 - diff * 4.0)
    return round(0.5 * book_score + 0.5 * agree_score, 3)


def _evaluate_outcome(event, i, fair_probs, p_market, p_model, cfg):
    """Spocita kompletny zaznam pre jeden vyber (bez filtrov). None ak su kurzy neplatne."""
    oc = event["outcomes"][i]
    odds = oc["best_odds"]
    n_books = oc.get("n_books", 0)
    p = fair_probs[i]
    if odds is None or odds <= 1.0 or p <= 0:
        return None

    ev_pct = ev(p, odds) * 100.0
    full_k = kelly_fraction(p, odds)
    stake_pct = min(full_k * cfg["kelly_fraction"] * 100.0, cfg["max_stake_pct"])
    conf = confidence(fair_probs, p_market, p_model, n_books)

    return {
        "league": event.get("league", ""),
        "sport_key": event.get("sport_key", ""),
        "home": event["home"],
        "away": event["away"],
        "commence": event["commence"],
        "market": event.get("market", "h2h"),
        "selection": oc["name"],
        "best_odds": round(odds, 3),
        "bookmaker": oc.get("best_book", ""),
        "fair_prob": round(p, 4),
        "fair_odds": round(1.0 / p, 3),
        "ev_pct": round(ev_pct, 2),
        "stake_pct": round(stake_pct, 2),
        "stake_amount": round(cfg["bankroll"] * stake_pct / 100.0, 2),
        "confidence": conf,
        "n_books": n_books,
    }


def _passes(rec, th):
    return (rec["n_books"] >= th["min_books"]
            and th["min_odds"] <= rec["best_odds"] <= th["max_odds"]
            and th["min_ev_pct"] <= rec["ev_pct"] <= th["max_ev_pct"]
            and rec["stake_pct"] > 0)


def find_value_picks(event, fair_probs, p_market, p_model, cfg):
    """Oficialne tipy: vybery, ktore prejdu prahmi v configu (na logovanie/ROI)."""
    th = cfg["thresholds"]
    picks = []
    for i in range(len(event["outcomes"])):
        rec = _evaluate_outcome(event, i, fair_probs, p_market, p_model, cfg)
        if rec and _passes(rec, th):
            picks.append(rec)
    return picks


def build_candidates(event, fair_probs, p_market, p_model, cfg):
    """
    Vsetci kandidati pre posuvnik rizika vo webe: kladne EV, rozumny strop kurzu.
    Web ich filtruje nazivo (bez noveho stahovania). Default prahy z configu su 'oficialne'.
    """
    cc = cfg.get("candidate", {})
    floor_ev = cc.get("min_ev_pct", 0.0)
    max_ev = cc.get("max_ev_pct", 20.0)
    max_odds = cc.get("max_odds", 8.0)
    min_books = cc.get("min_books", 3)
    out = []
    for i in range(len(event["outcomes"])):
        rec = _evaluate_outcome(event, i, fair_probs, p_market, p_model, cfg)
        if not rec:
            continue
        if (floor_ev <= rec["ev_pct"] <= max_ev
                and rec["best_odds"] <= max_odds and rec["n_books"] >= min_books):
            out.append(rec)
    return out


if __name__ == "__main__":
    # self-test: fer p favorita 0.55, sadzkar dava 2.10 -> ma byt value
    p = 0.55
    o = 2.10
    print("EV:", round(ev(p, o) * 100, 2), "%")
    print("full Kelly:", round(kelly_fraction(p, o) * 100, 2), "% banku")
