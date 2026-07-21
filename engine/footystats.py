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
import sys
import time
import urllib.request
import urllib.parse
import urllib.error

sys.path.insert(0, os.path.dirname(__file__))
import fetch as _fetch   # noqa: E402  (kvôli _best_non_outlier pre value zdroj)

API_BASE = "https://api.football-data-api.com"

# FootyStats názvy ostrých kníh v odds_comparison (v poradí preferencie pre devig)
FS_SHARP = ["Pncl", "Betfair", "Smarkets", "Matchbook"]


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


def chosen_season_ids(api_key=None, max_leagues=None):
    """
    Vráti season_id AKTUÁLNEJ sezóny pre každú ligu VYBRANÚ vo FootyStats dashboarde.
    Vďaka tomu netreba hardkódovať ID — user si ligy zvolí v dashboarde a appka ich pochytí.
    Vráti (ids, error).
    """
    try:
        resp = league_list(api_key, chosen_only=True)
    except (urllib.error.HTTPError, urllib.error.URLError) as e:
        return [], f"league-list zlyhal: {e}"
    if not resp.get("success"):
        return [], resp.get("message") or "league-list neúspešný"
    ids = []
    for lg in resp.get("data", []) or []:
        seasons = lg.get("season", []) or []
        if not seasons:
            continue
        best = max(seasons, key=lambda s: s.get("year", 0) or 0)
        if best.get("id"):
            ids.append(best["id"])
    if max_leagues:
        ids = ids[:max_leagues]
    return ids, None


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


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _outcome_from_books(disp, book_odds):
    """book_odds = {kniha: '1.58', ...} -> normalizovaný outcome (best non-outlier + sharp Pinnacle)."""
    prices, sharp, sharp_rank = [], None, None
    for book, od in (book_odds or {}).items():
        o = _num(od)
        if o is None or o <= 1.0:
            continue
        prices.append((o, book))
        if book in FS_SHARP:
            r = FS_SHARP.index(book)
            if sharp_rank is None or r < sharp_rank:
                sharp_rank, sharp = r, o
    if not prices:
        return None
    best_odds, best_book = _fetch._best_non_outlier(prices)
    return {"name": disp, "best_odds": best_odds, "best_book": best_book,
            "n_books": len({b for _, b in prices}), "sharp_odds": sharp}


def _unix_iso(unix):
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(unix), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def _event_from_match(det, market, sid):
    """Z detailu zápasu (odds_comparison) postaví jeden normalizovaný event pre daný trh."""
    oc = det.get("odds_comparison") or {}
    home, away = det.get("home_name", ""), det.get("away_name", "")
    commence = _unix_iso(det.get("date_unix"))
    league = det.get("competition_name") or det.get("league_name") or ""
    outs = []
    if market == "h2h":
        ftr = oc.get("FT Result") or {}
        for key, disp in (("1", home), ("X", "Draw"), ("2", away)):
            o = _outcome_from_books(disp, ftr.get(key))
            if o:
                outs.append(o)
    elif market == "totals":
        ou = oc.get("Over/Under") or {}
        for key in ("Over 2.5", "Under 2.5"):
            o = _outcome_from_books(key, ou.get(key))
            if o:
                outs.append(o)
    if len(outs) < 2:
        return None
    return {"league": league, "sport_key": "soccer", "home": home, "away": away,
            "commence": commence, "market": market, "outcomes": outs,
            "match_id": det.get("id")}


def value_events(cfg, api_key=None):
    """
    VALUE zdroj z FootyStats (náhrada za The Odds API) — bez limitu 6 líg.
    Použije ligy vybrané vo FootyStats dashboarde (chosen), pre nadchádzajúce zápasy stiahne
    odds_comparison (kurzy po knihách vrátane Pinnacle) a vráti normalizované eventy ako fetch.normalize().
    Vráti (events, info).
    """
    pcfg = (cfg.get("legs", {}) or {}).get("prediction", {}) or {}
    season_ids, err = chosen_season_ids(api_key, max_leagues=pcfg.get("max_leagues", 15))
    if err:
        return [], {"error": err}
    markets = cfg.get("markets", ["h2h", "totals"])
    max_per = cfg.get("value_max_matches_per_league", 25)
    horizon_h = cfg.get("horizon_hours", 72)
    now = time.time()
    until = now + horizon_h * 3600.0

    events = []
    # diagnostika — nech je z logu jasné, kde sa zápasy stratili
    info = {"seasons": len(season_ids), "remaining": None,
            "upcoming": 0, "in_horizon": 0, "details": 0, "with_odds": 0, "matches": 0}
    for sid in season_ids:
        try:
            matches, meta = league_matches(sid, api_key)
        except (urllib.error.HTTPError, urllib.error.URLError):
            continue
        info["remaining"] = meta.get("request_remaining")
        ups = upcoming_matches(matches)
        info["upcoming"] += len(ups)
        # detaily sťahujeme LEN pre zápasy v horizonte (šetrí requesty aj čas)
        inh = []
        for m in ups:
            try:
                t = float(m.get("date_unix") or 0)
            except (TypeError, ValueError):
                continue
            if now <= t <= until:
                inh.append(m)
        inh = inh[:max_per]
        info["in_horizon"] += len(inh)
        for base in inh:
            try:
                det = (match_detail(base["id"], api_key) or {}).get("data") or {}
            except (urllib.error.HTTPError, urllib.error.URLError):
                continue
            info["details"] += 1
            if det.get("odds_comparison"):
                info["with_odds"] += 1
            built = 0
            for market in markets:
                ev = _event_from_match(det, market, sid)
                if ev:
                    events.append(ev)
                    built += 1
            if built:
                info["matches"] += 1
            time.sleep(0.12)
    return events, info


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
