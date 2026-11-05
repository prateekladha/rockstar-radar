// Rockstar Radar — Control Center client. SSR renders the shell + config; this drives the
// live radar island (KPIs, trade tickets, full table with filters, signal journal).
(function(){
  const $=s=>document.querySelector(s), $$=s=>document.querySelectorAll(s);
  const fx=x=>typeof x==='number'?x.toLocaleString('en-IN',{maximumFractionDigits:2}):'—';
  const bare=s=>(s||'').replace('NSE:','').replace('-EQ','');
  const ACTIVE=['WATCH','READY','BREAKOUT_PENDING','CONFIRMED','RETEST_CANDIDATE','RETEST_READY'];
  let LAST=null;

  // ---- tabs ----
  function setTab(v){
    $$('.tab').forEach(t=>t.classList.toggle('active',t.dataset.view===v));
    $$('.view').forEach(s=>s.classList.toggle('active',s.id==='view-'+v));
    try{localStorage.setItem('rr_tab',v)}catch(e){}
  }
  $$('.tab').forEach(t=>t.addEventListener('click',()=>setTab(t.dataset.view)));
  try{const s=localStorage.getItem('rr_tab');if(s)setTab(s)}catch(e){}

  // ---- flash -> toast ----
  const q=new URLSearchParams(location.search);
  if(q.get('msg')||q.get('err')){toast(q.get('msg')||q.get('err'),q.get('err')?'err':'ok');
    history.replaceState({},'',location.pathname);}
  function toast(m,kind){const t=$('#toast');if(!t)return;t.textContent=m;t.className='toast show '+(kind||'');
    clearTimeout(t._t);t._t=setTimeout(()=>t.className='toast',3000);}

  function marketFrom(ts){
    if(!ts)return{label:'Market',cls:''};
    const [h,m]=ts.slice(11,16).split(':').map(Number), mins=h*60+m;
    if(mins<555)return{label:'Pre-open',cls:'warn'};
    if(mins<=930)return{label:'Open',cls:'live'};
    return{label:'Closed',cls:'off'};
  }
  function chip(state,prov){return `<span class="chip ${state}">${state}</span>${prov?'<span class="prov">LIVE·PROV</span>':''}`;}
  function sideCls(s){return s==='LONG'?'up':(s==='SHORT'?'down':'');}
  async function j(u){try{return await (await fetch(u,{cache:'no-store'})).json();}catch(e){return null;}}

  function renderStatus(st){
    if(!st)return;
    const c=st.connection,s=st.scanner;
    const cp=$('#connpill'); if(cp){cp.querySelector('.dot').className='dot '+(c.token_present?'live':'off');cp.querySelector('span:last-child').textContent=c.token_present?'Connected':'Not connected';}
    const sp=$('#scanpill'); if(sp){sp.querySelector('.dot').className='dot '+(s.running?'live':'off');sp.querySelector('span:last-child').textContent=s.running?'Scanner live':'Scanner off';}
  }

  function ticketHTML(r){
    const side=(r.side||'').toLowerCase(), rr=r.net_rr!=null?r.net_rr.toFixed(2):'—';
    return `<div class="ticket ${side}"><div class="top"><div class="sym">${bare(r.symbol)}</div>${chip(r.state,r.provisional)}</div>
      <div class="ladder"><div class="c"><div class="k">Entry</div><div class="v">${fx(r.entry)}</div></div>
      <div class="c"><div class="k">Stop</div><div class="v down">${fx(r.stop)}</div></div>
      <div class="c"><div class="k">Target</div><div class="v up">${fx(r.target)}</div></div></div>
      <div class="meta"><span>Side <b>${r.side||'—'}</b></span><span>R:R <b>${rr}</b></span><span>Qty <b>${r.qty??'—'}</b></span><span>Risk <b>${r.risk_amount!=null?'₹'+Math.round(r.risk_amount):'—'}</b></span></div>
      <div class="foot">Estimate only — verify before entry. Not an auto-order.</div></div>`;
  }
  function rowHTML(r){
    return `<tr><td class="sym-cell"><a href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent(r.symbol)}" target="_blank">${bare(r.symbol)}</a><span class="src ${r.source||'AUTO'}">${r.source||'AUTO'}</span></td>
      <td class="${sideCls(r.side)}">${r.side||'—'}</td><td>${chip(r.state,r.provisional)}</td>
      <td class="num">${fx(r.price)}</td><td class="num">${fx(r.orh)} / ${fx(r.orl)}</td>
      <td class="num">${r.rvol!=null?r.rvol.toFixed(2)+'×':'—'}</td><td class="num">${r.score}</td>
      <td class="num">${fx(r.entry)} / ${fx(r.stop)} / ${fx(r.target)}</td>
      <td class="num">${r.qty!=null?r.qty:'—'}${r.risk_amount!=null?' · ₹'+Math.round(r.risk_amount):''}</td></tr>`;
  }

  function renderTable(){
    if(!LAST||LAST.offline)return;
    const qq=($('#f_search').value||'').toUpperCase(),src=$('#f_source').value,side=$('#f_side').value,stt=$('#f_state').value;
    const rows=(LAST.all||[]).filter(r=>{
      if(qq && !bare(r.symbol).includes(qq))return false;
      if(src && (r.source||'AUTO')!==src)return false;
      if(side && r.side!==side)return false;
      if(stt==='active'){if(!ACTIVE.includes(r.state))return false;}
      else if(stt && r.state!==stt)return false;
      return true;
    });
    $('#f_count').textContent=rows.length+' shown';
    $('#radarbody').innerHTML=rows.length?rows.map(rowHTML).join('')
      :'<tr><td colspan="9"><div class="empty">No stocks match the filter.</div></td></tr>';
  }
  function renderJournal(ev){
    $('#jcount').textContent=ev.length?ev.length+' events':'—';
    $('#journal').innerHTML=ev.length?ev.slice(0,60).map(e=>
      `<div class="jitem"><div class="jhead"><span class="jsym">${bare(e.symbol)} ${e.side||''}</span>${chip(e.state,e.provisional)}</div>
       <div class="jnote"><span class="jtime">${(e.time||'').slice(11)}</span> · ${e.note||''}</div></div>`).join('')
      :'<div class="empty">No signals yet.</div>';
  }

  function renderLive(d){
    LAST=d;
    if(!d||d.offline){
      $('#radarhint').textContent=(d&&d.reason)||'Scanner idle';
      ['k_mon','k_or','k_base','k_ticks','k_active'].forEach(id=>$('#'+id).textContent='—');
      $('#tickets').innerHTML='';
      $('#radarbody').innerHTML='<tr><td colspan="9"><div class="empty"><div class="big">'+((d&&d.reason)||'Scanner idle')+'</div>Start the scanner from the Connect tab to see live candidates.</div></td></tr>';
      $('#journal').innerHTML='<div class="empty">No signals yet.</div>';
      $('#f_count').textContent='—';$('#jcount').textContent='—';
      return;
    }
    $('#k_mon').textContent=d.monitored??'—';
    $('#k_or').textContent=d.anchors_ready??'—';
    $('#k_base').textContent=d.baselines_ready??'—';
    $('#k_ticks').textContent=d.received_ticks??'—';
    $('#k_feed').textContent=(d.feed_health||'feed').slice(0,34);
    $('#k_active').textContent=d.active_candidates??'—';
    $('#radarhint').textContent=d.session_closed?('Review only — closed '+d.new_signals_stop+' IST')
      :('Updated '+(d.server_time_ist||'').slice(11)+' IST');
    const mk=marketFrom(d.server_time_ist);
    $('#clock').textContent=(d.server_time_ist||'').slice(11)+' IST';
    $('#mktdot').className='dot '+mk.cls; $('#mktlabel').textContent=mk.label;

    const act=(d.all||[]).filter(r=>r.state==='RETEST_READY'||r.state==='CONFIRMED').slice(0,8);
    $('#tickets').innerHTML=act.map(ticketHTML).join('');
    renderTable();
    renderJournal(d.events||[]);
  }

  ['f_search','f_source','f_side','f_state'].forEach(id=>{const el=$('#'+id);if(el)el.addEventListener('input',renderTable);});

  async function poll(){renderStatus(await j('/api/status'));renderLive(await j('/api/state'));}
  poll();setInterval(poll,3000);
})();
