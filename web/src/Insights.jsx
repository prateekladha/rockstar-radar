import React, { useEffect, useRef, useState } from 'react'
import { api, bare } from './api.js'
import { useViewMode } from './viewmode.js'

const money = (x) => (x == null ? '—' : (x < 0 ? '-₹' : '₹') + Math.abs(Math.round(x)).toLocaleString('en-IN'))

export default function Insights() {
  const [s, setS] = useState(null)
  const mode = useViewMode()
  useEffect(() => { setS(null); api('/api/insights?mode=' + mode).then(setS).catch(() => {}) }, [mode])
  if (!s) return <div className="empty">Loading insights…</div>
  if (!s.trades) return <div className="empty"><div className="big">No trades yet</div>Your performance shows up here once you've taken a few trades.</div>

  return (
    <div>
      <div className="kpis">
        <Tile label="Net P&L" val={money(s.realised)} cls="live" sub={`${s.trades} trades`} />
        <Tile label="Win rate" val={s.win_rate + '%'} cls="accent" sub={`${s.wins}W / ${s.losses}L`} />
        <Tile label="Expectancy" val={s.expectancy_r + 'R'} sub="per trade" />
        <Tile label="Total R" val={s.total_r + 'R'} sub="cumulative" />
        <Tile label="Avg R" val={s.avg_r + 'R'} sub="per trade" />
      </div>

      <div className="note" style={{ marginTop: 0, marginBottom: 16 }}>
        <strong>What's “R”?</strong> R is your result measured in units of the risk you took.
        <strong> 1R = entry − stop-loss</strong> (the amount at risk). Hitting your stop is −1R;
        making twice your risk is +2R. <strong>Expectancy</strong> is the average R you earn per
        trade — positive means your system has an edge, independent of position size.
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-h"><h2>Daily P&L</h2><span className="hint">realised ₹ per trading day</span></div>
        <div className="panel-b">{s.daily_pnl?.length
          ? <DailyPnlChart data={s.daily_pnl} />
          : <div className="empty">No closed trades yet.</div>}</div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-h"><h2>Equity curve</h2><span className="hint">cumulative R over your trades</span></div>
        <div className="panel-b"><EquityChart data={s.equity} /></div>
      </div>

      <div className="rlayout rl-even">
        <div className="panel"><div className="panel-h"><h2>By direction</h2></div>
          <div className="panel-b">
            <div className="planrow"><span className="pk up">Long</span><span className="pv mono">{s.long.total} trades · {s.long.win_rate}% win · {s.long.r}R</span></div>
            <div className="planrow"><span className="pk down">Short</span><span className="pv mono">{s.short.total} trades · {s.short.win_rate}% win · {s.short.r}R</span></div>
          </div>
        </div>
        <div className="panel"><div className="panel-h"><h2>Best &amp; worst</h2></div>
          <div className="panel-b">
            <div className="planrow"><span className="pk">Best trade</span><span className="pv mono up">{s.best ? bare(s.best.symbol) + '  ·  +' + s.best.r + 'R' : '—'}</span></div>
            <div className="planrow"><span className="pk">Worst trade</span><span className="pv mono down">{s.worst ? bare(s.worst.symbol) + '  ·  ' + s.worst.r + 'R' : '—'}</span></div>
          </div>
        </div>
      </div>
    </div>
  )
}

const Tile = ({ label, val, sub, cls }) => (
  <div className={'kpi ' + (cls || '')}><div className="label">{label}</div><div className="val">{val}</div><div className="sub">{sub}</div></div>
)

function useWidth() {
  const ref = useRef(null)
  const [w, setW] = useState(640)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(e => setW(e[0].contentRect.width))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, Math.max(320, w)]
}
const fmtDay = (iso) => { const d = new Date(iso); return isNaN(d) ? String(iso) : d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) }
const kfmt = (v) => { const a = Math.abs(v); return (v < 0 ? '-' : '') + (a >= 1000 ? (a / 1000).toFixed(a >= 10000 ? 0 : 1) + 'k' : Math.round(a)) }
const H = 240, PADL = 10, PADR = 50, PADT = 20, PADB = 30

