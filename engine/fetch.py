"""
Stiahnutie zajtrajsich zapasov + kurzov z The Odds API (https://the-odds-api.com).

Kluc sa cita z premennej prostredia ODDS_API_KEY (NIKDY nie z repa).
Free tier (500 req/mesiac) bohato staci na 1x denne cez par lig.

Funkcie:
  - fetch_odds(cfg): live stiahnutie -> normalizovane eventy
  - load_cached(path): nacita ulozenu JSON odpoved (na offline testovanie / debugging)
  - normalize(raw, cfg): surova odpoved API -> nas interny tvar

Iba stdlib (urllib, json).
"""
from __future__ import annotations
import json
import os
import urllib.request
import urllib.parse
import urllib.error

API_BASE = "https://api.the-odds-api.com/v4"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "value-bets/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8")), dict(r.headers)


def fetch_sport(sport, cfg, api_key):
    """Stiahne kurzy pre jeden sport key. Vrati (data, zostatok_requestov)."""
    params = {
        "apiKey": api_key,
        "regions": cfg.get("regions", "eu,uk"),
        "markets": ",".join(cfg.get("markets", ["h2h"])),
        "oddsFormat": cfg.get("odds_format", "decimal"),
        "dateFormat": "iso",
    }
    url = f"{API_BASE}/sports/{sport}/odds/?" + urllib.parse.urlencode(params)
    data, headers = _get(url)
    remaining = headers.get("x-requests-remaining", "?")
    return data, remaining


def fetch_odds(cfg, api_key=None):
    """Stiahne vsetky nakonfigurovane sporty. Vrati (raw_events, info)."""
    api_key = api_key or os.environ.get("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Chyba ODDS_API_KEY. Zaregistruj sa na the-odds-api.com a nastav:\n"
            "  export ODDS_API_KEY=tvoj_kluc"
        )
    all_events, remaining = [], "?"
    for sport in cfg["sports"]:
        try:
            data, remaining = fetch_sport(sport, cfg, api_key)
            for ev in data:
                ev["_sport"] = sport
            all_events.extend(data)
        except urllib.error.HTTPError as e:
            print(f"[fetch] HTTP chyba pre {sport}: {e.code} {e.reason}")
        except urllib.error.URLError as e:
            print(f"[fetch] sietova chyba pre {sport}: {e.reason}")
    return all_events, {"requests_remaining": remaining}


def load_cached(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _best_price_per_outcome(bookmakers, market_key, sharp_books):
    """
    Z bookmakers vytiahne pre dany market:
      - best_odds + best_book pre kazdy vyber (najvyssi kurz = kam podat tip)
      - sharp_odds: kurzy z ostrej knihy (na odhad fer p), prva dostupna zo sharp_books
      - n_books: pocet kancelarii ponukajucich market
    """
    best = {}            # outcome_name -> (odds, book)
    sharp_odds = {}      # outcome_name -> odds (z ostrej knihy)
    sharp_priority = {b: i for i, b in enumerate(sharp_books)}
    sharp_chosen_rank = {}
    books_seen = 0

    for bk in bookmakers:
        key = bk.get("key", "")
        market = next((m for m in bk.get("markets", []) if m.get("key") == market_key), None)
        if not market:
            continue
        books_seen += 1
        for oc in market.get("outcomes", []):
            name = oc.get("name")
            price = oc.get("price")
            point = oc.get("point")
            full_name = name if point is None else f"{name} {point}"
            if price is None:
                continue
            # najlepsi kurz napriec knihami
            if full_name not in best or price > best[full_name][0]:
                best[full_name] = (price, key)
            # ostra linka (podla priority v sharp_books)
            if key in sharp_priority:
                rank = sharp_priority[key]
                if full_name not in sharp_chosen_rank or rank < sharp_chosen_rank[full_name]:
                    sharp_chosen_rank[full_name] = rank
                    sharp_odds[full_name] = price
    return best, sharp_odds, books_seen


def normalize(raw_events, cfg):
    """
    Surova odpoved API -> zoznam eventov pre dalsie spracovanie.
    Kazdy event je rozbity na (event x market) kvoli h2h aj totals.
    """
    sharp_books = cfg.get("sharp_books", ["pinnacle"])
    out = []
    for ev in raw_events:
        bms = ev.get("bookmakers", [])
        if not bms:
            continue
        for market_key in cfg.get("markets", ["h2h"]):
            best, sharp_odds, n_books = _best_price_per_outcome(bms, market_key, sharp_books)
            if not best:
                continue
            # poradie vyberov: drz konzistentne s tym, co ma ostra kniha (ak ma)
            names = list(best.keys())
            outcomes = []
            for name in names:
                bo, bk = best[name]
                outcomes.append({
                    "name": name,
                    "best_odds": bo,
                    "best_book": bk,
                    "n_books": n_books,
                    "sharp_odds": sharp_odds.get(name),
                })
            out.append({
                "league": ev.get("sport_title", ev.get("_sport", "")),
                "sport_key": ev.get("_sport") or ev.get("sport_key", ""),
                "home": ev.get("home_team", ""),
                "away": ev.get("away_team", ""),
                "commence": ev.get("commence_time", ""),
                "market": market_key,
                "outcomes": outcomes,
            })
    return out


if __name__ == "__main__":
    import sys
    cfg = json.load(open(os.path.join(os.path.dirname(__file__), "..", "config.json")))
    try:
        raw, info = fetch_odds(cfg)
        print(f"Stiahnutych eventov: {len(raw)} | zostatok requestov: {info['requests_remaining']}")
        norm = normalize(raw, cfg)
        print(f"Normalizovanych (event x market): {len(norm)}")
        if norm:
            print(json.dumps(norm[0], ensure_ascii=False, indent=2))
    except RuntimeError as e:
        print(e)
        sys.exit(1)
