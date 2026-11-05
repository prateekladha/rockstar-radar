import React, { useEffect, useState } from 'react'
import { api } from './api.js'
import { Select } from './ui.jsx'

const ROLE_OPTS = [{ value: 'admin', label: 'Admin' }, { value: 'trader', label: 'Trader' }]
const okEmail = (e) => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(e)

export default function Family() {
  const [data, setData] = useState(null)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('trader')
  const [msg, setMsg] = useState('')
  const load = async () => setData(await api('/api/family'))
  useEffect(() => { load() }, [])
  if (!data) return <div className="empty">Loading…</div>

  const invite = async () => {
    try { await api('/api/family/invite', { method: 'POST', body: { email, role } }); setEmail(''); setMsg('Invited ' + email); load() }
    catch (e) { setMsg(e.message) }
  }
  const changeRole = async (id, r) => {
    try { await api('/api/family/member/' + id, { method: 'PATCH', body: { role: r } }); load() }
    catch (e) { setMsg(e.message) }
  }
  const remove = async (id) => { await api('/api/family/member/' + id, { method: 'DELETE' }); load() }

  return (
    <div className="panel">
      <div className="panel-h"><h2>{data.household}</h2><span className="hint">{data.members.length} member(s) · one setup for the whole family/firm</span></div>
      <div className="panel-b">
        {msg && <div className="banner ok">{msg}</div>}
        <div className="tbl-wrap" style={{ maxHeight: 'none', marginBottom: 18 }}>
          <table>
            <thead><tr><th>Member</th><th>Role</th><th>Status</th><th></th></tr></thead>
            <tbody>
              {data.members.map(m => (
                <tr key={m.id}>
                  <td className="sym-cell">{m.name || m.email}<div className="dim" style={{ fontWeight: 400, fontSize: 12 }}>{m.email}</div></td>
                  <td>{data.can_manage && !m.is_me
                    ? <Select value={m.role} onChange={v => changeRole(m.id, v)} options={ROLE_OPTS} width={130} />
                    : <span className="chip">{m.role}</span>}</td>
                  <td>{m.is_me ? <span className="chip CONFIRMED">you</span>
                    : m.pending ? <span className="chip WATCH">pending invite</span> : <span className="chip">active</span>}</td>
                  <td className="num">{data.can_manage && !m.is_me && m.role !== 'owner'
                    ? <button className="btn danger" onClick={() => remove(m.id)}>Remove</button> : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {data.can_manage && (
          <>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <input placeholder="family member email" value={email}
                className={email && !okEmail(email) ? 'input-bad' : ''}
                onChange={e => setEmail(e.target.value)} style={{ flex: '2 1 220px', minWidth: 200 }} />
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', flex: 'none' }}>
                <Select value={role} onChange={setRole} options={ROLE_OPTS} width={140} />
                <button className="btn primary" disabled={!okEmail(email)} onClick={invite}>Invite</button>
              </div>
            </div>
            {email && !okEmail(email) && <div className="err-txt">Enter a valid email</div>}
          </>
        )}
        <p className="note">Invited members sign in with Google using the same email and join this household automatically — they don't set anything up again.</p>
      </div>
    </div>
  )
}
