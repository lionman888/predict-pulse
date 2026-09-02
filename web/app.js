const fmtMoney=v=>v==null?'—':new Intl.NumberFormat('en-US',{notation:'compact',style:'currency',currency:'USD',maximumFractionDigits:1}).format(v);
const fmtDelta=v=>v==null?'—':`${v>=0?'+':''}${v.toFixed(1)}pt`;
const fmtCents=v=>v==null?'—':`${(v*100).toFixed(1)}¢`;
const cls=v=>v==null?'flat':v>0?'up':v<0?'down':'flat';
const escapeHtml=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
function render(data){
  document.querySelector('#status').textContent=data.status==='healthy'?'实时在线':'数据延迟';
  document.querySelector('#status').className=data.status==='healthy'?'up':'down';
  document.querySelector('#markets').textContent=data.market_count.toLocaleString();
  document.querySelector('#moved15').textContent=data.moved15_count.toLocaleString();
  document.querySelector('#alerts').textContent=data.alert_count.toLocaleString();
  document.querySelector('#updated').textContent=`更新于 ${new Date(data.updated_at*1000).toLocaleTimeString('zh-CN')}`;
  document.querySelector('#movers').innerHTML=data.movers.map(m=>`<tr>
    <td><a class="market" href="${escapeHtml(m.url)}" target="_blank" rel="noopener">${escapeHtml(m.title)}</a>${m.question&&m.question!==m.title?`<span class="question">${escapeHtml(m.question)}</span>`:''}</td>
    <td class="chance">${fmtCents(m.probability)}</td><td><span class="quote ask">买 ${fmtCents(m.best_ask)}</span><span class="quote bid">卖 ${fmtCents(m.best_bid)}</span></td>
    <td class="${cls(m.delta15)}">${fmtDelta(m.delta15)}</td><td class="${cls(m.delta60)}">${fmtDelta(m.delta60)}</td>
    <td>${fmtMoney(m.volume24h)}</td><td>${fmtMoney(m.liquidity)}</td></tr>`).join('')||'<tr><td colspan="7" class="empty">当前没有明显异动</td></tr>';
  const labels={probability_15m:'15分钟概率',probability_60m:'1小时概率',volume:'成交量',liquidity:'流动性',spread:'价差'};
  document.querySelector('#alert-list').innerHTML=data.alerts.map(a=>`<div class="alert-item"><div class="alert-kind">${escapeHtml(labels[a.kind]||a.kind)}</div><div class="alert-body"><strong>${escapeHtml(a.title)}</strong><br>${escapeHtml(a.body)}</div><div class="alert-time">${new Date(a.created_at*1000).toLocaleString('zh-CN')}</div></div>`).join('')||'<div class="empty">暂无异动告警，正在积累市场基线。</div>';
}
async function refresh(){try{const r=await fetch('api/dashboard',{cache:'no-store'});if(!r.ok)throw Error(r.status);render(await r.json())}catch(e){document.querySelector('#status').textContent='连接失败';document.querySelector('#status').className='down'}}
refresh();setInterval(refresh,30000);
