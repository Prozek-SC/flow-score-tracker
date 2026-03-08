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
    color, fontFamily: "'Inter', sans-serif", fontSize: 13, fontWeight: 600,
    cursor: "pointer", letterSpacing: 0, transition: "opacity 0.2s",
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
        <span style={{ fontSize: 22, fontWeight: 900, color, fontFamily: "'Inter', sans-serif" }}>{fmt(score, 0)}</span>
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
        <span style={{ fontSize: 12, color: "#ccc", letterSpacing: 0.1, fontWeight: 600 }}>
          {label}
          <span style={{ color: "#666", fontSize: 12, marginLeft: 6 }}>·{weight}%</span>
        </span>
        <span style={{ fontSize: 20, color, fontWeight: 900, fontFamily: "'Inter', sans-serif",
          textShadow: `0 0 10px ${color}88` }}>{score}</span>
      </div>
      <div style={{ background: "#0a0a18", borderRadius: 4, height: 8, overflow: "hidden" }}>
        <div style={{ background: `linear-gradient(90deg, ${color}88, ${color})`,
          width: `${score}%`, height: "100%", borderRadius: 4,
          transition: "width 0.6s ease", boxShadow: `0 0 8px ${color}66` }} />
      </div>
      {detail && <div style={{ fontSize: 12, color: "#aaa", marginTop: 5 }}>{detail}</div>}
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
            style={{ fontSize: 22, fontWeight: 900, color: "#00d4aa", fontFamily: "'Inter', sans-serif",
              textDecoration: "none", display: "block" }}
            onMouseEnter={e => e.currentTarget.style.textDecoration = "underline"}
            onMouseLeave={e => e.currentTarget.style.textDecoration = "none"}>
            {ticker} ↗
          </a>
          <div style={{ fontSize: 13, color: "#888" }}>${fmt(price, 2)}</div>
          <div style={{ display: "inline-block", marginTop: 6, padding: "2px 8px",
            background: `${gradeColor(rating)}22`, borderRadius: 4,
            fontSize: 11, color: gradeColor(rating), fontWeight: 700, letterSpacing: 0 }}>{label}</div>
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
        <XAxis dataKey="date" tick={{ fill: "#555", fontSize: 11 }} tickFormatter={d => d.slice(5)} />
        <YAxis domain={[0, 100]} tick={{ fill: "#555", fontSize: 11 }} />
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
          <div style={{ fontSize: 11, color: "#aaa", letterSpacing: 0.2, textTransform: "uppercase", marginBottom: 4 }}>
            {sector.etf}
          </div>
          <div style={{ fontSize: 18, fontWeight: 900, color: "#fff" }}>{sector.sector}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 11, color, fontWeight: 700, letterSpacing: 0 }}>
            {sector.above_200ma ? "▲ ABOVE 200MA" : "▼ BELOW 200MA"}
          </div>
          <div style={{ fontSize: 20, fontWeight: 900, color, fontFamily: "'Inter', sans-serif", marginTop: 4 }}>
            {sector.pct_from_200ma > 0 ? "+" : ""}{fmt(sector.pct_from_200ma)}%
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 20, marginTop: 16 }}>
        <div>
          <div style={{ fontSize: 12, color: "#888", letterSpacing: 0 }}>PRICE</div>
          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "'Inter', sans-serif", color: "#fff" }}>
            ${fmt(sector.price, 2)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: "#888", letterSpacing: 0 }}>200MA</div>
          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "'Inter', sans-serif", color: "#888" }}>
            ${fmt(sector.ma200, 2)}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: "#888", letterSpacing: 0 }}>3M PERF</div>
          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "'Inter', sans-serif", color: perfColor(sector.perf_3m) }}>
            {sector.perf_3m > 0 ? "+" : ""}{fmt(sector.perf_3m)}%
          </div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: "#888", letterSpacing: 0 }}>1M PERF</div>
          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "'Inter', sans-serif", color: perfColor(sector.perf_1m) }}>
            {sector.perf_1m > 0 ? "+" : ""}{fmt(sector.perf_1m)}%
          </div>
        </div>
      </div>
    </div>
  );
}

