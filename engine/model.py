"""
Poissonov model: z ocakavanych golov tImov odhadne pravdepodobnosti vysledkov.

Pre MS je to LEN DOPLNOK k trhu (narodne timy maju malo dat). Pri klubovych ligach
sa rola modelu zvysi (viac historickych zapasov -> lepsie ratingy).

Ratingy (utocna/obranna sila) sa drzia v data/ratings.json a daju sa priebezne
aktualizovat (zatial volitelne; ak rating chyba, model vrati None -> pouzije sa cisty trh).

Iba stdlib (math).
"""
from __future__ import annotations
import math
import json
import os

MAX_GOALS = 10  # horna hranica pre sumovanie Poisson rozdelenia


def poisson_pmf(k, lam):
    """P(X = k) pre Poisson so strednou hodnotou lam."""
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam ** k) / math.factorial(k)


def score_matrix(lam_home, lam_away):
    """Matica pravdepodobnosti vysledkov (i golov domaci, j golov hostia)."""
    home = [poisson_pmf(i, lam_home) for i in range(MAX_GOALS + 1)]
    away = [poisson_pmf(j, lam_away) for j in range(MAX_GOALS + 1)]
    return [[home[i] * away[j] for j in range(MAX_GOALS + 1)] for i in range(MAX_GOALS + 1)]


def h2h_probs(lam_home, lam_away):
    """1 / X / 2 pravdepodobnosti z Poisson matice."""
    m = score_matrix(lam_home, lam_away)
    p_home = p_draw = p_away = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            if i > j:
                p_home += m[i][j]
            elif i == j:
                p_draw += m[i][j]
            else:
                p_away += m[i][j]
    return {"home": p_home, "draw": p_draw, "away": p_away}


def totals_probs(lam_home, lam_away, line=2.5):
    """Over / Under pre danu ciaru golov."""
    m = score_matrix(lam_home, lam_away)
    p_over = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            if i + j > line:
                p_over += m[i][j]
    return {"over": p_over, "under": 1.0 - p_over}


def expected_goals(home_team, away_team, ratings):
    """
    Z ratingov odhadne ocakavane goly. ratings = {
        'home_advantage': float, 'league_avg_goals': float,
        'teams': { name: {'attack': a, 'defense': d} } }
    Vrati (lam_home, lam_away) alebo None ak chyba rating timu.
    """
    teams = ratings.get("teams", {})
    if home_team not in teams or away_team not in teams:
        return None
    ha = ratings.get("home_advantage", 0.0)
    base = ratings.get("league_avg_goals", 1.35)
    h, a = teams[home_team], teams[away_team]
    lam_home = max(0.05, base * h["attack"] * a["defense"] + ha)
    lam_away = max(0.05, base * a["attack"] * h["defense"])
    return lam_home, lam_away


def load_ratings(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "..", "data", "ratings.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def model_probs_for_event(event, ratings):
    """
    Vrati model pravdepodobnosti v poradi event['outcomes'], alebo None ak sa neda.
    Mapuje nazvy vyberov (mena timov / Over/Under) na model.
    """
    if not ratings:
        return None
    eg = expected_goals(event["home"], event["away"], ratings)
    if eg is None:
        return None
    lam_h, lam_a = eg

    out = []
    for oc in event["outcomes"]:
        name = oc["name"]
        if event["market"] == "h2h":
            p = h2h_probs(lam_h, lam_a)
            if name == event["home"]:
                out.append(p["home"])
            elif name == event["away"]:
                out.append(p["away"])
            else:  # Draw
                out.append(p["draw"])
        elif event["market"] == "totals":
            # name napr. "Over 2.5" / "Under 2.5"
            parts = name.split()
            line = float(parts[-1]) if parts and _is_float(parts[-1]) else 2.5
            p = totals_probs(lam_h, lam_a, line)
            out.append(p["over"] if name.lower().startswith("over") else p["under"])
        else:
            return None
    s = sum(out)
    return [x / s for x in out] if s > 0 else None


def _is_float(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    # self-test: dva rovnako silne timy, ocakavane ~1.4 gola kazdy
    print("h2h:", {k: round(v, 3) for k, v in h2h_probs(1.4, 1.1).items()})
    print("O/U 2.5:", {k: round(v, 3) for k, v in totals_probs(1.4, 1.1, 2.5).items()})
