import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, fmt, bare } from './api.js'
import Chart from './Chart.jsx'
import { PlaceOrder } from './Trades.jsx'
import { Chip, Select, Checkbox, SearchInput, label } from './ui.jsx'

const ACTIVE = ['WATCH', 'READY', 'BREAKOUT_PENDING', 'CONFIRMED', 'RETEST_CANDIDATE', 'RETEST_READY']
const NOISE = new Set(['NONE', 'WAIT_OR', 'NO_SETUP', 'FILTERED', 'WAIT_VOLUME', 'SESSION_CLOSED', ''])
const sideCls = (s) => (s === 'LONG' ? 'up' : s === 'SHORT' ? 'down' : '')
const feedLabel = (fh) => !fh ? 'feed'
  : /simul/i.test(fh) ? 'Simulated data' : /connected/i.test(fh) ? 'Live feed'
  : /halt|unavailable/i.test(fh) ? 'Paused' : fh.slice(0, 22)

export default function Radar() {
  const [d, setD] = useState(null)
  const [f, setF] = useState({ q: '', source: '', side: '', state: '' })
  const [showAll, setShowAll] = useState(false)
  const [chartFor, setChartFor] = useState(null)
  const [orderFor, setOrderFor] = useState(null)
  const nav = useNavigate()
  const timer = useRef(null)
  const toPreset = (r) => ({ symbol: r.symbol, side: r.side, qty: r.qty, entry: r.entry, stop: r.stop, target: r.target })

  useEffect(() => {
    const poll = async () => { try { setD(await api('/api/radar')) } catch {} }
    poll(); timer.current = setInterval(poll, 3000)
    return () => clearInterval(timer.current)
  }, [])

  const rows = useMemo(() => {
    if (!d || d.offline) return []
    return (d.all || []).filter(r => {
      if (!showAll && !f.state && NOISE.has(r.state)) return false
      if (f.q && !bare(r.symbol).includes(f.q.toUpperCase())) return false
      if (f.source && (r.source || 'AUTO') !== f.source) return false
      if (f.side && r.side !== f.side) return false
      if (f.state === 'active') { if (!ACTIVE.includes(r.state)) return false }
      else if (f.state && r.state !== f.state) return false
      return true
    })
  }, [d, f, showAll])

  const tickets = (d && !d.offline ? (d.all || []) : [])
    .filter(r => r.state === 'RETEST_READY' || r.state === 'CONFIRMED').slice(0, 8)
  const events = (d && d.events) || []
  if (!d) return <div className="empty">Loading radar…</div>
  if (d.need_broker) return (
    <div className="panel"><div className="panel-b"><div className="empty" style={{ padding: '64px 20px' }}>
      <div style={{ fontSize: 34, marginBottom: 12 }}>🔗</div>
      <div className="big">Connect your broker to see today's opportunities</div>
      <div style={{ maxWidth: 440, margin: '6px auto 0' }}>{d.reason}</div>
      <div style={{ marginTop: 20 }}><button className="btn primary btn-lg" onClick={() => nav('/brokers')}>Connect broker</button></div>
    </div></div></div>
  )
  if (d.need_login) return (
    <div className="panel"><div className="panel-b"><div className="empty" style={{ padding: '64px 20px' }}>
      <div style={{ fontSize: 34, marginBottom: 12 }}>🔑</div>
      <div className="big">Log in to your broker for today</div>
      <div style={{ maxWidth: 460, margin: '6px auto 0' }}>{d.reason}</div>
      <div style={{ marginTop: 20 }}><button className="btn primary btn-lg" onClick={() => nav('/brokers')}>Log in for today</button></div>
    </div></div></div>
  )
  const off = d.offline

  return (
    <>
      <div className="kpis">
        <Kpi label="Monitored" val={off ? '—' : d.monitored} sub="stocks tracked" />
        <Kpi label="Ready" val={off ? '—' : d.anchors_ready} sub="opening ranges set" cls="accent" />
        <Kpi label="Signals ready" val={off ? '—' : d.active_candidates} sub="setups to review" cls="live" />
        <Kpi label="Feed" cls={d.data_mode === 'live' ? 'live' : ''}
          val={off ? 'Off' : (d.data_mode === 'live' ? 'Live' : 'Demo')}
          sub={off ? 'starting…' : ((d.shared ? 'Shared · ' : '') + (d.universe || feedLabel(d.feed_health)))} />
        <Kpi label="Session" val={off ? '—' : (d.session_closed ? 'Closed' : 'Open')} sub={off ? '' : (d.server_time_ist || '').slice(11) + ' IST'} />
      </div>

      {tickets.length > 0 && (
        <div className="tickets">{tickets.map((r, i) => <Ticket key={i} r={r}
          onChart={() => setChartFor(r)} onTrade={() => setOrderFor(r)} />)}</div>
      )}

      <div className="rlayout">
        <div className="panel">
          <div className="panel-h"><h2>Opportunities</h2>
            <span className="hint">{off ? (d.reason || 'Scanner idle') : (d.session_closed ? 'Market closed — review' : 'Breakouts near the opening range')}</span></div>
          <div className="filterbar">
            <SearchInput value={f.q} onChange={v => setF({ ...f, q: v })} placeholder="Search symbol…" />
            <Select value={f.side} onChange={v => setF({ ...f, side: v })} options={[
              { value: '', label: 'Any side' }, { value: 'LONG', label: 'Long' }, { value: 'SHORT', label: 'Short' }]} />
            <Select value={f.state} onChange={v => setF({ ...f, state: v })} options={[
              { value: '', label: 'All signals' }, { value: 'active', label: 'Active only' },
              { value: 'RETEST_READY', label: 'Retest ready' }, { value: 'CONFIRMED', label: 'Confirmed' },
              { value: 'WATCH', label: 'Watch' }]} />
            <Checkbox checked={showAll} onChange={setShowAll}>Show all</Checkbox>
            <span className="spring" /><span className="hint">{rows.length} shown</span>
          </div>
          <div className="tbl-wrap">
            <table>
              <thead><tr><th>Symbol</th><th>Side</th><th>Signal</th><th className="num">Last</th>
                <th className="num">Range H / L</th><th className="num">RVOL</th><th className="num">Score</th>
                <th className="num">Entry / Stop / Target</th><th className="num">Qty · Risk</th></tr></thead>
              <tbody>
                {off ? <tr><td colSpan="9"><div className="empty"><div className="big">{d.reason || 'Scanner idle'}</div>Starting up…</div></td></tr>
                  : rows.length ? rows.map((r, i) => <Row key={i} r={r} onChart={() => setChartFor(r)} />)
                    : <tr><td colSpan="9"><div className="empty">No opportunities right now. Breakouts appear here as they form.</div></td></tr>}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel">
          <div className="panel-h"><h2>Activity</h2><span className="hint">{events.length ? events.length + ' today' : ''}</span></div>
          <div className="journal">
            {events.length ? events.slice(0, 60).map((e, i) => (
              <div className="jitem" key={i}>
                <div className="jhead"><span className="jsym">{bare(e.symbol)} {e.side || ''}</span><Chip state={e.state} prov={e.provisional} /></div>
                <div className="jnote"><span className="jtime">{(e.time || '').slice(11)}</span> · {humanNote(e)}</div>
              </div>
            )) : <div className="empty">No activity yet today.</div>}
          </div>
        </div>
      </div>
      {chartFor && <Chart symbol={chartFor.symbol} levels={toPreset(chartFor)} onClose={() => setChartFor(null)} />}
      {orderFor && <PlaceOrder preset={toPreset(orderFor)} onClose={() => setOrderFor(null)} onDone={() => setOrderFor(null)} />}
    </>
  )
}