function DailyPnlChart({ data }) {
  const [ref, W] = useWidth()
  const iw = W - PADL - PADR, ih = H - PADT - PADB
  const vmax = Math.max(0, ...data.map(d => d.pnl)), vmin = Math.min(0, ...data.map(d => d.pnl))
  const span = (vmax - vmin) || 1
  const y = (v) => PADT + ih * (vmax - v) / span
  const zeroY = y(0)
  const slot = iw / data.length
  const barW = Math.min(44, slot * 0.62)
  const step = Math.ceil(data.length / Math.max(1, Math.floor(iw / 56)))   // avoid label crowding
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <svg width={W} height={H} style={{ display: 'block' }}>
        <line x1={PADL} x2={PADL + iw} y1={zeroY} y2={zeroY} stroke="#2c3650" />
        <text x={W - PADR + 6} y={PADT + 4} fill="#97a4ba" fontSize="11">₹{kfmt(vmax)}</text>
        <text x={W - PADR + 6} y={zeroY + 4} fill="#97a4ba" fontSize="11">0</text>
        {vmin < 0 && <text x={W - PADR + 6} y={PADT + ih + 4} fill="#97a4ba" fontSize="11">-₹{kfmt(-vmin)}</text>}
        {data.map((d, i) => {
          const cx = PADL + slot * i + slot / 2, yv = y(d.pnl)
          const top = Math.min(yv, zeroY), h = Math.max(1, Math.abs(yv - zeroY))
          const col = d.pnl >= 0 ? '#34d399' : '#f87171'
          return (
            <g key={d.day}>
              <rect x={cx - barW / 2} y={top} width={barW} height={h} rx={3} fill={col} />
              <text x={cx} y={d.pnl >= 0 ? top - 5 : top + h + 13} textAnchor="middle" fill={col} fontSize="11" fontWeight="700">₹{kfmt(d.pnl)}</text>
              {i % step === 0 && <text x={cx} y={H - 9} textAnchor="middle" fill="#97a4ba" fontSize="11">{fmtDay(d.day)}</text>}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

function EquityChart({ data }) {
  const [ref, W] = useWidth()
  const iw = W - PADL - PADR, ih = H - PADT - PADB
  const vmax = Math.max(0, ...data.map(d => d.r)), vmin = Math.min(0, ...data.map(d => d.r))
  const span = (vmax - vmin) || 1
  const y = (v) => PADT + ih * (vmax - v) / span
  const x = (i) => data.length <= 1 ? PADL + iw / 2 : PADL + iw * i / (data.length - 1)
  const zeroY = y(0)
  const pts = data.map((d, i) => `${x(i)},${y(d.r)}`).join(' ')
  const labelIdx = [...new Set([0, Math.floor((data.length - 1) / 2), data.length - 1])]
  return (
    <div ref={ref} style={{ width: '100%' }}>
      <svg width={W} height={H} style={{ display: 'block' }}>
        <line x1={PADL} x2={PADL + iw} y1={zeroY} y2={zeroY} stroke="#2c3650" />
        {data.length > 1 && <polygon points={`${PADL},${zeroY} ${pts} ${x(data.length - 1)},${zeroY}`} fill="rgba(59,130,246,.14)" />}
        <polyline points={pts} fill="none" stroke="#3b82f6" strokeWidth="2" />
        {data.map((d, i) => <circle key={i} cx={x(i)} cy={y(d.r)} r="2.5" fill="#3b82f6" />)}
        <text x={W - PADR + 6} y={PADT + 4} fill="#97a4ba" fontSize="11">{vmax.toFixed(1)}R</text>
        <text x={W - PADR + 6} y={zeroY + 4} fill="#97a4ba" fontSize="11">0</text>
        {vmin < 0 && <text x={W - PADR + 6} y={PADT + ih + 4} fill="#97a4ba" fontSize="11">{vmin.toFixed(1)}R</text>}
        {labelIdx.map(i => <text key={i} x={x(i)} y={H - 9} textAnchor="middle" fill="#97a4ba" fontSize="11">{data[i].t ? fmtDay(data[i].t) : '#' + (i + 1)}</text>)}
      </svg>
    </div>
  )
}
