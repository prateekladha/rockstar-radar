import React, { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import { api, bare } from './api.js'

const money = (x) => (x == null ? '—' : (x < 0 ? '-₹' : '₹') + Math.abs(Math.round(x)).toLocaleString('en-IN'))

export default function Insights() {
  const [s, setS] = useState(null)
  useEffect(() => { api('/api/insights').then(setS).catch(() => {}) }, [])
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

function EquityChart({ data }) {
  const box = useRef(null)
  useEffect(() => {
    if (!box.current || !data?.length) return
    const chart = createChart(box.current, {
      width: box.current.clientWidth, height: 260,
      layout: { background: { color: 'transparent' }, textColor: '#97a4ba' },
      grid: { vertLines: { color: '#1a2130' }, horzLines: { color: '#1a2130' } },
      timeScale: { visible: false }, rightPriceScale: { borderColor: '#2c3650' },
    })
    const series = chart.addAreaSeries({ lineColor: '#3b82f6', topColor: 'rgba(59,130,246,.35)',
      bottomColor: 'rgba(59,130,246,0)', lineWidth: 2 })
    series.setData(data.map((d, i) => ({ time: i + 1, value: d.r })))
    chart.timeScale().fitContent()
    const onResize = () => chart.applyOptions({ width: box.current.clientWidth })
    window.addEventListener('resize', onResize)
    return () => { window.removeEventListener('resize', onResize); chart.remove() }
  }, [data])
  return <div ref={box} style={{ width: '100%' }} />
}
