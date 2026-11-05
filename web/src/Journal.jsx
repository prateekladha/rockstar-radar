import React, { useEffect, useState } from 'react'
import { api, fmtDateTime } from './api.js'
import { Pager } from './Watchlist.jsx'
import { Select, SearchInput, Chip, label } from './ui.jsx'

const fmtDay = (d) => { try { return new Date(d + 'T00:00:00').toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short' }) } catch { return d } }

export default function Journal() {
  const [data, setData] = useState(null)
  const [day, setDay] = useState('')
  const [f, setF] = useState({ q: '', side: '' })
  const [page, setPage] = useState(1)
  const [open, setOpen] = useState(null)   // row whose timeline is expanded

  const load = async () => {
    const p = new URLSearchParams({ ...f, page, page_size: 25 })
    if (day) p.set('day', day)
    const d = await api('/api/journal?' + p.toString())
    setData(d)
    if (!day && d.day) setDay(d.day)
  }
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t) }, [f, page, day])

  if (!data) return <div className="empty">Loading…</div>
  const pages = Math.max(1, Math.ceil(data.total / data.page_size))
  const dayOpts = (data.days && data.days.length ? data.days : [data.day]).map(d => ({ value: d, label: fmtDay(d) }))

  return (
    <div className="panel">
      <div className="panel-h"><h2>Daily journal</h2>
        <span className="hint">Every opportunity the radar flagged — and the ones you acted on</span></div>
      <div className="panel-b">
        <div className="filterbar">
          <Select value={day} onChange={setDay} options={dayOpts} width={180} />
          <SearchInput value={f.q} onChange={v => { setPage(1); setF({ ...f, q: v }) }} placeholder="Search symbol…" />
          <Select value={f.side} onChange={v => { setPage(1); setF({ ...f, side: v }) }} width={140}
            options={[{ value: '', label: 'Both sides' }, { value: 'LONG', label: 'Long' }, { value: 'SHORT', label: 'Short' }]} />
          <span className="spring" />
          <span className="dim" style={{ fontSize: 13 }}>{data.total} opportunities</span>
        </div>

        {data.items.length === 0 ? (
          <div className="empty">No opportunities recorded for this day. The journal fills up live during market hours once your broker is connected.</div>
        ) : (
          <div className="tbl-wrap" style={{ maxHeight: 'none' }}>
            <table>
              <thead><tr>
                <th>Symbol</th><th>Side</th><th>Best signal</th><th className="num">Score</th>
                <th className="num">Entry / Stop / Target</th><th className="num">R:R</th><th>Acted</th><th></th>
              </tr></thead>
              <tbody>
                {data.items.map(s => (
                  <React.Fragment key={s.id}>
                    <tr>
                      <td className="sym-cell">{(s.symbol || '').split(':').pop().replace('-EQ', '')}</td>
                      <td><span className={'chip ' + (s.side === 'LONG' ? 'CONFIRMED' : 'WATCH')}>{label(s.side)}</span></td>
                      <td><Chip state={s.state} prov={s.provisional} /></td>
                      <td className="num">{s.score}</td>
                      <td className="num">{s.entry || '—'} / {s.stop || '—'} / {s.target || '—'}</td>
                      <td className="num">{s.net_rr || '—'}</td>
                      <td>{s.acted ? <span className="chip CONFIRMED">traded</span> : <span className="chip">—</span>}</td>
                      <td className="num"><button className="btn" onClick={() => setOpen(open === s.id ? null : s.id)}>{open === s.id ? 'Hide' : 'Timeline'}</button></td>
                    </tr>
                    {open === s.id && (
                      <tr className="detail-row"><td colSpan={8}>
                        <div className="timeline">
                          {(s.timeline || []).length === 0 ? <span className="dim">No timeline recorded.</span>
                            : s.timeline.map((e, i) => (
                              <div className="tl-item" key={i}><span className="tl-t">{e.t}</span>
                                <span className="tl-ev">{label(e.event)}</span>
                                <span className="tl-d dim">{e.detail}</span></div>
                            ))}
                          {s.note && <div className="note" style={{ marginTop: 8 }}>{s.note}</div>}
                        </div>
                      </td></tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {pages > 1 && <Pager page={data.page} pages={pages} onPage={setPage} />}
      </div>
    </div>
  )
}
