# 🧠 HANDOFF — Value-bets / betnito.com

> Tento súbor je pre Claude (alebo človeka), ktorý preberá projekt a má v ňom pokračovať.
> Obsahuje VŠETKO podstatné: čo to je, ako to funguje, kde čo žije, rozhodnutia, gotchas a TODO.
> **Pravidlo č. 1 projektu: KVALITA > KVANTITA. Rozhodnutia musia byť podložené dátami, nie „od oka".**

---

## 1. Čo to je (a pre koho)
Webová appka **betnito.com** pre majiteľa (witgi), ktorá automaticky hľadá **value stávky** na futbal
(začalo na MS 2026, neskôr prenositeľné na iné ligy/športy zmenou `config.json`). Cieľ:
- Každý deň sama nájde tipy s **kladnou Expected Value** a zobrazí ich (aj na mobile).
- Užívateľ sa prihlási (Google), označí tipy „podané" a vidí svoju úspešnosť + globálne štatistiky.

**Filozofia (potvrdená užívateľom):**
- **Value betting** = jeden výber, jedna kancelária (kurz podceňuje reálnu pravdepodobnosť). **NIE arbitráž, NIE akumulátory** (kombi tiket = matematicky horšie, vysvetlené nižšie).
- Pravdepodobnosti **nehádame** — čítame ich z **ostrej linky (Pinnacle)**, čo je najpresnejší verejný odhad (lepší než vlastný model z verejných dát).

---

## 2. Stav: 🟢 LIVE
- Beží na **http://betnito.com** (HTTPS cert dobiehal pri handoffe — viď TODO).
- Denný cron (GitHub Actions) o 08:07 CEST sám generuje tipy, vyhodnocuje výsledky, píše do DB a nasadzuje web.
- Prihlásenie Google + osobné sledovanie funguje (overené).

---

## 3. Kde čo žije
| Vec | Kde |
|---|---|
| Kód (repo) | **github.com/witgi/betino** (verejné) |
| Lokálne | `~/value-bets/` |
| Doména | **betnito.com** (kúpená na websupporte) |
| Hosting | GitHub Pages (cez Actions workflow `site.yml`) |
| DNS | websupport: 4× A `185.199.108–111.153` (apex), CNAME `www`→`witgi.github.io`. Parkovacie A/AAAA (37.9.x / 2a00:4b40:aaaa:2001::6) zmazané; email záznamy (45.13.137.6) NECHANÉ. |
| Databáza + Auth | **Supabase** projekt `xqkorhjywtrcdtcbugob.supabase.co` (EU Frankfurt) |
| Dátový zdroj kurzov | **The Odds API** (free 500 req/mes), sport key `soccer_fifa_world_cup` |
| Historické dáta (backtest) | football-data.co.uk (zadarmo, CSV) |

