import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import Chart from './Chart.jsx'
import { Select, SearchInput, label } from './ui.jsx'

export default function Watchlist() {
  const [data, setData] = useState(null)
  const [q, setQ] = useState('')
  const [bias, setBias] = useState('')
  const [page, setPage] = useState(1)
  const [chartSym, setChartSym] = useState(null)

  const load = async () => {
    const p = new URLSearchParams({ q, bias, page, page_size: 10 })
    setData(await api('/api/smart-watchlist?' + p.toString()))
  }
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [q, bias, page])

  if (!data) return <div className="empty">Loading watchlist…</div>
  const pages = Math.max(1, Math.ceil(data.total / data.page_size))

  return (
    <div>
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-h"><h2>Smart watchlist</h2>
          <span className="hint">Today's intraday shortlist · {data.day}</span></div>
        <div className="filterbar">
          <SearchInput value={q} onChange={v => { setPage(1); setQ(v) }} placeholder="Search symbol…" />
          <Select value={bias} onChange={v => { setPage(1); setBias(v) }} options={[
            { value: '', label: 'All biases' }, { value: 'long', label: 'Long' },
            { value: 'short', label: 'Short' }, { value: 'both', label: 'Two-way' }]} />
          <span className="spring" /><span className="hint">{data.total} ideas</span>
        </div>
      </div>

      {data.items.length === 0 && <div className="empty">No ideas match.</div>}
      {data.items.map(p => (
        <div className="panel" key={p.id} style={{ marginBottom: 14 }}>
          <div className="panel-h">
            <h2>{p.focus ? '★ ' : ''}{p.symbol}</h2>
            <span className="hint">{p.name}</span>
            <span className={'chip ' + (p.bias === 'long' ? 'LONG' : p.bias === 'short' ? 'SHORT' : 'READY')}
              style={{ marginLeft: 8 }}>{label(p.bias)}</span>
            <span className="spring" />
            <button className="btn" onClick={() => setChartSym('NSE:' + p.symbol + '-EQ')}>Chart</button>
          </div>
          <div className="panel-b">
            <div className="rlayout rl-even">
              <Plan title="Long" cls="up" plan={p.long_plan} />
              <Plan title="Short" cls="down" plan={p.short_plan} />
            </div>
            {p.note && <p className="note">{p.note}</p>}
          </div>
        </div>
      ))}

      {pages > 1 && <Pager page={data.page} pages={pages} onPage={setPage} />}
      {chartSym && <Chart symbol={chartSym} onClose={() => setChartSym(null)} />}
    </div>
  )
}

function Plan({ title, cls, plan }) {
  if (!plan) return (
    <div style={{ opacity: .5 }}><div className="label" style={{ marginBottom: 8 }}>{title}</div>
      <div className="dim" style={{ fontSize: 13 }}>No {title.toLowerCase()} plan today.</div></div>
  )
  return (
    <div>
      <div className={title === 'Long' ? 'up' : 'down'} style={{ fontWeight: 700, marginBottom: 10 }}>{title}</div>
      <div className="planrow"><span className="pk">Entry</span><span className="pv mono">{plan.entry}</span></div>
      <div className="planrow"><span className="pk">Stop-loss</span><span className="pv mono down">{plan.sl}</span></div>
      <div className="planrow"><span className="pk">Invalidation</span><span className="pv mono">{plan.invalidation}</span></div>
      <div className="planrow"><span className="pk">Targets</span><span className="pv mono up">{(plan.targets || []).join(' → ')}</span></div>
      {plan.note && <p className="note" style={{ marginTop: 10 }}>{plan.note}</p>}
    </div>
  )
}

export function Pager({ page, pages, onPage }) {
  return (
    <div className="row" style={{ justifyContent: 'center', gap: 14, marginTop: 8 }}>
      <button className="btn" disabled={page <= 1} onClick={() => onPage(page - 1)}>← Prev</button>
      <span className="dim">Page {page} of {pages}</span>
      <button className="btn" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next →</button>
    </div>
  )
}
