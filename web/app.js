const fmtMoney=v=>v==null?'—':new Intl.NumberFormat('en-US',{notation:'compact',style:'currency',currency:'USD',maximumFractionDigits:1}).format(v);
const fmtDelta=v=>v==null?'—':`${v>=0?'+':''}${v.toFixed(1)}pt`;
const fmtCents=v=>v==null?'—':`${(v*100).toFixed(1)}¢`;
const cls=v=>v==null?'flat':v>0?'up':v<0?'down':'flat';
const escapeHtml=s=>String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const favoriteKey='predict-pulse-favorites-v1';
let dashboard=null;
let favorites=new Set(JSON.parse(localStorage.getItem(favoriteKey)||'[]'));

function score(m){return Math.max(Math.abs(m.delta15||0),Math.abs(m.delta60||0));}
async function hydrateFavorites(data){
  const present=new Set((data.markets||[]).map(m=>m.category_slug));
  const missing=[...favorites].filter(slug=>!present.has(slug));
  const fetched=await Promise.all(missing.map(async slug=>{
    try{const r=await fetch(`api/category/${encodeURIComponent(slug)}`,{cache:'no-store'});return r.ok?(await r.json()).markets:[]}catch{return []}
  }));
  data.markets=[...(data.markets||[]),...fetched.flat()];
}
function filteredMarkets(data,filter){
  if(filter==='all')return data.movers;
  let rows=[...(data.markets||[])];
  if(filter==='favorites')rows=rows.filter(m=>favorites.has(m.category_slug));
  else rows=rows.filter(m=>m.segment===filter);
  return rows.sort((a,b)=>score(b)-score(a)||(b.liquidity||0)-(a.liquidity||0)).slice(0,30);
}
function renderTable(data){
  const filter=document.querySelector('#segment-filter').value;
  const rows=filteredMarkets(data,filter);
  const labels={all:data.display_mode==='watchlist'?'市场观察 · 基线积累中':'市场异动排行',favorites:'我的自选',crypto:'加密市场',esports:'电竞市场',sports:'体育市场',politics:'政治市场',other:'其他市场'};
  document.querySelector('#market-heading').textContent=labels[filter];
  document.querySelector('#filter-note').textContent=filter==='favorites'?`已收藏 ${favorites.size} 个市场链接`:`显示 ${rows.length} 个市场`;
  document.querySelector('#movers').innerHTML=rows.map(m=>`<tr>
    <td><a class="market" href="${escapeHtml(m.url)}" target="_blank" rel="noopener">${escapeHtml(m.title)}</a>${m.question&&m.question!==m.title?`<span class="question">${escapeHtml(m.question)}</span>`:''}</td>
    <td class="chance">${fmtCents(m.probability)}</td><td><span class="quote ask">买 ${fmtCents(m.best_ask)}</span><span class="quote bid">卖 ${fmtCents(m.best_bid)}</span></td>
    <td class="${cls(m.delta15)}">${fmtDelta(m.delta15)}</td><td class="${cls(m.delta60)}">${fmtDelta(m.delta60)}</td>
    <td>${fmtMoney(m.volume24h)}</td><td>${fmtMoney(m.liquidity)}</td></tr>`).join('')||'<tr><td colspan="7" class="empty">当前筛选下暂无市场</td></tr>';
  const visibleIds=new Set(rows.map(m=>String(m.market_id)));
  const alerts=filter==='all'?data.alerts:data.alerts.filter(a=>visibleIds.has(String(a.market_id)));
  const kinds={probability_15m:'15分钟概率',probability_60m:'1小时概率',volume:'成交量',liquidity:'流动性',spread:'价差'};
  document.querySelector('#alert-list').innerHTML=alerts.map(a=>`<div class="alert-item"><div class="alert-kind">${escapeHtml(kinds[a.kind]||a.kind)}</div><div class="alert-body"><strong>${escapeHtml(a.title)}</strong><br>${escapeHtml(a.body)}</div><div class="alert-time">${new Date(a.created_at*1000).toLocaleString('zh-CN')}</div></div>`).join('')||'<div class="empty">当前筛选下暂无异动告警。</div>';
}
function render(data){
  dashboard=data;
  document.querySelector('#status').textContent=data.status==='healthy'?'实时在线':'数据延迟';
  document.querySelector('#status').className=data.status==='healthy'?'up':'down';
  document.querySelector('#markets').textContent=data.market_count.toLocaleString();
  document.querySelector('#moved15').textContent=data.moved15_count.toLocaleString();
  document.querySelector('#alerts').textContent=data.alert_count.toLocaleString();
  document.querySelector('#updated').textContent=`更新于 ${new Date(data.updated_at*1000).toLocaleTimeString('zh-CN')}`;
  renderTable(data);
}
function slugFromUrl(value){
  try{const u=new URL(value);if(!u.hostname.endsWith('predict.fun'))return null;const m=u.pathname.match(/^\/category\/([^/]+)/);return m?decodeURIComponent(m[1]):null}catch{return null}
}
document.querySelector('#segment-filter').addEventListener('change',async()=>{if(dashboard){await hydrateFavorites(dashboard);renderTable(dashboard)}});
document.querySelector('#add-market').addEventListener('click',async()=>{
  const input=document.querySelector('#market-url');const slug=slugFromUrl(input.value.trim());
  if(!slug){document.querySelector('#filter-note').textContent='请输入有效的 Predict 市场链接';return}
  favorites.add(slug);localStorage.setItem(favoriteKey,JSON.stringify([...favorites]));input.value='';
  document.querySelector('#segment-filter').value='favorites';if(dashboard){await hydrateFavorites(dashboard);renderTable(dashboard)}
});
document.querySelector('#clear-markets').addEventListener('click',()=>{favorites.clear();localStorage.removeItem(favoriteKey);if(dashboard)renderTable(dashboard)});
async function refresh(){try{const r=await fetch('api/dashboard',{cache:'no-store'});if(!r.ok)throw Error(r.status);const data=await r.json();await hydrateFavorites(data);render(data)}catch{document.querySelector('#status').textContent='连接失败';document.querySelector('#status').className='down'}}
refresh();setInterval(refresh,30000);
