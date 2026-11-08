import React, { useEffect, useRef, useState } from 'react'
import { api, bare } from './api.js'
import { useViewMode } from './viewmode.js'

const money = (x) => (x == null ? '—' : (x < 0 ? '-₹' : '₹') + Math.abs(Math.round(x)).toLocaleString('en-IN'))

function ChartToggle({ v, set }) {
  return (
    <span className="charttoggle">
      <button className={v === 'bar' ? 'on' : ''} onClick={() => set('bar')}>Bars</button>
      <button className={v === 'line' ? 'on' : ''} onClick={() => set('line')}>Line</button>
    </span>
  )
}

export default function Insights() {
  const [s, setS] = useState(null)
  const [pnlKind, setPnlKind] = useState('bar')
  const mode = useViewMode()
  useEffect(() => { setS(null); api('/api/insights?mode=' + mode).then(setS).catch(() => {}) }, [mode])
  if (!s) return <div className="empty">Loading insights…</div>
  if (!s.trades) return <div className="empty"><div className="big">No trades yet</div>Your performance shows up here once you've taken a few trades.</div>

  return (
    <div>
      <div className="kpis">
        <Tile label="Running P&L" val={money(s.running_pnl)} cls="live" sub={s.sim ? 'practice · live' : 'this session · live'} />
        <Tile label="Realised P&L" val={money(s.realised)} sub={s.sim ? 'sim — not booked' : 'booked · ended sessions'} />
        <Tile label="Win rate" val={s.win_rate + '%'} cls="accent" sub={`${s.wins}W / ${s.losses}L`} />
        <Tile label="Expectancy" val={s.expectancy_r + 'R'} sub="per trade" />
        <Tile label="Total R" val={s.total_r + 'R'} sub={`cumulative · ${s.trades} trades`} />
      </div>

      <div className="note" style={{ marginTop: 0, marginBottom: 16 }}>
        <strong>What's “R”?</strong> R is your result measured in units of the risk you took.
        <strong> 1R = entry − stop-loss</strong> (the amount at risk). Hitting your stop is −1R;
        making twice your risk is +2R. <strong>Expectancy</strong> is the average R you earn per
        trade — positive means your system has an edge, independent of position size.
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-h"><h2>Daily P&L</h2><span className="hint">realised ₹ per trading day</span>
          <span className="spring" /><ChartToggle v={pnlKind} set={setPnlKind} /></div>
        <div className="panel-b">{s.daily_pnl?.length
          ? <TradeChart points={s.daily_pnl.map(d => ({ label: d.day, value: d.pnl }))} kind={pnlKind} unit="₹" />
          : <div className="empty">No closed trades yet.</div>}</div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-h"><h2>Equity curve</h2><span className="hint">cumulative R by trade number · hover a point</span></div>
        <div className="panel-b"><TradeChart points={s.equity.map((d, i) => ({ value: d.r, name: '#' + (i + 1) + ' ' + bare(d.symbol) + (d.t ? ' · ' + fmtDay(d.t) : '') }))} kind="line" unit="R" /></div>
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
const H = 240, PADL = 10, PADR = 52, PADT = 20, PADB = 30

// One chart for both Daily P&L (bars or line) and the Equity curve (line). Hovering any point shows
// its x (date / trade) and y (value) in a tooltip.
function TradeChart({ points, kind, unit }) {
  const [ref, W] = useWidth()
  const [hi, setHi] = useState(null)
  const iw = W - PADL - PADR, ih = H - PADT - PADB
  const n = points.length
  const vmax = Math.max(0, ...points.map(p => p.value)), vmin = Math.min(0, ...points.map(p => p.value))
  const span = (vmax - vmin) || 1
  const y = (v) => PADT + ih * (vmax - v) / span
  const zeroY = y(0)
  const lab = (v) => (unit === '₹' ? '₹' + kfmt(v) : (v.toFixed(2) + 'R'))
  const col = (v) => v >= 0 ? '#34d399' : '#f87171'
  const slot = iw / n
  const cxBar = (i) => PADL + slot * i + slot / 2
  const xi = (i) => kind === 'bar' ? cxBar(i) : (n <= 1 ? PADL + iw / 2 : PADL + iw * i / (n - 1))
  const step = Math.max(1, Math.ceil(n / Math.max(1, Math.floor(iw / 58))))
  const xlabel = (p, i) => p.label && /\d{4}-\d{2}-\d{2}/.test(String(p.label)) ? fmtDay(p.label) : '#' + (i + 1)
  const linePts = points.map((p, i) => `${xi(i)},${y(p.value)}`).join(' ')
  const hp = hi != null ? points[hi] : null
  return (
    <div ref={ref} style={{ width: '100%', position: 'relative' }}>
      <svg width={W} height={H} style={{ display: 'block' }} onMouseLeave={() => setHi(null)}>
        <line x1={PADL} x2={PADL + iw} y1={zeroY} y2={zeroY} stroke="#2c3650" />
        <text x={W - PADR + 6} y={PADT + 4} fill="#97a4ba" fontSize="11">{lab(vmax)}</text>
        <text x={W - PADR + 6} y={zeroY + 4} fill="#97a4ba" fontSize="11">0</text>
        {vmin < 0 && <text x={W - PADR + 6} y={PADT + ih + 4} fill="#97a4ba" fontSize="11">{lab(vmin)}</text>}
        {kind === 'bar'
          ? points.map((p, i) => {
            const cx = cxBar(i), yv = y(p.value)
            const top = Math.min(yv, zeroY), h = Math.max(1, Math.abs(yv - zeroY)), bw = Math.min(44, slot * 0.62)
            return (
              <g key={i}>
                <rect x={cx - bw / 2} y={top} width={bw} height={h} rx={3} fill={col(p.value)} opacity={hi == null || hi === i ? 1 : 0.5} />
                {n <= 24 && <text x={cx} y={p.value >= 0 ? top - 5 : top + h + 13} textAnchor="middle" fill={col(p.value)} fontSize="11" fontWeight="700">{lab(p.value)}</text>}
                {i % step === 0 && <text x={cx} y={H - 9} textAnchor="middle" fill="#97a4ba" fontSize="11">{xlabel(p, i)}</text>}
              </g>
            )
          })
          : <>
            {n > 1 && <polygon points={`${PADL},${zeroY} ${linePts} ${xi(n - 1)},${zeroY}`} fill="rgba(59,130,246,.14)" />}
            <polyline points={linePts} fill="none" stroke="#3b82f6" strokeWidth="2" />
            {points.map((p, i) => <circle key={i} cx={xi(i)} cy={y(p.value)} r={hi === i ? 5 : 3} fill="#3b82f6" stroke="#0a0e16" strokeWidth={hi === i ? 2 : 0} />)}
            {[...new Set([0, Math.floor((n - 1) / 2), n - 1])].map(i => <text key={i} x={xi(i)} y={H - 9} textAnchor="middle" fill="#97a4ba" fontSize="11">{xlabel(points[i], i)}</text>)}
          </>}
        {hp != null && <line x1={xi(hi)} x2={xi(hi)} y1={PADT} y2={PADT + ih} stroke="#3b82f6" strokeDasharray="3 3" opacity="0.5" />}
        {/* invisible hover hit-areas */}
        {points.map((p, i) => <rect key={'h' + i} x={PADL + slot * i} y={PADT} width={slot} height={ih}
          fill="transparent" onMouseEnter={() => setHi(i)} />)}
      </svg>
      {hp != null && (
        <div className="charttip" style={{ left: Math.min(Math.max(xi(hi), 60), W - 60), top: y(hp.value) - 8 }}>
          <div className="t1">{lab(hp.value)}</div>
          <div className="t2">{hp.name || xlabel(hp, hi)}</div>
        </div>
      )}
    </div>
  )
}
