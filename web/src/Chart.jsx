import React, { useEffect, useRef, useState } from 'react'
import { createChart } from 'lightweight-charts'
import { api, bare } from './api.js'

const TFS = ['1m', '5m', '15m', '1d']
const TV_INT = { '1m': '1', '5m': '5', '15m': '15', '1d': 'D' }

export default function Chart({ symbol, levels, onClose }) {
  const box = useRef(null)
  const [tf, setTf] = useState('5m')
  const [err, setErr] = useState('')

  useEffect(() => {
    let chart, disposed = false
    ;(async () => {
      const qs = '?tf=' + tf + (levels?.entry ? '&base=' + levels.entry : '')
      const d = await api('/api/chart/' + encodeURIComponent(symbol) + qs).catch(() => null)
      if (!d || !box.current || disposed) { if (!d) setErr('Could not load chart.'); return }
      chart = createChart(box.current, {
        width: box.current.clientWidth, height: 400,
        layout: { background: { color: 'transparent' }, textColor: '#97a4ba' },
        grid: { vertLines: { color: '#1a2130' }, horzLines: { color: '#1a2130' } },
        timeScale: { timeVisible: tf !== '1d', borderColor: '#2c3650' },
        rightPriceScale: { borderColor: '#2c3650' },
        crosshair: { mode: 1 },
        handleScroll: true, handleScale: true,
      })
      const s = chart.addCandlestickSeries({ upColor: '#22c55e', downColor: '#f43f5e',
        wickUpColor: '#22c55e', wickDownColor: '#f43f5e', borderVisible: false })
      s.setData(d.candles)
      const line = (price, color, title) => price && s.createPriceLine({
        price: Number(price), color, lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title })
      line(d.or_high, '#8bbaff', 'OR H'); line(d.or_low, '#8bbaff', 'OR L')
      if (levels) { line(levels.entry, '#e7edf5', 'Entry'); line(levels.stop, '#f43f5e', 'Stop'); line(levels.target, '#22c55e', 'Target') }
      chart.timeScale().fitContent()
      const onResize = () => box.current && chart.applyOptions({ width: box.current.clientWidth })
      window.addEventListener('resize', onResize)
      chart._cleanup = () => window.removeEventListener('resize', onResize)
    })()
    return () => { disposed = true; if (chart) { chart._cleanup?.(); chart.remove() } }
  }, [symbol, tf])

  const tvUrl = 'https://www.tradingview.com/chart/?symbol=' + encodeURIComponent(symbol) + '&interval=' + TV_INT[tf]
  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" style={{ maxWidth: 860 }} onClick={e => e.stopPropagation()}>
        <div className="panel-h"><h2>{bare(symbol)}</h2>
          <div className="tf-tabs">{TFS.map(t => (
            <button key={t} className={'tf' + (t === tf ? ' active' : '')} onClick={() => setTf(t)}>{t}</button>))}</div>
          <span className="spring" />
          <a href={tvUrl} target="_blank" rel="noreferrer">TradingView ↗</a>
          <button className="btn" style={{ marginLeft: 12 }} onClick={onClose}>Close</button></div>
        <div className="panel-b">
          {err ? <div className="empty">{err}</div> : <div ref={box} style={{ width: '100%' }} />}
          <p className="note">Drag to pan, scroll to zoom. Blue = opening range; white/red/green = your entry/stop/target.</p>
        </div>
      </div>
    </div>
  )
}
