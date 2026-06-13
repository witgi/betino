// Value tipy — front-end.
// Funkcie: globalne + osobne sledovanie, posuvnik rizika, Google login (Supabase),
// oznacovanie tipov "podane".

// Absolutne od korena servera -> funguje lokalne (/web/index.html) aj nasadene (root domeny).
const DATA_URL = "/data/predictions.json";
const STATS_URL = "/data/stats.json";

// --- Supabase klient ---
const sb = window.supabase.createClient(
  window.VB_CONFIG.SUPABASE_URL, window.VB_CONFIG.SUPABASE_KEY
);

// --- stav ---
let DATA = null;
let STATS = null;
let OFFICIAL = new Set();     // kluce oficialnych tipov (default prahy)
let PLACED = new Map();       // tip_key -> riadok user_bets (co som oznacil podane)
let TIPRES = new Map();       // tip_key -> vysledok (tip_results) na osobny P/L
let USER = null;

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
  box.innerHTML = `
    <div class="g-head">📊 Globálne výsledky (keby dávaš všetko podľa mňa)</div>
    <div class="g-hero">
      <div class="g-bank"><span>Virtuálny bank</span>
        <b class="${cls}">${s.virtual_bankroll.toFixed(0)} €</b>
        <small class="${cls}">${prof >= 0 ? "+" : ""}${prof.toFixed(0)} € (${s.roi_pct > 0 ? "+" : ""}${s.roi_pct} % ROI)</small>
      </div>${sparkline(s.equity)}
    </div>
    <div class="g-stats">
      <div><b>${s.settled}</b><span>tipov</span></div>
      <div><b>${s.win_rate_pct}%</b><span>úspech</span></div>
      <div><b>${s.wins}-${s.losses}${s.pushes ? "-" + s.pushes : ""}</b><span>V-P${s.pushes ? "-R" : ""}</span></div>
      ${s.clv_beat_pct != null ? `<div><b>${s.clv_beat_pct}%</b><span>CLV beat</span></div>` : ""}
      ${s.pending ? `<div><b>${s.pending}</b><span>čaká</span></div>` : ""}
    </div>
    <p class="g-note">Štart banku ${s.start_bankroll} € · vklady podľa odporúčaného Kelly.</p>`;
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
    p.best_odds >= th.minOdds && p.best_odds <= th.maxOdds && p.n_books >= th.minBooks);
  document.getElementById("risk-info").innerHTML =
    `<b>${cands.length}</b> tip(ov) · EV ≥ ${th.minEv.toFixed(1)} % · kurz ${th.minOdds.toFixed(2)}–${th.maxOdds.toFixed(1)} · min. ${th.minBooks} kancelárií`;
  const main = document.getElementById("picks");
  main.innerHTML = "";
  document.getElementById("empty").classList.toggle("hidden", cands.length > 0);
  cands.forEach(p => main.appendChild(card(p)));
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

    document.getElementById("risk").addEventListener("input", applyRisk);

    await refreshUserState();
    sb.auth.onAuthStateChange(() => { refreshUserState(); });
  } catch (e) {
    meta.textContent = "Nepodarilo sa načítať dáta (" + e.message + "). Spusti cez lokálny server alebo skontroluj predictions.json.";
  }
}

main();
