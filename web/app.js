// Value tipy — front-end.
// Funkcie: globalne + osobne sledovanie, posuvnik rizika, Google login (Supabase),
// oznacovanie tipov "podane".

// Absolutne od korena servera -> funguje lokalne (/web/index.html) aj nasadene (root domeny).
const DATA_URL = "/data/predictions.json";
const STATS_URL = "/data/stats.json";
const SIGNALS_URL = "/data/signals.json";   // jednotný výstup (value + prediction + arb)

// --- Supabase klient ---
const sb = window.supabase.createClient(
  window.VB_CONFIG.SUPABASE_URL, window.VB_CONFIG.SUPABASE_KEY
);

// --- stav ---
let DATA = null;
let STATS = null;
let PREDICTIONS = null;   // prediction-signály zo signals.json
let ARBS = null;          // arb-signály zo signals.json
let OFFICIAL = new Set();     // kluce oficialnych tipov (default prahy)
let PLACED = new Map();       // tip_key -> riadok user_bets (co som oznacil podane)
let TIPRES = new Map();       // tip_key -> vysledok (tip_results) na osobny P/L
let USER = null;
let ARB_BOOKS = [];           // všetky kancelárie vyskytujúce sa v arboch
let ARB_BOOK_SEL = null;      // Set vybraných kancelárií (null = zatiaľ neurčené → všetky)

// historická presnosť predikčného modelu (z backtest/backtest_predict.py, EPL 18/19)
const PRED_BACKTEST = { matches: 360, h2h: 56, ou25: 54, btts: 50 };

