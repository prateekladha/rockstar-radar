import React, { useEffect, useRef, useState } from 'react'

// Human labels for enums (code/CSS keep the enum key; the UI shows these).
const LABELS = {
  RETEST_READY: 'Retest ready', CONFIRMED: 'Confirmed', BREAKOUT_PENDING: 'Breakout pending',
  WATCH: 'Watch', READY: 'Ready', RETEST_CANDIDATE: 'Retest candidate', RISK_FAIL: 'Risk rejected',
  FAILED: 'Failed', EXPIRED: 'Expired', RETRACTED: 'Retracted', NONE: 'No setup',
  WAIT_OR: 'Waiting for range', NO_SETUP: 'No setup', WAIT_VOLUME: 'Low volume',
  RECOVERING: 'Recovering', SESSION_CLOSED: 'Closed', FILTERED: 'Filtered', HALTED: 'Paused',
  STALE: 'Stale', LONG: 'Long', SHORT: 'Short',
  open: 'Open', closed: 'Closed', cancelled: 'Cancelled',
  target: 'Target hit', stop: 'Stopped out',
  long: 'Long', short: 'Short', both: 'Two-way', avoid: 'Avoid',
}
export const label = (k) => (k == null ? '—' : (LABELS[k] ?? String(k)))

export const Chip = ({ state, prov, children }) => (
  <span className={'chip ' + state}>{children ?? label(state)}
    {prov ? <span className="prov">LIVE</span> : null}</span>
)

// Fully-styled dropdown (custom menu so options are themed, unlike native <select>).
export function Select({ value, onChange, options, placeholder = 'Select', width }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    const close = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('click', close); return () => document.removeEventListener('click', close)
  }, [])
  const cur = options.find(o => String(o.value) === String(value))
  return (
    <div className="sel" ref={ref} style={width ? { width } : undefined}>
      <button type="button" className={'sel-btn' + (open ? ' open' : '')} onClick={() => setOpen(!open)}>
        <span className={cur ? '' : 'faint'}>{cur ? cur.label : placeholder}</span>
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 6l4 4 4-4" /></svg>
      </button>
      {open && (
        <div className="sel-menu">
          {options.map(o => (
            <button type="button" key={o.value} disabled={o.disabled}
              className={'sel-opt' + (String(o.value) === String(value) ? ' active' : '')}
              onClick={() => { if (!o.disabled) { onChange(o.value); setOpen(false) } }}>
              {o.label}{o.disabled ? <span className="faint" style={{ marginLeft: 6 }}>soon</span> : null}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function Checkbox({ checked, onChange, children }) {
  return (
    <label className="cbx">
      <input type="checkbox" checked={!!checked} onChange={e => onChange(e.target.checked)} />
      <span className="cbx-box"><svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M3 8l3.5 3.5L13 4" /></svg></span>
      {children && <span>{children}</span>}
    </label>
  )
}

export function SearchInput({ value, onChange, placeholder = 'Search…', width }) {
  return (
    <div className="searchbox" style={width ? { width } : undefined}>
      <svg className="s-ico" width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="7" cy="7" r="5" /><path d="M11 11l3 3" strokeLinecap="round" /></svg>
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} />
      {value && <button type="button" className="s-clear" onClick={() => onChange('')} aria-label="Clear">×</button>}
    </div>
  )
}
