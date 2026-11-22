import React, { useState } from 'react'
import { api, fmt, bare } from './api.js'

const ZONE_COLORS = {
  'PREMIUM': '#ff8797',
  'DISCOUNT': '#48d3a4',
  'EQUILIBRIUM': '#93a0b6'
}

const getZoneColor = (zone) => {
  return ZONE_COLORS[zone] || '#93a0b6'
}

export default function DebugRadar() {
  const [symbol, setSymbol] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [failInfo, setFailInfo] = useState(null)   // full non-success response (e.g. prereq fail)

  const run = async (force) => {
    if (!symbol.trim()) {
      setError('Please enter a stock symbol')
      return
    }
    setLoading(true)
    setError(null)
    setResult(null)
    setFailInfo(null)
    try {
      const data = await api('/api/debug-stock', {
        method: 'POST',
        body: { symbol: symbol.trim(), ...(force ? { force: true } : {}) }
      })
      if (data.success) {
        setResult(data)
      } else {
        setError(data.message || data.error || 'Analysis failed')
        setFailInfo(data)   // keep the full payload so we can show details + a Refetch button
      }
    } catch (e) {
      setError(e.message || 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = (e) => { e.preventDefault(); run(false) }
  const handleRefetch = () => run(true)

  return (
    <>
      <div className="banner" style={{ marginBottom: 14, borderColor: '#2b4c8a' }}>
        🔍 <strong>Debug Radar</strong> — Single stock SMC analysis tool. Fetch historical data and run SMC engine for any NSE stock.
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2>Stock Analysis</h2>
          <span className="hint">Enter NSE stock symbol to analyze</span>
        </div>

        <div className="panel-b" style={{ padding: 20 }}>
          <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 10, marginBottom: 20, alignItems: 'flex-end' }}>
            <div className="field" style={{ flex: 1 }}>
              <label>Stock Symbol</label>
              <input
                type="text"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                placeholder="e.g., RELIANCE, TCS, INFY"
                disabled={loading}
                style={{
                  width: '100%',
                  padding: '10px 12px',
                  fontSize: 14,
                  border: '1px solid #2a3650',
                  borderRadius: 8,
                  background: '#0b1020',
                  color: '#f2f6ff'
                }}
              />
              <div className="hint" style={{ marginTop: 6, fontSize: 11 }}>
                Enter symbol name (RELIANCE) or full format (NSE:RELIANCE-EQ)
              </div>
            </div>

            <button
              type="submit"
              className="btn primary"
              disabled={loading || !symbol.trim()}
              style={{ padding: '10px 20px', whiteSpace: 'nowrap' }}
            >
              {loading ? 'Analyzing...' : 'Analyze Stock'}
            </button>
          </form>

          {error && (
            <div className="banner err" style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              <span>
                ❌ <strong>{failInfo?.error || 'Error'}:</strong> {error}
                {failInfo && (failInfo.rvol !== undefined) && (
                  <> — RVOL {failInfo.rvol === null ? 'unavailable' : Number(failInfo.rvol).toFixed(2)}
                    {failInfo.prereq_details?.rvol?.threshold !== undefined &&
                      ` (need ≥ ${failInfo.prereq_details.rvol.threshold})`}
                    {failInfo.rvol_mode && `, ${failInfo.rvol_mode} mode`}
                    {failInfo.candles_count !== undefined && `, ${failInfo.candles_count} candles`}
                    {failInfo.from_cache && ' — loaded from cache'}
                  </>
                )}
              </span>
              {failInfo && (
                <button
                  className="btn"
                  onClick={handleRefetch}
                  disabled={loading}
                  style={{ fontSize: 12, padding: '6px 12px', whiteSpace: 'nowrap' }}
                >
                  🔄 Refetch fresh data
                </button>
              )}
            </div>
          )}

          {result?.ema && <EmaSection ema={result.ema} />}

          {result && (
            <>
              <div className="banner ok" style={{ marginBottom: 20, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>
                  ✅ <strong>Analysis Complete</strong> — {result.candles_count} candles loaded
                  {result.from_cache && ' (from cache)'}
                </span>
                {result.from_cache && (
                  <button
                    className="btn"
                    onClick={handleRefetch}
                    disabled={loading}
                    style={{ fontSize: 12, padding: '6px 12px' }}
                  >
                    🔄 Refetch
                  </button>
                )}
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12, marginBottom: 24 }}>
                <StatCard label="Symbol" value={bare(result.symbol)} />
                <StatCard label="Current Price" value={fmt(result.current_price)} />
                <StatCard label="Trailing High" value={fmt(result.trailing_high)} color="#ff8797" />
                <StatCard label="Trailing Low" value={fmt(result.trailing_low)} color="#48d3a4" />
                <StatCard label="ATR (14)" value={result.atr?.toFixed(2) || '—'} />
                <StatCard label="Trend" value={result.trend || '—'} />
              </div>

              {result.opportunity ? (
                <div className="panel" style={{ marginTop: 20, background: '#131b2e' }}>
                  <div className="panel-h">
                    <h2>SMC Opportunity Detected</h2>
                  </div>
                  <div className="panel-b" style={{ padding: 20 }}>
                    <OpportunityCard opp={result.opportunity} swingHigh={result.swing_high} swingLow={result.swing_low} />
                  </div>
                </div>
              ) : (
                <div className="banner" style={{ marginTop: 20, borderColor: '#6b5435', background: '#33291e' }}>
                  ℹ️ <strong>No Opportunity Found</strong> — {result.message || 'Score below 35 or insufficient confluence'}
                </div>
              )}

              {/* Show pivot details table even without opportunity */}
              {!result.opportunity && (result.swing_high || result.swing_low) && (
                <div className="panel" style={{ marginTop: 20, background: '#131b2e' }}>
                  <div className="panel-h">
                    <h2>Detected Pivots (No Opportunity Yet)</h2>
                  </div>
                  <div className="panel-b" style={{ padding: 20 }}>
                    <div className="tbl-wrap">
                      <table>
                        <thead>
                          <tr>
                            <th>Strong High</th>
                            <th>Strong Low</th>
                            <th>Weak High</th>
                            <th>Weak Low</th>
                            <th>Structure</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <td className="num">
                              {result.swing_high?.is_strong ? fmt(result.swing_high.level) : '—'}
                            </td>
                            <td className="num">
                              {result.swing_low?.is_strong ? fmt(result.swing_low.level) : '—'}
                            </td>
                            <td className="num">
                              {result.swing_high && !result.swing_high.is_strong ? fmt(result.swing_high.level) : '—'}
                            </td>
                            <td className="num">
                              {result.swing_low && !result.swing_low.is_strong ? fmt(result.swing_low.level) : '—'}
                            </td>
                            <td style={{ fontSize: 11 }}>—</td>
                          </tr>
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}

              {(result.swing_high || result.swing_low) && (
                <div className="panel" style={{ marginTop: 20, background: '#131b2e' }}>
                  <div className="panel-h">
                    <h2>Swing Pivots</h2>
                  </div>
                  <div className="panel-b" style={{ padding: 20 }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
                      {result.swing_high && (
                        <div>
                          <div style={{ fontSize: 12, color: '#93a0b6', marginBottom: 6 }}>Swing High</div>
                          <div style={{ fontSize: 20, fontWeight: 700, color: '#ff8797', marginBottom: 4 }}>
                            {fmt(result.swing_high.level)}
                          </div>
                          <div style={{ fontSize: 11, color: '#93a0b6' }}>
                            {result.swing_high.is_strong ? '🔴 Strong High' : '⚪ Weak High'}
                          </div>
                          <div style={{ fontSize: 10, color: '#6b7a92', marginTop: 4 }}>
                            {new Date(result.swing_high.time).toLocaleString('en-IN')}
                          </div>
                        </div>
                      )}

                      {result.swing_low && (
                        <div>
                          <div style={{ fontSize: 12, color: '#93a0b6', marginBottom: 6 }}>Swing Low</div>
                          <div style={{ fontSize: 20, fontWeight: 700, color: '#48d3a4', marginBottom: 4 }}>
                            {fmt(result.swing_low.level)}
                          </div>
                          <div style={{ fontSize: 11, color: '#93a0b6' }}>
                            {result.swing_low.is_strong ? '🟢 Strong Low' : '⚪ Weak Low'}
                          </div>
                          <div style={{ fontSize: 10, color: '#6b7a92', marginTop: 4 }}>
                            {new Date(result.swing_low.time).toLocaleString('en-IN')}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )}

              {result.score_breakdown && (
                <div className="panel" style={{ marginTop: 20, background: '#131b2e' }}>
                  <div className="panel-h">
                    <h2>📊 Score Breakdown</h2>
                  </div>
                  <div className="panel-b" style={{ padding: 20 }}>
                    <ScoreBreakdown breakdown={result.score_breakdown} />
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-h">
          <h2>About Debug Analysis</h2>
        </div>
        <div className="panel-b" style={{ padding: 20 }}>
          <div style={{ lineHeight: 1.6, color: '#93a0b6', fontSize: 13 }}>
            <p style={{ marginTop: 0 }}>
              <strong style={{ color: '#f2f6ff' }}>Purpose:</strong> Debug and test SMC analysis for individual stocks without affecting production scanner.
            </p>
            <p>
              <strong style={{ color: '#f2f6ff' }}>Data Source:</strong> Fetches last 5 days of historical candles (same as warmup process). Cached in <code style={{ background: '#1b263a', padding: '2px 6px', borderRadius: 4 }}>data/debug/</code> folder.
            </p>
            <p>
              <strong style={{ color: '#f2f6ff' }}>Cache:</strong> First fetch creates cache. Subsequent fetches load instantly from cache. Use "Refetch" to force fresh data from FYERS API.
            </p>
            <p style={{ marginBottom: 0 }}>
              <strong style={{ color: '#f2f6ff' }}>Requirements:</strong> Need at least 101 candles (~500 minutes) for proper swing detection (50 bars left + 1 pivot + 50 bars right).
            </p>
          </div>
        </div>
      </div>
    </>
  )
}

const StatCard = ({ label, value, color }) => (
  <div style={{
    padding: 16,
    background: '#1b263a',
    border: '1px solid #2a3650',
    borderRadius: 10
  }}>
    <div style={{ fontSize: 11, color: '#93a0b6', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 0.5 }}>
      {label}
    </div>
    <div style={{ fontSize: 20, fontWeight: 700, color: color || '#f2f6ff' }}>
      {value}
    </div>
  </div>
)

const EmaSection = ({ ema }) => {
  if (!ema) return null
  const trend = ema.trend
  const tcolor = trend === 'BULLISH' ? '#48d3a4' : trend === 'BEARISH' ? '#ff8797' : '#93a0b6'
  const tbg = trend === 'BULLISH' ? '#12301f' : trend === 'BEARISH' ? '#301216' : '#1b263a'
  const cross = ema.cross
  return (
    <div className="panel" style={{ marginBottom: 24, background: '#131b2e' }}>
      <div className="panel-h" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2>EMA 5 / EMA 20 Trend</h2>
        <span style={{ padding: '4px 12px', borderRadius: 20, background: tbg, color: tcolor, fontWeight: 700, fontSize: 13 }}>
          {trend || '—'}
        </span>
      </div>
      <div className="panel-b" style={{ padding: 20 }}>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12 }}>
          <StatCard label={`EMA ${ema.fast_period}`} value={ema.ema_fast != null ? ema.ema_fast.toFixed(2) : '—'} color="#8fb6ff" />
          <StatCard label={`EMA ${ema.slow_period}`} value={ema.ema_slow != null ? ema.ema_slow.toFixed(2) : '—'} color="#c58fff" />
          <StatCard label="Trend" value={trend || '—'} color={tcolor} />
        </div>
        <p className="note" style={{ marginTop: 12 }}>
          {ema.ema_fast == null
            ? `Not enough candles to compute EMA ${ema.slow_period}.`
            : cross
              ? <>Last crossover: EMA {ema.fast_period} crossed{' '}
                  <strong style={{ color: cross.direction === 'UP' ? '#48d3a4' : '#ff8797' }}>
                    {cross.direction === 'UP' ? 'above (bullish)' : 'below (bearish)'}
                  </strong>{' '}
                  EMA {ema.slow_period}, {cross.bars_ago} bar{cross.bars_ago === 1 ? '' : 's'} ago.</>
              : `No EMA ${ema.fast_period}/${ema.slow_period} crossover in the loaded window — EMA ${ema.fast_period} has stayed ${trend === 'BULLISH' ? 'above' : 'below'} EMA ${ema.slow_period}.`}
          {' '}(5-minute candles.)
        </p>
      </div>
    </div>
  )
}

const OpportunityCard = ({ opp, swingHigh, swingLow }) => {
  // Use opportunity data if available, otherwise fallback to swing pivot data
  const strongHigh = opp.strong_high || (swingHigh?.is_strong ? swingHigh.level : null)
  const strongLow = opp.strong_low || (swingLow?.is_strong ? swingLow.level : null)
  const weakHigh = opp.weak_high || (swingHigh && !swingHigh.is_strong ? swingHigh.level : null)
  const weakLow = opp.weak_low || (swingLow && !swingLow.is_strong ? swingLow.level : null)

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      <div style={{ display: 'flex', gap: 20, alignItems: 'center', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: 12, color: '#93a0b6', marginBottom: 4 }}>Score</div>
          <div style={{
            fontSize: 32,
            fontWeight: 700,
            color: opp.score >= 85 ? '#48d3a4' : opp.score >= 70 ? '#e9c46a' : '#93a0b6'
          }}>
            {opp.score}
          </div>
        </div>

        <div>
          <div style={{ fontSize: 12, color: '#93a0b6', marginBottom: 4 }}>Zone</div>
          <span style={{
            padding: '8px 16px',
            borderRadius: 8,
            fontSize: 13,
            fontWeight: 700,
            backgroundColor: getZoneColor(opp.zone) + '20',
            color: getZoneColor(opp.zone),
            border: `1px solid ${getZoneColor(opp.zone)}40`,
            display: 'inline-block'
          }}>
            {opp.zone || '—'}
          </span>
        </div>

        <div>
          <div style={{ fontSize: 12, color: '#93a0b6', marginBottom: 4 }}>Price</div>
          <div style={{ fontSize: 20, fontWeight: 700 }}>
            {fmt(opp.price)}
          </div>
        </div>
      </div>

      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Strong High</th>
              <th>Strong Low</th>
              <th>Weak High</th>
              <th>Weak Low</th>
              <th>Structure</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="num">{strongHigh ? fmt(strongHigh) : '—'}</td>
              <td className="num">{strongLow ? fmt(strongLow) : '—'}</td>
              <td className="num">{weakHigh ? fmt(weakHigh) : '—'}</td>
              <td className="num">{weakLow ? fmt(weakLow) : '—'}</td>
              <td style={{ fontSize: 11 }}>{opp.recent_structure || '—'}</td>
            </tr>
          </tbody>
        </table>
      </div>

      {opp.note && (
        <div style={{
          padding: 12,
          background: '#1b263a',
          border: '1px solid #2a3650',
          borderRadius: 8,
          fontSize: 12,
          color: '#93a0b6',
          lineHeight: 1.5
        }}>
          <strong style={{ color: '#f2f6ff' }}>Note:</strong> {opp.note}
        </div>
      )}
    </div>
  )
}

const ScoreBreakdown = ({ breakdown }) => {
  if (!breakdown) return null

  const getScoreColor = (score, max) => {
    const pct = (score / max) * 100
    if (pct >= 80) return '#48d3a4'  // Green
    if (pct >= 60) return '#e9c46a'  // Yellow
    if (pct >= 40) return '#f2f6ff'  // White
    return '#93a0b6'  // Gray
  }

  const components = [
    { key: 'zone_score', label: 'Zone Proximity', max: 35, detail: breakdown.details?.zone },
    { key: 'key_level_score', label: 'Key Level', max: 30, detail: breakdown.details?.key_level },
    { key: 'order_block_score', label: 'Order Blocks', max: 20, detail: breakdown.details?.order_blocks },
    { key: 'fvg_score', label: 'Fair Value Gap', max: 15, detail: breakdown.details?.fvg },
    { key: 'structure_score', label: 'Structure', max: 10, detail: breakdown.details?.structure },
    { key: 'recency_score', label: 'Recency', max: 15, detail: breakdown.details?.recency }
  ]

  return (
    <div style={{ display: 'grid', gap: 16 }}>
      {/* Summary */}
      <div style={{ display: 'flex', gap: 20, alignItems: 'baseline', paddingBottom: 16, borderBottom: '1px solid #2a3650' }}>
        <div>
          <span style={{ fontSize: 12, color: '#93a0b6', marginRight: 8 }}>Final Score:</span>
          <span style={{
            fontSize: 28,
            fontWeight: 700,
            color: breakdown.final_score >= 85 ? '#48d3a4' : breakdown.final_score >= 70 ? '#e9c46a' : '#93a0b6'
          }}>
            {breakdown.final_score}
          </span>
          <span style={{ fontSize: 14, color: '#6b7a92', marginLeft: 4 }}>/100</span>
        </div>
        {breakdown.raw_total > 100 && (
          <div style={{ fontSize: 12, color: '#93a0b6' }}>
            (Raw: {breakdown.raw_total}, capped at 100)
          </div>
        )}
      </div>

      {/* Component Breakdown */}
      <div style={{ display: 'grid', gap: 12 }}>
        {components.map(comp => {
          const score = breakdown[comp.key] || 0
          const percentage = (score / comp.max) * 100

          return (
            <div key={comp.key} style={{ display: 'grid', gap: 6 }}>
              {/* Label and Score */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: '#f2f6ff' }}>
                  {comp.label}
                </span>
                <span style={{ fontSize: 14, fontWeight: 700, color: getScoreColor(score, comp.max) }}>
                  {score} <span style={{ fontSize: 11, color: '#6b7a92' }}>/ {comp.max}</span>
                </span>
              </div>

              {/* Progress Bar */}
              <div style={{
                height: 6,
                background: '#1b263a',
                borderRadius: 3,
                overflow: 'hidden',
                position: 'relative'
              }}>
                <div style={{
                  height: '100%',
                  width: `${Math.min(percentage, 100)}%`,
                  background: getScoreColor(score, comp.max),
                  borderRadius: 3,
                  transition: 'width 0.3s ease'
                }} />
              </div>

              {/* Detail */}
              {comp.detail && (
                <div style={{
                  fontSize: 11,
                  color: '#93a0b6',
                  fontStyle: 'italic',
                  paddingLeft: 4
                }}>
                  {comp.detail}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