**Tajomstvá (NIE sú v repe):**
- Lokálne `~/value-bets/.env` → `ODDS_API_KEY` (gitignored).
- GitHub Actions secrets: `ODDS_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.
- Verejné (smú byť v kóde): Supabase URL + `publishable` (anon) kľúč → `web/config.js`. Chráni RLS, nie utajenie.

---

## 4. Ako to funguje (metóda — jadro kvality)
Pre každý zápas a trh (h2h = 1X2, totals = Over/Under):
1. **Stiahni kurzy** od ~40 kancelárií (The Odds API, hlavný `/odds` endpoint).
2. **Ostrá linka** = Pinnacle (príp. Betfair/Smarkets) → odstráň maržu **Shin metódou** (`engine/devig.py`) → `p_market` (pravdivá pravdepodobnosť).
3. (Voliteľne) Poisson model z ratingov (`engine/model.py`) — teraz VYPNUTÝ (chýba `data/ratings.json`), používa sa čistý trh. OK pre MS.
4. **Najlepší NEodľahlý kurz** naprieč kanceláriami → `EV = p·(kurz−1) − (1−p)`.
5. **Stake** = frakčný **Kelly** (¼, strop 2.5 % banku).
6. **Filtre** (config): EV v pásme, kurz v zóne, min. počet kancelárií, **strop EV** (nad ním = chyba, nie value).

**Dôležitá ochrana (pridaná po reálnom bugu):** jedna kancelária (marathonbet) posielala rozbité kurzy
(Germany @3.42 vs Curaçao) → fake EV +200 %. Fix v `engine/fetch.py`: `_best_non_outlier()` zahodí
kurz vyšší než **medián × `OUTLIER_CAP` (1.30)**. Plus poistka `candidate.max_ev_pct`. **Jedna zbláznená kancelária už systém neotrávi.**

---

## 5. Trhy
- ✅ **1X2 (h2h)** a **Over/Under (totals)** — zapnuté v `config.json` (`markets`). Obe overené backtestom.
- ⚠️ **Ázijský handicap (spreads)** — dostupné (7 kníh), NEzapnuté (tenšie, komplikované štvrťové čiary).
- ❌ **BTTS, rohy, karty, strelci, počet gólov tímu** — The Odds API ich na tomto pláne **nedáva kvalitne**
  (1 kniha alebo vôbec; per‑zápas endpoint by zožral free limit). Ani platený plán to nerieši — chcelo by to iný feed (OddsJam/BetsAPI/Betfair) + vlastné modely = samostatný projekt.

---

## 6. Štruktúra repo
```
config.json            # JEDINÉ miesto na ladenie (šport, prahy, bankroll, candidate, outlier)
engine/
  fetch.py             # The Odds API + normalizácia + _best_non_outlier (outlier fix)
  devig.py             # Shin devig (odstránenie marže)
  model.py             # Poisson model (zatiaľ nepoužitý, čaká na ratings.json)
  blend.py             # EV, Kelly, confidence, find_value_picks + build_candidates
  predict.py           # orchestrácia → data/predictions.json
  reconcile.py         # log tipov + settle výsledkov (The Odds API /scores) → history.jsonl
  stats.py             # globálne štatistiky + virtuálny bankroll → data/stats.json
  push_supabase.py     # upsert výsledkov do Supabase tip_results (service key)
backtest/backtest.py   # validácia na football-data.co.uk (--market h2h|totals)
data/
  predictions.json     # výstup pre web (picks = oficiálne, candidates = pre posuvník)
  stats.json           # globálne výsledky + equity krivka
  history.jsonl        # log každého tipu (result, clv_beat)
db/schema.sql          # Supabase tabuľky (tip_results, user_bets + RLS)
web/                   # index.html, app.js, style.css, config.js, CNAME(betnito.com)
.github/workflows/site.yml  # denný cron + Pages deploy
run_daily.sh           # lokálny ekvivalent cronu
SETUP.md               # návod na účty/DNS (pre usera)
```

---

## 7. Web appka (web/)
- **Posuvník „miera rizika"** — filtruje `candidates` naživo v prehliadači (vľavo bezpečné/nízke kurzy → vpravo riskantné/vyššie). Mapovanie prahov v `app.js` (`thresholdsFor`).
- **Google login** (Supabase Auth). **Tlačidlo „Podať"** → zápis do `user_bets`.
- **Panel „Tvoje výsledky"** (osobné +/− z podaných) + **„Globálne výsledky"** (virtuálny bankroll „keby dávaš všetko", equity sparkline z `stats.json`).
- Dátové cesty absolútne `/data/...` (funguje lokálne aj na doméne).
- Cron generuje `data/predictions.json` + `stats.json`; `push_supabase.py` plní `tip_results` (web podľa nej + `user_bets` ráta osobné štatistiky).

---

## 8. Databáza (Supabase)
- `tip_results` (tip_key PK; verejne čitateľné; zapisuje len cron service-key) — výsledky všetkých tipov.
- `user_bets` (RLS: každý vidí len svoje; default `user_id = auth.uid()`) — čo si user označil „podané".
- Auth: Google (OAuth client v Google Cloud, redirect `https://xqkorhjywtrcdtcbugob.supabase.co/auth/v1/callback`).
- URL Configuration: Site URL `https://betnito.com`, redirect `https://betnito.com/**`, `https://www.betnito.com/**`, `http://localhost:8765/**`.

---

## 9. Backtest (dôkaz, že metóda funguje na minulých dátach)
```
python3 backtest/backtest.py E0 E1 SP1 D1 I1 F1 N1 P1 --seasons 1920 2021 2122 2223 2324            # 1X2
python3 backtest/backtest.py E0 E1 SP1 D1 I1 F1 N1 P1 --seasons 1920 2021 2122 2223 2324 --market totals  # O/U
```
Výsledky (zachytené pri handoffe):
- **1X2:** 891 stávok, yield **+6.4 %**, **CLV beat 74.6 %**.
- **Over/Under:** 32 stávok (vzácne!), yield +60 %* (málo dát), **CLV beat 84.4 %**.
- CLV beat = % stávok, kde sme mali lepší kurz než záverečná ostrá linka = najlepší dôkaz presnosti.

