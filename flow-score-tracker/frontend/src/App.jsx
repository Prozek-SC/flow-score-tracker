import { useState, useEffect, useMemo } from "react";
import "./cockpit.css";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:5000";

// ---- thermal scale: capital as heat (color encodes the score) ----
const lerp = (a, b, t) => a + (b - a) * t;
const hex = (c) => {
  c = c.replace("#", "");
  return [parseInt(c.slice(0, 2), 16), parseInt(c.slice(2, 4), 16), parseInt(c.slice(4, 6), 16)];
};
const mix = (c1, c2, t) => {
  const a = hex(c1), b = hex(c2);
  return `rgb(${Math.round(lerp(a[0], b[0], t))},${Math.round(lerp(a[1], b[1], t))},${Math.round(lerp(a[2], b[2], t))})`;
};
const THERMAL = [
  [0, "#243349"], [30, "#2A3C5C"], [42, "#34538C"], [55, "#6A5E9E"],
  [66, "#8B6FB0"], [74, "#C77B45"], [82, "#E89B3C"], [92, "#F4D58D"], [100, "#FBEFC9"],
];
function thermal(s) {
  s = Math.max(0, Math.min(100, s));
  for (let i = 0; i < THERMAL.length - 1; i++) {
    if (s <= THERMAL[i + 1][0]) {
      const t = (s - THERMAL[i][0]) / (THERMAL[i + 1][0] - THERMAL[i][0]);
      return mix(THERMAL[i][1], THERMAL[i + 1][1], t);
    }
  }
  return THERMAL[THERMAL.length - 1][1];
}
const inkfor = (s) => (s >= 70 ? "#0c1722" : "#e9e6da");
const gradeColor = (g) => ({ A: "#F4D58D", B: "#E89B3C", C: "#8B6FB0", D: "#5C7184", F: "#E2574C" }[g] || "#5C7184");
const TIER = {
  TIER_1_BURST: "Burst", TIER_2_NEAR_BURST: "Near burst", TIER_3_BIG_MOVE: "Big move",
  TIER_4_HIGH_CONVICTION: "Conviction", FLOW_TRADE: "Flow",
};
const oiFmt = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`);

const normStock = (r) => {
  const p = r.pillars || {};
  const sc = (x) => Math.round((x && x.score) || 0);
  return {
    ticker: r.ticker, sector: r.sector || "",
    score: Math.round(r.flow_score || 0),
    cf: sc(p.capital_flow), trend: sc(p.trend), mom: sc(p.momentum),
    jump: r.week_jump ?? null,
    tier: (r.burst && r.burst.tier) || null,
  };
};
const normSector = (r) => ({
  sector: r.sector, etf: r.etf || "",
  score: Math.round(r.flow_score || 0),
  cf: Math.round(r.capital_flow || 0), trend: Math.round(r.trend || 0), mom: Math.round(r.momentum || 0),
  flow: r.etf_flow_m || 0,
});

export default function App() {
  const [tab, setTab] = useState("stocks");
  const [stocks, setStocks] = useState(null);
  const [sectors, setSectors] = useState(null);
  const [error, setError] = useState(null);
  const [grades, setGrades] = useState({});   // ticker -> {loading} | {data} | {error}
  const [open, setOpen] = useState(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/api/scores/latest`).then((r) => r.json()),
      fetch(`${API_BASE}/api/sectors/latest`).then((r) => r.json()).catch(() => []),
    ])
      .then(([s, sec]) => { setStocks(s || []); setSectors(sec || []); })
      .catch((e) => setError(String(e)));
  }, []);

  const rows = useMemo(
    () => (stocks ? stocks.map(normStock).sort((a, b) => b.score - a.score) : []),
    [stocks]
  );
  const secRows = useMemo(
    () => (sectors ? sectors.map(normSector).sort((a, b) => b.score - a.score) : []),
    [sectors]
  );

  const toggle = (ticker) => {
    if (open === ticker) { setOpen(null); return; }
    setOpen(ticker);
    if (grades[ticker]) return;
    setGrades((g) => ({ ...g, [ticker]: { loading: true } }));
    fetch(`${API_BASE}/api/options/${ticker}`)
      .then((r) => r.json())
      .then((r) => setGrades((g) => ({ ...g, [ticker]: r.grade ? { data: r } : { error: r.error || "no tradable contract" } })))
      .catch((e) => setGrades((g) => ({ ...g, [ticker]: { error: String(e) } })));
  };

  if (error) return <Shell><div className="center">Couldn't reach the Flow Score API.<br />{error}</div></Shell>;
  if (!stocks || !sectors) return <Shell><div className="center">Reading the tape&hellip;</div></Shell>;

  const above = rows.filter((s) => s.score >= 70).length;
  const bursts = rows.filter((s) => s.tier === "TIER_1_BURST").length;
  const lead = rows[0];
  const leadSectors = secRows.filter((s) => s.score >= 60).slice(0, 3);

  return (
    <Shell>
      <header>
        <div className="brand">
          <div className="ey">TTI / Flow Score System / The Hit List</div>
          <h1>The Flow Map<span className="dim"> / </span><span className="dim">{tab === "sectors" ? "sectors" : "stocks"}</span></h1>
        </div>
        <div className="gauge">
          {lead && <div className="g"><div className="n" style={{ color: thermal(lead.score) }}>{lead.score}</div><div className="l">{lead.ticker} tops</div></div>}
          <div className="g"><div className="n">{above}</div><div className="l">score 70+</div></div>
          <div className="g"><div className="n" style={{ color: "var(--amber)" }}>{bursts}</div><div className="l">burst triggers</div></div>
        </div>
      </header>

      <nav>
        {["stocks", "sectors"].map((t) => (
          <button key={t} className={`tab${tab === t ? " on" : ""}`} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>

      {tab === "stocks" && (
        rows.length === 0
          ? <div className="center">No scored stocks yet &mdash; the weekly pipeline hasn't run.</div>
          : <Stocks rows={rows} grades={grades} open={open} toggle={toggle} leadSectors={leadSectors} />
      )}
      {tab === "sectors" && (
        secRows.length === 0
          ? <div className="center">No sector data yet.</div>
          : <Sectors rows={secRows} />
      )}
    </Shell>
  );
}

const Shell = ({ children }) => <div className="app"><div className="wrap">{children}</div></div>;

const Bars = ({ cf, trend, mom }) => (
  <div className="bars" title={`CF ${cf}/40 · Trend ${trend}/30 · Mom ${mom}/30`}>
    {[["cf", cf, 40, "var(--amber)"], ["t", trend, 30, "var(--violet)"], ["m", mom, 30, "var(--slate)"]].map(
      ([k, v, mx, col]) => <i key={k} style={{ height: 4 + (v / mx) * 22, background: col }} />
    )}
  </div>
);

// ============================ STOCKS ============================
function Stocks({ rows, grades, open, toggle, leadSectors }) {
  return (
    <section>
      <div className="sub">
        Every scored name, ranked by Flow Score. Click a row to grade the options contract to buy &mdash; liquidity, delta, IV, and the double target.
      </div>
      {leadSectors.length > 0 && (
        <div className="chips">
          <span className="chip">leading sectors</span>
          {leadSectors.map((s) => (
            <span className="chip" key={s.sector}><b style={{ color: thermal(s.score) }}>{s.sector}</b> {s.score}</span>
          ))}
        </div>
      )}
      <div className="board">
        {rows.map((s, i) => {
          const g = grades[s.ticker];
          const jc = s.jump > 0 ? "var(--pos)" : s.jump < 0 ? "var(--neg)" : "var(--ink-faint)";
          return (
            <div className={`brow${open === s.ticker ? " open" : ""}`} key={s.ticker}>
              <div className="bmain" onClick={() => toggle(s.ticker)}>
                <div className="rk">{String(i + 1).padStart(2, "0")}</div>
                <div className="tk"><b>{s.ticker}</b><span className="sec">{s.sector}</span></div>
                <div className="bmid">
                  <Bars cf={s.cf} trend={s.trend} mom={s.mom} />
                  {s.tier && TIER[s.tier] && <div className="tier">{TIER[s.tier]}</div>}
                  <div className="jump" style={{ color: jc }}>{s.jump == null ? "·" : s.jump > 0 ? `+${s.jump}` : s.jump}</div>
                </div>
                <div className="bright">
                  <div className="bsc" style={{ color: thermal(s.score) }}>{s.score}</div>
                  <GradeChip state={g} />
                </div>
              </div>
              {open === s.ticker && <ContractPanel state={g || { loading: true }} />}
            </div>
          );
        })}
      </div>
    </section>
  );
}

function GradeChip({ state }) {
  if (!state) return <div className="gradechip pending">–</div>;
  if (state.loading) return <div className="gradechip load">…</div>;
  if (state.error) return <div className="gradechip err">–</div>;
  const g = state.data.grade;
  return <div className="gradechip" style={{ background: gradeColor(g) }}>{g}</div>;
}

function ContractPanel({ state }) {
  if (state.loading) return <div className="contract"><div className="cerr">Grading the chain&hellip;</div></div>;
  if (state.error) return <div className="contract"><div className="cerr">No clean contract — {state.error}</div></div>;
  const d = state.data, c = d.contract;
  return (
    <div className="contract">
      <div className="cmeta">
        <span><span className="k">contract</span> {c.symbol}</span>
        <span><span className="k">delta</span> {c.delta}</span>
        <span><span className="k">IV</span> {c.iv}%</span>
        <span><span className="k">mid</span> ${c.mid}</span>
        <span><span className="k">double</span> ${c.double}</span>
        <span><span className="k">OI</span> {oiFmt(c.open_interest)}</span>
        <span><span className="k">exp</span> {d.expiration}</span>
        <span><span className="k">plan</span> {d.template}</span>
      </div>
      {d.recommendation && <div className="crec">{d.recommendation}</div>}
      <div className="cchecks">
        {d.checks.map((ck, i) => (
          <div className="ck" key={i}>
            <span className={"ico " + (ck.pass ? "ok" : "no")}>{ck.pass ? "✓" : "✕"}</span>
            <span className="cname">{ck.name}</span>
            <span className="cdet">{ck.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================ SECTORS (context) ============================
function Sectors({ rows }) {
  const W = 620, H = 420, P = 44, HI = 30;
  const x = (v) => P + (v / HI) * (W - 2 * P);
  const y = (v) => H - P - (v / HI) * (H - 2 * P);
  return (
    <section>
      <div className="sub">Where the wind is blowing. Only hunt stocks in sectors up and to the right — the leaders.</div>
      <div className="cur">
        <div className="field">
          <svg viewBox={`0 0 ${W} ${H}`}>
            <rect x={x(15)} y={P} width={W - P - x(15)} height={y(15) - P} fill="#e89b3c08" />
            {[0, 5, 10, 15, 20, 25, 30].map((v) => (
              <g key={v}>
                <line x1={x(v)} y1={P} x2={x(v)} y2={H - P} stroke="#ffffff08" />
                <line x1={P} y1={y(v)} x2={W - P} y2={y(v)} stroke="#ffffff08" />
              </g>
            ))}
            <line x1={x(15)} y1={P} x2={x(15)} y2={H - P} stroke="#ffffff20" strokeDasharray="3 4" />
            <line x1={P} y1={y(15)} x2={W - P} y2={y(15)} stroke="#ffffff20" strokeDasharray="3 4" />
            <text className="qlabel" x={W - P - 4} y={P + 14} textAnchor="end">LEADING</text>
            <text className="qlabel" x={P + 4} y={P + 14}>IMPROVING</text>
            <text className="qlabel" x={W - P - 4} y={H - P - 6} textAnchor="end">WEAKENING</text>
            <text className="qlabel" x={P + 4} y={H - P - 6}>LAGGING</text>
            <text className="qlabel" x={W / 2} y={H - 12} textAnchor="middle" fill="#5C7184">TREND</text>
            <text className="qlabel" x={14} y={H / 2} transform={`rotate(-90 14 ${H / 2})`} textAnchor="middle" fill="#5C7184">MOMENTUM</text>
            {rows.map((s) => {
              const r = 6 + (s.cf / 40) * 12, col = thermal(s.score);
              return (
                <g key={s.sector}>
                  <circle cx={x(s.trend)} cy={y(s.mom)} r={r + 6} fill={col} opacity="0.1" />
                  <circle cx={x(s.trend)} cy={y(s.mom)} r={r} fill={col} stroke="#0c1722" strokeWidth="1.5" />
                  <text x={x(s.trend)} y={y(s.mom) + 3.5} textAnchor="middle" fontFamily="IBM Plex Mono" fontSize="9.5" fontWeight="600" fill={inkfor(s.score)}>{s.etf}</text>
                </g>
              );
            })}
          </svg>
        </div>
        <div className="ladder">
          {rows.map((s, i) => (
            <div className="lrow" key={s.sector}>
              <div className="rk mono">{String(i + 1).padStart(2, "0")}</div>
              <div className="nm"><b>{s.sector}</b><span className="etf">{s.etf}</span></div>
              <div className="rt">
                <Bars cf={s.cf} trend={s.trend} mom={s.mom} />
                <div className="sc" style={{ color: thermal(s.score) }}>{s.score}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
