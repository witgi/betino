"""
BetBurger API klient — zdroj pre ARBITRÁŽNU nohu (3. noha, PLAN_V2).

Token sa číta z premennej prostredia BETBURGER_API_KEY (NIKDY nie z repa).
BetBurger bez plateného API plánu OREŽE výsledky na surebety do ~1 % zisku (zadarmo k web predplatnému).

API:
  POST https://rest-api-pr.betburger.com/api/v1/arbs/bot_pro_search
  auth: query param ?access_token=...
  body (form-encoded): search_filter[]=<ID filtra z dashboardu>, per_page, bookmakers2[]...
  odpoveď: { arbs:[ArbsDto], bets:[BetDto], total, ... }
    ArbsDto: id, percent (zisk %), home, away, league, sport_id, started_at, bk_ids,
             bet1_id/bet2_id/bet3_id (-> bets[].id)
    BetDto:  id, koef (kurz), bookmaker_id, market_and_bet_type(+_param), direct_link, home, away

Filter (search_filter) si user vytvorí v BetBurger dashboarde (sekcia Filters) a dá nám jeho ID.
Odporúčanie: jeden ŠIROKÝ filter (prematch, všetky tvoje knihy) — výber kníh riešime až vo webe (klient-side).

Iba stdlib (urllib, json).
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
import signal as signal_mod   # noqa: E402

API_BASE = "https://rest-api-pr.betburger.com"

# bookmaker_id -> názov. Doplníme podľa reálnych dát (po prvom úspešnom fetchi vypíše neznáme ID).
BOOKMAKER_NAMES = {
    # vyplní sa empiricky, napr.: 2: "bet365", ...: "Tipsport", ...: "Unibet"
}

# market_and_bet_type -> hrubý label (doplníme podľa dát; teraz orientačné)
def _market_label(bet):
    t = bet.get("market_and_bet_type")
    p = bet.get("market_and_bet_type_param")
    base = {1: "1", 2: "X", 3: "2"}.get(t)
    if base:
        return base
    if p not in (None, "", 0):
        return f"typ{t} {p}"
    return f"typ{t}"


def _book_name(bid):
    return BOOKMAKER_NAMES.get(bid, f"bk:{bid}")


def _post(path, params):
    token = os.environ.get("BETBURGER_API_KEY")
    if not token:
        raise RuntimeError("Chýba BETBURGER_API_KEY (vlož do ~/value-bets/.env alebo GH secrets).")
    url = f"{API_BASE}/{path}?access_token={urllib.parse.quote(token)}"
    body = urllib.parse.urlencode(params, doseq=True).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"User-Agent": "value-bets/1.0",
                                          "Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_arbs(filter_ids, per_page=50):
    """Stiahne surebety pre dané filter ID. Vráti (arbs, bets_by_id, meta)."""
    params = {"search_filter[]": list(filter_ids), "per_page": per_page}
    try:
        resp = _post("api/v1/arbs/bot_pro_search", params)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:200] if hasattr(e, "read") else e.reason
        return [], {}, {"error": f"HTTP {e.code}: {detail}"}
    except urllib.error.URLError as e:
        return [], {}, {"error": f"sieťová chyba: {e.reason}"}
    arbs = resp.get("arbs", []) or []
    bets_by_id = {b.get("id"): b for b in (resp.get("bets", []) or [])}
    meta = {"total": resp.get("total"), "maxPercentByFilter": resp.get("maxPercentByFilter")}
    return arbs, bets_by_id, meta


def _arb_to_signal(arb, bets_by_id):
    """ArbsDto + napojené BetDto -> jednotný arb signál (signal.py)."""
    leg_ids = [arb.get("bet1_id"), arb.get("bet2_id"), arb.get("bet3_id")]
    legs = []
    for bid in leg_ids:
        if not bid:
            continue
        b = bets_by_id.get(bid)
        if not b:
            continue
        legs.append(signal_mod.make_leg(
            selection=_market_label(b),
            book=_book_name(b.get("bookmaker_id")),
            odds=b.get("koef"),
        ))
    if len(legs) < 2:
        return None
    started = arb.get("started_at")
    commence = _unix_to_iso(started)
    sig = signal_mod.make_signal(
        stype=signal_mod.TYPE_ARB,
        sport=f"sport:{arb.get('sport_id')}",
        home=arb.get("home", ""), away=arb.get("away", ""),
        commence=commence,
        market=arb.get("arb_type", ""),
        legs=legs,
        edge_value=float(arb.get("percent") or 0.0),   # garantovaný zisk %
        confidence=None,
        league=arb.get("league", ""),
        expires_hint=commence,
        extra={
            "source": "betburger",
            "arb_id": arb.get("id"),
            "is_live": arb.get("is_live"),
            "bk_ids": arb.get("bk_ids"),
            "direct_links": [bets_by_id.get(b, {}).get("direct_link") for b in leg_ids if b],
        },
    )
    return sig


def _unix_to_iso(unix):
    from datetime import datetime, timezone
    try:
        return datetime.fromtimestamp(int(unix), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def build_arb_signals(cfg):
    """Postaví arb-signály podľa config['legs']['arb']. Vráti (signals, notes)."""
    leg_cfg = (cfg.get("legs", {}) or {}).get("arb", {}) or {}
    if not leg_cfg.get("enabled"):
        return [], ["arb noha vypnutá (config.legs.arb.enabled=false)"]
    filter_ids = leg_cfg.get("filter_ids", [])
    if not filter_ids:
        return [], ["arb noha: chýbajú filter_ids (vytvor filter v BetBurger dashboarde a daj jeho ID do configu)"]

    arbs, bets_by_id, meta = fetch_arbs(filter_ids, leg_cfg.get("per_page", 50))
    if meta.get("error"):
        return [], [f"BetBurger: {meta['error']}"]

    signals, unknown_books = [], set()
    for a in arbs:
        sig = _arb_to_signal(a, bets_by_id)
        if sig:
            signals.append(sig)
            for bid in (a.get("bk_ids") or []):
                if bid not in BOOKMAKER_NAMES:
                    unknown_books.add(bid)
    signals.sort(key=lambda s: s["edge"]["value"], reverse=True)
    notes = [f"BetBurger: {len(signals)} arbov (total~{meta.get('total')}, max%~{meta.get('maxPercentByFilter')})"]
    if unknown_books:
        notes.append(f"neznáme bookmaker_id (doplniť do BOOKMAKER_NAMES): {sorted(unknown_books)}")
    return signals, notes


if __name__ == "__main__":
    # vyžaduje BETBURGER_API_KEY v prostredí + aspoň jedno filter ID ako argument
    fids = [int(x) for x in sys.argv[1:]] or []
    if not fids:
        print("Použitie: BETBURGER_API_KEY=... python3 engine/betburger.py <filter_id> [filter_id2 ...]")
        sys.exit(0)
    sigs, notes = build_arb_signals({"legs": {"arb": {"enabled": True, "filter_ids": fids}}})
    for n in notes:
        print("[betburger]", n)
    print(f"[betburger] arb signálov: {len(sigs)}")
    if sigs:
        print(json.dumps(sigs[0], ensure_ascii=False, indent=2))
