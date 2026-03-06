import { useState, useEffect, useCallback } from "react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:5000";

// ============================================================
// UTILITIES
// ============================================================
function tvLink(ticker) {
  return `https://www.tradingview.com/chart/?symbol=${ticker}`;
}

function scoreColor(score) {
  if (score >= 80) return "#00d4aa";
  if (score >= 65) return "#7fff7f";
  if (score >= 50) return "#ffd700";
  if (score >= 35) return "#ff9944";
  return "#ff4444";
}

function gradeColor(grade) {
  return { A: "#00d4aa", B: "#7fff7f", C: "#ffd700", D: "#ff9944", F: "#ff4444" }[grade] || "#888";
}

function fmt(num, decimals = 1) {
  return Number(num || 0).toFixed(decimals);
}

function perfColor(val) {
  if (val > 5) return "#00d4aa";
  if (val > 0) return "#7fff7f";
  if (val > -5) return "#ff9944";
  return "#ff4444";
}

function btnStyle(bg, color) {
  return {
    background: bg, border: "none", borderRadius: 6, padding: "10px 16px",
    color, fontFamily: "monospace", fontSize: 11, fontWeight: 700,
    cursor: "pointer", letterSpacing: 1, transition: "opacity 0.2s",
    whiteSpace: "nowrap"
  };
}

// ============================================================
// SHARED COMPONENTS
// ============================================================
function ScoreRing({ score, grade }) {
  const radius = 40;
  const circumference = 2 * Math.PI * radius;
  const filled = (score / 100) * circumference;
  const color = scoreColor(score);
  return (
    <div style={{ position: "relative", width: 100, height: 100, flexShrink: 0 }}>
      <svg width={100} height={100} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={50} cy={50} r={radius} fill="none" stroke="#1a1a2e" strokeWidth={8} />
        <circle cx={50} cy={50} r={radius} fill="none" stroke={color} strokeWidth={8}
          strokeDasharray={`${filled} ${circumference - filled}`} strokeLinecap="round"
          style={{ transition: "stroke-dasharray 0.8s ease" }} />
      </svg>
      <div style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%",
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        <span style={{ fontSize: 22, fontWeight: 900, color, fontFamily: "monospace" }}>{fmt(score, 0)}</span>
        <span style={{ fontSize: 13, color, fontWeight: 700 }}>{grade}</span>
      </div>
    </div>
  );
}

