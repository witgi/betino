# 🏗️ PLAN V2 — betnito.com ako 3-nohá platforma

> Posun vízie (2026-06-21): z jednej nohy (value tipy) robíme **tri prepínateľné nohy**:
> **1) Value tipy · 2) Predikcie (BETEGY-style) · 3) Arbitráž (surebety)**.
> Spoločné konto, sledovanie ziskovosti per noha, primárne futbal ale pripravené na iné športy.
> **Pravidlo č. 1 ostáva: KVALITA > KVANTITA, rozhodnutia podložené dátami.**
>
> ⚠️ Zmena oproti pôvodnému handfoffu: arbitráž bola predtým zámerne vylúčená. Teraz ju robíme,
> ale poctivo — vrátane praktických úskalí (viď Fáza 2 / Riziká).

---

## 0. Východisko (čo už máme — staviame na tom, nezahadzujeme)
- **Engine (Python stdlib, 0 závislostí):** fetch (The Odds API), devig (Shin), blend (EV/Kelly),
  model (Poisson — pripravený, vypnutý), predict, reconcile (settle), stats, push_supabase.
- **Web:** statický, Supabase Auth (Google) + označovanie „podané" + osobné/globálne štatistiky + posuvník rizika.
- **Infra:** GitHub Actions denný cron → Pages deploy na betnito.com. Supabase (EU) DB+Auth.
- **Dáta:** The Odds API (free 500 kreditov/mes, ~40 kníh, Pinnacle ✅), football-data.co.uk (backtest).
- **Backtest dôkaz:** 1X2 yield +6.4 %, CLV beat 74.6 %.

---

## 1. Cieľová architektúra (modulárna, 3 nohy zdieľajú jadro)

```
config/
  sports/<sport>.json     # per-šport profil (kľúče, trhy, prahy, sharp knihy)
  legs.json               # nastavenia per noha (value / predict / arb)
engine/
  core/
    signal.py             # JEDNOTNÝ dátový model "signal" pre všetky 3 nohy
    normalize.py          # spoločná normalizácia eventov/trhov
    config.py             # načítanie per-sport + per-leg configu
  sources/                # pluggable dátové zdroje (jeden súbor = jeden poskytovateľ)
    odds_theoddsapi.py    # kurzy (value + arb) — refaktor dnešného fetch.py
    stats_clubelo.py      # Elo kluby (zadarmo)
    stats_understat.py    # xG (zadarmo)
    stats_apifootball.py  # neskôr / platené (fixtures, lineupy, multi-šport)
  legs/
    value.py              # dnešný EV flow (devig→EV→Kelly)
    predict.py            # NOVÉ: Elo+Poisson+xG → predikcie
    arb.py                # NOVÉ: detekcia surebetov + stake split
  devig.py  model.py  blend.py   # zdieľané výpočty (ostávajú)
  pipeline.py             # orchestrácia: pre každú zapnutú nohu → data/signals.json
  reconcile.py  stats.py  push_supabase.py   # vyhodnotenie + DB (rozšírené o 'type'/'sport')
data/
  signals.json            # JEDEN výstup pre web: zoznam signálov s poľom type=value|prediction|arb
  ratings.json            # Elo/rating pipeline výstup (pre predikcie)
  stats.json  history.jsonl
web/
  index.html app.js ...   # + prepínač 3 nôh, panely ziskovosti per noha
```

**Jednotný „signal" (jadro celej appky):**
```jsonc
{
  "type": "value | prediction | arb",
  "sport": "soccer_epl",
  "event": { "home": "...", "away": "...", "commence": "ISO" },
  "market": "h2h | totals | ...",
  "legs": [ { "selection": "...", "book": "...", "odds": 2.10, "stake_pct": 1.8 } ],
  "edge": { "metric": "ev_pct | model_prob | arb_profit_pct", "value": 4.2 },
  "confidence": 0.0,            // 0–1
  "label": "overená value | predikcia (neoverená) | surebet",
  "expires_hint": "ISO/null"   // kedy príležitosť pravdepodobne zmizne
}
```
Value/predikcia = `legs` má 1 prvok. Arb = `legs` má 2–3 prvky (rôzne knihy).

---

## 2. Dátové zdroje — lacný štart vs. platené škálovanie
(detailný prieskum nižšie zhrnutý; plné porovnanie v poznámkach k pláne)

| Noha | Lacný štart (~€0–60/mes) | Platené škálovanie |
|---|---|---|
| **Value** | The Odds API $30–59 (Pinnacle benchmark) | upgrade $119, príp. SportsGameOdds/OddsPapi |
| **Predikcie** | ClubElo (zadarmo) + Understat xG (zadarmo) + football-data.co.uk (backtest); API-Football free (100 req/deň) na fixtures | FootyStats £70 (xG+predictions) alebo API-Football €19–159, per-šport moduly |
| **Arbitráž** | The Odds API — **len pre-match** detektor (refresh 15–30 min) | BetBurger/OddsJam/OpticOdds ($499+/enterprise) pre live + 100+ kníh |

**Pozor (overené v prieskume):**
- The Odds API má **kreditový** model (1 call = viac kreditov podľa trhov×regiónov) → častý polling rastie rýchlo; pri arbe reálne treba $59 plán.
- **Live arbitráž bez enterprise feedu nie je konkurencieschopná** (žije sekundy). Robíme **pre-match** arb.
- **Najväčší praktický limit value/arb nie sú dáta, ale limitovanie/zatváranie účtov** bookmakermi. Appku staviame ako **detektor príležitostí**, nie sľub garantovaného zisku.
- Understat/ClubElo sú neoficiálne cesty → maj fallback; FBref od jan 2026 stratil Opta licenciu (len historické).

---

