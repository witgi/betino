"""
Odstranenie bookmaker marze (vig) z kurzov -> "pravdive" pravdepodobnosti.

Bookmaker do kurzov zarata maржu, takze sucet implikovanych pravdepodobnosti
je > 100 % (tzv. overround). Aby sme dostali realny odhad, marzu treba odstranit.

Dve metody:
  - multiplicative: jednoduche normovanie (vydelenie overroundom). Rychle, OK baseline.
  - shin: zohladnuje "favourite-longshot bias" (sadzkare viac orezavaju outsiderov).
          Pre futbal 1X2 byva presnejsie. Pouzivame ako default.

Vsetko cisto v stdlib (math), ziadne zavislosti.
"""
from __future__ import annotations
import math


def implied_probs(odds):
    """Decimalne kurzy -> surove implikovane pravdepodobnosti (sucet > 1)."""
    return [1.0 / o for o in odds]


def overround(odds):
    """Marza trhu: sucet implikovanych p. 1.05 = 5 % overround."""
    return sum(implied_probs(odds))


def devig_multiplicative(odds):
    """Naivna normalizacia: kazdu implikovanu p vydelime sumou."""
    raw = implied_probs(odds)
    s = sum(raw)
    return [p / s for p in raw]


def devig_shin(odds, max_iter=200, tol=1e-12):
    """
    Shin (1992/1993) metoda. Odhaduje podiel "informovaneho obchodovania" z (z toho
    plynie favourite-longshot korekcia) a vrati fer pravdepodobnosti.

    Pre 2 vybery ma uzavrety vzorec; pre n vyberov riesime z iterativne.
    Padne spat na multiplicative, ak by nieco zlyhalo.
    """
    pi = implied_probs(odds)   # surove implikovane p (sucet = overround)
    s = sum(pi)                # overround (Pi)
    n = len(pi)
    if n < 2 or s <= 0:
        return devig_multiplicative(odds)

    def probs_for_z(z):
        # Shin: p_i = (sqrt(z^2 + 4(1-z) * pi_i^2 / Pi) - z) / (2(1-z))
        # kde pi_i su surove implikovane p a Pi = sum(pi_i).
        out = []
        denom = 2.0 * (1.0 - z)
        for p_raw in pi:
            val = (math.sqrt(z * z + 4.0 * (1.0 - z) * (p_raw * p_raw) / s) - z) / denom
            out.append(val)
        return out

    # hladame z tak, aby sucet p == 1. z je v [0, 1).
    lo, hi = 0.0, 0.999999
    # f(z) = sum(probs_for_z) - 1 ; monotonne -> bisekcia
    try:
        for _ in range(max_iter):
            mid = 0.5 * (lo + hi)
            f = sum(probs_for_z(mid)) - 1.0
            if abs(f) < tol:
                break
            # pri z=0 dostaneme prakticky q (sucet 1). Smer korekcie urcime numericky.
            f_lo = sum(probs_for_z(lo)) - 1.0
            if (f > 0) == (f_lo > 0):
                lo = mid
            else:
                hi = mid
        p = probs_for_z(0.5 * (lo + hi))
        ssum = sum(p)
        if ssum <= 0 or any(x <= 0 for x in p):
            return devig_multiplicative(odds)
        return [x / ssum for x in p]  # final safety-normalizacia
    except (ValueError, ZeroDivisionError):
        return devig_multiplicative(odds)


def fair_probs(odds, method="shin"):
    """Hlavny vstupny bod. Vrati fer pravdepodobnosti pre dane kurzy."""
    if method == "multiplicative":
        return devig_multiplicative(odds)
    return devig_shin(odds)


def fair_odds_from_prob(p):
    """Pravdepodobnost -> fer kurz (1/p). Bezpecne voci 0."""
    return float("inf") if p <= 0 else 1.0 / p


if __name__ == "__main__":
    # rychly self-test: typicky 1X2 trh
    test = [1.91, 3.50, 4.20]
    print("kurzy:        ", test)
    print("overround:    ", round(overround(test), 4))
    print("multiplicative:", [round(x, 4) for x in devig_multiplicative(test)])
    print("shin:          ", [round(x, 4) for x in devig_shin(test)])
    print("sum shin:      ", round(sum(devig_shin(test)), 6))