function SignalBar({ label, score, detail, weight }) {
  const color = scoreColor(score);
  return (
    <div style={{ marginBottom: 10, padding: "10px 12px", background: "#070714",
      borderRadius: 6, border: "1px solid #1a1a2e" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <span style={{ fontSize: 12, color: "#ccc", letterSpacing: 1, fontWeight: 600 }}>
          {label}
          <span style={{ color: "#666", fontSize: 10, marginLeft: 6 }}>·{weight}%</span>
        </span>
        <span style={{ fontSize: 20, color, fontWeight: 900, fontFamily: "monospace",
          textShadow: `0 0 10px ${color}88` }}>{score}</span>
      </div>
      <div style={{ background: "#0a0a18", borderRadius: 4, height: 8, overflow: "hidden" }}>
        <div style={{ background: `linear-gradient(90deg, ${color}88, ${color})`,
          width: `${score}%`, height: "100%", borderRadius: 4,
          transition: "width 0.6s ease", boxShadow: `0 0 8px ${color}66` }} />
      </div>
      {detail && <div style={{ fontSize: 10, color: "#aaa", marginTop: 5 }}>{detail}</div>}
    </div>
  );
}

// ============================================================
// SCORES TAB COMPONENTS
// ============================================================
const SIGNAL_LABELS = {
  capital_flow: "Capital Flow", trend: "Trend", momentum: "Momentum",
};
const SIGNAL_WEIGHTS = { capital_flow: 40, trend: 30, momentum: 30 };

function TickerCard({ data, onClick, isSelected }) {
  const { ticker, flow_score, rating, label, price, pillars = {} } = data;
  const parsedPillars = typeof pillars === "string" ? JSON.parse(pillars) : pillars;

  return (
    <div onClick={() => onClick(data)}
      style={{ background: isSelected ? "#0f0f28" : "#0a0a18",
        border: `1px solid ${isSelected ? "#00d4aa44" : "#1a1a2e"}`,
        borderRadius: 8, padding: 20, cursor: "pointer", transition: "all 0.2s ease",
        boxShadow: isSelected ? "0 0 20px #00d4aa22" : "none" }}
      onMouseEnter={e => e.currentTarget.style.borderColor = "#00d4aa44"}
      onMouseLeave={e => e.currentTarget.style.borderColor = isSelected ? "#00d4aa44" : "#1a1a2e"}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
        <ScoreRing score={flow_score || 0} grade={rating || "F"} />
        <div style={{ flex: 1 }}>
          <a href={tvLink(ticker)} target="_blank" rel="noreferrer"
            style={{ fontSize: 22, fontWeight: 900, color: "#00d4aa", fontFamily: "monospace",
              textDecoration: "none", display: "block" }}
            onMouseEnter={e => e.currentTarget.style.textDecoration = "underline"}
            onMouseLeave={e => e.currentTarget.style.textDecoration = "none"}>
            {ticker} ↗
          </a>
          <div style={{ fontSize: 13, color: "#888" }}>${fmt(price, 2)}</div>
          <div style={{ display: "inline-block", marginTop: 6, padding: "2px 8px",
            background: `${gradeColor(rating)}22`, borderRadius: 4,
            fontSize: 11, color: gradeColor(rating), fontWeight: 700, letterSpacing: 1 }}>{label}</div>
        </div>
      </div>
      <div>
        {Object.entries(SIGNAL_LABELS).map(([key, labelText]) => {
          const s = parsedPillars[key] || {};
          return <SignalBar key={key} label={labelText} score={s.score || 0}
            detail={s.detail || ""} weight={SIGNAL_WEIGHTS[key]} />;
        })}
      </div>
    </div>
  );
}

function HistoryChart({ ticker }) {
  const [history, setHistory] = useState([]);
  useEffect(() => {
    if (!ticker) return;
    fetch(`${API_BASE}/api/scores/history/${ticker}`).then(r => r.json()).then(setHistory).catch(() => {});
  }, [ticker]);
  if (!history.length) return (
    <div style={{ color: "#888", textAlign: "center", padding: 32, fontSize: 12 }}>No history yet</div>
  );
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={history} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
        <CartesianGrid stroke="#1a1a2e" strokeDasharray="3 3" />
        <XAxis dataKey="date" tick={{ fill: "#555", fontSize: 10 }} tickFormatter={d => d.slice(5)} />
        <YAxis domain={[0, 100]} tick={{ fill: "#555", fontSize: 10 }} />
        <Tooltip contentStyle={{ background: "#0a0a18", border: "1px solid #1a1a2e", borderRadius: 6 }}
          labelStyle={{ color: "#888" }} itemStyle={{ color: "#00d4aa" }} />
        <Line type="monotone" dataKey="flow_score" stroke="#00d4aa" strokeWidth={2}
          dot={{ fill: "#00d4aa", r: 3 }} name="Score" />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ============================================================
// SCANNER TAB COMPONENTS
// ============================================================
function SectorCard({ sector, isSelected, onClick }) {
  const color = sector.above_200ma ? "#00d4aa" : "#ff4444";
  return (
    <div onClick={onClick}
      style={{ background: isSelected ? "#0f0f28" : "#0a0a18",
        border: `1px solid ${isSelected ? "#00d4aa44" : "#1a1a2e"}`,
        borderRadius: 8, padding: 20, cursor: "pointer", transition: "all 0.2s ease" }}
      onMouseEnter={e => e.currentTarget.style.borderColor = "#00d4aa44"}
      onMouseLeave={e => e.currentTarget.style.borderColor = isSelected ? "#00d4aa44" : "#1a1a2e"}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 11, color: "#aaa", letterSpacing: 2, textTransform: "uppercase", marginBottom: 4 }}>
            {sector.etf}
          </div>
          <div style={{ fontSize: 18, fontWeight: 900, color: "#fff" }}>{sector.sector}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 11, color, fontWeight: 700, letterSpacing: 1 }}>
            {sector.above_200ma ? "▲ ABOVE 200MA" : "▼ BELOW 200MA"}
          </div>
          <div style={{ fontSize: 20, fontWeight: 900, color, fontFamily: "monospace", marginTop: 4 }}>
            {sector.pct_from_200ma > 0 ? "+" : ""}{fmt(sector.pct_from_200ma)}%
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 20, marginTop: 16 }}>
        <div>
          <div style={{ fontSize: 10, color: "#888", letterSpacing: 1 }}>PRICE</div>
          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "monospace", color: "#fff" }}>
            ${fmt(sector.price, 2)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#888", letterSpacing: 1 }}>200MA</div>
          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "monospace", color: "#888" }}>
            ${fmt(sector.ma200, 2)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#888", letterSpacing: 1 }}>3M PERF</div>
          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "monospace", color: perfColor(sector.perf_3m) }}>
            {sector.perf_3m > 0 ? "+" : ""}{fmt(sector.perf_3m)}%
          </div>
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#888", letterSpacing: 1 }}>1M PERF</div>
          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "monospace", color: perfColor(sector.perf_1m) }}>
            {sector.perf_1m > 0 ? "+" : ""}{fmt(sector.perf_1m)}%
          </div>
        </div>
      </div>
    </div>
  );
}

