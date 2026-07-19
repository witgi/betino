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

# bookmaker_id -> názov (BetBurger číselník, betburger.com/api/entity_ids). Doplniť podľa potreby.
BOOKMAKER_NAMES = {
    1: "Pinnacle", 2: "Betcity", 3: "Sbobet", 4: "Marathon", 6: "Fonbet", 9: "Bwin",
    10: "Bet365", 11: "Betfair", 13: "William Hill", 19: "Unibet", 20: "DafaSports",
    21: "1xBet", 27: "Olimp", 30: "Leon", 39: "Tipsport", 48: "Betsson", 50: "Smarkets",
    80: "Fortuna", 94: "Pamestoixima", 95: "888Sport", 102: "Snai", 105: "Sportmarket",
    119: "BetinAsia", 127: "FortuneJack", 167: "Netbet", 199: "Bet365", 279: "Winamax",
    308: "Sazka", 313: "DaznBet", 318: "Lvbet", 319: "Virginbet", 329: "Superbet",
    346: "Betway", 348: "Olimpo", 425: "1win", 426: "BetRivers", 464: "NorskTipping",
    483: "Polymarket", 486: "Betplay", 489: "Tipos", 700: "Expekt", 706: "EsportesDaSorte",
    728: "Kalshi", 729: "Betano", 732: "HKJC",
}

# sport_id -> názov
SPORT_NAMES = {
    1: "Baseball", 2: "Basketbal", 4: "Futsal", 5: "Hádzaná", 6: "Hokej", 7: "Futbal",
    8: "Tenis", 9: "Volejbal", 10: "Am. futbal", 11: "Snooker", 12: "Šípky",
    13: "Stolný tenis", 14: "Bedminton", 15: "Rugby League", 24: "Kriket",
    39: "E-Soccer", 41: "E-Basketbal", 43: "Rugby Union", 44: "Box", 45: "MMA",
}

# market_and_bet_type -> šablóna labelu (%s = čiara/param). Pokrýva bežné trhy; zvyšok fallback.
MARKET_NAMES = {
    1: "1", 2: "2", 3: "1 (bez remízy)", 4: "2 (bez remízy)",
    5: "EH 1 %s", 6: "EH X %s", 7: "EH 2 %s",
    8: "Oba skórujú – áno", 9: "Oba skórujú – nie",
    11: "1", 12: "X", 13: "2", 14: "1X", 15: "X2", 16: "12",
    17: "AH 1 %s", 18: "AH 2 %s",
    19: "Nad %s", 20: "Pod %s",
    21: "Nad %s (dom.)", 22: "Pod %s (dom.)", 23: "Nad %s (hos.)", 24: "Pod %s (hos.)",
    25: "Nepárne", 26: "Párne", 67: "Presný skór %s",
    1210: "Oba skórujú %s – áno", 1211: "Oba skórujú %s – nie",
}


def _fmt_param(p):
    try:
        f = float(p)
        return str(int(f)) if f == int(f) else f"{f:g}"
    except (TypeError, ValueError):
        return str(p)


def _market_label(bet):
    t = bet.get("market_and_bet_type")
    p = bet.get("market_and_bet_type_param")
    tmpl = MARKET_NAMES.get(t)
    if tmpl:
        return tmpl % _fmt_param(p) if "%s" in tmpl else tmpl
    return f"typ{t}" + (f" {_fmt_param(p)}" if p not in (None, "", 0, 0.0) else "")


def _book_name(bid):
    return BOOKMAKER_NAMES.get(bid, f"bk:{bid}")


def _sport_name(sid):
    return SPORT_NAMES.get(sid, f"šport:{sid}")


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
        sport=_sport_name(arb.get("sport_id")),
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
            for l in sig["legs"]:   # nemapované knihy majú book "bk:<id>"
                if isinstance(l.get("book"), str) and l["book"].startswith("bk:"):
                    unknown_books.add(l["book"])
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
