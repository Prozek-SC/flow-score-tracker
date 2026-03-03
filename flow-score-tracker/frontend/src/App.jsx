import { useState, useEffect, useCallback } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, BarChart, Bar, Cell } from "recharts";

const API = process.env.REACT_APP_API_URL || "http://localhost:5000";

// ============================================================
// CONSTANTS
// ============================================================
const RATING_COLOR = { ELITE: "#00ff88", STRONG: "#7fff7f", NEUTRAL: "#ffd700", WEAK: "#ff9944", TOXIC: "#ff3333" };
const STATUS_COLOR = { LEADING: "#00ff88", NEUTRAL: "#ffd700", WEAK: "#ff4444" };
const SECTORS_LIST = ["Energy","Utilities","Consumer Staples","Industrials","Materials","Health Care","Real Estate","Comm Services","Consumer Disc","Financials","Technology"];

function scoreColor(s) {
  if (s >= 85) return "#00ff88";
  if (s >= 70) return "#7fff7f";
  if (s >= 50) return "#ffd700";
  if (s >= 30) return "#ff9944";
  return "#ff3333";
}

function fmt(n, d = 1) { return Number(n || 0).toFixed(d); }

function api(path, opts) {
  return fetch(`${API}${path}`, opts).then(r => r.json()).catch(() => null);
}

// ============================================================
// REUSABLE UI COMPONENTS
// ============================================================

function ScoreRing({ score, rating, size = 90 }) {
  const r = size * 0.42;
  const circ = 2 * Math.PI * r;
  const filled = (score / 100) * circ;
  const color = scoreColor(score);
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke="#0d0d1a" strokeWidth={7} />
        <circle cx={size/2} cy={size/2} r={r} fill="none" stroke={color} strokeWidth={7}
          strokeDasharray={`${filled} ${circ - filled}`} strokeLinecap="round"
          style={{ transition: "stroke-dasharray 0.8s ease", filter: `drop-shadow(0 0 4px ${color}66)` }} />
      </svg>
      <div style={{ position:"absolute", inset:0, display:"flex", flexDirection:"column", alignItems:"center", justifyContent:"center" }}>
        <span style={{ fontSize: size*0.24, fontWeight:900, color, fontFamily:"monospace", lineHeight:1 }}>{Math.round(score)}</span>
        {rating && <span style={{ fontSize: size*0.12, color, fontWeight:700, letterSpacing:1 }}>{rating}</span>}
      </div>
    </div>
  );
}

function PillarBar({ label, score, max, color }) {
  const pct = (score / max) * 100;
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{ display:"flex", justifyContent:"space-between", marginBottom:3 }}>
        <span style={{ fontSize:10, color:"#666", letterSpacing:1 }}>{label}</span>
        <span style={{ fontSize:11, color, fontFamily:"monospace", fontWeight:700 }}>{fmt(score,0)}/{max}</span>
      </div>
      <div style={{ background:"#0a0a18", borderRadius:4, height:8, overflow:"hidden" }}>
        <div style={{ background:color, width:`${pct}%`, height:"100%", borderRadius:4,
          transition:"width 0.7s ease", boxShadow:`0 0 8px ${color}55` }} />
      </div>
    </div>
  );
}

function Tag({ children, color = "#00ff88", bg }) {
  return (
    <span style={{ display:"inline-block", padding:"2px 8px", background: bg || `${color}22`,
      border:`1px solid ${color}44`, borderRadius:4, fontSize:10, color, fontWeight:700, letterSpacing:1 }}>
      {children}
    </span>
  );
}

function Panel({ title, subtitle, children, action }) {
  return (
    <div style={{ background:"#0a0a18", border:"1px solid #1a1a2e", borderRadius:10, overflow:"hidden", marginBottom:20 }}>
      <div style={{ background:"#0d0d22", padding:"12px 20px", borderBottom:"1px solid #1a1a2e",
        display:"flex", justifyContent:"space-between", alignItems:"center" }}>
        <div>
          <div style={{ fontSize:10, color:"#00ff88", letterSpacing:3, textTransform:"uppercase" }}>{title}</div>
          {subtitle && <div style={{ fontSize:10, color:"#444", marginTop:2 }}>{subtitle}</div>}
        </div>
        {action}
      </div>
      <div style={{ padding:20 }}>{children}</div>
    </div>
  );
}

function Btn({ onClick, children, color = "#00ff88", disabled, small }) {
  return (
    <button onClick={onClick} disabled={disabled} style={{
      background: disabled ? "#1a1a2e" : color === "ghost" ? "transparent" : color,
      border: color === "ghost" ? "1px solid #2a2a4a" : "none",
      borderRadius:6, padding: small ? "6px 12px" : "10px 18px",
      color: disabled ? "#555" : color === "ghost" ? "#888" : "#000",
      fontFamily:"monospace", fontSize: small ? 10 : 11, fontWeight:700,
      cursor: disabled ? "not-allowed" : "pointer", letterSpacing:1, whiteSpace:"nowrap",
      transition:"opacity 0.2s"
    }}>
      {children}
    </button>
  );
}

