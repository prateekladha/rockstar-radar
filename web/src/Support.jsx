import React, { useState } from 'react'
import { api } from './api.js'
import { Select } from './ui.jsx'

const KINDS = [
  { value: 'question', label: 'Question' },
  { value: 'issue', label: 'Report an issue' },
  { value: 'feature', label: 'Feature request' },
]

export default function Support({ onClose }) {
  const [kind, setKind] = useState('question')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)
  const [err, setErr] = useState('')

  const submit = async () => {
    setErr('')
    if (message.trim().length < 3) { setErr('Please enter a bit more detail.'); return }
    setBusy(true)
    try { const r = await api('/api/support', { method: 'POST', body: { kind, message } }); setDone(r.message) }
    catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="scrim" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="panel-h"><h2>Contact &amp; support</h2><span className="spring" />
          <button className="btn" onClick={onClose}>Close</button></div>
        <div className="panel-b">
          {done ? (
            <div className="empty" style={{ padding: '28px 10px' }}>
              <div style={{ fontSize: 30, marginBottom: 10 }}>✅</div>
              <div className="big">Message sent</div>
              <div style={{ maxWidth: 320, margin: '6px auto 0' }}>{done}</div>
              <div style={{ marginTop: 18 }}><button className="btn primary" onClick={onClose}>Done</button></div>
            </div>
          ) : (
            <>
              {err && <div className="banner err">{err}</div>}
              <div className="field"><label>What's this about?</label>
                <Select value={kind} onChange={setKind} options={KINDS} width={'100%'} /></div>
              <div className="field"><label>Message</label>
                <textarea rows={5} value={message} onChange={e => setMessage(e.target.value)}
                  style={{ fontFamily: 'var(--sans)', minHeight: 120 }}
                  placeholder="Tell us your question, the issue you hit, or what you'd like to see…" /></div>
              <button className="btn primary btn-lg" style={{ width: '100%', justifyContent: 'center' }}
                disabled={busy} onClick={submit}>{busy ? 'Sending…' : 'Send message'}</button>
              <p className="note">Goes straight to the team. We'll reply to your account email.</p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
