// Nacita data/predictions.json a vykresli karty s value tipmi.
// Ziadne zavislosti, ciste vanilla JS.

const DATA_URL = "../data/predictions.json"; // na GitHub Pages uprav podla nasadenia

function fmtTime(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleString("sk-SK", {
      weekday: "short", day: "numeric", month: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch (e) { return iso; }
}

function stars(conf) {
  const n = Math.max(1, Math.min(5, Math.round((conf || 0) * 5)));
  return "★".repeat(n) + "☆".repeat(5 - n);
}

function selectionLabel(p) {
  // h2h: nazov timu alebo "Draw"; totals: "Over 2.5" atd. uz pride hotove v 'selection'
  if (p.selection === "Draw") return "Remíza";
  return p.selection;
}

function card(p) {
  const el = document.createElement("article");
  el.className = "card";
  el.innerHTML = `
    <div class="card-top">
      <span>${p.league || ""}</span>
      <span>${fmtTime(p.commence)}</span>
    </div>
    <div class="match"><b>${p.home}</b><span class="vs">vs</span><b>${p.away}</b></div>
    <div class="pick">
      <div class="sel">${selectionLabel(p)}
        <small>podaj v: ${p.bookmaker}</small>
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

function renderPerf(perf) {
  const box = document.getElementById("perf");
  if (!perf) { box.classList.add("hidden"); return; }
  const roiCls = perf.roi_pct >= 0 ? "pos" : "neg";
  const parts = [
    `<div class="stat"><b class="${roiCls}">${perf.roi_pct > 0 ? "+" : ""}${perf.roi_pct} %</b><span>ROI</span></div>`,
    `<div class="stat"><b>${perf.win_rate_pct} %</b><span>úspešnosť</span></div>`,
    `<div class="stat"><b>${perf.settled_bets}</b><span>tipov</span></div>`,
  ];
  if (perf.clv_beat_pct != null) {
    parts.push(`<div class="stat"><b>${perf.clv_beat_pct} %</b><span>CLV beat</span></div>`);
  }
  box.innerHTML = parts.join("");
  box.classList.remove("hidden");
}

async function main() {
  const meta = document.getElementById("meta");
  try {
    const res = await fetch(DATA_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();

    meta.textContent =
      `Aktualizované: ${fmtTime(data.generated_at)} · bank ${data.bankroll} € · ` +
      `${data.n_picks} tip(ov) z ${data.n_events_considered} zápasov`;

    renderPerf(data.performance);

    const main = document.getElementById("picks");
    const picks = data.picks || [];
    if (picks.length === 0) {
      document.getElementById("empty").classList.remove("hidden");
    } else {
      picks.forEach((p) => main.appendChild(card(p)));
    }
  } catch (e) {
    meta.textContent = "Nepodarilo sa načítať dáta (" + e.message + "). Spusti cez lokálny server alebo skontroluj predictions.json.";
  }
}

main();
