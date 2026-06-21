"""
FootyStats API klient (https://footystats.org/api) — zdroj pre PREDIKČNÚ nohu.

Kľúč sa číta z premennej prostredia FOOTYSTATS_API_KEY (NIKDY nie z repa).
Na testovanie bez platby existuje verejný kľúč "example" (len EPL 2018/19, season_id 1625).

Plán "Serious" = 150 líg, 3600 req/hod. Sezónu treba najprv VYBRAŤ vo footystats dashboarde,
inak league-matches vráti prázdno aj s platným kľúčom.

Dôležité dáta pre predikcie (priamo z API, predpočítané):
  - team_a_xg_prematch / team_b_xg_prematch  -> kŕmime do Poisson modelu (model.py)
  - *_potential (o25_potential, btts_potential, ...) = FootyStats vlastné predikčné % (záloha)
  - odds_ft_1/x/2, odds_ft_over25, ... = trhové kvóty (na porovnanie value)

Iba stdlib (urllib, json).
"""
from __future__ import annotations
import json
import os
import time
import urllib.request
import urllib.parse
import urllib.error

API_BASE = "https://api.football-data-api.com"


def _get(path, params):
    url = f"{API_BASE}/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "value-bets/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _key(api_key=None):
    return api_key or os.environ.get("FOOTYSTATS_API_KEY") or "example"


def league_list(api_key=None, chosen_only=False):
    """Zoznam líg + season_id pre každú sezónu. chosen_only=True vráti len vybrané ligy (platený kľúč)."""
    params = {"key": _key(api_key)}
    if chosen_only:
        params["chosen_leagues_only"] = "true"
    return _get("league-list", params)


def league_matches(season_id, api_key=None, max_pages=10):
    """
    Všetky zápasy ligy/sezóny (vrátane nadchádzajúcich, status='incomplete').
    Stránkuje automaticky. Vráti (matches, meta) kde meta nesie request_remaining.
    """
    key = _key(api_key)
    all_matches, page, meta = [], 1, {}
    while page <= max_pages:
        try:
            resp = _get("league-matches", {"key": key, "season_id": season_id, "page": page})
        except urllib.error.HTTPError as e:
            # FootyStats vracia napr. 417 keď sezóna nie je vybraná/dostupná pre tento kľúč
            detail = "sezóna nie je vybraná/dostupná pre tento kľúč" if e.code == 417 else e.reason
            meta["error"] = f"HTTP {e.code}: {detail}"
            break
        except urllib.error.URLError as e:
            meta["error"] = f"sieťová chyba: {e.reason}"
            break
        meta = resp.get("metadata", {})
        if not resp.get("success"):
            # napr. "League is not chosen by the user" pri example kľúči mimo EPL 2018/19
            meta["error"] = resp.get("message") or "neúspešná odpoveď"
            break
        data = resp.get("data", []) or []
        all_matches.extend(data)
        pager = resp.get("pager", {}) or {}
        if page >= int(pager.get("max_page", 1) or 1):
            break
        page += 1
        time.sleep(0.2)   # jemný throttle
    return all_matches, meta


def match_detail(match_id, api_key=None):
    """Detail jedného zápasu (+ h2h, odds_comparison)."""
    return _get("match", {"key": _key(api_key), "match_id": match_id})


def upcoming_matches(matches):
    """Filtruje len nadchádzajúce zápasy (status incomplete)."""
    return [m for m in matches if m.get("status") == "incomplete"]


def match_xg(m):
    """Prematch očakávané góly (lam_home, lam_away) z FootyStats, alebo None ak chýbajú."""
    h = m.get("team_a_xg_prematch")
    a = m.get("team_b_xg_prematch")
    try:
        h, a = float(h), float(a)
    except (TypeError, ValueError):
        return None
    if h <= 0 or a <= 0:
        return None
    return h, a


if __name__ == "__main__":
    # self-test cez verejný example kľúč (EPL 2018/19, season_id 1625)
    print("[footystats] test cez key=example, season_id=1625 (EPL 2018/19)")
    matches, meta = league_matches(1625, api_key="example")
    print(f"  zápasov: {len(matches)} | request_remaining: {meta.get('request_remaining')}"
          + (f" | chyba: {meta['error']}" if meta.get("error") else ""))
    with_xg = [m for m in matches if match_xg(m)]
    print(f"  s prematch xG: {len(with_xg)}")
    if with_xg:
        m = with_xg[0]
        print(f"  vzorka: {m.get('home_name')} vs {m.get('away_name')} | "
              f"xG {m.get('team_a_xg_prematch')}-{m.get('team_b_xg_prematch')} | "
              f"o25_potential={m.get('o25_potential')} btts_potential={m.get('btts_potential')} | "
              f"odds_ft {m.get('odds_ft_1')}/{m.get('odds_ft_x')}/{m.get('odds_ft_2')}")
