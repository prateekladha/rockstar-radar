import React, { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, fmt, bare } from './api.js'

const ZONE_COLORS = {
  'PREMIUM': '#ff8797',
  'DISCOUNT': '#48d3a4',
  'EQUILIBRIUM': '#93a0b6'
}

const getZoneLabel = (zone) => {
  if (!zone) return '—'
  return zone
}

const getZoneColor = (zone) => {
  return ZONE_COLORS[zone] || '#93a0b6'
}

export default function SMCRadar() {
  const [d, setD] = useState(null)
  const [filter, setFilter] = useState({ zone: '', minScore: 0 })
  const nav = useNavigate()
  const timer = useRef(null)

  useEffect(() => {
    const poll = async () => {
      try {
        const data = await api('/api/smc-radar')
        setD(data)
      } catch (e) {
        console.error('SMC radar fetch failed:', e)
      }
    }
    poll()
    timer.current = setInterval(poll, 3000)
    return () => clearInterval(timer.current)
  }, [])

  if (!d) return <div className="empty">Loading SMC Radar…</div>

  if (d.offline) {
    return (
      <div className="panel">
        <div className="panel-b">
          <div className="empty" style={{ padding: '64px 20px' }}>
            <div style={{ fontSize: 34, marginBottom: 12 }}>📊</div>
            <div className="big">SMC Radar starting...</div>
            <div style={{ maxWidth: 460, margin: '6px auto 0' }}>
              {d.reason || 'Loading Smart Money Concepts analysis...'}
            </div>
          </div>
        </div>
      </div>
    )
  }

  const opportunities = d.opportunities || []

  // Filter opportunities
  const filtered = opportunities.filter(opp => {
    if (filter.zone && opp.zone !== filter.zone) return false
    if (opp.score < filter.minScore) return false
    return true
  })

  const premiumCount = opportunities.filter(o => o.zone === 'PREMIUM').length
  const discountCount = opportunities.filter(o => o.zone === 'DISCOUNT').length
  const equilibriumCount = opportunities.filter(o => o.zone === 'EQUILIBRIUM').length

  return (
    <>
      <div className="banner" style={{ marginBottom: 14, borderColor: '#2b4c8a' }}>
        📊 <strong>SMC Radar</strong> — Smart Money Concepts analysis showing institutional trading zones. Stocks are scored based on confluence of Premium/Discount zones with Strong/Weak highs and lows.
      </div>

      <div className="kpis">
        <Kpi label="Premium Zone" val={premiumCount} sub="near strong/weak highs" cls="warn" />
        <Kpi label="Discount Zone" val={discountCount} sub="near strong/weak lows" cls="live" />
        <Kpi label="Equilibrium" val={equilibriumCount} sub="balanced price zones" cls="" />
        <Kpi label="Opportunities" val={filtered.length} sub="sorted by score" cls="accent" />
      </div>

      <div className="panel">
        <div className="panel-h">
          <h2>SMC Opportunities</h2>
          <span className="hint">
            {filtered.length} shown · Highest scores = Premium+Strong High or Discount+Strong Low
          </span>
        </div>

        <div className="filterbar">
          <select value={filter.zone} onChange={e => setFilter({ ...filter, zone: e.target.value })}>
            <option value="">All zones</option>
            <option value="PREMIUM">Premium zone</option>
            <option value="DISCOUNT">Discount zone</option>
            <option value="EQUILIBRIUM">Equilibrium</option>
          </select>

          <select value={filter.minScore} onChange={e => setFilter({ ...filter, minScore: parseInt(e.target.value) })}>
            <option value="0">All scores</option>
            <option value="70">Score ≥ 70</option>
            <option value="85">Score ≥ 85</option>
          </select>

          <span className="spring" />
          <span className="hint">{filtered.length} of {opportunities.length} opportunities</span>
        </div>

        <div className="tbl-wrap">
          <table>
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Score</th>
                <th>Zone</th>
                <th className="num">Price</th>
                <th>Strong High</th>
                <th>Strong Low</th>
                <th>Weak High</th>
                <th>Weak Low</th>
                <th>Structure</th>
                <th>Confluence</th>
                <th>Note</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length ? (
                filtered.map((opp, i) => (
                  <OpportunityRow key={i} opp={opp} />
                ))
              ) : (
                <tr>
                  <td colSpan="11">
                    <div className="empty">
                      No SMC opportunities matching your filters. Adjust filters or wait for market conditions to develop.
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <div className="panel-h">
          <h2>About SMC Scoring</h2>
        </div>
        <div className="panel-b" style={{ padding: 20 }}>
          <div style={{ lineHeight: 1.6, color: '#93a0b6' }}>
            <p style={{ marginTop: 0 }}>
              <strong style={{ color: '#f2f6ff' }}>Score 90-100:</strong> Premium + Strong High or Discount + Strong Low — highest confluence, potential institutional reversal zones
            </p>
            <p>
              <strong style={{ color: '#f2f6ff' }}>Score 70-85:</strong> Premium + Weak High or Discount + Weak Low — good setups with moderate confluence
            </p>
            <p>
              <strong style={{ color: '#f2f6ff' }}>Score 40-70:</strong> Equilibrium zones or moderate setups — watch for confirmation
            </p>
            <p style={{ marginBottom: 0 }}>
              <strong style={{ color: '#f2f6ff' }}>Additional factors:</strong> Order blocks nearby (+5-15 points), Recent structure breaks (+10 points)
            </p>
          </div>
        </div>
      </div>
    </>
  )
}

const Kpi = ({ label, val, sub, cls }) => (
  <div className={'kpi ' + (cls || '')}>
    <div className="label">{label}</div>
    <div className="val">{val}</div>
    <div className="sub">{sub}</div>
  </div>
)

const OpportunityRow = ({ opp }) => (
  <tr>
    <td className="sym-cell">
      <span style={{ fontWeight: 700 }}>{bare(opp.symbol)}</span>
    </td>
    <td>
      <span style={{
        fontWeight: 700,
        fontSize: 16,
        color: opp.score >= 85 ? '#48d3a4' : opp.score >= 70 ? '#e9c46a' : '#93a0b6'
      }}>
        {opp.score}
      </span>
    </td>
    <td>
      <span style={{
        padding: '4px 8px',
        borderRadius: 6,
        fontSize: 11,
        fontWeight: 700,
        backgroundColor: getZoneColor(opp.zone) + '20',
        color: getZoneColor(opp.zone),
        border: `1px solid ${getZoneColor(opp.zone)}40`
      }}>
        {getZoneLabel(opp.zone)}
      </span>
    </td>
    <td className="num">{fmt(opp.price)}</td>
    <td className="num">{opp.strong_high ? fmt(opp.strong_high) : '—'}</td>
    <td className="num">{opp.strong_low ? fmt(opp.strong_low) : '—'}</td>
    <td className="num">{opp.weak_high ? fmt(opp.weak_high) : '—'}</td>
    <td className="num">{opp.weak_low ? fmt(opp.weak_low) : '—'}</td>
    <td style={{ fontSize: 11 }}>
      {opp.recent_structure || '—'}
    </td>
    <ConfluenceCell c={opp.confluence} />
    <td style={{ fontSize: 11, color: '#93a0b6', maxWidth: 300 }}>
      {opp.note || '—'}
    </td>
  </tr>
)

// Decision-support confluence stack — the trader's full read at a glance (context, not an auto signal).
const ConfluenceCell = ({ c }) => {
  if (!c) return <td style={{ fontSize: 11, color: '#93a0b6' }}>—</td>
  const n = (x, d = 0) => (x == null ? '—' : Number(x).toFixed(d))
  const p = c.pivots
  const title = [
    `Confluence ${c.score}/100`,
    p ? `Pivots  P ${p.P}  R1 ${p.R1} R2 ${p.R2} R3 ${p.R3}  S1 ${p.S1} S2 ${p.S2} S3 ${p.S3}` : '',
    c.vp ? `Vol profile  VAH ${c.vp.vah}  POC ${c.vp.poc}  VAL ${c.vp.val}  shape ${c.vp.shape}` : '',
    c.components ? 'Weights  ' + Object.entries(c.components).map(([k, v]) => `${k}:${v}`).join('  ') : '',
  ].filter(Boolean).join('\n')
  return (
    <td style={{ fontSize: 11 }} title={title}>
      <div><strong style={{ color: c.score >= 50 ? '#48d3a4' : '#93a0b6' }}>{n(c.score)}</strong>
        <span style={{ color: '#93a0b6' }}> conf</span></div>
      <div style={{ color: '#93a0b6' }}>RSI {n(c.rsi)} · RVOL {c.rvol_cum == null ? '—' : n(c.rvol_cum, 1) + '×'}</div>
      <div style={{ color: '#93a0b6' }}>VP {c.vp ? c.vp.shape : '—'} · {c.trend || '—'}</div>
    </td>
  )
}
