const fmtMoney=v=>v==null?'—':new Intl.NumberFormat('en-US',{notation:'compact',style:'currency',currency:'USD',maximumFractionDigits:1}).format(v);
const fmtDelta=v=>v==null?'—':`${v>=0?'+':''}${v.toFixed(1)}pt`;
const cls=v=>v==null?'flat':v>0?'up':v<0?'down':'flat';
const escapeHtml=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
function render(data){
  document.querySelector('#status').textContent=data.status==='healthy'?'实时在线':'数据延迟';
  document.querySelector('#status').className=data.status==='healthy'?'up':'down';
  document.querySelector('#markets').textContent=data.market_count.toLocaleString();
  document.querySelector('#snapshots').textContent=data.snapshot_count.toLocaleString();
  document.querySelector('#alerts').textContent=data.alert_count.toLocaleString();
  document.querySelector('#updated').textContent=`更新于 ${new Date(data.updated_at*1000).toLocaleTimeString('zh-CN')}`;
  document.querySelector('#movers').innerHTML=data.movers.map(m=>`<tr>
    <td><a class="market" href="${escapeHtml(m.url)}" target="_blank">${escapeHtml(m.title)}</a><span class="question">${escapeHtml(m.question)}</span></td>
    <td class="chance">${m.probability==null?'—':(m.probability*100).toFixed(1)+'%'}</td>
    <td class="${cls(m.delta15)}">${fmtDelta(m.delta15)}</td><td class="${cls(m.delta60)}">${fmtDelta(m.delta60)}</td>
    <td>${fmtMoney(m.volume24h)}</td><td>${fmtMoney(m.liquidity)}</td></tr>`).join('')||'<tr><td colspan="6" class="empty">暂无市场</td></tr>';
  document.querySelector('#alert-list').innerHTML=data.alerts.map(a=>`<div class="alert-item"><div class="alert-kind">${escapeHtml(a.kind)}</div><div class="alert-body"><strong>${escapeHtml(a.title)}</strong><br>${escapeHtml(a.body)}</div><div class="alert-time">${new Date(a.created_at*1000).toLocaleString('zh-CN')}</div></div>`).join('')||'<div class="empty">暂无异动告警，正在积累市场基线。</div>';
}
async function refresh(){try{const r=await fetch('api/dashboard',{cache:'no-store'});if(!r.ok)throw Error(r.status);render(await r.json())}catch(e){document.querySelector('#status').textContent='连接失败';document.querySelector('#status').className='down'}}
refresh();setInterval(refresh,30000);