// ============================================================
// TICKER SCORE CARD
// ============================================================
function TickerCard({ data, onSelect, isSelected }) {
  const { ticker, flow_score = 0, rating, label, action, price, sector, burst = {}, pillars = {} } = data;
  const color = scoreColor(flow_score);
  const rColor = RATING_COLOR[rating] || "#888";
  const cf = pillars?.capital_flow?.score || 0;
  const tr = pillars?.trend?.score || 0;
  const mo = pillars?.momentum?.score || 0;

  return (
    <div onClick={() => onSelect(data)} style={{
      background: isSelected ? "#0f0f28" : "#0a0a18",
      border: `1px solid ${isSelected ? "#00ff8855" : "#1a1a2e"}`,
      borderRadius:10, padding:20, cursor:"pointer", transition:"all 0.2s",
      boxShadow: isSelected ? "0 0 24px #00ff8811" : "none",
    }}
    onMouseEnter={e => { if (!isSelected) e.currentTarget.style.borderColor = "#2a2a4a"; }}
    onMouseLeave={e => { if (!isSelected) e.currentTarget.style.borderColor = "#1a1a2e"; }}>

      {burst.is_burst && (
        <div style={{ background:"#ff660022", border:"1px solid #ff660055", borderRadius:6,
          padding:"6px 12px", marginBottom:14, fontSize:10, color:"#ff6600", fontWeight:700, letterSpacing:1 }}>
          ⚡ BURST TRADE · Score jumped +{fmt(burst.score_jump, 0)}pts this week
        </div>
      )}

      <div style={{ display:"flex", gap:16, alignItems:"center", marginBottom:16 }}>
        <ScoreRing score={flow_score} rating={rating} size={88} />
        <div style={{ flex:1 }}>
          <div style={{ fontSize:22, fontWeight:900, color:"#fff", fontFamily:"monospace" }}>{ticker}</div>
          <div style={{ fontSize:11, color:"#555", marginBottom:4 }}>${fmt(price,2)} · {sector}</div>
          <Tag color={rColor}>{label || rating}</Tag>
          {burst.is_burst && <Tag color="#ff6600" style={{ marginLeft:8 }}>Burst Trade</Tag>}
        </div>
      </div>

      <PillarBar label="CAPITAL FLOW" score={cf} max={40} color="#00aaff" />
      <PillarBar label="TREND" score={tr} max={30} color="#aa88ff" />
      <PillarBar label="MOMENTUM" score={mo} max={30} color="#ff88aa" />

      {action && (
        <div style={{ marginTop:14, padding:"10px 14px", background:"#0d0d1a",
          borderRadius:6, fontSize:10, color:"#666", fontFamily:"monospace" }}>
          ↳ {action}
        </div>
      )}
    </div>
  );
}

