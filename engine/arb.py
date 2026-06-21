"""
ARBITRÁŽNA noha (PLAN_V2 Fáza 2) — detekcia pre-match surebetov.

Surebet = pre úplný trh (h2h: 1/X/2; totals: Over/Under jednej čiary) vezmeme NAJLEPŠÍ kurz
na KAŽDÝ výber (môže byť z rôznych kancelárií). Ak súčet prevrátených hodnôt < 1, dá sa
rozložiť stávka tak, že zarobíš nech sa stane čokoľvek:

    sum_inv = Σ (1 / najlepší_kurz_i)
    ak sum_inv < 1  ->  garantovaný zisk = (1/sum_inv − 1) × 100 %
    rozdelenie vkladu: podiel_i = (1/kurz_i) / sum_inv   (časť celkového vkladu)

POCTIVO: arbitráž má praktické úskalia (kancelárie limitujú/zatvárajú účty, kurzy sa menia,
pre-match arby žijú minúty–hodiny). Toto je DETEKTOR príležitostí, nie záruka zisku.

Ochrana proti falošným arbom: používame best_non_outlier kurzy (fetch.py už filtruje uletené
kurzy podľa mediánu) + strop max_profit_pct (vyšší zisk = takmer isto chyba dát, nie arb).

Iba stdlib.
"""
from __future__ import annotations
import os
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)

import signal as signal_mod    # noqa: E402


def detect_arb(event, max_profit_pct=15.0):
    """
    Z jedného normalizovaného eventu (jeden trh) vráti arb dict alebo None.
    event['outcomes'] = [{name, best_odds, best_book, n_books, ...}, ...]
    """
    outcomes = event.get("outcomes", [])
    if len(outcomes) < 2:
        return None
    # každý výber musí mať platný kurz
    legs = []
    sum_inv = 0.0
    for oc in outcomes:
        odds = oc.get("best_odds")
        if not odds or odds <= 1.0:
            return None
        sum_inv += 1.0 / odds
        legs.append((oc.get("name"), oc.get("best_book"), odds))

    if sum_inv >= 1.0:
        return None  # žiadny arb

    profit_pct = (1.0 / sum_inv - 1.0) * 100.0
    if profit_pct > max_profit_pct:
        return None  # príliš veľa = takmer isto chyba dát, nie reálny surebet

    # všetky výbery z jednej knihy = kniha si protirečí (často chyba/už neplatí) -> preskoč
    books = {b for _, b, _ in legs}
    if len(books) < 2:
        return None

    return {"profit_pct": profit_pct, "sum_inv": sum_inv, "legs": legs}


def arb_to_signal(event, arb, total_stake=100.0):
    """Arb dict -> jednotný signál (type=arb) so stake split per noha."""
    sig_legs = []
    for name, book, odds in arb["legs"]:
        stake_pct = (1.0 / odds) / arb["sum_inv"] * 100.0   # % z celkového vkladu
        sig_legs.append(signal_mod.make_leg(
            selection=name, book=book, odds=odds, stake_pct=stake_pct,
        ))
    return signal_mod.make_signal(
        stype=signal_mod.TYPE_ARB,
        sport=event.get("sport_key", ""),
        home=event.get("home", ""),
        away=event.get("away", ""),
        commence=event.get("commence", ""),
        market=event.get("market", "h2h"),
        legs=sig_legs,
        edge_value=arb["profit_pct"],
        confidence=None,
        league=event.get("league", ""),
        expires_hint=event.get("commence", ""),
        extra={
            "total_stake_ref": total_stake,
            "stake_split": [
                {"selection": l["selection"], "book": l["book"], "odds": l["odds"],
                 "stake": round(total_stake * l["stake_pct"] / 100.0, 2)}
                for l in sig_legs
            ],
        },
    )


def find_arbs(events, cfg):
    """Prejde normalizované eventy, vráti zoznam arb-signálov (zoradené podľa zisku)."""
    leg_cfg = (cfg.get("legs", {}) or {}).get("arb", {}) or {}
    max_profit = leg_cfg.get("max_profit_pct", 15.0)
    total_stake = leg_cfg.get("total_stake_ref", 100.0)
    out = []
    for ev in events:
        arb = detect_arb(ev, max_profit_pct=max_profit)
        if arb:
            out.append(arb_to_signal(ev, arb, total_stake=total_stake))
    out.sort(key=lambda s: s["edge"]["value"], reverse=True)
    return out


if __name__ == "__main__":
    import json
    # synteticky test: jasny arb (1/2.10 + 1/2.10 = 0.952 < 1 -> ~5% zisk)
    ev = {
        "league": "TEST", "sport_key": "soccer_test", "home": "A", "away": "B",
        "commence": "2026-08-01T16:00:00Z", "market": "h2h",
        "outcomes": [
            {"name": "A", "best_odds": 2.10, "best_book": "book1", "n_books": 5},
            {"name": "B", "best_odds": 2.10, "best_book": "book2", "n_books": 5},
        ],
    }
    arb = detect_arb(ev)
    print("arb zisk %:", round(arb["profit_pct"], 2) if arb else None)
    sig = arb_to_signal(ev, arb, total_stake=100.0)
    print(json.dumps(sig["stake_split"], ensure_ascii=False, indent=2))
    # negativny test: ziadny arb (1/1.80 + 1/1.90 = 1.08 > 1)
    ev2 = dict(ev, outcomes=[
        {"name": "A", "best_odds": 1.80, "best_book": "b1", "n_books": 5},
        {"name": "B", "best_odds": 1.90, "best_book": "b2", "n_books": 5},
    ])
    print("ziadny arb (ocakavane None):", detect_arb(ev2))