function StockRow({ stock, rank, sector, onAdd, added }) {
  const rsColor = perfColor(stock.rs_vs_etf);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "32px 80px 1fr 60px 80px 80px 80px 80px 60px 80px",
      gap: 12, padding: "12px 16px", borderBottom: "1px solid #0f0f1e",
      alignItems: "center", transition: "background 0.15s" }}
      onMouseEnter={e => e.currentTarget.style.background = "#0a0a18"}
      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
      <div style={{ fontSize: 13, color: "#888", fontFamily: "monospace" }}>{rank}</div>
      <div>
        <a href={tvLink(stock.ticker)} target="_blank" rel="noreferrer"
          style={{ fontSize: 14, fontWeight: 900, color: "#00d4aa", fontFamily: "monospace",
            textDecoration: "none" }}
          onMouseEnter={e => e.currentTarget.style.textDecoration = "underline"}
          onMouseLeave={e => e.currentTarget.style.textDecoration = "none"}>
          {stock.ticker} ↗
        </a>
        <div style={{ fontSize: 9, color: "#aaa", marginTop: 1 }}>${fmt(stock.price, 2)}</div>
      </div>
      <div style={{ fontSize: 12, color: "#888", overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
        {stock.name}
      </div>
      <div style={{ textAlign: "center" }}>
        {stock.flow_score != null ? (
          <div style={{ fontSize: 13, fontWeight: 900, fontFamily: "monospace",
            color: scoreColor(stock.flow_score) }}>{fmt(stock.flow_score, 0)}</div>
        ) : (
          <div style={{ fontSize: 10, color: "#555" }}>—</div>
        )}
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "monospace", color: rsColor }}>
          {stock.rs_vs_etf > 0 ? "+" : ""}{fmt(stock.rs_vs_etf)}%
        </div>
        <div style={{ fontSize: 10, color: "#888" }}>RS vs ETF</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 12, fontFamily: "monospace", color: perfColor(stock.perf_3m) }}>
          {stock.perf_3m > 0 ? "+" : ""}{fmt(stock.perf_3m)}%
        </div>
        <div style={{ fontSize: 9, color: "#888" }}>3M</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 12, fontFamily: "monospace", color: perfColor(stock.perf_1m) }}>
          {stock.perf_1m > 0 ? "+" : ""}{fmt(stock.perf_1m)}%
        </div>
        <div style={{ fontSize: 9, color: "#888" }}>1M</div>
      </div>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 11, fontWeight: 700,
          color: stock.above_200ma ? "#00d4aa" : "#ff4444",
          background: stock.above_200ma ? "#00d4aa11" : "#ff444411",
          padding: "2px 6px", borderRadius: 4 }}>
          {stock.above_200ma ? "▲200" : "▼200"}
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 13, fontFamily: "monospace", color: "#888" }}>${fmt(stock.mktcap_b, 1)}B</div>
        <div style={{ fontSize: 9, color: "#888" }}>MKTCAP</div>
      </div>
      <div style={{ textAlign: "center" }}>
        <button
          onClick={e => { e.stopPropagation(); onAdd(stock.ticker, sector); }}
          disabled={added}
          style={{ fontSize: 11, fontWeight: 700, cursor: added ? "default" : "pointer",
            color: added ? "#00d4aa" : "#888",
            background: added ? "#00d4aa11" : "#1a1a2e",
            border: `1px solid ${added ? "#00d4aa44" : "#2a2a3e"}`,
            borderRadius: 4, padding: "4px 8px", fontFamily: "monospace" }}>
          {added ? "✓" : "+ WL"}
        </button>
      </div>
    </div>
  );
}