function StockRow({ stock, rank, sector, onAdd, added, showSector = false, accentColor = "#00d4aa" }) {
  const rsColor = perfColor(stock.rs_vs_etf);
  const nameOrSector = showSector
    ? (stock.sector || "—")
    : (stock.name || stock.ticker);

  return (
    <div style={{ display: "grid",
      gridTemplateColumns: showSector
        ? "36px 90px 1fr 80px 70px 80px 80px 80px 70px 90px"
        : "36px 90px 1fr 80px 80px 80px 80px 80px 70px 90px",
      gap: 10, padding: "14px 18px", borderBottom: "1px solid #0f0f1e",
      alignItems: "center", transition: "background 0.15s" }}
      onMouseEnter={e => e.currentTarget.style.background = "#0a0a18"}
      onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
      {/* Rank */}
      <div style={{ fontSize: 14, color: "#888", fontFamily: "'Inter', sans-serif" }}>{rank}</div>

      {/* Ticker + price */}
      <div>
        <a href={tvLink(stock.ticker)} target="_blank" rel="noreferrer"
          style={{ fontSize: 15, fontWeight: 900, color: accentColor, fontFamily: "'Inter', sans-serif", textDecoration: "none" }}
          onMouseEnter={e => e.currentTarget.style.textDecoration = "underline"}
          onMouseLeave={e => e.currentTarget.style.textDecoration = "none"}>
          {stock.ticker} ↗
        </a>
        <div style={{ fontSize: 12, color: "#888", marginTop: 2 }}>${fmt(stock.price, 2)}</div>
      </div>

      {/* Name or Sector */}
      <div style={{ fontSize: 13, color: "#888", overflow: "hidden", whiteSpace: "nowrap", textOverflow: "ellipsis" }}>
        {nameOrSector}
      </div>

      {/* Flow score */}
      <div style={{ textAlign: "right" }}>
        {stock.flow_score != null ? (
          <div style={{ fontSize: 15, fontWeight: 900, fontFamily: "'Inter', sans-serif", color: scoreColor(stock.flow_score) }}>
            {fmt(stock.flow_score, 0)}
          </div>
        ) : (
          <div style={{ fontSize: 12, color: "#444" }}>—</div>
        )}
      </div>

      {/* RS vs ETF (or 3M for BBS) */}
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 15, fontWeight: 700, fontFamily: "'Inter', sans-serif", color: rsColor }}>
          {stock.rs_vs_etf > 0 ? "+" : ""}{fmt(stock.rs_vs_etf)}%
        </div>
      </div>

      {/* 3M perf */}
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 15, fontFamily: "'Inter', sans-serif", color: perfColor(stock.perf_3m) }}>
          {stock.perf_3m > 0 ? "+" : ""}{fmt(stock.perf_3m)}%
        </div>
        <div style={{ fontSize: 11, color: "#666" }}>3M</div>
      </div>

      {/* 1M perf */}
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 15, fontFamily: "'Inter', sans-serif", color: perfColor(stock.perf_1m) }}>
          {stock.perf_1m > 0 ? "+" : ""}{fmt(stock.perf_1m)}%
        </div>
        <div style={{ fontSize: 11, color: "#666" }}>1M</div>
      </div>

      {/* MA badge */}
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 12, fontWeight: 700,
          color: stock.above_200ma ? "#00d4aa" : "#ff4444",
          background: stock.above_200ma ? "#00d4aa11" : "#ff444411",
          padding: "3px 8px", borderRadius: 4 }}>
          {stock.above_200ma ? "▲200" : "▼200"}
        </div>
      </div>

      {/* Market cap */}
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 15, fontFamily: "'Inter', sans-serif", color: "#aaa" }}>${fmt(stock.mktcap_b, 1)}B</div>
      </div>

      {/* Add to watchlist */}
      <div style={{ textAlign: "center" }}>
        <button
          onClick={e => { e.stopPropagation(); onAdd(stock.ticker, sector); }}
          disabled={added}
          style={{ fontSize: 12, fontWeight: 700, cursor: added ? "default" : "pointer",
            color: added ? accentColor : "#888",
            background: added ? accentColor + "11" : "#1a1a2e",
            border: `1px solid ${added ? accentColor + "44" : "#2a2a3e"}`,
            borderRadius: 4, padding: "5px 10px", fontFamily: "'Inter', sans-serif" }}>
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
      <div style={{ fontSize: 16, fontWeight: 900, fontFamily: "'Inter', sans-serif", color: "#fff", minWidth: 60 }}>
        {item.ticker}
      </div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, color: "#aaa" }}>
          Vol: {item.total_volume?.toLocaleString()} · OI: {item.total_oi?.toLocaleString()}
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 13, fontWeight: 900, fontFamily: "'Inter', sans-serif", color }}>
          {fmt(item.vol_oi_ratio)}x
        </div>
        <div style={{ fontSize: 11, color, fontWeight: 700, letterSpacing: 0 }}>
          {item.bias?.toUpperCase()}
        </div>
      </div>
    </div>
  );
}

