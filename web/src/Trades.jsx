import React, { useEffect, useRef, useState } from 'react'
import { api, fmt, bare, fmtDateTime } from './api.js'
import { Pager } from './Watchlist.jsx'
import { Select, SearchInput, label } from './ui.jsx'

const money = (x) => (x == null ? '—' : (x < 0 ? '-₹' : '₹') + Math.abs(Math.round(x)).toLocaleString('en-IN'))

export default function Trades() {
  const [pnl, setPnl] = useState(null)
  const [positions, setPositions] = useState([])
  const [running, setRunning] = useState(0)
  const [working, setWorking] = useState([])
  const [orders, setOrders] = useState(null)
  const [f, setF] = useState({ q: '', status: '', side: '' })
  const [page, setPage] = useState(1)
  const [place, setPlace] = useState(false)

  // Self-updating: positions/working/P&L refresh on a timer so running P&L and auto fills/closes
  // (paper from the live feed, live from the broker) show up on their own.
  const refreshLive = async () => {
    setPnl(await api('/api/pnl'))
    const p = await api('/api/positions'); setPositions(p.items); setRunning(p.running_pnl)
    setWorking((await api('/api/working-orders')).items)
  }
  const loadOrders = async () => {
    const p = new URLSearchParams({ ...f, page, page_size: 10 })
    setOrders(await api('/api/orders?' + p.toString()))
  }
  useEffect(() => { refreshLive(); const t = setInterval(refreshLive, 5000); return () => clearInterval(t) }, [])
  useEffect(() => { const t = setTimeout(loadOrders, 250); return () => clearTimeout(t) }, [f, page])

  const close = async (id) => { await api(`/api/orders/${id}/close`, { method: 'POST', body: {} }); refreshLive(); loadOrders() }
  const cancel = async (id) => { await api(`/api/orders/${id}/cancel`, { method: 'POST' }); refreshLive(); loadOrders() }
  const afterPlace = () => { setPlace(false); refreshLive(); loadOrders() }
  if (!pnl || !orders) return <div className="empty">Loading…</div>
  const pages = Math.max(1, Math.ceil(orders.total / orders.page_size))

  return (
    <div>
      <div className="kpis k4">
        <div className="kpi"><div className="label">Realised P&L</div><div className="val" style={{ color: pnl.realised >= 0 ? 'var(--long-ink)' : 'var(--short-ink)' }}>{money(pnl.realised)}</div><div className="sub">{pnl.trades} closed trades</div></div>
        <div className="kpi live"><div className="label">Running P&L <span className="livedot" /></div><div className="val" style={{ color: running >= 0 ? 'var(--long-ink)' : 'var(--short-ink)' }}>{money(running)}</div><div className="sub">{pnl.open} open · updates live</div></div>
        <div className="kpi accent"><div className="label">Win rate</div><div className="val">{pnl.win_rate}%</div><div className="sub">{pnl.wins} winners</div></div>
        <div className="kpi"><div className="label">Working</div><div className="val">{pnl.working}</div><div className="sub">orders not yet filled</div></div>
      </div>

      {working.length > 0 && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div className="panel-h"><h2>Working orders</h2>
            <span className="hint">Not filled yet — waiting for your entry. Cancel any time.</span></div>
          <div className="tbl-wrap" style={{ maxHeight: 'none' }}>
            <table>
              <thead><tr><th>Symbol</th><th>Side</th><th className="num">Qty</th><th className="num">Entry</th>
                <th className="num">Stop</th><th className="num">Target</th><th>Mode</th><th></th></tr></thead>
              <tbody>
                {working.map(o => (
                  <tr key={o.id}><td className="sym-cell">{bare(o.symbol)}</td>
                    <td className={o.side === 'LONG' ? 'up' : 'down'}>{label(o.side)}</td>
                    <td className="num">{o.qty}</td><td className="num">{fmt(o.entry)}</td>
                    <td className="num">{fmt(o.stop)}</td><td className="num">{fmt(o.target)}</td>
                    <td><span className="chip WATCH">{o.mode === 'live' ? 'Live · working' : 'Paper · working'}</span></td>
                    <td className="num"><button className="btn" onClick={() => cancel(o.id)}>Cancel</button></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-h"><h2>Open positions</h2>
          <span className="hint">Filled · P&L updates live</span><span className="spring" />
          <button className="btn primary" onClick={() => setPlace(true)}>+ New order</button></div>
        <div className="tbl-wrap" style={{ maxHeight: 'none' }}>
          <table>
            <thead><tr><th>Symbol</th><th>Side</th><th className="num">Qty</th><th className="num">Fill</th>
              <th className="num">Stop</th><th className="num">Target</th><th className="num">Running P&L</th><th></th></tr></thead>
            <tbody>
              {positions.length ? positions.map(o => (
                <tr key={o.id}><td className="sym-cell">{bare(o.symbol)}</td>
                  <td className={o.side === 'LONG' ? 'up' : 'down'}>{label(o.side)}</td>
                  <td className="num">{o.qty}</td><td className="num">{fmt(o.fill_price != null ? o.fill_price : o.entry)}</td>
                  <td className="num">{fmt(o.stop)}</td><td className="num">{fmt(o.target)}</td>
                  <td className={'num ' + (o.unrealized != null ? (o.unrealized >= 0 ? 'up' : 'down') : '')}>{o.unrealized != null ? money(o.unrealized) : '—'}</td>
                  <td className="num"><button className="btn danger" onClick={() => close(o.id)}>Close</button></td></tr>
              )) : <tr><td colSpan="8"><div className="empty">No open positions. Place an order or act on a radar signal.</div></td></tr>}
            </tbody>
          </table>
        </div>
      </div>

      <div className="panel">
        <div className="panel-h"><h2>Order history</h2><span className="spring" />
          <a className="btn" href="/api/audit.csv">Export CSV</a></div>
        <div className="filterbar">
          <SearchInput value={f.q} onChange={v => { setPage(1); setF({ ...f, q: v }) }} placeholder="Search symbol…" />
          <Select value={f.side} onChange={v => { setPage(1); setF({ ...f, side: v }) }} options={[
            { value: '', label: 'Any side' }, { value: 'LONG', label: 'Long' }, { value: 'SHORT', label: 'Short' }]} />
          <Select value={f.status} onChange={v => { setPage(1); setF({ ...f, status: v }) }} options={[
            { value: '', label: 'All statuses' }, { value: 'pending', label: 'Working' },
            { value: 'open', label: 'Open' }, { value: 'closed', label: 'Closed' },
            { value: 'cancelled', label: 'Cancelled' }]} />
          <span className="spring" /><span className="hint">{orders.total} orders</span>
        </div>
        <div className="tbl-wrap">
          <table>
            <thead><tr><th>Placed</th><th>Symbol</th><th>Side</th><th className="num">Qty</th>
              <th className="num">Entry → Exit</th><th>Status</th><th className="num">P&L</th><th className="num">R</th></tr></thead>
            <tbody>
              {orders.items.map(o => (
                <tr key={o.id}><td className="dim">{fmtDateTime(o.created_at)}</td>
                  <td className="sym-cell">{bare(o.symbol)}</td>
                  <td className={o.side === 'LONG' ? 'up' : 'down'}>{label(o.side)}</td>
                  <td className="num">{o.qty}</td>
                  <td className="num">{fmt(o.fill_price != null ? o.fill_price : o.entry)} → {o.exit_price != null ? fmt(o.exit_price) : '—'}</td>
                  <td><span className={'chip ' + statusChip(o)}>{statusLabel(o.status)}</span></td>
                  <td className={'num ' + (o.pnl >= 0 ? 'up' : 'down')}>{o.pnl != null ? money(o.pnl) : '—'}</td>
                  <td className={'num ' + ((o.result_r || 0) >= 0 ? 'up' : 'down')}>{o.result_r != null ? o.result_r + 'R' : '—'}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        {pages > 1 && <Pager page={orders.page} pages={pages} onPage={setPage} />}
      </div>

      {place && <PlaceOrder onClose={() => setPlace(false)} onDone={afterPlace} />}
    </div>
  )
}

const statusLabel = (s) => ({ pending: 'Working', open: 'Open', closed: 'Closed',
  cancelled: 'Cancelled', rejected: 'Rejected' }[s] || s)
function statusChip(o) {
  if (o.status === 'closed') return (o.pnl >= 0 ? 'CONFIRMED' : 'FAILED')
  if (o.status === 'open') return 'READY'
  if (o.status === 'cancelled' || o.status === 'rejected') return 'STALE'
  return 'WATCH'  // pending / working
}

export function PlaceOrder({ preset, onClose, onDone }) {
  const [o, setO] = useState({ symbol: preset?.symbol || '', side: preset?.side || 'LONG',
    qty: preset?.qty ? String(preset.qty) : '', entry: preset?.entry != null ? String(preset.entry) : '',
    stop: preset?.stop != null ? String(preset.stop) : '', target: preset?.target != null ? String(preset.target) : '' })
  const [touched, setTouched] = useState({})
  const [mode, setMode] = useState('paper')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const set = (k, v) => setO({ ...o, [k]: v })
  const mark = (k) => setTouched({ ...touched, [k]: true })

  const isNum = (v) => v !== '' && !isNaN(Number(v))
  const errs = {
    symbol: !o.symbol.trim() ? 'Pick a stock' : '',
    qty: !isNum(o.qty) ? 'Enter a number' : Number(o.qty) <= 0 || !Number.isInteger(Number(o.qty)) ? 'Whole number > 0' : '',
    entry: !isNum(o.entry) ? 'Enter a price' : Number(o.entry) <= 0 ? 'Must be > 0' : '',
    stop: o.stop !== '' && (!isNum(o.stop) || Number(o.stop) <= 0) ? 'Must be a price > 0' : '',
    target: o.target !== '' && (!isNum(o.target) || Number(o.target) <= 0) ? 'Must be a price > 0' : '',
  }
  const valid = !errs.symbol && !errs.qty && !errs.entry && !errs.stop && !errs.target

  const submit = async () => {
    setTouched({ symbol: 1, qty: 1, entry: 1, stop: 1, target: 1 })
    if (!valid) return
    setBusy(true)
    try { await api('/api/orders', { method: 'POST', body: { ...o, mode, source: preset ? 'signal' : 'manual' } }); onDone() }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  const Num = ({ k, lbl, ph }) => (
    <div className="field" style={{ flex: 1 }}>
      <label>{lbl}</label>
      <input inputMode="decimal" className={touched[k] && errs[k] ? 'input-bad' : ''} value={o[k]}
        onChange={e => set(k, e.target.value.replace(/[^\d.]/g, ''))} onBlur={() => mark(k)} placeholder={ph} />
      {touched[k] && errs[k] && <div className="err-txt">{errs[k]}</div>}
    </div>
  )

  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="panel-h"><h2>Place order</h2><span className="hint">{mode}</span><span className="spring" />
          <button className="btn" onClick={onClose}>Close</button></div>
        <div className="panel-b">
          {err && <div className="banner err">{err}</div>}
          <div className="field"><label>Stock</label>
            <SymbolSearch value={o.symbol} onPick={v => { set('symbol', v); mark('symbol') }} />
            {touched.symbol && errs.symbol && <div className="err-txt">{errs.symbol}</div>}</div>
          <div className="row">
            <div className="field" style={{ flex: 1 }}><label>Side</label>
              <Select value={o.side} onChange={v => set('side', v)} options={[{ value: 'LONG', label: 'Long' }, { value: 'SHORT', label: 'Short' }]} /></div>
            <Num k="qty" lbl="Quantity" ph="e.g. 100" />
          </div>
          <div className="row">
            <Num k="entry" lbl="Entry" ph="price" />
            <Num k="stop" lbl="Stop" ph="price" />
            <Num k="target" lbl="Target" ph="price" />
          </div>
          <div className="field"><label>Order mode</label>
            <div className="segmented">
              <button type="button" className={'seg' + (mode === 'paper' ? ' on' : '')} onClick={() => setMode('paper')}>Paper <span className="segsub">simulated</span></button>
              <button type="button" className={'seg' + (mode === 'live' ? ' on' : '')} onClick={() => setMode('live')}>Live <span className="segsub">real money</span></button>
            </div>
          </div>
          {mode === 'live' && <div className="banner warn">⚠️ Live order — this places a <strong>real order on your broker</strong> the moment you confirm. Needs today's broker login. Risk is capped at your limit.</div>}
          <button className={'btn btn-lg ' + (mode === 'live' ? 'good' : 'primary')} style={{ width: '100%', justifyContent: 'center', marginTop: 4 }}
            disabled={busy || !valid} onClick={submit}>{busy ? 'Placing…' : (mode === 'live' ? 'Place LIVE order' : 'Place paper order')}</button>
          <p className="note">{mode === 'live'
            ? 'Routed to your own connected broker (INTRADAY). You confirm every order; nothing fires on its own.'
            : 'Paper order — tracked for your P&L and journal. Switch to Live to route to your broker.'}</p>
        </div>
      </div>
    </div>
  )
}

export function SymbolSearch({ value, onPick }) {
  const [q, setQ] = useState(value || '')
  const [opts, setOpts] = useState([])
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => { setQ(value || '') }, [value])
  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('click', close); return () => document.removeEventListener('click', close)
  }, [])
  useEffect(() => {
    if (!q || q.length < 2) { setOpts([]); return }
    const t = setTimeout(async () => {
      const r = await api('/api/symbols?q=' + encodeURIComponent(q)).catch(() => ({ items: [] }))
      setOpts(r.items || [])
    }, 200)
    return () => clearTimeout(t)
  }, [q])
  return (
    <div style={{ position: 'relative' }} ref={ref}>
      <input value={q} placeholder="Search by name or symbol…" onFocus={() => setOpen(true)}
        onChange={e => { setQ(e.target.value); setOpen(true); onPick(e.target.value) }} />
      {open && opts.length > 0 && (
        <div className="sel-menu" style={{ left: 0, right: 0 }}>
          {opts.map(s => (
            <button type="button" key={s.symbol} className="sel-opt"
              onClick={() => { onPick(s.symbol); setQ(s.symbol); setOpen(false) }}>{s.name}
              <span className="faint" style={{ marginLeft: 8 }}>{s.symbol}</span></button>
          ))}
        </div>
      )}
    </div>
  )
}