---

## 10. Konfigurácia (config.json — hlavné „kohútiky")
- `sports` — sport keys (po MS zmeniť, napr. `soccer_epl`, `basketball_nba`).
- `horizon_hours` = 72 (ako ďaleko dopredu).
- `thresholds`: `min_ev_pct`=2, `max_ev_pct`=15, `min_odds`=1.4, `max_odds`=4.0, `min_books`=4 (agresívny profil, zvolený userom).
- `candidate`: širší zoznam pre posuvník (min_ev 0, max_ev 20, max_odds 8, min_books 3).
- `bankroll`=1000, `kelly_fraction`=0.25, `max_stake_pct`=2.5.
- `OUTLIER_CAP` (v `engine/fetch.py`) = 1.30.

---

## 11. ⚠️ Gotchas pre pokračovanie
- **Push na GitHub & verejné akcie**: auto-mode classifier BLOKUJE agentovi vytváranie verejných repo /
  „public surface". Bežný `git push` na existujúce repo funguje agentovi OK; ale `gh repo create --public`,
  zapnutie Pages a pod. musí **spustiť user sám** v termináli (alebo to robí agent po explicitnom súhlase + cez user).
- `gh` CLI je nainštalované v `/usr/local/bin/gh`, user je prihlásený (`gh auth status`).
- **Cron commituje dáta** → pri lokálnom pushi rob `git pull --rebase` (časté konflikty na generovaných `data/*.json` — riešiť v prospech čerstvo vygenerovaných, alebo regenerovať).
- **Value je pominuteľná**: tip zmizne zo zoznamu, keď kurz dobehne ostrú linku (aj pred výkopom) — to je správne, nie bug. Podané tipy (`user_bets`) ostávajú bez ohľadu na zoznam.
- The Odds API: free 500 req/mes. Každý `predict.py` beh = 1 req na sport. Pri škálovaní na viac líg dôjde limit → platený plán kvôli OBJEMU (nie kvôli novým trhom).
- Po MS: `soccer_fifa_world_cup` prestane byť aktívne → zmeniť `sports` na klubové ligy. Vtedy aj zapnúť Poisson model (viac dát).

---

## 12. 📋 TODO / nápady do budúcna
- [ ] **HTTPS**: keď GitHub vystaví cert, zapnúť `gh api -X PUT repos/witgi/betino/pages -f https_enforced=true` + otestovať Google login priamo na betnito.com.
- [ ] **„Predikcie" mód (2. záložka, BETEGY-style)** — užívateľ chcel prepínač: value tipy ↔ model-predikcie z formy/štatistík (viac tipov, jasne označené ako „predikcia, nie overená value", aj backtestnuté). Dáta: zadarmo (Elo národné tímy + football-data kluby) alebo platené FootyStats API. **Rozhodnutie zatiaľ POZASTAVENÉ userom.**
- [ ] **Live CLV tracking** — zachytiť záverečnú linku ~5 min pred výkopom (zatiaľ len v backteste).
- [ ] **Poisson model ako „druhý názor"** pri klubových ligách (ratings.json pipeline).
- [ ] Voliteľne ázijský handicap (spreads), ak by user chcel viac trhov.

---

## 13. Ako robiť zmeny / nasadiť
1. Uprav kód v `~/value-bets/`.
2. `git add ... && git commit -m "..."` → `git pull --rebase origin main` → `git push origin main`.
3. Push spustí `site.yml` → web na betnito.com sa prerobí **do ~1 min**.
4. Manuálne spustenie cronu (test compute + Supabase): `gh workflow run site.yml -R witgi/betino`.
5. Lokálny náhľad: `cd ~/value-bets && python3 -m http.server 8765` → http://localhost:8765/web/index.html
   (potrebuje `export ODDS_API_KEY=...` pre live `predict.py`, alebo `--cache data/cache/sample_raw.json`).

---

*Posledná aktualizácia: 2026-06-14. Stav: live na betnito.com, čisté dáta po oprave outlierov, čaká sa na HTTPS cert.*
