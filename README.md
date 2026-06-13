# ⚽ value-bets

Jednoduchý nástroj, ktorý každý deň sám nájde **value tipy** na zajtrajšie zápasy a ukáže
ich na webovej stránke (aj na mobile). Začína na MS vo futbale, ale po zmene jedného riadku
v configu funguje na ľubovoľnú ligu či šport.

> **Čo je value betting (a čo NIE):** dostaneš vždy *jeden konkrétny tip — tento zápas,
> tento výsledok, podaj v tejto kancelárii*, pretože ponúkaný kurz podceňuje reálnu
> pravdepodobnosť. **Nie je to arbitráž** (žiadne „1 v jednej a X2 v druhej kancelárii").

## Ako to funguje (stručne)
1. **Stiahne kurzy** z viacerých kancelárií (The Odds API).
2. **Ostrá linka (Pinnacle) → odhad pravdivej pravdepodobnosti** odstránením marže (Shin metóda).
3. (Voliteľne) **Poissonov model** z foriem/gólov ako kontrola — pri MS len doplnok.
4. **Value:** porovná pravdivú pravdepodobnosť s najlepším dostupným kurzom → Expected Value.
5. **Veľkosť stávky:** frakčný Kelly (¼), strop 2–3 % banku.
6. **Filtre:** EV v rozumnom pásme, kurz 1.5–3.5, min. počet kancelárií.

## Štruktúra
```
config.json          # JEDINÉ miesto na ladenie (šport, prahy, bankroll)
engine/  fetch · devig · model · blend · predict · reconcile
backtest/ backtest.py
data/    predictions.json (web) · history.jsonl (sledovanie ROI/CLV)
web/     index.html · app.js · style.css
run_daily.sh         # denný beh pre cron/routine
```

## Spustenie (lokálne)
```bash
# 1) API kľúč (zdarma: the-odds-api.com)
export ODDS_API_KEY=tvoj_kluc

# 2) vygeneruj tipy na zajtra
python3 engine/predict.py

# 3) pozri web
python3 -m http.server 8765
# otvor http://localhost:8765/web/index.html
```
Offline test bez kľúča: `python3 engine/predict.py --cache data/cache/sample_raw.json`

## Backtest (over si výhodu skôr, než staviaš)
```bash
python3 backtest/backtest.py E0 SP1 D1 I1 F1 --seasons 2122 2223 2324
```
Vypíše ROI/yield, počet stávok, max drawdown a **CLV beat %** (>50 % = dobré znamenie).
Dáta zadarmo z football-data.co.uk. **Ak yield ≤ 0 → nenasadzovať, doladiť prahy v configu.**

## Prepnutie na inú ligu / šport
V `config.json` zmeň `sports`, napr.:
```json
"sports": ["soccer_epl"]              // anglická liga
"sports": ["basketball_nba"]         // NBA
"sports": ["icehockey_nhl"]          // NHL
```
Devig + EV + Kelly sú univerzálne; Poissonov model sa pre nefutbalové športy automaticky
preskočí (použije sa čistý trh). Zoznam kľúčov: `_sports_examples` v configu.

## Denná automatika
`run_daily.sh` spustí vyhodnotenie → nové predikcie → commit/push. Volá ho cloudový agent
(routine) alebo lokálny cron. Web (GitHub Pages) sa po pushi sám obnoví.

## Dôležité (úprimne)
- Výhoda je malá a prejaví sa až cez **stovky** stávok; krátkodobo môžeš prehrávať.
- Soft kancelárie **limitujú/rušia** dlhodobo úspešných hráčov.
- Backtest je historický a in-sample — realita býva skromnejšia.
- Stávkuj len peniaze, ktoré si môžeš dovoliť stratiť. 18+.
