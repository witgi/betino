# Setup — spustenie online s prihlasovaním (tvoj checklist)

Appka beží lokálne. Aby bola **online na tvojej doméne, s Google prihlásením a osobným
sledovaním**, treba spraviť kroky nižšie. Účty a nákup domény musíš spraviť ty (ja ich za
teba zakladať/platiť nemôžem); **všetko ostatné spravím ja.**

Pošli mi nakoniec: **Supabase Project URL + anon key** a potvrď, že service key je v GitHub
secrets a doména kúpená. Potom dorobím Google login + označovanie tipov + osobné štatistiky
a nasadíme.

---

## 1) Supabase (prihlásenie + databáza) — zdarma
1. Choď na [supabase.com](https://supabase.com) → **Sign up** (cez GitHub je to najrýchlejšie).
2. **New project** → názov `value-bets`, zvoľ región **EU (Frankfurt)**, vymysli DB heslo.
3. Po vytvorení choď do **Project Settings → API** a skopíruj si:
   - **Project URL** (napr. `https://xxxx.supabase.co`)
   - **anon public** key  → *toto mi pošleš (je bezpečné, je verejné)*
   - **service_role** key → *TOTO NIKOMU, dáš ho len do GitHub secrets (krok 4)*
4. Choď do **SQL Editor → New query**, vlož obsah súboru `db/schema.sql` z repa a daj **Run**.

## 2) Google prihlásenie (OAuth)
1. [console.cloud.google.com](https://console.cloud.google.com) → vytvor projekt (napr. `value-bets`).
2. **APIs & Services → OAuth consent screen** → External → vyplň názov a svoj e-mail →
   v *Test users* pridaj svoj Gmail (alebo neskôr publikuj).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID** → typ **Web application**.
   - Do **Authorized redirect URIs** vlož:
     `https://<tvoj-projekt>.supabase.co/auth/v1/callback`
   - Vznikne **Client ID** + **Client secret**.
4. Späť v **Supabase → Authentication → Providers → Google** → zapni a vlož Client ID + secret.

## 3) Doména (websupport)
1. Kúp doménu na [websupport.sk](https://www.websupport.sk) (napr. `mojetipy.sk`).
2. DNS nastavenie spravíme spolu (CNAME/A záznam na GitHub Pages) — len mi daj vedieť názov.

## 4) GitHub (hosting + denný cron) — to spravím ja, ty len potvrdíš prístup
- Spustím repo na tvojom GitHub a do **Settings → Secrets and variables → Actions** pridám
  (alebo ti poviem presne čo vložiť, ak chceš secrets zadať sám):
  - `ODDS_API_KEY` — kľúč z the-odds-api.com
  - `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` — z kroku 1
- Zapnem **GitHub Actions** (denný výpočet) a **GitHub Pages** (hosting + tvoja doména).
- Aby som vedel pushovať z tohto počítača, spusti raz v termináli:
  ```bash
  brew install gh && gh auth login
  ```

---

## Čo už je hotové (bez účtov)
- Engine, web, **posuvník rizika**, backtest, denný `run_daily.sh`.
- **Globálne sledovanie + virtuálny bankroll** („ako by si dopadol, keby dávaš všetko") —
  napĺňa sa automaticky, ako sa zápasy dohrávajú.

## Čo dorobím po tvojich kľúčoch
- Google prihlásenie v appke.
- Tlačidlo „označiť ako podané" pri každom tipe.
- Osobné štatistiky (tvoje +/−) a porovnanie **podané vs. nepodané**.