function ScannerTab({ scannerType = "breakout", watchlistTickers = new Set(), onWatchlistChange }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [scanStatus, setScanStatus] = useState(null);
  const [selectedSector, setSelectedSector] = useState(null);
  const [lastRun, setLastRun] = useState(null);
  const [cacheNotice, setCacheNotice] = useState(null);

  const isBreakout = scannerType === "breakout";

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
        setLastRun(json.run_date || json.data.run_at);
        setCacheNotice(json.cache_notice || null);
        if (isBreakout && json.data.top_sectors?.length > 0) {
          setSelectedSector(prev => prev || json.data.top_sectors[0].sector);
        }
        return json.data;
      }
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
    return null;
  }, [isBreakout]);

  useEffect(() => { fetchResults(); }, [fetchResults]);

  const runScan = async () => {
    setRunning(true);
    setScanStatus("Scanning markets...");
    try {
      const runRes = await fetch(`${API_BASE}/api/scanner/run`, { method: "POST" });
      const runJson = await runRes.json();
      if (runJson.cached) {
        await fetchResults();
        setRunning(false);
        setScanStatus(null);
        return;
      }
      let attempts = 0;
      const poll = setInterval(async () => {
        attempts++;
        if (attempts <= 1) setScanStatus("Fetching stocks...");
        else setScanStatus(`Scoring top stocks... (${attempts * 15}s)`);
        const latest = await fetchResults();
        const breakoutHasScores = Object.values(latest?.sector_stocks || {}).flat().some(s => s.flow_score != null);
        const bbsHasScores = (latest?.big_blue_sky || []).some(s => s.flow_score != null);
        const hasScores = breakoutHasScores || bbsHasScores;
        if (hasScores || attempts >= 12) {
          clearInterval(poll);
          setRunning(false);
          setScanStatus(null);
        }
      }, 15000);
    } catch (e) { setRunning(false); setScanStatus(null); }
  };

  const breakoutStocks = selectedSector && data?.sector_stocks?.[selectedSector] || [];
  const bbsStocks = data?.big_blue_sky || [];
  const unusual = data?.unusual_activity || [];

  const scanLabel = isBreakout ? "50-Day Breakout Scanner" : "Big Blue Sky Scanner";
  const scanDesc = isBreakout
    ? "Top 3 sectors by 200MA strength · Optionable · Near 52W High · Above 50MA"
    : "Mid-cap & under · New 52W High · Above 50MA · Optionable";
  const accentColor = isBreakout ? "#00d4aa" : "#7b9fff";

  return (
    <div>
      {/* Scanner header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
        <div>
          <div style={{ fontSize: 20, fontWeight: 900, color: "#fff", marginBottom: 4 }}>{scanLabel}</div>
          <div style={{ fontSize: 13, color: "#888" }}>{scanDesc}</div>
          {lastRun && (
            <div style={{ fontSize: 12, color: "#555", marginTop: 4 }}>
              Last run: {new Date(lastRun).toLocaleString()}
            </div>
          )}
          {cacheNotice && (
            <div style={{ fontSize: 12, color: "#ffd700", marginTop: 6, background: "#1a1500", border: "1px solid #ffd70044", borderRadius: 6, padding: "6px 10px", display: "inline-block" }}>
              📅 {cacheNotice}
            </div>
          )}
          {scanStatus && !cacheNotice && (
            <div style={{ fontSize: 13, color: accentColor, marginTop: 6, letterSpacing: 0 }}>
              ⏳ {scanStatus}
            </div>
          )}
        </div>
        <button onClick={runScan} disabled={running}
          style={btnStyle(running ? "#1a1a2e" : accentColor, running ? "#555" : "#000")}>
          {running ? "⟳ Scanning..." : `▶ Run Scanner`}
        </button>
      </div>

      {loading && (
        <div style={{ textAlign: "center", color: accentColor, padding: 60, fontSize: 14, letterSpacing: 0 }}>
          Loading results...
        </div>
      )}

      {!loading && !data && (
        <div style={{ textAlign: "center", padding: 80 }}>
          <div style={{ fontSize: 16, color: "#aaa", marginBottom: 16 }}>No results yet</div>
          <div style={{ fontSize: 13, color: "#888", marginBottom: 24 }}>Click "Run Scanner" to start</div>
          <button onClick={runScan} style={btnStyle(accentColor, "#000")}>▶ Run Scanner</button>
        </div>
      )}

      {!loading && data && (
        <div style={{ display: "grid", gridTemplateColumns: unusual.length > 0 ? "1fr 300px" : "1fr", gap: 24 }}>
          <div>

            {/* ── 50-DAY BREAKOUT: sector cards + sector stock table ── */}
            {isBreakout && (
              <>
                <div style={{ fontSize: 12, color: "#888", letterSpacing: 0.2, marginBottom: 12, textTransform: "uppercase" }}>
                  Top Sectors — Above 200MA
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 12, marginBottom: 28 }}>
                  {data.top_sectors?.map(s => (
                    <SectorCard key={s.sector} sector={s}
                      isSelected={selectedSector === s.sector}
                      onClick={() => setSelectedSector(s.sector)} />
                  ))}
                </div>

                {selectedSector && (
                  <>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                      <div style={{ fontSize: 13, color: "#aaa", letterSpacing: 0.2, textTransform: "uppercase" }}>
                        {selectedSector} · Near 52W High · Above 50MA
                      </div>
                      <div style={{ fontSize: 12, color: "#888" }}>{breakoutStocks.length} stocks</div>
                    </div>
                    <StockTable stocks={breakoutStocks} sector={selectedSector}
                      watchlistTickers={watchlistTickers} onAdd={addToWatchlist}
                      showRsLabel="RS vs ETF" accentColor={accentColor} />
                  </>
                )}
              </>
            )}

            {/* ── BIG BLUE SKY: flat stock list ── */}
            {!isBreakout && (
              <>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <div style={{ fontSize: 13, color: "#aaa", letterSpacing: 0.2, textTransform: "uppercase" }}>
                    New 52W Highs · Mid-Cap & Under
                  </div>
                  <div style={{ fontSize: 12, color: "#888" }}>{bbsStocks.length} stocks</div>
                </div>
                {bbsStocks.length === 0 ? (
                  <div style={{ textAlign: "center", padding: "40px 0", color: "#888", fontSize: 14 }}>
                    No results yet — run the scanner
                  </div>
                ) : (
                  <StockTable stocks={bbsStocks} sector={null}
                    watchlistTickers={watchlistTickers} onAdd={addToWatchlist}
                    showRsLabel="3M Perf" accentColor={accentColor} showSector={true} />
                )}
              </>
            )}
          </div>

          {/* Unusual activity panel */}
          {unusual.length > 0 && (
            <div>
              <div style={{ fontSize: 12, color: "#aaa", letterSpacing: 0.2, marginBottom: 12, textTransform: "uppercase" }}>
                ⚡ Unusual Options Activity
              </div>
              <div style={{ background: "#0a0a18", border: "1px solid #1a1a2e", borderRadius: 8, padding: 16 }}>
                <div style={{ fontSize: 12, color: "#888", marginBottom: 12, lineHeight: 1.6 }}>
                  Vol/OI {'>'} 2.0 · New money signal
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

// Shared stock table used by both scanners
function StockTable({ stocks, sector, watchlistTickers, onAdd, showRsLabel, accentColor, showSector = false }) {
  return (
    <div style={{ background: "#0a0a18", border: "1px solid #1a1a2e", borderRadius: 8, overflow: "hidden" }}>
      <div style={{ display: "grid",
        gridTemplateColumns: showSector
          ? "36px 90px 1fr 80px 70px 80px 80px 80px 70px 90px"
          : "36px 90px 1fr 80px 80px 80px 80px 80px 70px 90px",
        gap: 10, padding: "12px 18px", borderBottom: "1px solid #1a1a2e", background: "#0d0d1a" }}>
        {["#", "TICKER", showSector ? "SECTOR" : "NAME", "SCORE", showRsLabel, "3M", "1M", "MA", "MKT CAP", ""].map((h, i) => (
          <div key={i} style={{ fontSize: 11, color: "#666", letterSpacing: 0.1, textTransform: "uppercase",
            textAlign: ["SCORE", showRsLabel, "3M", "1M", "MKT CAP"].includes(h) ? "right" : "left" }}>
            {h}
          </div>
        ))}
      </div>
      {stocks.length === 0 ? (
        <div style={{ padding: 32, textAlign: "center", color: "#888", fontSize: 14 }}>No stocks found</div>
      ) : (
        stocks.map((s, i) => (
          <StockRow key={s.ticker} stock={s} rank={i + 1} sector={sector || s.sector}
            onAdd={onAdd} added={watchlistTickers.has(s.ticker)}
            showSector={showSector} accentColor={accentColor} />
        ))
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
  const [newTicker, setNewTicker] = useState("");
  const [newSector, setNewSector] = useState("");
  const [lastUpdated, setLastUpdated] = useState(null);
  const [tab, setTab] = useState("breakout");

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

  const [scanning, setScanning] = useState(false);
  const [scanningMarket, setScanningMarket] = useState(false);

  const runScan = async () => {
    setScanning(true);
    try {
      await fetch(`${API_BASE}/api/scan/weekly`, { method: "POST" });
      setTimeout(async () => { await fetchScores(); setScanning(false); }, 3000);
    } catch (e) { setScanning(false); }
  };

  const runBothScanners = async () => {
    setScanningMarket(true);
    try {
      await fetch(`${API_BASE}/api/scanner/run`, { method: "POST" });
      // Poll until scores appear
      let attempts = 0;
      const poll = setInterval(async () => {
        attempts++;
        try {
          const res = await fetch(`${API_BASE}/api/scanner/results`);
          const json = await res.json();
          const data = json.data || {};
          const hasScores =
            Object.values(data.sector_stocks || {}).flat().some(s => s.flow_score != null) ||
            (data.big_blue_sky || []).some(s => s.flow_score != null);
          if (hasScores || attempts >= 12) {
            clearInterval(poll);
            setScanningMarket(false);
          }
        } catch { }
      }, 15000);
    } catch (e) { setScanningMarket(false); }
  };

  const tabs = [
    { id: "breakout", label: "50-Day Breakout" },
    { id: "bigbluesky", label: "Big Blue Sky" },
    { id: "scores", label: `Scores (${scores.length})` },
    { id: "watchlist", label: `Watchlist (${watchlist.length})` },
  ];

  return (
    <div style={{ minHeight: "100vh", background: "#0d0d1a",
      fontFamily: "'Inter', sans-serif", color: "#fff" }}>

      {/* Header */}
      <div style={{ borderBottom: "1px solid #1a1a2e", padding: "20px 32px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        background: "#0a0a18", position: "sticky", top: 0, zIndex: 100 }}>
        <div>
          <div style={{ fontSize: 12, color: "#00d4aa", letterSpacing: 0.5, textTransform: "uppercase" }}>
            Flow Score Tracker
          </div>
          <div style={{ fontSize: 22, fontWeight: 900, color: "#fff" }}>Market Intelligence Dashboard</div>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          {lastUpdated && (
            <div style={{ fontSize: 12, color: "#888", marginRight: 8 }}>
              Updated {lastUpdated.toLocaleTimeString()}
            </div>
          )}
          <button onClick={() => window.open(`${API_BASE}/api/export/scores`, "_blank")} style={btnStyle("#1a1a2e", "#888")}>↓ CSV</button>
          <button onClick={runBothScanners} disabled={scanningMarket}
            style={btnStyle(scanningMarket ? "#1a1a2e" : "#7b9fff", scanningMarket ? "#555" : "#000")}>
            {scanningMarket ? "⟳ Scanning..." : "▶ Run Both Scanners"}
          </button>
          <button onClick={runScan} disabled={scanning} style={btnStyle(scanning ? "#1a1a2e" : "#00d4aa", scanning ? "#555" : "#000")}>
            {scanning ? "Scoring..." : "▶ Score Watchlist"}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div style={{ padding: "0 32px", borderBottom: "1px solid #1a1a2e", background: "#0a0a18" }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            background: "none", border: "none", padding: "16px 24px",
            color: tab === t.id ? "#00d4aa" : "#666", cursor: "pointer",
            fontSize: 13, letterSpacing: 0.2, textTransform: "uppercase", fontFamily: "'Inter', sans-serif",
            borderBottom: tab === t.id ? "2px solid #00d4aa" : "2px solid transparent",
            fontWeight: tab === t.id ? 700 : 400,
          }}>{t.label}</button>
        ))}
      </div>

      <div style={{ padding: 32 }}>

        {/* 50-DAY BREAKOUT SCANNER TAB */}
        {tab === "breakout" && <ScannerTab
          scannerType="breakout"
          watchlistTickers={new Set(watchlist.map(w => w.ticker))}
          onWatchlistChange={fetchWatchlist}
        />}

        {/* BIG BLUE SKY SCANNER TAB */}
        {tab === "bigbluesky" && <ScannerTab
          scannerType="bigbluesky"
          watchlistTickers={new Set(watchlist.map(w => w.ticker))}
          onWatchlistChange={fetchWatchlist}
        />}

        {/* SCORES TAB — table view */}
        {tab === "scores" && (
          <>
            {loading && (
              <div style={{ textAlign: "center", color: "#00d4aa", padding: 60, fontSize: 14, letterSpacing: 0 }}>
                Loading scores...
              </div>
            )}
            {!loading && scores.length === 0 && (
              <div style={{ textAlign: "center", padding: 80 }}>
                <div style={{ fontSize: 16, color: "#aaa", marginBottom: 16 }}>No scores yet</div>
                <div style={{ fontSize: 13, color: "#888", marginBottom: 24 }}>Run a scanner to generate scores</div>
              </div>
            )}
            {scores.length > 0 && (
              <div>
                {/* Table header */}
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "120px 90px 80px 120px 1fr 1fr 1fr",
                  gap: 8, padding: "10px 16px",
                  borderBottom: "1px solid #1a1a2e",
                  fontSize: 11, color: "#666", letterSpacing: 0.2, textTransform: "uppercase"
                }}>
                  <div>Ticker</div>
                  <div>Score</div>
                  <div>Rating</div>
                  <div>Source</div>
                  <div>Capital Flow</div>
                  <div>Trend</div>
                  <div>Momentum</div>
                </div>
                {scores.map(d => {
                  const pillars = d.pillars || {};
                  const cf = pillars.capital_flow?.score ?? "—";
                  const tr = pillars.trend?.score ?? "—";
                  const mo = pillars.momentum?.score ?? "—";
                  const scoreColor = d.flow_score >= 80 ? "#00ff88"
                    : d.flow_score >= 70 ? "#7fff7f"
                    : d.flow_score >= 50 ? "#ffd700"
                    : d.flow_score >= 30 ? "#ff9944" : "#ff3333";

                  // Determine scanner source from watchlist sector tag or score metadata
                  const isBBS = d.rating === "BBS" || (d.sector && d.sector.includes("BBS"));
                  const sourceLabel = isBBS ? "Big Blue Sky" : "50-Day Breakout";
                  const sourceColor = isBBS ? "#7b9fff" : "#00d4aa";

                  return (
                    <div key={d.ticker} style={{
                      display: "grid",
                      gridTemplateColumns: "120px 90px 80px 120px 1fr 1fr 1fr",
                      gap: 8, padding: "14px 16px",
                      borderBottom: "1px solid #0f0f1e",
                      alignItems: "center",
                    }}
                      onMouseEnter={e => e.currentTarget.style.background = "#0f0f22"}
                      onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                    >
                      <div>
                        <a href={tvLink(d.ticker)} target="_blank" rel="noreferrer"
                          style={{ fontSize: 16, fontWeight: 900, color: "#00d4aa", textDecoration: "none", fontFamily: "'Inter', sans-serif" }}
                          onMouseEnter={e => e.currentTarget.style.textDecoration = "underline"}
                          onMouseLeave={e => e.currentTarget.style.textDecoration = "none"}>
                          {d.ticker} ↗
                        </a>
                        {d.price > 0 && <div style={{ fontSize: 12, color: "#888" }}>${(+d.price).toFixed(2)}</div>}
                      </div>
                      <div style={{ fontSize: 22, fontWeight: 900, fontVariantNumeric: 'tabular-nums', color: scoreColor, fontFamily: "'Inter', sans-serif" }}>
                        {d.flow_score ?? "—"}
                      </div>
                      <div style={{ fontSize: 13, color: scoreColor, fontWeight: 700 }}>
                        {d.rating || "—"}
                      </div>
                      <div>
                        <span style={{
                          fontSize: 11, fontWeight: 700, color: sourceColor,
                          background: sourceColor + "22", padding: "3px 8px",
                          borderRadius: 4, letterSpacing: 1
                        }}>{sourceLabel}</span>
                      </div>
                      <div>
                        <span style={{ fontSize: 15, fontWeight: 700, color: "#aaa" }}>{cf}</span>
                        <span style={{ fontSize: 11, color: "#555", marginLeft: 4 }}>/40</span>
                      </div>
                      <div>
                        <span style={{ fontSize: 15, fontWeight: 700, color: "#aaa" }}>{tr}</span>
                        <span style={{ fontSize: 11, color: "#555", marginLeft: 4 }}>/30</span>
                      </div>
                      <div>
                        <span style={{ fontSize: 15, fontWeight: 700, color: "#aaa" }}>{mo}</span>
                        <span style={{ fontSize: 11, color: "#555", marginLeft: 4 }}>/30</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </>
        )}

        {/* WATCHLIST TAB */}
        {tab === "watchlist" && (
          <div style={{ maxWidth: 600 }}>
            <div style={{ marginBottom: 24 }}>
              <div style={{ fontSize: 13, color: "#aaa", marginBottom: 12, letterSpacing: 0 }}>ADD TICKER</div>
              <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
                <input value={newTicker} onChange={e => setNewTicker(e.target.value.toUpperCase())}
                  onKeyDown={e => e.key === "Enter" && addTicker()} placeholder="Ticker (e.g. NVDA)"
                  style={{ flex: 1, background: "#0a0a18", border: "1px solid #1a1a2e", borderRadius: 6,
                    padding: "12px 16px", color: "#fff", fontFamily: "'Inter', sans-serif", fontSize: 15, outline: "none" }} />
                <input value={newSector} onChange={e => setNewSector(e.target.value)}
                  placeholder="Sector (optional)"
                  style={{ flex: 1, background: "#0a0a18", border: "1px solid #1a1a2e", borderRadius: 6,
                    padding: "12px 16px", color: "#fff", fontFamily: "'Inter', sans-serif", fontSize: 15, outline: "none" }} />
                <button onClick={addTicker} style={btnStyle("#00d4aa", "#000")}>Add</button>
              </div>
            </div>
            {watchlist.length === 0 && (
              <div style={{ color: "#888", fontSize: 14, padding: "32px 0" }}>No tickers yet.</div>
            )}
            {watchlist.map(w => (
              <div key={w.ticker} style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "14px 16px", background: "#0a0a18", border: "1px solid #1a1a2e",
                borderRadius: 6, marginBottom: 8 }}>
                <div>
                  <a href={tvLink(w.ticker)} target="_blank" rel="noreferrer"
                    style={{ fontSize: 17, fontWeight: 700, color: "#00d4aa", fontFamily: "'Inter', sans-serif",
                      textDecoration: "none" }}
                    onMouseEnter={e => e.currentTarget.style.textDecoration = "underline"}
                    onMouseLeave={e => e.currentTarget.style.textDecoration = "none"}>
                    {w.ticker} ↗
                  </a>
                  {w.sector && <span style={{ fontSize: 13, color: "#aaa", marginLeft: 12 }}>{w.sector}</span>}
                </div>
                <button onClick={() => removeTicker(w.ticker)}
                  style={{ background: "none", border: "1px solid #2a1a1a", borderRadius: 4, color: "#ff4444", cursor: "pointer", padding: "4px 12px", fontSize: 13 }}>
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
