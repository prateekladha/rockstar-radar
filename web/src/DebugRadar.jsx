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

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!symbol.trim()) {
      setError('Please enter a stock symbol')
      return
    }

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const data = await api('/api/debug-stock', {
        method: 'POST',
        body: { symbol: symbol.trim() }
      })

      if (data.success) {
        setResult(data)
      } else {
        setError(data.message || data.error || 'Analysis failed')
      }
    } catch (e) {
      setError(e.message || 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  const handleRefetch = async () => {
    if (!symbol.trim()) return

    setLoading(true)
    setError(null)

    try {
      const data = await api('/api/debug-stock', {
        method: 'POST',
        body: { symbol: symbol.trim(), force: true }
      })

      if (data.success) {
        setResult(data)
      } else {
        setError(data.message || data.error || 'Analysis failed')
      }
    } catch (e) {
      setError(e.message || 'Request failed')
    } finally {
      setLoading(false)
    }
  }

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
            <div className="banner err" style={{ marginBottom: 20 }}>
              ❌ <strong>Error:</strong> {error}
            </div>
          )}

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
                    <OpportunityCard opp={result.opportunity} />
                  </div>
                </div>
              ) : (
                <div className="banner" style={{ marginTop: 20, borderColor: '#6b5435', background: '#33291e' }}>
                  ℹ️ <strong>No Opportunity Found</strong> — {result.message || 'Score below 40 or insufficient confluence'}
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

const OpportunityCard = ({ opp }) => (
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
            <td className="num">{opp.strong_high ? fmt(opp.strong_high) : '—'}</td>
            <td className="num">{opp.strong_low ? fmt(opp.strong_low) : '—'}</td>
            <td className="num">{opp.weak_high ? fmt(opp.weak_high) : '—'}</td>
            <td className="num">{opp.weak_low ? fmt(opp.weak_low) : '—'}</td>
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