function humanNote(e) {
  if (e.state === 'RETEST_READY') return `Pulled back to the level and held — ${e.net_rr || '—'}:1 reward.`
  if (e.state === 'CONFIRMED') return 'Broke the opening range with strong volume.'
  if (e.state === 'BREAKOUT_PENDING') return 'Pushing through the range — waiting for the candle to close.'
  if (e.state === 'RETRACTED') return 'Breakout faded — stand down.'
  return e.note || ''
}
const Kpi = ({ label, val, sub, cls }) => (
  <div className={'kpi ' + (cls || '')}><div className="label">{label}</div><div className="val">{val}</div><div className="sub">{sub}</div></div>
)
const Ticket = ({ r, onChart, onTrade }) => (
  <div className={'ticket ' + (r.side || '').toLowerCase()}>
    <div className="top"><div className="sym">{bare(r.symbol)}</div><Chip state={r.state} prov={r.provisional} /></div>
    <div className="ladder">
      <div className="c"><div className="k">Entry</div><div className="v">{fmt(r.entry)}</div></div>
      <div className="c"><div className="k">Stop</div><div className="v down">{fmt(r.stop)}</div></div>
      <div className="c"><div className="k">Target</div><div className="v up">{fmt(r.target)}</div></div></div>
    <div className="meta"><span>{label(r.side)}</span><span>R:R <b>{r.net_rr != null ? r.net_rr.toFixed(2) : '—'}</b></span>
      <span>Qty <b>{r.qty ?? '—'}</b></span><span>Risk <b>{r.risk_amount != null ? '₹' + Math.round(r.risk_amount) : '—'}</b></span></div>
    <div className="row" style={{ marginTop: 12 }}>
      <button className="btn primary" style={{ flex: 1, justifyContent: 'center' }} onClick={onTrade}>Trade</button>
      <button className="btn" style={{ flex: 1, justifyContent: 'center' }} onClick={onChart}>Chart</button>
    </div>
  </div>
)
const Row = ({ r, onChart }) => (
  <tr style={{ cursor: 'pointer' }} onClick={onChart}>
    <td className="sym-cell"><a onClick={e => { e.preventDefault(); onChart() }} href="#">{bare(r.symbol)}</a></td>
    <td className={sideCls(r.side)}>{r.side ? label(r.side) : '—'}</td>
    <td><Chip state={r.state} prov={r.provisional} /></td>
    <td className="num">{fmt(r.price)}</td>
    <td className="num">{fmt(r.orh)} / {fmt(r.orl)}</td>
    <td className="num">{r.rvol != null ? r.rvol.toFixed(2) + '×' : '—'}</td>
    <td className="num">{r.score}</td>
    <td className="num">{fmt(r.entry)} / {fmt(r.stop)} / {fmt(r.target)}</td>
    <td className="num">{r.qty != null ? r.qty : '—'}{r.risk_amount != null ? ' · ₹' + Math.round(r.risk_amount) : ''}</td>
  </tr>
)