// ---------- pomocne ----------
function lerp(a, b, t) { return a + (b - a) * t; }
function thresholdsFor(r) {
  const t = r / 100;
  return {
    minEv: lerp(4.0, 0.5, t), minOdds: lerp(1.60, 1.20, t),
    maxOdds: lerp(3.0, 8.0, t), maxEv: lerp(12, 60, t), minBooks: Math.round(lerp(5, 3, t)),
  };
}
function zoneLabel(r) { return r <= 33 ? "Bezpečné" : r <= 66 ? "Vyvážené" : "Riskantné"; }
function fmtTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("sk-SK", {
      weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch (e) { return iso; }
}
function stars(c) { const n = Math.max(1, Math.min(5, Math.round((c || 0) * 5))); return "★".repeat(n) + "☆".repeat(5 - n); }
function selectionLabel(p) { return p.selection === "Draw" ? "Remíza" : p.selection; }
function pickKey(p) { return `${p.commence}|${p.home}|${p.away}|${p.market}|${p.selection}`; }

// ---- zoradenie podľa dátumu výkopu (najbližšie hore) ----
function sigCommence(s) { return (s.event && s.event.commence) || s.commence || ""; }
function byDate(a, b) {
  const ta = Date.parse(sigCommence(a)) || Infinity, tb = Date.parse(sigCommence(b)) || Infinity;
  return ta - tb;
}
// ---- arb: jednotný prístup k nohám (OddsAPI dáva stake_split, BetBurger legs) ----
function arbLegs(s) { return (s.stake_split && s.stake_split.length) ? s.stake_split : (s.legs || []); }
function arbBooksOf(s) { return arbLegs(s).map(l => l.book).filter(Boolean); }
// ---- výber kancelárií (localStorage, funguje aj bez prihlásenia) ----
function loadArbBookSel() {
  try { const j = JSON.parse(localStorage.getItem("arbBooks")); if (Array.isArray(j)) return new Set(j); } catch (e) {}
  return null;
}
function saveArbBookSel() {
  if (ARB_BOOK_SEL) localStorage.setItem("arbBooks", JSON.stringify([...ARB_BOOK_SEL]));
}

function sparkline(equity) {
  if (!equity || equity.length < 2) return "";
  const vals = equity.map(e => e.bankroll);
  const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
  const W = 300, H = 48;
  const pts = vals.map((v, i) => `${((i / (vals.length - 1)) * W).toFixed(1)},${(H - ((v - min) / span) * H).toFixed(1)}`).join(" ");
  const col = vals[vals.length - 1] >= vals[0] ? "var(--accent)" : "#f85149";
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="2" /></svg>`;
}

// ---------- AUTH ----------
function renderAuth() {
  const box = document.getElementById("auth");
  if (USER) {
    const name = USER.email || USER.user_metadata?.name || "účet";
    box.innerHTML = `<span class="who">${name}</span><button id="logout" class="btn-sm">Odhlásiť</button>`;
    document.getElementById("logout").onclick = async () => { await sb.auth.signOut(); };
  } else {
    box.innerHTML = `<button id="login" class="btn-sm btn-g">Prihlásiť cez Google</button>`;
    document.getElementById("login").onclick = async () => {
      const { error } = await sb.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: window.location.href },
      });
      if (error) alert("Prihlásenie zatiaľ nefunguje (treba dokončiť nastavenie Google OAuth): " + error.message);
    };
  }
}

async function loadUserBets() {
  PLACED = new Map();
  if (!USER) return;
  const { data, error } = await sb.from("user_bets").select("*");
  if (!error && data) data.forEach(r => PLACED.set(r.tip_key, r));
}

async function loadTipResults() {
  TIPRES = new Map();
  const { data, error } = await sb.from("tip_results").select("*");
  if (!error && data) data.forEach(r => TIPRES.set(r.tip_key, r));
}

async function togglePlaced(p, btn) {
  if (!USER) { document.getElementById("login")?.click(); return; }
  const key = pickKey(p);
  btn.disabled = true;
  if (PLACED.has(key)) {
    const { error } = await sb.from("user_bets").delete().eq("tip_key", key);
    if (!error) PLACED.delete(key);
  } else {
    const row = {
      user_id: USER.id, tip_key: key, league: p.league, home: p.home, away: p.away,
      commence: p.commence, market: p.market, selection: p.selection,
      best_odds: p.best_odds, bookmaker: p.bookmaker, stake: p.stake_amount,
    };
    const { error } = await sb.from("user_bets").upsert(row, { onConflict: "user_id,tip_key" });
    if (!error) PLACED.set(key, row);
    else alert("Nepodarilo sa uložiť: " + error.message);
  }
  btn.disabled = false;
  applyRisk();
  renderPersonal();
}

// ---------- GLOBALNY PANEL ----------
function renderGlobal(s) {
  const box = document.getElementById("global");
  if (!s) { box.innerHTML = ""; return; }
  if (!s.settled) {
    box.innerHTML = `<div class="g-head">📊 Globálne výsledky (všetky moje tipy)</div>
      <p class="g-empty">Začíname zbierať výsledky. Tu uvidíš, ako by si dopadol, keby dávaš
      <b>všetko</b> podľa mňa — celkový zisk/strata, úspešnosť a vývoj banku.
      ${s.pending ? `<br>Práve čaká na vyhodnotenie: <b>${s.pending}</b> tip(ov).` : ""}</p>`;
    return;
  }
  const prof = s.profit_units, cls = prof >= 0 ? "pos" : "neg";
  const bankGrow = (s.virtual_bankroll / s.start_bankroll - 1) * 100;
  box.innerHTML = `
    <div class="g-head">📊 Globálne výsledky (keby dávaš všetko podľa mňa)</div>
    <div class="g-hero">
      <div class="g-bank"><span>Virtuálny bank</span>
        <b class="${cls}">${s.virtual_bankroll.toFixed(0)} €</b>
        <small class="${cls}">${prof >= 0 ? "+" : ""}${prof.toFixed(0)} € · bank ${bankGrow >= 0 ? "+" : ""}${bankGrow.toFixed(1)} %</small>
      </div>${sparkline(s.equity)}
    </div>
    <div class="g-stats">
      <div><b>${s.settled}</b><span>tipov</span></div>
      <div><b>${s.win_rate_pct}%</b><span>úspech</span></div>
      <div><b>${s.wins}-${s.losses}${s.pushes ? "-" + s.pushes : ""}</b><span>V-P${s.pushes ? "-R" : ""}</span></div>
      <div><b class="${s.roi_pct >= 0 ? "pos" : "neg"}">${s.roi_pct > 0 ? "+" : ""}${s.roi_pct}%</b><span>ROI z vkladov</span></div>
      ${s.clv_beat_pct != null ? `<div><b>${s.clv_beat_pct}%</b><span>CLV beat</span></div>` : ""}
      ${s.pending ? `<div><b>${s.pending}</b><span>čaká</span></div>` : ""}
    </div>
    <p class="g-note">Štart banku ${s.start_bankroll} € · vklady podľa odporúčaného Kelly.
    <br><b>ROI</b> = zisk delený tým, čo si vsadil (nie bankom). Bank rastie pomalšie, lebo stavíš
    len malú časť (Kelly). Dlhodobý reálny cieľ je ~4–6 % ROI — vyššie čísla na málo tipoch sú výkyv.</p>`;
}

// ---------- OSOBNY PANEL ----------
function renderPersonal() {
  const box = document.getElementById("personal");
  if (!USER) {
    box.classList.remove("hidden");
    box.innerHTML = `<div class="p-card"><b>👤 Tvoje výsledky</b>
      <p>Prihlás sa cez Google a označuj tipy, ktoré si reálne podal — appka ti spočíta
      tvoju vlastnú úspešnosť a porovná ju s tým, ako by si dopadol, keby dávaš všetko.</p></div>`;
    return;
  }
  box.classList.remove("hidden");

  // osobne P/L z podanych + vysledkov
  let staked = 0, profit = 0, settled = 0, wins = 0, losses = 0, pending = 0;
  for (const [key, bet] of PLACED) {
    const res = TIPRES.get(key);
    if (!res || !["win", "loss", "push"].includes(res.result)) { pending++; continue; }
    const stake = Number(bet.stake) || 0;
    const odds = Number(bet.best_odds) || 1;
    staked += stake; settled++;
    if (res.result === "win") { profit += stake * (odds - 1); wins++; }
    else if (res.result === "loss") { profit -= stake; losses++; }
  }
  const roi = staked > 0 ? (profit / staked * 100) : null;
  const placedCount = PLACED.size;
  const allProfit = STATS ? STATS.profit_units : null;

  if (placedCount === 0) {
    box.innerHTML = `<div class="p-card"><b>👤 Tvoje výsledky</b>
      <p>Zatiaľ si neoznačil žiadny tip ako podaný. Klikni <b>„Podať"</b> pri tipe a sleduj
      svoju vlastnú úspešnosť.</p></div>`;
    return;
  }
  const cls = profit >= 0 ? "pos" : "neg";
  box.innerHTML = `<div class="p-card">
    <div class="p-head">👤 Tvoje výsledky (čo si podal)</div>
    <div class="p-row">
      <div class="p-big ${cls}">${profit >= 0 ? "+" : ""}${profit.toFixed(0)} €
        <small>${roi != null ? (roi > 0 ? "+" : "") + roi.toFixed(1) + " % ROI" : "—"}</small></div>
      <div class="p-mini">
        <div><b>${placedCount}</b><span>podaných</span></div>
        <div><b>${settled}</b><span>hotových</span></div>
        <div><b>${wins}-${losses}</b><span>V-P</span></div>
        ${pending ? `<div><b>${pending}</b><span>čaká</span></div>` : ""}
      </div>
    </div>
    ${allProfit != null ? `<p class="p-cmp">Keby si dal <b>všetko</b> podľa mňa: <b class="${allProfit >= 0 ? "pos" : "neg"}">${allProfit >= 0 ? "+" : ""}${allProfit.toFixed(0)} €</b></p>` : ""}
  </div>`;
}

// ---------- KARTY ----------
function card(p) {
  const el = document.createElement("article");
  el.className = "card";
  const key = pickKey(p);
  const official = OFFICIAL.has(key);
  const placed = PLACED.has(key);
  el.innerHTML = `
    <div class="card-top"><span>${p.league || ""}</span><span>${fmtTime(p.commence)}</span></div>
    <div class="match"><b>${p.home}</b><span class="vs">vs</span><b>${p.away}</b></div>
    <div class="pick">
      <div class="sel">${selectionLabel(p)}
        <small>podaj v: ${p.bookmaker}${official ? ' · <span class="badge">odporúčané</span>' : ""}</small>
      </div>
      <div class="odds"><b>${p.best_odds.toFixed(2)}</b><small>kurz</small></div>
    </div>
    <div class="grid">
      <div class="item"><span>Hodnota (EV)</span><b class="ev-pos">+${p.ev_pct.toFixed(1)} %</b></div>
      <div class="item"><span>Férový kurz</span><b>${p.fair_odds ? p.fair_odds.toFixed(2) : "–"}</b></div>
      <div class="item"><span>Vklad</span><b>${p.stake_pct.toFixed(1)} % · ${p.stake_amount.toFixed(0)} €</b></div>
      <div class="item"><span>Istota</span><b class="stars">${stars(p.confidence)}</b></div>
    </div>
    <button class="place ${placed ? "placed" : ""}">${placed ? "✓ Podané" : "Podať"}</button>`;
  el.querySelector(".place").onclick = (e) => togglePlaced(p, e.target);
  return el;
}

function applyRisk() {
  const r = Number(document.getElementById("risk").value);
  const th = thresholdsFor(r);
  document.getElementById("risk-zone").textContent = zoneLabel(r);
  document.getElementById("risk-warn").classList.toggle("hidden", r <= 66);
  const cands = (DATA.candidates || []).filter(p =>
    p.ev_pct >= th.minEv && p.ev_pct <= th.maxEv &&
    p.best_odds >= th.minOdds && p.best_odds <= th.maxOdds && p.n_books >= th.minBooks)
    .sort(byDate);
  document.getElementById("risk-info").innerHTML =
    `<b>${cands.length}</b> tip(ov) · EV ≥ ${th.minEv.toFixed(1)} % · kurz ${th.minOdds.toFixed(2)}–${th.maxOdds.toFixed(1)} · min. ${th.minBooks} kancelárií`;
  const main = document.getElementById("picks");
  main.innerHTML = "";
  document.getElementById("empty").classList.toggle("hidden", cands.length > 0);
  cands.forEach(p => main.appendChild(card(p)));
}

// ---------- TABY ----------
function switchTab(tab) {
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  document.getElementById("tab-value").classList.toggle("hidden", tab !== "value");
  document.getElementById("tab-prediction").classList.toggle("hidden", tab !== "prediction");
  document.getElementById("tab-arb").classList.toggle("hidden", tab !== "arb");
  if (tab === "prediction") renderPredictions();
  if (tab === "arb") renderArbs();
}

// ---------- PREDIKCIE ----------
function pct(x) { return x == null ? "–" : Math.round(x * 100) + " %"; }

function predCard(s) {
  const ev = s.event || {};
  const x = s.xg || {};
  const p = s.probs_1x2 || {};
  const top = (s.top_scores && s.top_scores[0]) ? s.top_scores[0] : null;
  const evVal = s.model_ev_pct;
  const valueBadge = (evVal != null && evVal > 0)
    ? `<span class="badge badge-val">možná value +${evVal.toFixed(1)} %</span>` : "";
  const pickName = (s.legs && s.legs[0]) ? (s.legs[0].selection === "Draw" ? "Remíza" : s.legs[0].selection) : "?";
  const pickOdds = (s.legs && s.legs[0] && s.legs[0].odds) ? s.legs[0].odds.toFixed(2) : "–";

  const el = document.createElement("article");
  el.className = "card pred-card";
  el.innerHTML = `
    <div class="card-top"><span>${s.league || ev_sport(s)}</span><span>${fmtTime(ev.commence)}</span></div>
    <div class="match"><b>${ev.home}</b><span class="vs">vs</span><b>${ev.away}</b></div>
    <div class="pick">
      <div class="sel">Tip modelu: ${pickName} ${valueBadge}
        <small>istota predikcie ${pct(s.edge && s.edge.value)} · kurz trhu ${pickOdds}</small>
      </div>
      <div class="odds"><b>${pct(s.edge && s.edge.value)}</b><small>pravdepod.</small></div>
    </div>
    <div class="pred-bars">
      ${bar("1", p.home)} ${bar("X", p.draw)} ${bar("2", p.away)}
    </div>
    <div class="grid">
      <div class="item"><span>Očak. góly (xG)</span><b>${x.home ?? "–"} : ${x.away ?? "–"}</b></div>
      <div class="item"><span>Nad 2.5 gólu</span><b>${pct(s.ou25 && s.ou25.over)}</b></div>
      <div class="item"><span>Oba skórujú</span><b>${pct(s.btts && s.btts.yes)}</b></div>
      <div class="item"><span>Najpravdep. skóre</span><b>${top ? top[0] : "–"}</b></div>
    </div>
    <p class="pred-foot">🔮 predikcia (neoverená value)${s.fs_potential && s.fs_potential.o25 != null ? ` · FootyStats nad2.5: ${s.fs_potential.o25}%` : ""}</p>`;
  return el;
}
function ev_sport(s) { return s.sport || ""; }
function bar(lbl, v) {
  const h = Math.round((v || 0) * 100);
  return `<div class="pbar"><div class="pbar-fill" style="height:${h}%"></div><span class="pbar-lbl">${lbl}</span><span class="pbar-val">${h}%</span></div>`;
}

function renderPredPerf() {
  const box = document.getElementById("pred-perf");
  if (!box) return;
  const b = PRED_BACKTEST;
  box.innerHTML = `
    <div class="g-head">📈 Úspešnosť predikcií (historický backtest)</div>
    <div class="g-stats">
      <div><b>${b.h2h}%</b><span>1 / X / 2</span></div>
      <div><b>${b.ou25}%</b><span>nad/pod 2.5</span></div>
      <div><b>${b.btts}%</b><span>oba skórujú</span></div>
      <div><b>${b.matches}</b><span>zápasov</span></div>
    </div>
    <p class="g-note">Koľko % predikcií trafilo výsledok v backteste (EPL 18/19). Ostrý trh býva presnejší —
    ber ako orientáciu, nie dokázanú výhodu. Živé výsledky sa budú zbierať postupne.</p>`;
}

function renderPredictions() {
  renderPredPerf();
  const main = document.getElementById("predictions");
  const empty = document.getElementById("pred-empty");
  if (!main) return;
  main.innerHTML = "";
  const list = PREDICTIONS || [];
  empty.classList.toggle("hidden", list.length > 0);
  list.forEach(s => main.appendChild(predCard(s)));
}

// ---------- ARBITRÁŽ ----------
function arbCard(s) {
  const ev = s.event || {};
  const legs = arbLegs(s);
  const profit = s.edge ? s.edge.value : 0;
  const totalStake = s.total_stake_ref || 100;
  // ak chýba rozloženie vkladu (BetBurger len kurzy) — dopočítaj z kurzov (stake ∝ 1/kurz)
  let stakes = legs.map(l => l.stake);
  if (!legs.some(l => l.stake != null)) {
    const inv = legs.map(l => (l.odds && l.odds > 1) ? 1 / l.odds : 0);
    const sum = inv.reduce((a, b) => a + b, 0) || 1;
    stakes = inv.map(x => totalStake * x / sum);
  }
  const rows = legs.map((l, i) => {
    const sel = l.selection === "Draw" ? "Remíza" : l.selection;
    const st = stakes[i];
    return `<tr><td>${sel}</td><td>${l.book || "?"}</td><td class="r">${l.odds ? l.odds.toFixed(2) : "–"}</td><td class="r"><b>${st != null ? st.toFixed(2) : "–"} €</b></td></tr>`;
  }).join("");
  const guaranteedReturn = totalStake * (1 + profit / 100);

  const el = document.createElement("article");
  el.className = "card arb-card";
  el.innerHTML = `
    <div class="card-top"><span>${s.league || s.sport || ""}</span><span>${fmtTime(ev.commence)}</span></div>
    <div class="match"><b>${ev.home}</b><span class="vs">vs</span><b>${ev.away}</b></div>
    <div class="pick">
      <div class="sel">Garantovaný zisk
        <small>vklad ${totalStake.toFixed(0)} € → späť ${guaranteedReturn.toFixed(2)} €</small>
      </div>
      <div class="odds"><b>+${profit.toFixed(2)} %</b><small>istý výnos</small></div>
    </div>
    <table class="arb-table">
      <thead><tr><th>Staviť na</th><th>Kancelária</th><th class="r">Kurz</th><th class="r">Vklad</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="pred-foot">⚖️ surebet · staviť VŠETKY riadky naraz · kurzy sa rýchlo menia</p>`;
  return el;
}

function renderArbFilter() {
  const box = document.getElementById("arb-filter");
  if (!box) return;
  if (!ARB_BOOKS.length) { box.classList.add("hidden"); return; }
  box.classList.remove("hidden");
  const sel = ARB_BOOK_SEL;   // null = všetky zapnuté
  const chips = ARB_BOOKS.map(b => {
    const on = !sel || sel.has(b);
    return `<button class="bookchip ${on ? "on" : ""}" data-book="${b}">${on ? "✓ " : ""}${b}</button>`;
  }).join("");
  box.innerHTML = `<div class="bf-head">Moje kancelárie
      <small>klikni len tie, kde máš účet — ukážem len arby medzi nimi</small></div>
    <div class="bf-chips">${chips}</div>
    <div class="bf-actions"><button id="bf-all" class="btn-sm">Označiť všetky</button></div>`;
  box.querySelectorAll(".bookchip").forEach(btn => btn.onclick = () => toggleBook(btn.dataset.book));
  const allBtn = document.getElementById("bf-all");
  if (allBtn) allBtn.onclick = () => { ARB_BOOK_SEL = null; localStorage.removeItem("arbBooks"); renderArbs(); };
}

function toggleBook(book) {
  if (!ARB_BOOK_SEL) ARB_BOOK_SEL = new Set(ARB_BOOKS);   // začni od „všetky zapnuté"
  if (ARB_BOOK_SEL.has(book)) ARB_BOOK_SEL.delete(book); else ARB_BOOK_SEL.add(book);
  saveArbBookSel();
  renderArbs();
}

function renderArbs() {
  renderArbFilter();
  const main = document.getElementById("arbs");
  const empty = document.getElementById("arb-empty");
  if (!main) return;
  main.innerHTML = "";
  let list = (ARBS || []).slice();
  // filter: arb sa zobrazí len ak VŠETKY jeho nohy sú v mojich vybraných knihách
  if (ARB_BOOK_SEL) list = list.filter(s => arbBooksOf(s).every(b => ARB_BOOK_SEL.has(b)));
  empty.classList.toggle("hidden", list.length > 0);
  if (list.length === 0 && (ARBS || []).length > 0) {
    empty.textContent = "Pri vybraných kanceláriách teraz niet arbu. Uprav výber kníh alebo klikni „Označiť všetky\".";
  } else {
    empty.textContent = "Práve teraz nie je dostupný žiadny pre-match surebet. Príležitosti sú vzácne a krátke — skús neskôr.";
  }
  list.forEach(s => main.appendChild(arbCard(s)));
}

async function loadSignals() {
  try {
    const res = await fetch(SIGNALS_URL, { cache: "no-store" });
    if (!res.ok) return;
    const sig = await res.json();
    PREDICTIONS = (sig.signals || []).filter(s => s.type === "prediction").sort(byDate);
    ARBS = (sig.signals || []).filter(s => s.type === "arb").sort(byDate);
    // zoznam všetkých kancelárií v arboch + načítaj uložený výber
    const books = new Set();
    ARBS.forEach(s => arbBooksOf(s).forEach(b => books.add(b)));
    ARB_BOOKS = [...books].sort();
    ARB_BOOK_SEL = loadArbBookSel();   // null = všetky zobrazené
  } catch (e) { PREDICTIONS = null; ARBS = null; }
}

// ---------- INIT ----------
async function refreshUserState() {
  const { data } = await sb.auth.getSession();
  USER = data?.session?.user || null;
  await Promise.all([loadUserBets(), loadTipResults()]);
  renderAuth();
  renderPersonal();
  if (DATA) applyRisk();
}

async function main() {
  const meta = document.getElementById("meta");
  try {
    const res = await fetch(DATA_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    DATA = await res.json();
    OFFICIAL = new Set((DATA.picks || []).map(pickKey));
    meta.textContent = `Aktualizované: ${fmtTime(DATA.generated_at)} · bank ${DATA.bankroll} € · ${(DATA.candidates || []).length} kandidátov z ${DATA.n_events_considered} zápasov`;

    try { const sres = await fetch(STATS_URL, { cache: "no-store" }); if (sres.ok) STATS = await sres.json(); } catch (e) {}
    renderGlobal(STATS);

    await loadSignals();
    document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => switchTab(b.dataset.tab)));

    document.getElementById("risk").addEventListener("input", applyRisk);

    await refreshUserState();
    sb.auth.onAuthStateChange(() => { refreshUserState(); });
  } catch (e) {
    meta.textContent = "Nepodarilo sa načítať dáta (" + e.message + "). Spusti cez lokálny server alebo skontroluj predictions.json.";
  }
}

main();
