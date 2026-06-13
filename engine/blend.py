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


def find_value_picks(event, fair_probs, p_market, p_model, cfg):
    """
    event: {'home','away','commence','league','outcomes':[{'name','best_odds','best_book','n_books'}...]}
            poradie outcomes zodpoveda poradiu fair_probs.
    Vrati zoznam tipov (najcastejsie 0 alebo 1 na zapas/trh).
    """
    th = cfg["thresholds"]
    bankroll = cfg["bankroll"]
    kf = cfg["kelly_fraction"]
    max_stake_pct = cfg["max_stake_pct"]

    picks = []
    for i, oc in enumerate(event["outcomes"]):
        odds = oc["best_odds"]
        n_books = oc.get("n_books", 0)
        p = fair_probs[i]

        if odds is None or odds <= 1.0:
            continue
        if n_books < th["min_books"]:
            continue
        if not (th["min_odds"] <= odds <= th["max_odds"]):
            continue

        e = ev(p, odds)
        ev_pct = e * 100.0
        if ev_pct < th["min_ev_pct"]:
            continue
        if ev_pct > th["max_ev_pct"]:
            # podozrenie na chybu v datach, nie realna value -> preskocit
            continue

        full_k = kelly_fraction(p, odds)
        stake_pct = min(full_k * kf * 100.0, max_stake_pct)
        if stake_pct <= 0:
            continue

        conf = confidence(fair_probs, p_market, p_model, n_books)

        picks.append({
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
            "fair_odds": round(1.0 / p, 3) if p > 0 else None,
            "ev_pct": round(ev_pct, 2),
            "stake_pct": round(stake_pct, 2),
            "stake_amount": round(bankroll * stake_pct / 100.0, 2),
            "confidence": conf,
            "n_books": n_books,
        })
    return picks


if __name__ == "__main__":
    # self-test: fer p favorita 0.55, sadzkar dava 2.10 -> ma byt value
    p = 0.55
    o = 2.10
    print("EV:", round(ev(p, o) * 100, 2), "%")
    print("full Kelly:", round(kelly_fraction(p, o) * 100, 2), "% banku")