// ============================================================
// SECTOR RANKINGS TABLE
// ============================================================
function SectorRankings({ sectors }) {
  if (!sectors || sectors.length === 0)
    return <div style={{ color:"#333", fontSize:12, padding:20 }}>No sector data yet — run a weekly scan.</div>;

  const sorted = [...sectors].sort((a,b) => (a.rank || 99) - (b.rank || 99));

  return (
    <div style={{ overflowX:"auto" }}>
      <table style={{ width:"100%", borderCollapse:"collapse", fontSize:12 }}>
        <thead>
          <tr style={{ borderBottom:"1px solid #1a1a2e" }}>
            {["Rank","Sector","ETF","Flow Score","Capital /40","Trend /30","Momentum /30","ETF Flow $M","Status"].map(h => (
              <th key={h} style={{ padding:"8px 12px", textAlign:"left", color:"#444",
                fontSize:10, fontWeight:400, letterSpacing:1, whiteSpace:"nowrap" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map(s => {
            const sc = scoreColor(s.flow_score);
            const stColor = STATUS_COLOR[s.status] || "#888";
            return (
              <tr key={s.sector} style={{ borderBottom:"1px solid #0d0d1a" }}
                onMouseEnter={e => e.currentTarget.style.background="#0d0d22"}
                onMouseLeave={e => e.currentTarget.style.background="transparent"}>
                <td style={{ padding:"10px 12px", color:"#555", fontFamily:"monospace" }}>#{s.rank}</td>
                <td style={{ padding:"10px 12px", color:"#fff", fontWeight:700 }}>{s.sector}</td>
                <td style={{ padding:"10px 12px", color:"#888", fontFamily:"monospace" }}>{s.etf}</td>
                <td style={{ padding:"10px 12px" }}>
                  <div style={{ display:"flex", alignItems:"center", gap:8 }}>
                    <div style={{ background:"#0d0d1a", borderRadius:3, height:6, width:60, overflow:"hidden" }}>
                      <div style={{ background:sc, width:`${s.flow_score}%`, height:"100%" }} />
                    </div>
                    <span style={{ color:sc, fontWeight:900, fontFamily:"monospace" }}>{fmt(s.flow_score,0)}</span>
                  </div>
                </td>
                <td style={{ padding:"10px 12px", color:"#00aaff", fontFamily:"monospace" }}>{fmt(s.capital_flow,0)}</td>
                <td style={{ padding:"10px 12px", color:"#aa88ff", fontFamily:"monospace" }}>{fmt(s.trend,0)}</td>
                <td style={{ padding:"10px 12px", color:"#ff88aa", fontFamily:"monospace" }}>{fmt(s.momentum,0)}</td>
                <td style={{ padding:"10px 12px", color: s.etf_flow_m >= 0 ? "#00ff88" : "#ff4444",
                  fontFamily:"monospace" }}>{s.etf_flow_m >= 0 ? "+" : ""}{fmt(s.etf_flow_m,0)}</td>
                <td style={{ padding:"10px 12px" }}>
                  <Tag color={stColor}>{s.status}</Tag>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ============================================================
// FLOW LEADERS / EXITS
// ============================================================
function FlowTable({ items, title, isLeaders }) {
  if (!items || items.length === 0)
    return <div style={{ color:"#333", fontSize:12, padding:"12px 0" }}>No data yet.</div>;

  return (
    <table style={{ width:"100%", borderCollapse:"collapse", fontSize:12 }}>
      <thead><tr style={{ borderBottom:"1px solid #1a1a2e" }}>
        {["Ticker","Industry","Flow /40","Trend /30","Momentum /30","Score"].map(h => (
          <th key={h} style={{ padding:"8px 10px", textAlign:"left", color:"#444", fontSize:10, fontWeight:400 }}>{h}</th>
        ))}
      </tr></thead>
      <tbody>
        {items.map(r => {
          const sc = scoreColor(r.flow_score);
          return (
            <tr key={r.ticker} style={{ borderBottom:"1px solid #0d0d1a" }}
              onMouseEnter={e => e.currentTarget.style.background="#0d0d22"}
              onMouseLeave={e => e.currentTarget.style.background="transparent"}>
              <td style={{ padding:"10px 10px", fontWeight:700, color:"#fff", fontFamily:"monospace" }}>{r.ticker}</td>
              <td style={{ padding:"10px 10px", color:"#666" }}>{r.sector || "—"}</td>
              <td style={{ padding:"10px 10px", color:"#00aaff", fontFamily:"monospace" }}>{fmt(r.capital_flow,0)}</td>
              <td style={{ padding:"10px 10px", color:"#aa88ff", fontFamily:"monospace" }}>{fmt(r.trend,0)}</td>
              <td style={{ padding:"10px 10px", color:"#ff88aa", fontFamily:"monospace" }}>{fmt(r.momentum,0)}</td>
              <td style={{ padding:"10px 10px", fontWeight:900, color:sc, fontFamily:"monospace" }}>{fmt(r.flow_score,0)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

// ============================================================
// BURST TRADE ALERTS
// ============================================================
function BurstAlerts({ bursts }) {
  if (!bursts || bursts.length === 0)
    return <div style={{ color:"#333", fontSize:12, padding:"12px 0" }}>No burst trades detected this week.</div>;

  return (
    <div style={{ display:"flex", flexDirection:"column", gap:12 }}>
      {bursts.map(r => (
        <div key={r.ticker} style={{ background:"#1a0800", border:"1px solid #ff660055", borderRadius:8, padding:"14px 18px" }}>
          <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:8 }}>
            <div style={{ display:"flex", gap:12, alignItems:"center" }}>
              <span style={{ fontSize:18, fontWeight:900, color:"#fff", fontFamily:"monospace" }}>{r.ticker}</span>
              <Tag color="#ff6600">⚡ +{fmt(r.burst?.score_jump,0)}pts jump</Tag>
              <Tag color="#ffd700">{r.sector}</Tag>
            </div>
            <ScoreRing score={r.flow_score} size={60} />
          </div>
          <div style={{ fontSize:11, color:"#ff9944", fontFamily:"monospace", marginBottom:4 }}>
            Burst Trade Parameters
          </div>
          <div style={{ fontSize:11, color:"#888" }}>
            30-45 DTE · .40-.50 Delta · Never roll · Sell the double · Exit within 20 DTE if target not hit
          </div>
        </div>
      ))}
    </div>
  );
}

// ============================================================
// FUND FLOWS PANEL
// ============================================================
function FundFlowsPanel({ flows, onAddFlow }) {
  const [form, setForm] = useState({ week_ending:"", equity_total:"", equity_domestic:"", equity_world:"", bond_total:"", commodity:"" });
  const [showForm, setShowForm] = useState(false);

  const handleSubmit = async () => {
    await api("/api/fund-flows", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        week_ending: form.week_ending,
        equity_total: parseFloat(form.equity_total) || 0,
        equity_domestic: parseFloat(form.equity_domestic) || 0,
        equity_world: parseFloat(form.equity_world) || 0,
        bond_total: parseFloat(form.bond_total) || 0,
        commodity: parseFloat(form.commodity) || 0,
      })
    });
    setShowForm(false);
    onAddFlow();
  };

  const recent = flows?.slice(0, 5) || [];
  const chartData = [...recent].reverse().map(f => ({
    week: f.week_ending?.slice(5),
    equity: f.equity_total,
    bond: f.bond_total,
    commodity: f.commodity,
  }));

  const inputStyle = {
    background:"#0d0d1a", border:"1px solid #1a1a2e", borderRadius:6,
    padding:"8px 12px", color:"#fff", fontFamily:"monospace", fontSize:11,
    outline:"none", width:"100%", boxSizing:"border-box"
  };

  return (
    <div>
      {chartData.length > 0 && (
        <div style={{ marginBottom:20 }}>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={chartData} margin={{ top:5, right:5, left:-25, bottom:0 }}>
              <CartesianGrid stroke="#1a1a2e" strokeDasharray="3 3" />
              <XAxis dataKey="week" tick={{ fill:"#444", fontSize:10 }} />
              <YAxis tick={{ fill:"#444", fontSize:10 }} />
              <Tooltip contentStyle={{ background:"#0a0a18", border:"1px solid #1a1a2e", borderRadius:6, fontSize:11 }}
                labelStyle={{ color:"#888" }} />
              <Bar dataKey="equity" name="Equity $M" fill="#00aaff" radius={[3,3,0,0]} />
              <Bar dataKey="bond" name="Bond $M" fill="#aa88ff" radius={[3,3,0,0]} />
              <Bar dataKey="commodity" name="Commodity $M" fill="#ff88aa" radius={[3,3,0,0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {recent.length > 0 && (
        <table style={{ width:"100%", borderCollapse:"collapse", fontSize:11, marginBottom:16 }}>
          <thead><tr style={{ borderBottom:"1px solid #1a1a2e" }}>
            {["Week Ending","Equity $M","Domestic","World","Bond $M","Commodity"].map(h => (
              <th key={h} style={{ padding:"6px 10px", textAlign:"right", color:"#444", fontSize:10, fontWeight:400 }}
              >{h}</th>
            ))}
          </tr></thead>
          <tbody>
            {recent.map(f => (
              <tr key={f.week_ending} style={{ borderBottom:"1px solid #0d0d1a" }}>
                <td style={{ padding:"8px 10px", color:"#888", textAlign:"right", fontFamily:"monospace" }}>{f.week_ending}</td>
                <td style={{ padding:"8px 10px", color: f.equity_total >= 0 ? "#00aaff" : "#ff4444",
                  fontFamily:"monospace", textAlign:"right", fontWeight:700 }}>
                  {f.equity_total >= 0 ? "+" : ""}{Number(f.equity_total).toLocaleString()}
                </td>
                <td style={{ padding:"8px 10px", color:"#666", fontFamily:"monospace", textAlign:"right" }}>{Number(f.equity_domestic).toLocaleString()}</td>
                <td style={{ padding:"8px 10px", color:"#666", fontFamily:"monospace", textAlign:"right" }}>{Number(f.equity_world).toLocaleString()}</td>
                <td style={{ padding:"8px 10px", color:"#aa88ff", fontFamily:"monospace", textAlign:"right" }}>{Number(f.bond_total).toLocaleString()}</td>
                <td style={{ padding:"8px 10px", color:"#ff88aa", fontFamily:"monospace", textAlign:"right" }}>{Number(f.commodity).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <Btn onClick={() => setShowForm(!showForm)} color="ghost" small>{showForm ? "Cancel" : "+ Enter Weekly ICI Data"}</Btn>

      {showForm && (
        <div style={{ marginTop:16, padding:16, background:"#0d0d1a", borderRadius:8, border:"1px solid #1a1a2e" }}>
          <div style={{ fontSize:10, color:"#666", marginBottom:12, lineHeight:1.6 }}>
            Source: ici.org/research/stats/weekly · All values in $millions
          </div>
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr 1fr", gap:10 }}>
            {[
              ["week_ending","Week Ending (YYYY-MM-DD)"],
              ["equity_total","Equity Total $M"],
              ["equity_domestic","Equity Domestic $M"],
              ["equity_world","Equity World $M"],
              ["bond_total","Bond Total $M"],
              ["commodity","Commodity $M"],
            ].map(([key, label]) => (
              <div key={key}>
                <div style={{ fontSize:10, color:"#555", marginBottom:4 }}>{label}</div>
                <input value={form[key]} onChange={e => setForm(f => ({...f, [key]: e.target.value}))}
                  style={inputStyle} placeholder={key === "week_ending" ? "2026-02-18" : "14637"} />
              </div>
            ))}
          </div>
          <div style={{ marginTop:12 }}>
            <Btn onClick={handleSubmit} color="#00ff88" small>Save Fund Flow Data</Btn>
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================
// TICKER DETAIL PANEL
// ============================================================
function TickerDetail({ data, onClose }) {
  const [history, setHistory] = useState([]);
  const { ticker, flow_score=0, rating, pillars={}, burst={} } = data;

  useEffect(() => {
    api(`/api/scores/history/${ticker}`).then(d => d && setHistory(d));
  }, [ticker]);

  const chartData = history.map(h => ({ date: h.date?.slice(5), score: h.flow_score, price: h.price }));
  const cf = pillars.capital_flow || {};
  const tr = pillars.trend || {};
  const mo = pillars.momentum || {};

  return (
    <div style={{ background:"#0a0a18", border:"1px solid #1a1a2e", borderRadius:10,
      padding:24, position:"sticky", top:90, alignSelf:"start" }}>
      <div style={{ display:"flex", justifyContent:"space-between", marginBottom:20 }}>
        <div>
          <div style={{ fontSize:10, color:"#00ff88", letterSpacing:3 }}>DETAIL · {ticker}</div>
          <div style={{ fontSize:20, fontWeight:900, color:"#fff" }}>Score History</div>
        </div>
        <button onClick={onClose} style={{ background:"none", border:"none", color:"#555", cursor:"pointer", fontSize:18 }}>✕</button>
      </div>

      {chartData.length > 0 ? (
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={chartData} margin={{ top:5, right:5, left:-25, bottom:0 }}>
            <CartesianGrid stroke="#1a1a2e" strokeDasharray="3 3" />
            <XAxis dataKey="date" tick={{ fill:"#444", fontSize:9 }} />
            <YAxis domain={[0,100]} tick={{ fill:"#444", fontSize:9 }} />
            <Tooltip contentStyle={{ background:"#0a0a18", border:"1px solid #1a1a2e", borderRadius:6, fontSize:11 }}
              labelStyle={{ color:"#888" }} itemStyle={{ color:"#00ff88" }} />
            <Line type="monotone" dataKey="score" stroke="#00ff88" strokeWidth={2}
              dot={{ fill:"#00ff88", r:3 }} name="Flow Score" />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <div style={{ color:"#333", fontSize:11, padding:"24px 0", textAlign:"center" }}>No history yet</div>
      )}

      <div style={{ marginTop:20 }}>
        <div style={{ fontSize:10, color:"#444", letterSpacing:2, marginBottom:14 }}>PILLAR BREAKDOWN</div>

        {[
          { label:"CAPITAL FLOW", data: cf, max:40, color:"#00aaff",
            subs:[ {label:"L1 Asset Class",score:cf.level1?.score||0,max:10},
                   {label:"L2 Sector",score:cf.level2?.score||0,max:15},
                   {label:"L3 Stock",score:cf.level3?.score||0,max:15} ] },
          { label:"TREND", data: tr, max:30, color:"#aa88ff",
            subs:[ {label:"20-day MA",score:tr.raw?.s20||0,max:10},
                   {label:"50-day MA",score:tr.raw?.s50||0,max:10},
                   {label:"200-day MA",score:tr.raw?.s200||0,max:10} ] },
          { label:"MOMENTUM", data: mo, max:30, color:"#ff88aa",
            subs:[ {label:"Rate of Change",score:mo.raw?.roc_score||0,max:6},
                   {label:"Relative Strength",score:mo.raw?.rs_score||0,max:6},
                   {label:"Acceleration",score:mo.raw?.accel_score||0,max:6},
                   {label:"MACD",score:mo.raw?.macd_score||0,max:6},
                   {label:"ADX",score:mo.raw?.adx_score||0,max:6} ] },
        ].map(pillar => (
          <div key={pillar.label} style={{ marginBottom:16, padding:"12px 14px",
            background:"#0d0d1a", borderRadius:8 }}>
            <div style={{ display:"flex", justifyContent:"space-between", marginBottom:10 }}>
              <span style={{ fontSize:10, color:pillar.color, fontWeight:700, letterSpacing:2 }}>{pillar.label}</span>
              <span style={{ fontSize:12, fontWeight:900, color:pillar.color, fontFamily:"monospace" }}>
                {fmt(pillar.data?.score||0,0)}/{pillar.max}
              </span>
            </div>
            {pillar.subs.map(sub => (
              <div key={sub.label} style={{ marginBottom:6 }}>
                <div style={{ display:"flex", justifyContent:"space-between", marginBottom:2 }}>
                  <span style={{ fontSize:10, color:"#555" }}>{sub.label}</span>
                  <span style={{ fontSize:10, color:"#888", fontFamily:"monospace" }}>{fmt(sub.score,0)}/{sub.max}</span>
                </div>
                <div style={{ background:"#0a0a18", borderRadius:3, height:4 }}>
                  <div style={{ background:pillar.color, width:`${(sub.score/sub.max)*100}%`, height:"100%",
                    borderRadius:3, opacity:0.7 }} />
                </div>
              </div>
            ))}
            <div style={{ fontSize:10, color:"#444", marginTop:8, lineHeight:1.5 }}>{pillar.data?.detail}</div>
          </div>
        ))}

        {burst.is_burst && (
          <div style={{ padding:"12px 14px", background:"#1a0800", border:"1px solid #ff660044", borderRadius:8 }}>
            <div style={{ fontSize:10, color:"#ff6600", fontWeight:700, marginBottom:6 }}>⚡ BURST TRADE DETECTED</div>
            <div style={{ fontSize:11, color:"#888" }}>{burst.options_params}</div>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================
// SETTINGS / CREDENTIALS
// ============================================================
function Settings({ onClose }) {
  const fields = [
    { key:"TRADESTATION_CLIENT_ID", label:"TradeStation Client ID" },
    { key:"TRADESTATION_CLIENT_SECRET", label:"TradeStation Client Secret", secret:true },
    { key:"FINVIZ_EMAIL", label:"Finviz Elite Email" },
    { key:"FINVIZ_PASSWORD", label:"Finviz Elite Password", secret:true },
    { key:"UNUSUAL_WHALES_API_KEY", label:"Unusual Whales API Key", secret:true },
    { key:"SUPABASE_URL", label:"Supabase URL" },
    { key:"SUPABASE_SERVICE_KEY", label:"Supabase Service Key", secret:true },
    { key:"SENDGRID_API_KEY", label:"SendGrid API Key", secret:true },
    { key:"REPORT_EMAIL_TO", label:"Send Report To (email)" },
    { key:"REPORT_EMAIL_FROM", label:"Send Report From (email)" },
  ];

  const inputStyle = { width:"100%", background:"#0a0a18", border:"1px solid #1a1a2e",
    borderRadius:6, padding:"10px 12px", color:"#fff", fontFamily:"monospace", fontSize:12,
    outline:"none", boxSizing:"border-box" };

  return (
    <div style={{ position:"fixed", inset:0, background:"#000000dd", zIndex:1000,
      display:"flex", alignItems:"center", justifyContent:"center" }}>
      <div style={{ background:"#0d0d1a", border:"1px solid #1a1a2e", borderRadius:12,
        padding:32, width:560, maxHeight:"85vh", overflowY:"auto" }}>
        <div style={{ display:"flex", justifyContent:"space-between", marginBottom:24 }}>
          <div>
            <div style={{ fontSize:10, color:"#00ff88", letterSpacing:3 }}>CONFIGURATION</div>
            <div style={{ fontSize:20, fontWeight:900, color:"#fff" }}>API Credentials</div>
          </div>
          <button onClick={onClose} style={{ background:"none", border:"none", color:"#888", cursor:"pointer", fontSize:20 }}>✕</button>
        </div>

        <div style={{ background:"#0a0a18", borderRadius:8, padding:"12px 16px", marginBottom:20,
          fontSize:11, color:"#555", lineHeight:1.7 }}>
          Enter these values in Railway → Your Service → Variables tab.<br/>
          They are stored securely on the server, not in the browser.
        </div>

        {fields.map(f => (
          <div key={f.key} style={{ marginBottom:14 }}>
            <div style={{ fontSize:10, color:"#666", marginBottom:5, letterSpacing:1 }}>{f.label}</div>
            <input type={f.secret ? "password" : "text"} readOnly
              placeholder={`Set in Railway: ${f.key}`} style={inputStyle} />
          </div>
        ))}

        <div style={{ marginTop:20, padding:"14px 16px", background:"#0a0a18", borderRadius:8, fontSize:11, color:"#444", lineHeight:1.8 }}>
          <span style={{ color:"#00ff88", fontWeight:700 }}>Railway setup:</span><br/>
          railway.app → Project → Service → Variables → Add each key above
        </div>

        <div style={{ marginTop:16 }}>
          <Btn onClick={onClose} color="#00ff88">Close</Btn>
        </div>
      </div>
    </div>
  );
}

// ============================================================
// WATCHLIST MANAGER
// ============================================================
function WatchlistManager({ watchlist, onRefresh }) {
  const [ticker, setTicker] = useState("");
  const [sector, setSector] = useState("");

  const add = async () => {
    if (!ticker.trim()) return;
    await api("/api/watchlist", { method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ ticker: ticker.trim().toUpperCase(), sector }) });
    setTicker(""); setSector(""); onRefresh();
  };

  const remove = async (t) => {
    await api(`/api/watchlist/${t}`, { method:"DELETE" });
    onRefresh();
  };

  const inputStyle = { background:"#0a0a18", border:"1px solid #1a1a2e", borderRadius:6,
    padding:"10px 14px", color:"#fff", fontFamily:"monospace", fontSize:13, outline:"none" };

  return (
    <div style={{ maxWidth:560 }}>
      <div style={{ display:"flex", gap:10, marginBottom:24, flexWrap:"wrap" }}>
        <input value={ticker} onChange={e => setTicker(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === "Enter" && add()} placeholder="Ticker (e.g. CVX)"
          style={{ ...inputStyle, width:140 }} />
        <select value={sector} onChange={e => setSector(e.target.value)}
          style={{ ...inputStyle, color: sector ? "#fff" : "#555" }}>
          <option value="">Select Sector</option>
          {SECTORS_LIST.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <Btn onClick={add} color="#00ff88">Add Ticker</Btn>
      </div>

      {watchlist.length === 0 && (
        <div style={{ color:"#333", fontSize:12, padding:"32px 0" }}>No tickers yet. Add some above.</div>
      )}

      {watchlist.map(w => (
        <div key={w.ticker} style={{ display:"flex", alignItems:"center", justifyContent:"space-between",
          padding:"12px 16px", background:"#0a0a18", border:"1px solid #1a1a2e", borderRadius:8, marginBottom:8 }}>
          <div>
            <span style={{ fontSize:16, fontWeight:700, color:"#fff", fontFamily:"monospace" }}>{w.ticker}</span>
            {w.sector && <span style={{ fontSize:11, color:"#555", marginLeft:12 }}>{w.sector}</span>}
          </div>
          <button onClick={() => remove(w.ticker)} style={{ background:"none", border:"1px solid #2a1a1a",
            borderRadius:4, color:"#ff4444", cursor:"pointer", padding:"4px 10px", fontSize:11 }}>
            Remove
          </button>
        </div>
      ))}
    </div>
  );
}

// ============================================================
// MAIN APP
// ============================================================
export default function App() {
  const [tab, setTab] = useState("scores");
  const [scores, setScores] = useState([]);
  const [sectors, setSectors] = useState([]);
  const [leaders, setLeaders] = useState([]);
  const [exits, setExits] = useState([]);
  const [bursts, setBursts] = useState([]);
  const [flows, setFlows] = useState([]);
  const [watchlist, setWatchlist] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    const [sc, sec, ld, ex, bu, fl, wl] = await Promise.all([
      api("/api/scores/latest"),
      api("/api/sectors/latest"),
      api("/api/leaders"),
      api("/api/exits"),
      api("/api/burst-trades"),
      api("/api/fund-flows"),
      api("/api/watchlist"),
    ]);
    if (sc) setScores(sc);
    if (sec) setSectors(sec);
    if (ld) setLeaders(ld);
    if (ex) setExits(ex);
    if (bu) setBursts(bu);
    if (fl) setFlows(fl);
    if (wl) setWatchlist(wl);
    setLastUpdate(new Date());
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const runWeekly = async () => {
    setScanning(true);
    await api("/api/scan/weekly", { method:"POST" });
    await fetchAll();
    setScanning(false);
  };

  const runDaily = async () => {
    await api("/api/scan/daily", { method:"POST" });
    await fetchAll();
  };

  const TABS = [
    { id:"scores", label:`Scores (${scores.length})` },
    { id:"sectors", label:"Sector Rankings" },
    { id:"leaders", label:"Flow Leaders" },
    { id:"bursts", label: bursts.length > 0 ? `⚡ Burst Alerts (${bursts.length})` : "Burst Alerts" },
    { id:"flows", label:"Fund Flows" },
    { id:"watchlist", label:`Watchlist (${watchlist.length})` },
  ];

  return (
    <div style={{ minHeight:"100vh", background:"#0d0d1a", fontFamily:"'Courier New',monospace", color:"#fff" }}>

      {/* HEADER */}
      <div style={{ background:"#080818", borderBottom:"1px solid #1a1a2e", padding:"18px 28px",
        display:"flex", alignItems:"center", justifyContent:"space-between",
        position:"sticky", top:0, zIndex:100 }}>
        <div>
          <div style={{ fontSize:9, color:"#00ff88", letterSpacing:5, textTransform:"uppercase" }}>Institutional Intelligence</div>
          <div style={{ fontSize:20, fontWeight:900, color:"#fff", letterSpacing:1 }}>The Flow Score</div>
          <div style={{ fontSize:9, color:"#333", marginTop:1 }}>
            Capital Flow 40% · Trend 30% · Momentum 30%
            {lastUpdate && ` · Updated ${lastUpdate.toLocaleTimeString()}`}
          </div>
        </div>

        <div style={{ display:"flex", gap:8, alignItems:"center" }}>
          {bursts.length > 0 && (
            <div style={{ background:"#ff660022", border:"1px solid #ff660055", borderRadius:6,
              padding:"6px 14px", fontSize:10, color:"#ff6600", fontWeight:700 }}>
              ⚡ {bursts.length} BURST {bursts.length === 1 ? "TRADE" : "TRADES"}
            </div>
          )}
          <a href={`${API}/api/export/scores`} target="_blank" rel="noreferrer">
            <Btn color="ghost" small>↓ CSV</Btn>
          </a>
          <Btn onClick={() => setShowSettings(true)} color="ghost" small>⚙ Settings</Btn>
          <Btn onClick={runDaily} color="ghost" small disabled={scanning}>↻ Daily</Btn>
          <Btn onClick={runWeekly} disabled={scanning} color="#00ff88">
            {scanning ? "Scanning..." : "▶ Weekly Scan"}
          </Btn>
        </div>
      </div>

      {/* TABS */}
      <div style={{ background:"#080818", borderBottom:"1px solid #1a1a2e", padding:"0 28px" }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            background:"none", border:"none", padding:"12px 16px", cursor:"pointer", fontFamily:"monospace",
            fontSize:10, letterSpacing:2, textTransform:"uppercase",
            color: tab === t.id ? "#00ff88" : "#444",
            borderBottom: tab === t.id ? "2px solid #00ff88" : "2px solid transparent",
            fontWeight: tab === t.id ? 700 : 400,
          }}>{t.label}</button>
        ))}
      </div>

      {/* CONTENT */}
      <div style={{ padding:"28px", maxWidth:"100%" }}>

        {loading && (
          <div style={{ textAlign:"center", color:"#00ff88", padding:60, fontSize:11, letterSpacing:3 }}>
            LOADING FLOW DATA...
          </div>
        )}

        {/* SCORES TAB */}
        {!loading && tab === "scores" && (
          <>
            {scores.length === 0 ? (
              <div style={{ textAlign:"center", padding:80 }}>
                <div style={{ fontSize:13, color:"#333", marginBottom:12 }}>No scores yet</div>
                <div style={{ fontSize:11, color:"#222", marginBottom:24 }}>Add tickers to watchlist then run a weekly scan</div>
                <Btn onClick={() => setTab("watchlist")} color="#00ff88">Add Tickers →</Btn>
              </div>
            ) : (
              <div style={{ display:"grid", gridTemplateColumns: selected ? "1fr 360px" : "repeat(auto-fill, minmax(340px, 1fr))", gap:20, alignItems:"start" }}>
                <div style={{ display:"grid", gridTemplateColumns: selected ? "1fr" : "repeat(auto-fill, minmax(340px, 1fr))", gap:20 }}>
                  {scores.map(s => (
                    <TickerCard key={s.ticker} data={s}
                      onSelect={d => setSelected(selected?.ticker === d.ticker ? null : d)}
                      isSelected={selected?.ticker === s.ticker} />
                  ))}
                </div>
                {selected && <TickerDetail data={selected} onClose={() => setSelected(null)} />}
              </div>
            )}
          </>
        )}

        {/* SECTOR RANKINGS */}
        {!loading && tab === "sectors" && (
          <Panel title="Sector Rankings" subtitle="Flow Score by GICS sector · Updated weekly">
            <SectorRankings sectors={sectors} />
          </Panel>
        )}

        {/* FLOW LEADERS & EXITS */}
        {!loading && tab === "leaders" && (
          <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:20 }}>
            <Panel title="Capital Flow Leaders" subtitle="Top 10 · Institutional money chasing these NOW">
              <FlowTable items={leaders} isLeaders />
            </Panel>
            <Panel title="Smart Money Exits" subtitle="Institutions heading for the door">
              <FlowTable items={exits} />
            </Panel>
          </div>
        )}

        {/* BURST ALERTS */}
        {!loading && tab === "bursts" && (
          <Panel title="⚡ Burst Trade Alerts"
            subtitle="Score jumped 15+ points this week · 30-45 DTE · .40-.50 Delta · Never roll · Sell the double">
            <BurstAlerts bursts={bursts} />
          </Panel>
        )}

        {/* FUND FLOWS */}
        {!loading && tab === "flows" && (
          <Panel title="ICI Fund Flows" subtitle="Weekly estimated fund flows · Source: ICI.org"
            action={<div style={{ fontSize:10, color:"#444" }}>Data as of most recent entry</div>}>
            <FundFlowsPanel flows={flows} onAddFlow={fetchAll} />
          </Panel>
        )}

        {/* WATCHLIST */}
        {!loading && tab === "watchlist" && (
          <Panel title="Watchlist Manager" subtitle="Add tickers and assign sectors for accurate Flow Score calculation">
            <WatchlistManager watchlist={watchlist} onRefresh={fetchAll} />
          </Panel>
        )}
      </div>

      {showSettings && <Settings onClose={() => setShowSettings(false)} />}
    </div>
  );
}