## 3. Fázový plán (každá fáza = samostatne nasaditeľná, nič nerozbije predošlé)

### Fáza 0 — Modulárny základ (bez nového API, bez zmeny správania)
- Zaviesť `engine/core/signal.py` (jednotný model) + `engine/sources/` (refaktor `fetch.py` → `odds_theoddsapi.py`).
- Presunúť dnešný value flow do `engine/legs/value.py`; výstup do `data/signals.json` s `type:"value"`.
- **Regresný test:** existujúci backtest musí dať rovnaké čísla (+6.4 % yield) → dôkaz, že refaktor nič nezmenil.
- DB migrácia: `tip_results`→pridať `type`, `sport`; `user_bets`→`type`, `sport`. Bez straty dát.
- Web: prečítať `signals.json` (zatiaľ zobrazí len value, vizuálne bez zmeny).
- **Výsledok:** rovnaká appka, ale pripravená na 2 ďalšie nohy.

### Fáza 1 — Predikcie noha (zadarmo dáta)
- `engine/sources/stats_clubelo.py` + `stats_understat.py` → `data/ratings.json` (Elo + xG korekcia).
- `engine/legs/predict.py`: zapnúť Poisson `model.py` → 1X2, O/U 2.5, BTTS, top-N presný skór.
- Jasný label „predikcia (neoverená value)" + confidence z modelu.
- **Backtest kalibrácia:** Brier score / log-loss vs. closing odds (football-data.co.uk), + simulovaný ROI.
- Web: 2. tab „Predikcie".
- **Výsledok:** druhá noha, zadarmo, backtestnutá.

### Fáza 2 — Arbitráž noha (pre-match, z existujúceho feedu)
- `engine/legs/arb.py`: pre event/market nájdi kombináciu kníh kde Σ(1/kurz) < 1 → surebet;
  vráť stake split + garantovaný zisk %. Rovnaká outlier ochrana ako value (chybný kurz = falošný arb).
- Realisticky pre-match, refresh 15–30 min → **intra-day cron** (alebo druhý workflow len pre arb).
- Web: 3. tab „Arbitráž" + stake kalkulačka; poctivý disclaimer (limitovanie účtov, krátka životnosť).
- Sledovať spotrebu The Odds API kreditov (častejší polling).
- **Výsledok:** tretia noha, prepínač funguje.

### Fáza 3 — Konto & ziskovosť per noha
- DB: per-leg bankroll + ROI + equity per `type`. Arb = skupina nôh (viac book-stávok ako jedna „podaná" jednotka).
- Web: prepínač value/predikcie/arb + osobné aj globálne štatistiky **per noha** + spoločný súhrn.
- Virtuálny bankroll „keby dávaš všetko" počítaný osobitne pre každú nohu.
- **Výsledok:** plnohodnotné konto naprieč 3 nohami.

### Fáza 4 — Platené škálovanie + multi-šport
- Upgrade The Odds API plánu; pridať FootyStats/API-Football pre predikcie a ďalšie športy.
- Per-šport stats moduly (api-sports rodina) — value+arb idú multi-šport hneď (jeden odds API).
- Voliteľne always-on worker / enterprise arb feed ak sa arb osvedčí.

---

## 4. Riziká a poctivé limity
- **Limitovanie účtov** (soft books) — hlavný reálny limit. Pinnacle/Betfair nelimitujú, ale tam arb nie je.
- **Arb životnosť** — pre-match minúty/hodiny (OK pri 15–30 min refresh), live sekundy (mimo nášho rozsahu v1).
- **Kreditový model API** — strážiť spotrebu, inak prekvapivé náklady.
- **Neoficiálne dáta** (Understat/ClubElo) — môžu zmeniť štruktúru → fallback + monitoring.
- **Predikcie ≠ value** — jasne oddelené v UI, aby si nestaval na predikciách ako na overenej výhode.

---

## 5. Rozhodnutia (ODSÚHLASENÉ 2026-06-21)
1. **Rozpočet na API:** **€100+/mes** → môžeme rovno počítať s FootyStats/API-Football (xG+predictions) + väčší odds plán.
2. **Arbitráž v1:** **len pre-match detektor** (lacné, realistické).
3. **Infra:** **always-on worker OK**, ak náklady nebudú stovky €/mes → cieľ ~€4–10/mes (Hetzner/Oracle free-tier/Fly.io). GitHub cron ostáva fallback.
4. **Poradie:** po Fáze 0 ide **Predikcie ako prvá noha** (zadarmo dáta, Poisson pripravený), potom Arbitráž.

### Realita nákladov na worker (cieľ < stovky €)
- **Oracle Cloud Always Free** (ARM VM) = €0, ale setup náročnejší.
- **Hetzner CX22 ~€4/mes** alebo **Fly.io shared ~€0–5/mes** = jednoduché, lacné, beží Python loop.
- Worker bude pravidelne (napr. á 15–30 min) ťahať kurzy pre value+arb a 1×/deň predikcie; zápis do Supabase + deploy dát.

---

## 6. Postup realizácie — Fáza 0 (prebieha)
1. ✅ Zachytiť baseline backtest (dôkaz pred refaktorom).
2. `engine/core/signal.py` — jednotný dátový model.
3. `engine/sources/odds_theoddsapi.py` — refaktor `fetch.py`.
4. `engine/legs/value.py` — presun dnešného value flow, výstup `signals.json` (type=value).
5. Regresný test: backtest musí dať rovnaké čísla ako baseline.
6. DB migrácia (+type,+sport) + web číta `signals.json`.

---

*Vytvorené 2026-06-21. Nadväzuje na HANDOFF.md. Rozhodnutia v sekcii 5 odsúhlasené → beží Fáza 0.*
