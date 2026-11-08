// Global Paper/Actual view toggle — every screen scopes its data to this so paper, live and
// simulation data never mix. Persisted across reloads; broadcast to all subscribers on change.
import { useEffect, useState } from 'react'

let _mode = localStorage.getItem('viewMode') === 'live' ? 'live' : 'paper'
const subs = new Set()

export function getViewMode() { return _mode }
export function setViewMode(m) {
  _mode = m === 'live' ? 'live' : 'paper'
  localStorage.setItem('viewMode', _mode)
  subs.forEach(f => f(_mode))
}
export function useViewMode() {
  const [m, setM] = useState(_mode)
  useEffect(() => { const f = (x) => setM(x); subs.add(f); return () => subs.delete(f) }, [])
  return m
}
