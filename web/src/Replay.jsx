import React, { useEffect, useMemo, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import { api, fmt, bare } from './api.js'
import { Chip, Select, label } from './ui.jsx'

// lightweight-charts has no timezone support and renders every axis label in UTC, so shift the
// series into IST — a replay is meaningless if the breakout reads 03:55 instead of 09:25.
const IST = 5.5 * 3600
const istTime = (t) => new Date(t * 1000).toLocaleTimeString('en-IN',
  { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hour12: false })

const SPEEDS = [{ value: '1', label: '1×' }, { value: '2', label: '2×' }, { value: '4', label: '4×' }]

const stateColor = (s) =>
  s === 'CONFIRMED' || s === 'RETEST_READY' ? '#22c55e'
    : s === 'READY' || s === 'BREAKOUT_PENDING' ? '#60a5fa'
      : s === 'WATCH' ? '#f5b84a'
        : s === 'EXPIRED' ? '#64708a' : '#f43f5e'

export default function Replay({ symbol, day, onClose }) {
  const box = useRef(null)
  const chartRef = useRef(null)
  const priceRef = useRef(null)
  const volRef = useRef(null)
  const linesRef = useRef([])

  const [d, setD] = useState(null)
  const [err, setErr] = useState('')
  const [i, setI] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState('2')

  // Read inside the polling interval, which would otherwise close over stale values.
  const dRef = useRef(null)
  const iRef = useRef(0)
  useEffect(() => { dRef.current = d }, [d])
  useEffect(() => { iRef.current = i }, [i])

  const url = '/api/replay/' + encodeURIComponent(symbol) + (day ? '?day=' + day : '')

  useEffect(() => {
    let dead = false
    ;(async () => {
      try {
        const r = await api(url)
        if (dead) return
        if (r.offline) { setErr(r.reason || 'Replay is not available right now.'); return }
        if (!r.candles || !r.candles.length) {
          setErr('No candles for this stock yet — its session has not produced any.'); return
        }
        setD(r); setI(0); setPlaying(true)
      } catch { if (!dead) setErr('Could not load the replay.') }
    })()
    return () => { dead = true }
  }, [url])

  // Follow a running session. Bars print every 5 minutes, so a 15s poll feels immediate and
  // costs nothing at the broker — /api/replay reads engine memory and never calls FYERS. The
  // engine tells us when the day is done so we stop re-fetching an payload that can't change.
  const following = !!(d && d.live)
  useEffect(() => {
    if (!following) return
    let dead = false
    const pull = async () => {
      if (document.hidden) return
      try {
        const r = await api(url)
        if (dead || r.offline || !r.candles || !r.candles.length) return
        const prev = dRef.current
        setD(r)
        // Ride the leading edge only if the user was already on it; if they have scrubbed back
        // to study a transition, new bars must not yank the chart out from under them.
        if (prev && r.candles.length > prev.candles.length &&
            iRef.current >= prev.candles.length - 1) {
          setI(r.candles.length - 1)
        }
      } catch { /* transient: keep showing the session we already have */ }
    }
    const id = setInterval(pull, 15000)
    return () => { dead = true; clearInterval(id) }
  }, [following, url])

  // Each transition is pinned to the bar you would have seen it on, so the chart marker, the
  // scrubber and the "what the engine saw" panel always reveal in lockstep.
  const events = useMemo(() => {
    if (!d) return []
    const ts = d.candles.map(c => c.t)
    return d.events.map(e => {
      let bi = 0
      for (let k = 0; k < ts.length; k++) { if (ts[k] <= e.t) bi = k; else break }
      return { ...e, bi }
    })
  }, [d])

  const shown = events.filter(e => e.bi <= i)
  const now = shown.length ? shown[shown.length - 1] : null
  const levels = [...shown].reverse().find(e => e.entry) || null
  const bar = d ? d.candles[Math.min(i, d.candles.length - 1)] : null

  // Built once, then fed by the effect below. Keyed on `ready` rather than `d` so a live poll
  // refreshes the series instead of tearing down and rebuilding the whole chart.
  const ready = !!d
  useEffect(() => {
    if (!ready || !box.current) return
    const chart = createChart(box.current, {
      width: box.current.clientWidth, height: 360,
      layout: { background: { color: 'transparent' }, textColor: '#97a4ba', fontFamily: 'Inter, sans-serif' },
      grid: { vertLines: { color: '#1a2130' }, horzLines: { color: '#1a2130' } },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#2c3650' },
      rightPriceScale: { borderColor: '#2c3650', scaleMargins: { top: 0.08, bottom: 0.26 } },
      crosshair: { mode: 1 },
    })
    const price = chart.addCandlestickSeries({
      upColor: '#22c55e', downColor: '#f43f5e', wickUpColor: '#22c55e',
      wickDownColor: '#f43f5e', borderVisible: false,
    })
    const vol = chart.addHistogramSeries({ priceFormat: { type: 'volume' }, priceScaleId: '' })
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } })
    chartRef.current = chart; priceRef.current = price; volRef.current = vol
    const onResize = () => box.current && chart.applyOptions({ width: box.current.clientWidth })
    window.addEventListener('resize', onResize)
    return () => {
      window.removeEventListener('resize', onResize)
      chart.remove()
      chartRef.current = priceRef.current = volRef.current = null
      linesRef.current = []
    }
  }, [ready])

  useEffect(() => {
    const price = priceRef.current, vol = volRef.current, chart = chartRef.current
    if (!d || !price || !vol || !chart) return
    const bars = d.candles.slice(0, i + 1)
    price.setData(bars.map(c => ({ time: c.t + IST, open: c.open, high: c.high, low: c.low, close: c.close })))
    vol.setData(bars.map(c => ({
      time: c.t + IST, value: c.volume, color: c.close >= c.open ? '#22c55e40' : '#f43f5e40',
    })))
    price.setMarkers(shown.map(e => ({
      time: d.candles[e.bi].t + IST,
      position: e.side === 'SHORT' ? 'aboveBar' : 'belowBar',
      shape: e.side === 'SHORT' ? 'arrowDown' : 'arrowUp',
      color: stateColor(e.state), text: label(e.state),
    })))

    linesRef.current.forEach(l => { try { price.removePriceLine(l) } catch { /* already gone */ } })
    linesRef.current = []
    const line = (p, color, title, style = 2) => {
      if (p == null || !Number(p)) return
      linesRef.current.push(price.createPriceLine({
        price: Number(p), color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title,
      }))
    }
    if (d.opening && bars.length && d.opening.t <= bars[bars.length - 1].t) {
      line(d.opening.high, '#8bbaff', 'OR High')
      line(d.opening.low, '#8bbaff', 'OR Low')
    }
    if (levels) {
      line(levels.entry, '#e7edf5', 'Entry', 0)
      line(levels.stop, '#f43f5e', 'Stop')
      line(levels.target, '#22c55e', 'Target')
    }
    chart.timeScale().fitContent()
  }, [d, i])

  useEffect(() => {
    if (!playing || !d) return
    const id = setInterval(() => {
      setI(prev => {
        if (prev >= d.candles.length - 1) { setPlaying(false); return prev }
        return prev + 1
      })
    }, Math.max(90, 700 / Number(speed)))
    return () => clearInterval(id)
  }, [playing, speed, d])

  const last = d ? d.candles.length - 1 : 0
  const atEnd = i >= last

  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 1080 }} onClick={e => e.stopPropagation()}>
        <div className="panel-h">
          <h2>{bare(symbol)}</h2>
          <span className="hint">Session replay — what the scanner saw, bar by bar</span>
          <span className="spring" />
          {d && d.live && <span className="rp-live">LIVE</span>}
          {d && <span className="hint">{d.session} · {d.mode}</span>}
          <button className="btn" style={{ marginLeft: 12 }} onClick={onClose}>Close</button>
        </div>

        <div className="panel-b">
          {err ? <div className="empty"><div className="big">Nothing to replay</div>{err}</div>
            : !d ? <div className="empty">Loading the session…</div> : (
              <>
                <div className="rp-grid">
                  <div style={{ minWidth: 0 }}>
                    <div ref={box} style={{ width: '100%' }} />
                    <div className="rp-transport">
                      <button className="btn" onClick={() => { setI(0); setPlaying(true) }} title="Restart">⏮</button>
                      <button className="btn primary" style={{ minWidth: 92, justifyContent: 'center' }}
                        onClick={() => { if (atEnd) setI(0); setPlaying(!playing) }}>
                        {playing ? '❚❚ Pause' : (atEnd ? '↻ Replay' : '▶ Play')}
                      </button>
                      <input type="range" min={0} max={last} value={i}
                        onChange={e => { setPlaying(false); setI(Number(e.target.value)) }} />
                      <span className="mono" style={{ fontSize: 13, minWidth: 92, textAlign: 'right' }}>
                        {bar ? istTime(bar.t) : '--:--'} IST
                      </span>
                      <Select value={speed} onChange={setSpeed} options={SPEEDS} width={78} />
                      {d.live && !atEnd && (
                        <button className="btn" onClick={() => { setPlaying(false); setI(last) }}>
                          Jump to live
                        </button>
                      )}
                    </div>
                    <p className="note" style={{ marginTop: 10 }}>
                      Bar {i + 1} of {last + 1}. Blue = opening range; white/red/green = the entry, stop and
                      target the engine derived. Arrows mark each state change. Times are IST.
                      {d.live && (atEnd
                        ? ' Following the session — new bars appear as they close.'
                        : ' Scrubbed back; press Jump to live to follow the session again.')}
                    </p>
                  </div>

                  <div className="rp-side">
                    <div style={{ marginBottom: 10 }}>
                      {now ? <Chip state={now.state} prov={now.provisional} />
                        : <span className="chip">Watching</span>}
                      {now && now.side ? <span className="faint" style={{ marginLeft: 8, fontSize: 12 }}>{label(now.side)}</span> : null}
                    </div>
                    <div style={{ fontSize: 12.5, color: 'var(--dim)', lineHeight: 1.5, minHeight: 54 }}>
                      {now ? now.note : 'No signal yet — the engine is still building the opening range and volume baseline.'}
                    </div>

                    <div style={{ margin: '14px 0' }}>
                      <KV k="Price" v={bar ? fmt(bar.close) : '—'} />
                      <KV k="Volume" v={bar ? bar.volume.toLocaleString('en-IN') : '—'} />
                      <KV k="RVOL" v={now && now.rvol != null ? now.rvol.toFixed(2) + '×' : '—'} />
                      <KV k="Score" v={now ? now.score + '/100' : '—'} />
                      <KV k="Entry" v={levels ? fmt(levels.entry) : '—'} />
                      <KV k="Stop" v={levels ? fmt(levels.stop) : '—'} />
                      <KV k="Target" v={levels ? fmt(levels.target) : '—'} />
                      <KV k="Net R:R" v={levels && levels.net_rr != null ? levels.net_rr.toFixed(2) + ':1' : '—'} />
                    </div>

                    <div className="hint" style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: '.08em', color: 'var(--faint)', marginBottom: 6 }}>
                      Transitions
                    </div>
                    {events.length ? events.map((e, k) => (
                      <button key={k} className={'rp-step' + (e.bi > i ? ' future' : (e === now ? ' now' : ''))}
                        onClick={() => { setPlaying(false); setI(e.bi) }}>
                        <span className="t mono">{(e.time || '').slice(11, 16)}</span>
                        <span style={{ flex: 1 }}>
                          <Chip state={e.state} prov={e.provisional} />
                          {e.net_rr != null && <span className="faint" style={{ marginLeft: 6, fontSize: 11 }}>{e.net_rr.toFixed(2)}:1</span>}
                        </span>
                      </button>
                    )) : <div className="faint" style={{ fontSize: 12 }}>This stock never set up today.</div>}
                  </div>
                </div>
              </>
            )}
        </div>
      </div>
    </div>
  )
}

const KV = ({ k, v }) => (
  <div className="rp-kv"><span>{k}</span><span className="mono">{v}</span></div>
)
