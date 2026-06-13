// Nacita data/predictions.json a vykresli value tipy.
// Posuvnik "miera rizika" filtruje kandidatov NAZIVO (bez noveho stahovania).

const DATA_URL = "../data/predictions.json"; // na GitHub Pages uprav podla nasadenia
const STATS_URL = "../data/stats.json";

let DATA = null;
let OFFICIAL = new Set(); // kluce oficialnych tipov (default prahy)

function lerp(a, b, t) { return a + (b - a) * t; }

// Posuvnik 0..100 -> prahy. Vlavo = prisne (bezpecne), vpravo = volne (riskantne).
function thresholdsFor(r) {
  const t = r / 100;
  return {
    minEv: lerp(4.0, 0.5, t),
    minOdds: lerp(1.60, 1.20, t),
    maxOdds: lerp(3.0, 8.0, t),
    maxEv: lerp(12, 60, t),
    minBooks: Math.round(lerp(5, 3, t)),
  };
}

function zoneLabel(r) {
  if (r <= 33) return "Bezpečné";
  if (r <= 66) return "Vyvážené";
  return "Riskantné";
}

function fmtTime(iso) {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("sk-SK", {
      weekday: "short", day: "numeric", month: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch (e) { return iso; }
}

function stars(conf) {
  const n = Math.max(1, Math.min(5, Math.round((conf || 0) * 5)));
  return "★".repeat(n) + "☆".repeat(5 - n);
}

function selectionLabel(p) {
  return p.selection === "Draw" ? "Remíza" : p.selection;
}

function pickKey(p) {
  return `${p.commence}|${p.home}|${p.away}|${p.market}|${p.selection}`;
}

function card(p) {
  const el = document.createElement("article");
  el.className = "card";
  const official = OFFICIAL.has(pickKey(p));
  el.innerHTML = `
    <div class="card-top">
      <span>${p.league || ""}</span>
      <span>${fmtTime(p.commence)}</span>
    </div>
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
    </div>`;
  return el;
}

function sparkline(equity) {
  if (!equity || equity.length < 2) return "";
  const vals = equity.map(e => e.bankroll);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const W = 300, H = 48;
  const pts = vals.map((v, i) => {
    const x = (i / (vals.length - 1)) * W;
    const y = H - ((v - min) / span) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  const col = up ? "var(--accent)" : "#f85149";
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <polyline points="${pts}" fill="none" stroke="${col}" stroke-width="2" /></svg>`;
}

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
  const prof = s.profit_units;
  const cls = prof >= 0 ? "pos" : "neg";
  box.innerHTML = `
    <div class="g-head">📊 Globálne výsledky (keby dávaš všetko podľa mňa)</div>
    <div class="g-hero">
      <div class="g-bank"><span>Virtuálny bank</span>
        <b class="${cls}">${s.virtual_bankroll.toFixed(0)} €</b>
        <small class="${cls}">${prof >= 0 ? "+" : ""}${prof.toFixed(0)} € (${s.roi_pct > 0 ? "+" : ""}${s.roi_pct} % ROI)</small>
      </div>
      ${sparkline(s.equity)}
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

function applyRisk() {
  const r = Number(document.getElementById("risk").value);
  const th = thresholdsFor(r);
  document.getElementById("risk-zone").textContent = zoneLabel(r);
  document.getElementById("risk-warn").classList.toggle("hidden", r <= 66);

  const cands = (DATA.candidates || []).filter(p =>
    p.ev_pct >= th.minEv && p.ev_pct <= th.maxEv &&
    p.best_odds >= th.minOdds && p.best_odds <= th.maxOdds &&
    p.n_books >= th.minBooks
  );

  document.getElementById("risk-info").innerHTML =
    `<b>${cands.length}</b> tip(ov) · EV ≥ ${th.minEv.toFixed(1)} % · ` +
    `kurz ${th.minOdds.toFixed(2)}–${th.maxOdds.toFixed(1)} · min. ${th.minBooks} kancelárií`;

  const main = document.getElementById("picks");
  main.innerHTML = "";
  document.getElementById("empty").classList.toggle("hidden", cands.length > 0);
  cands.forEach(p => main.appendChild(card(p)));
}

async function main() {
  const meta = document.getElementById("meta");
  try {
    const res = await fetch(DATA_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    DATA = await res.json();
    OFFICIAL = new Set((DATA.picks || []).map(pickKey));

    meta.textContent =
      `Aktualizované: ${fmtTime(DATA.generated_at)} · bank ${DATA.bankroll} € · ` +
      `${(DATA.candidates || []).length} kandidátov z ${DATA.n_events_considered} zápasov`;

    try {
      const sres = await fetch(STATS_URL, { cache: "no-store" });
      if (sres.ok) renderGlobal(await sres.json());
    } catch (e) { /* stats.json este nemusi existovat */ }
    document.getElementById("risk").addEventListener("input", applyRisk);
    applyRisk();
  } catch (e) {
    meta.textContent = "Nepodarilo sa načítať dáta (" + e.message +
      "). Spusti cez lokálny server alebo skontroluj predictions.json.";
  }
}

main();