function UnusualActivityBadge({ item }) {
  const color = item.bias === "bullish" ? "#00d4aa" : "#ff4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 16px",
      background: "#0a0a18", border: `1px solid ${color}22`, borderRadius: 6, marginBottom: 8 }}>
      <div style={{ fontSize: 16, fontWeight: 900, fontFamily: "monospace", color: "#fff", minWidth: 60 }}>
        {item.ticker}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 10, color: "#aaa" }}>
          Vol: {item.total_volume?.toLocaleString()} · OI: {item.total_oi?.toLocaleString()}
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 13, fontWeight: 900, fontFamily: "monospace", color }}>
          {fmt(item.vol_oi_ratio)}x
        </div>
        <div style={{ fontSize: 9, color, fontWeight: 700, letterSpacing: 1 }}>
          {item.bias?.toUpperCase()}
        </div>
      </div>
    </div>
  );
}

function ScannerTab({ watchlistTickers = new Set(), onWatchlistChange }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [scanStatus, setScanStatus] = useState(null);
  const [selectedSector, setSelectedSector] = useState(null);
  const [lastRun, setLastRun] = useState(null);
  const addToWatchlist = async (ticker, sector) => {
    try {
      await fetch(`${API_BASE}/api/watchlist`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, sector: sector || "" })
      });
      if (onWatchlistChange) onWatchlistChange();
    } catch (e) { console.error(e); }
  };

  const fetchResults = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/scanner/results`);
      const json = await res.json();
      if (json.success && json.data) {
        setData(json.data);
        setLastRun(json.data.run_at);
        if (json.data.top_sectors?.length > 0) {
          setSelectedSector(prev => prev || json.data.top_sectors[0].sector);
        }
        return json.data;
      }
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
    return null;
  }, []);

  useEffect(() => { fetchResults(); }, [fetchResults]);

  const runScan = async () => {
    setRunning(true);
    setScanStatus("Scanning sectors...");
    try {
      await fetch(`${API_BASE}/api/scanner/run`, { method: "POST" });
      // Poll every 15s for up to 3 min — scanner returns quickly, scoring takes ~2 min
      let attempts = 0;
      const poll = setInterval(async () => {
        attempts++;
        if (attempts <= 1) setScanStatus("Fetching stocks...");
        else setScanStatus(`Scoring top stocks... (${attempts * 15}s)`);
        const latest = await fetchResults();
        const hasScores = Object.values(latest?.sector_stocks || {})
          .flat().some(s => s.flow_score != null);
        if (hasScores || attempts >= 12) {
          clearInterval(poll);
          setRunning(false);
          setScanStatus(null);
        }
      }, 15000);
    } catch (e) { setRunning(false); setScanStatus(null); }
  };

  const stocks = selectedSector && data?.sector_stocks?.[selectedSector] || [];
  const unusual = data?.unusual_activity || [];

  return (
    <div>
      {/* Scanner header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 11, color: "#aaa", letterSpacing: 2, textTransform: "uppercase" }}>
            Market Scanner
          </div>
          {lastRun && (
            <div style={{ fontSize: 10, color: "#888", marginTop: 4 }}>
              Last run: {new Date(lastRun).toLocaleString()}
            </div>
          )}
        </div>
        <button onClick={runScan} disabled={running} style={btnStyle(running ? "#1a1a2e" : "#00d4aa", running ? "#555" : "#000")}>
          {running ? "⟳ Scanning..." : "▶ Market Scanner"}
        </button>
      </div>

      {loading && (
        <div style={{ textAlign: "center", color: "#00d4aa", padding: 60, fontSize: 12, letterSpacing: 2 }}>
          Loading scanner results...
        </div>
      )}

      {!loading && !data && (
        <div style={{ textAlign: "center", padding: 80 }}>
          <div style={{ fontSize: 14, color: "#aaa", marginBottom: 16 }}>No scanner results yet</div>
          <div style={{ fontSize: 11, color: "#888", marginBottom: 24 }}>Click "Market Scanner" to find top sectors and stocks</div>
          <button onClick={runScan} style={btnStyle("#00d4aa", "#000")}>▶ Market Scanner</button>
        </div>
      )}

      {!loading && data && (
        <div style={{ display: "grid", gridTemplateColumns: unusual.length > 0 ? "1fr 280px" : "1fr", gap: 24 }}>
          <div>
            {/* Top sectors */}
            <div style={{ fontSize: 11, color: "#aaa", letterSpacing: 2, marginBottom: 12 }}>
              TOP SECTORS — ABOVE 200MA
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12, marginBottom: 28 }}>
              {data.top_sectors?.map(s => (
                <SectorCard key={s.sector} sector={s}
                  isSelected={selectedSector === s.sector}
                  onClick={() => setSelectedSector(s.sector)} />
              ))}
            </div>

            {/* Stock table */}
            {selectedSector && (
              <>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <div style={{ fontSize: 11, color: "#aaa", letterSpacing: 2 }}>
                    TOP 25 — {selectedSector.toUpperCase()} · RANKED BY RS vs ETF
                  </div>
                  <div style={{ fontSize: 10, color: "#888" }}>{stocks.length} stocks</div>
                </div>

                <div style={{ background: "#0a0a18", border: "1px solid #1a1a2e", borderRadius: 8, overflow: "hidden" }}>
                  {/* Table header */}
                  <div style={{ display: "grid", gridTemplateColumns: "32px 80px 1fr 60px 80px 80px 80px 80px 60px 80px",
                    gap: 12, padding: "10px 16px", borderBottom: "1px solid #1a1a2e",
                    background: "#0d0d1a" }}>
                    {["#", "TICKER", "NAME", "SCORE", "RS vs ETF", "3M", "1M", "MA", "MKTCAP", ""].map(h => (
                      <div key={h} style={{ fontSize: 10, color: "#888", letterSpacing: 1,
                        textAlign: ["RS vs ETF", "3M", "1M", "MKTCAP"].includes(h) ? "right" : "center" === h ? "center" : "left" }}>
                        {h}
                      </div>
                    ))}
                  </div>
                  {stocks.length === 0 ? (
                    <div style={{ padding: 32, textAlign: "center", color: "#888", fontSize: 12 }}>No stocks found</div>
                  ) : (
                    stocks.map((s, i) => <StockRow key={s.ticker} stock={s} rank={i + 1} sector={selectedSector} onAdd={addToWatchlist} added={watchlistTickers.has(s.ticker)} />)
                  )}
                </div>
              </>
            )}
          </div>

          {/* Unusual activity panel */}
          {unusual.length > 0 && (
            <div>
              <div style={{ fontSize: 11, color: "#aaa", letterSpacing: 2, marginBottom: 12 }}>
                ⚡ UNUSUAL OPTIONS ACTIVITY
              </div>
              <div style={{ background: "#0a0a18", border: "1px solid #1a1a2e", borderRadius: 8, padding: 16 }}>
                <div style={{ fontSize: 10, color: "#888", marginBottom: 12, lineHeight: 1.6 }}>
                  Vol/OI ratio {'>'} 2.0 · New money signal
                </div>
                {unusual.map(item => <UnusualActivityBadge key={item.ticker} item={item} />)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================
// MAIN APP
// ============================================================
export default function App() {
  const [scores, setScores] = useState([]);
  const [watchlist, setWatchlist] = useState([]);
  const [selectedTicker, setSelectedTicker] = useState(null);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [newTicker, setNewTicker] = useState("");
  const [newSector, setNewSector] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [tab, setTab] = useState("scores");

  const fetchScores = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/scores/latest`);
      const data = await res.json();
      setScores(data);
      setLastUpdated(new Date());
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  const fetchWatchlist = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/watchlist`);
      setWatchlist(await res.json());
    } catch (e) {}
  }, []);

  useEffect(() => { fetchScores(); fetchWatchlist(); }, [fetchScores, fetchWatchlist]);

  const addTicker = async () => {
    if (!newTicker.trim()) return;
    await fetch(`${API_BASE}/api/watchlist`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: newTicker.trim().toUpperCase(), sector: newSector.trim() })
    });
    setNewTicker(""); setNewSector(""); fetchWatchlist();
  };

  const removeTicker = async (ticker) => {
    await fetch(`${API_BASE}/api/watchlist/${ticker}`, { method: "DELETE" });
    fetchWatchlist();
  };

  const runScan = async () => {
    setScanning(true);
    try {
      await fetch(`${API_BASE}/api/scan/weekly`, { method: "POST" });
      setTimeout(async () => { await fetchScores(); setScanning(false); }, 3000);
    } catch (e) { setScanning(false); }
  };

  const tabs = [
    { id: "scores", label: `Scores (${scores.length})` },
    { id: "scanner", label: "Scanner" },
    { id: "watchlist", label: `Watchlist (${watchlist.length})` },
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#0d0d1a",
      fontFamily: "'Courier New', 'Lucida Console', monospace", color: "#fff" }}>

      {/* Header */}
      <div style={{ borderBottom: "1px solid #1a1a2e", padding: "20px 32px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        background: "#0a0a18", position: "sticky", top: 0, zIndex: 100 }}>
        <div>
          <div style={{ fontSize: 10, color: "#00d4aa", letterSpacing: 4, textTransform: "uppercase" }}>
            Flow Score Tracker
          </div>
          <div style={{ fontSize: 18, fontWeight: 900, color: "#fff" }}>Market Intelligence Dashboard</div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {lastUpdated && (
            <div style={{ fontSize: 10, color: "#888", marginRight: 8 }}>
              Updated {lastUpdated.toLocaleTimeString()}
            </div>
          )}
          <button onClick={() => window.open(`${API_BASE}/api/export/scores`, "_blank")} style={btnStyle("#1a1a2e", "#888")}>↓ CSV</button>
          <button onClick={runScan} disabled={scanning} style={btnStyle(scanning ? "#1a1a2e" : "#00d4aa", scanning ? "#555" : "#000")}>
            {scanning ? "Scoring..." : "▶ Score Watchlist"}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ padding: "0 32px", borderBottom: "1px solid #1a1a2e", background: "#0a0a18" }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            background: "none", border: "none", padding: "14px 20px",
            color: tab === t.id ? "#00d4aa" : "#555", cursor: "pointer",
            fontSize: 11, letterSpacing: 2, textTransform: "uppercase", fontFamily: "monospace",
            borderBottom: tab === t.id ? "2px solid #00d4aa" : "2px solid transparent",
            fontWeight: tab === t.id ? 700 : 400,
          }}>{t.label}</button>
        ))}
      </div>

      <div style={{ padding: 32 }}>

        {/* SCORES TAB */}
        {tab === "scores" && (
          <>
            {loading && (
              <div style={{ textAlign: "center", color: "#00d4aa", padding: 60, fontSize: 12, letterSpacing: 2 }}>
                Loading scores...
              </div>
            )}
            {!loading && scores.length === 0 && (
              <div style={{ textAlign: "center", padding: 80 }}>
                <div style={{ fontSize: 14, color: "#aaa", marginBottom: 16 }}>No scores yet</div>
                <div style={{ fontSize: 11, color: "#888", marginBottom: 24 }}>Add tickers to watchlist, then run a scan</div>
                <button onClick={() => setTab("watchlist")} style={btnStyle("#00d4aa", "#000")}>Add Tickers →</button>
              </div>
            )}
            {scores.length > 0 && (
              <div style={{ display: "grid", gridTemplateColumns: selectedTicker ? "1fr 380px" : "repeat(auto-fill, minmax(380px, 1fr))", gap: 20 }}>
                <div style={{ display: "grid", gridTemplateColumns: selectedTicker ? "1fr" : "repeat(auto-fill, minmax(380px, 1fr))", gap: 20, alignContent: "start" }}>
                  {scores.map(d => (
                    <TickerCard key={d.ticker} data={d}
                      onClick={t => setSelectedTicker(selectedTicker?.ticker === t.ticker ? null : t)}
                      isSelected={selectedTicker?.ticker === d.ticker} />
                  ))}
                </div>
                {selectedTicker && (
                  <div style={{ background: "#0a0a18", border: "1px solid #1a1a2e", borderRadius: 8, padding: 24, alignSelf: "start", position: "sticky", top: 100 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 20 }}>
                      <div>
                        <div style={{ fontSize: 10, color: "#00d4aa", letterSpacing: 3, textTransform: "uppercase" }}>Detail View</div>
                        <div style={{ fontSize: 22, fontWeight: 900, color: "#fff" }}>{selectedTicker.ticker}</div>
                      </div>
                      <button onClick={() => setSelectedTicker(null)} style={{ background: "none", border: "none", color: "#aaa", cursor: "pointer", fontSize: 18 }}>✕</button>
                    </div>
                    <div style={{ fontSize: 11, color: "#aaa", marginBottom: 12, letterSpacing: 2, textTransform: "uppercase" }}>Score History</div>
                    <HistoryChart ticker={selectedTicker.ticker} />
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {/* SCANNER TAB */}
        {tab === "scanner" && <ScannerTab watchlistTickers={new Set(watchlist.map(w => w.ticker))} onWatchlistChange={fetchWatchlist} />}

        {/* WATCHLIST TAB */}
        {tab === "watchlist" && (
          <div style={{ maxWidth: 600 }}>
            <div style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 11, color: "#aaa", marginBottom: 12, letterSpacing: 2 }}>ADD TICKER</div>
              <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
                <input value={newTicker} onChange={e => setNewTicker(e.target.value.toUpperCase())}
                  onKeyDown={e => e.key === "Enter" && addTicker()} placeholder="Ticker (e.g. NVDA)"
                  style={{ flex: 1, background: "#0a0a18", border: "1px solid #1a1a2e", borderRadius: 6,
                    padding: "12px 16px", color: "#fff", fontFamily: "monospace", fontSize: 14, outline: "none" }} />
                <input value={newSector} onChange={e => setNewSector(e.target.value)}
                  placeholder="Sector (optional)"
                  style={{ flex: 1, background: "#0a0a18", border: "1px solid #1a1a2e", borderRadius: 6,
                    padding: "12px 16px", color: "#fff", fontFamily: "monospace", fontSize: 14, outline: "none" }} />
                <button onClick={addTicker} style={btnStyle("#00d4aa", "#000")}>Add</button>
              </div>
            </div>
            {watchlist.length === 0 && (
              <div style={{ color: "#888", fontSize: 12, padding: "32px 0" }}>No tickers yet.</div>
            )}
            {watchlist.map(w => (
              <div key={w.ticker} style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "14px 16px", background: "#0a0a18", border: "1px solid #1a1a2e",
                borderRadius: 6, marginBottom: 8 }}>
                <div>
                  <a href={tvLink(w.ticker)} target="_blank" rel="noreferrer"
                    style={{ fontSize: 16, fontWeight: 700, color: "#00d4aa", fontFamily: "monospace",
                      textDecoration: "none" }}
                    onMouseEnter={e => e.currentTarget.style.textDecoration = "underline"}
                    onMouseLeave={e => e.currentTarget.style.textDecoration = "none"}>
                    {w.ticker} ↗
                  </a>
                  {w.sector && <span style={{ fontSize: 11, color: "#aaa", marginLeft: 12 }}>{w.sector}</span>}
                </div>
                <button onClick={() => removeTicker(w.ticker)}
                  style={{ background: "none", border: "1px solid #2a1a1a", borderRadius: 4, color: "#ff4444", cursor: "pointer", padding: "4px 10px", fontSize: 11 }}>
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
