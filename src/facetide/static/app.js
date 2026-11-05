'use strict';
const domainMeta=[
 ['career','工作与职业','◇','工作的内容、节奏与去向'],
 ['finance','财务与安全','◈','安全、风险和未来选择'],
 ['health','身体与健康','✳','身体与日常照料'],
 ['family','爱与家庭','♡','亲密、家庭协作与连接'],
 ['social','朋友与社交','♧','来往、边界与归属'],
 ['leisure','休息与玩','☼','恢复与没有用途的喜欢'],
 ['environment','家与环境','⌂','空间与日常物理系统']
];
const state={token:'',snapshot:null,context:null,history:[],ratings:{},goalId:null,goalVersion:null,revisionOf:null};
const $=id=>document.getElementById(id);
const escapeHtml=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const dname=id=>domainMeta.find(d=>d[0]===id)?.[1]||id;
let toastTimer;
function toast(message,error=false){const node=$('toast');node.textContent=message;node.style.background=error?'#994c40':'#285a47';node.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>node.classList.remove('show'),4000)}
async function api(path,options={}){
 const response=await fetch(path,{cache:'no-store',...options,
  headers:{...(options.method==='POST'?{'Content-Type':'application/json','X-Facetide-Token':state.token}:{}),...(options.headers||{})}});
 let body;try{body=await response.json()}catch{throw Error('无法解析本地服务响应')}
 if(!response.ok)throw Error(body.error||'操作失败');
 return body;
}
const post=(url,data)=>api(url,{method:'POST',body:JSON.stringify(data)});
function nav(page){
 document.querySelectorAll('.page').forEach(el=>el.classList.toggle('active',el.id==='page-'+page));
 document.querySelectorAll('[data-page]').forEach(el=>el.classList.toggle('active',el.dataset.page===page));
 $('breadcrumb').textContent=({overview:'OVERVIEW / 生活总览',review:'REVIEW / 周期复盘',goals:'GOALS / 目标与够了',history:'HISTORY / 历史轨迹'})[page];
 window.scrollTo(0,0);
}
function polar(cx,cy,r,a){return [cx+Math.cos(a)*r,cy+Math.sin(a)*r]}
function wheelSvg(scores){
 const cx=230,cy=210,r=145,step=Math.PI*2/7;
 let grid='',fills='',labels='';
 [1,2,3,4,5].forEach(n=>{grid+=`<circle cx="${cx}" cy="${cy}" r="${r*n/5}" fill="none" stroke="#e7eee8" stroke-width="1"/>`});
 const count=Object.keys(scores).filter(d=>Number.isInteger(scores[d])).length;
 domainMeta.forEach((d,i)=>{
  const a=-Math.PI/2+i*step,b=a+step,mid=(a+b)/2,p1=polar(cx,cy,r,a),p2=polar(cx,cy,r,b);
  grid+=`<path d="M${cx} ${cy} L${p1[0]} ${p1[1]} A${r} ${r} 0 0 1 ${p2[0]} ${p2[1]} Z" fill="transparent" stroke="#e7eee8" stroke-width=".8"/>`;
  const score=scores[d[0]];
  if(Number.isInteger(score)){
   const rr=r*score/5,q1=polar(cx,cy,rr,a+.03),q2=polar(cx,cy,rr,b-.03),p=polar(cx,cy,rr,mid);
   fills+=`<path d="M${cx} ${cy} L${q1[0]} ${q1[1]} A${rr} ${rr} 0 0 1 ${q2[0]} ${q2[1]} Z" fill="#70a68d" fill-opacity="${(.11+score*.075).toFixed(2)}" stroke="#4d8d70" stroke-width="1.1"/><circle cx="${p[0]}" cy="${p[1]}" r="3.2" fill="#377f61"/>`;
  }
  const label=polar(cx,cy,r+36,mid);
  labels+=`<text x="${label[0]}" y="${label[1]}" text-anchor="middle" dominant-baseline="central" font-size="11" fill="${Number.isInteger(score)?'#496c5a':'#95a59b'}" font-weight="600">${escapeHtml(d[1])}</text>`;
 });
 return `<svg viewBox="0 0 460 420" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="七个生活领域的本人评分"><circle cx="${cx}" cy="${cy}" r="${r+5}" fill="#fcfefc" stroke="#e5ebe6"/>${grid}${fills}${labels}<circle cx="${cx}" cy="${cy}" r="35" fill="#fff" stroke="#dfeae2"/><text x="${cx}" y="${cy-2}" text-anchor="middle" font-size="21" fill="#377b61" font-weight="700">${count}<tspan font-size="12" fill="#9db4a3"> / 7</tspan></text><text x="${cx}" y="${cy+15}" text-anchor="middle" font-size="10" fill="#8ea597">已评价</text></svg>`;
}
function renderOverview(){
 const s=state.snapshot,r=s.latest_review,scores=r?.domain_scores||{};
 $('wheel').innerHTML=wheelSvg(scores);
 $('lastReview').textContent=r?'最近快照 · '+r.period_end:'尚无评分';
 const rated=Object.keys(scores).length;
 $('quickSummary').textContent=rated?rated+' 个领域已有本人评价':'开始记录自己的生活判断';
 $('growthAxis').textContent=r?.personal_growth||'尚无记录';
 $('realizationAxis').textContent=r?.self_realization||'尚无已确认记录';
 if(!r?.personal_growth){
   const candidates=state.context?.axis_drafts?.personal_growth?.insights;
   if(candidates?.length)$('growthAxis').textContent='Agent 未确认草稿：'+candidates[0].summary;
 }
 if(!r?.self_realization){
   const candidates=state.context?.axis_drafts?.self_realization?.insights;
   if(candidates?.length)$('realizationAxis').textContent='Agent 未确认草稿：'+candidates[0].summary;
 }
 $('domainCards').innerHTML=domainMeta.map(([id,name,icon,desc])=>{
  const score=scores[id],goals=s.goals.filter(g=>g.domain_ids.includes(id)).length;
  const card=(state.context?.domain_cards||[]).find(c=>c.domain_id===id);
  const evidence=card?.evidence?.[0];
  return `<article class="panel domain"><div class="domain-head"><div class="domain-icon">${icon}</div><div class="domain-score">${Number.isInteger(score)?score:'—'} <small>/ 5</small></div></div><h3>${name}</h3><p>${desc} · ${goals} 项目标</p><p class="observed-mini">${evidence?escapeHtml(evidence.summary):'本期暂无相关证据'} <small>${evidence?'来源：'+escapeHtml(evidence.source_type)+' · 未确认':'未知不等于退步'}</small></p><div class="bar"><span style="width:${Number.isInteger(score)?score*20:0}%"></span></div></article>`;
 }).join('');
}
function renderRatingRows(previous={}){
 $('ratingRows').innerHTML=domainMeta.map(([id,name])=>`<div class="rating-row" data-domain="${id}"><div><b>${name}</b><small>上次：${Number.isInteger(previous[id])?previous[id]+' 分':'尚无评分'}</small></div><div class="ratings" role="group" aria-label="${name}满意度">${[1,2,3,4,5].map(x=>`<button type="button" data-value="${x}" aria-pressed="false">${x}</button>`).join('')}<button class="clear" data-clear="yes" type="button">留空</button></div></div>`).join('');
 $('ratingRows').querySelectorAll('button').forEach(btn=>btn.addEventListener('click',()=>{
  const key=btn.closest('[data-domain]').dataset.domain;
  if(btn.dataset.clear)delete state.ratings[key];else state.ratings[key]=Number(btn.dataset.value);
  refreshRatingState();
 }));
 refreshRatingState();
}
function refreshRatingState(){
 document.querySelectorAll('.rating-row').forEach(row=>{
  const v=state.ratings[row.dataset.domain];
  row.querySelectorAll('[data-value]').forEach(btn=>{const on=Number(btn.dataset.value)===v;btn.classList.toggle('selected',on);btn.setAttribute('aria-pressed',String(on))});
 });
}
function renderContext(ctx){
 state.context=ctx;
 const previous=ctx.previous_review;
 $('previousSnapshot').innerHTML=previous?`<strong>${escapeHtml(previous.period_start)} → ${escapeHtml(previous.period_end)}</strong>`+
 domainMeta.map(([id,name])=>`<div>${name}：<b>${Number.isInteger(previous.domain_scores[id])?previous.domain_scores[id]+'/5':'未评'}</b></div>`).join(''):'<p>没有更早的快照。可以直接进行第一次复盘。</p>';
 renderRatingRows(previous?.domain_scores||{});
 const active=ctx.evidence.filter(e=>e.resolution_status==='active').length;
 $('evidenceCount').textContent=`${active} 条可引用证据`;
 $('evidenceList').innerHTML=ctx.evidence.length?ctx.evidence.map((e,i)=>
  `<label class="evidence"><input type="checkbox" data-evidence="${i}" ${e.resolution_status==='active'?'':'disabled'}><div><strong>${escapeHtml(e.summary||'[无可用摘要]')}</strong><small>${escapeHtml(e.source_type)} · ${escapeHtml(e.evidence_kind)} · 发生：${escapeHtml(e.occurred_at)} · 获知：${escapeHtml(e.known_at||'未知')}</small><small>关联：${e.domain_ids.map(dname).join('、')||'待归类'} · ${escapeHtml(e.resolution_status)} · ${escapeHtml(e.source_ref)}</small></div></label>`).join(''):
  '<div class="empty">本期没有可用证据。缺失不是退步；可以手动复盘。</div>';
 $('warnings').textContent=(ctx.warnings||[]).slice(0,6).join('\n');
 const stats=ctx.compilation||{};
 $('compilationStatus').textContent=(stats.compiled_items||0)+' / '+(stats.active_items||0)+' 条已编译';
 $('compiledDomains').innerHTML=(ctx.domain_cards||[]).map(card=>{
   const list=(card.evidence||[]).slice(0,5).map(e=>
     `<li><span>${escapeHtml(e.summary)}</span><small>${escapeHtml(e.source_type)} / ${escapeHtml(e.source_ref)} · ${escapeHtml(e.classification)} · ${escapeHtml(e.confidence||'来源标注')}</small></li>`).join('');
   return `<div class="compiled-card"><div class="compiled-card-top"><b>${dname(card.domain_id)}</b><small>${card.total_evidence||0} 条证据 · ${escapeHtml(card.status)}</small></div>${list?`<ul>${list}</ul>`:'<p class="soft">本期没有足够相关证据，不等于生活退步。</p>'}</div>`;
 }).join('');
 $('compilationWarnings').textContent=(stats.pending||0)?
   `尚有 ${stats.pending} 条来源记录等待 Agent 分类。可在连接的 Agent 中运行 facetide_reflection_guide；刷新本期后查看。`:
   (stats.unclassified||0)?`已处理记录中有 ${stats.unclassified} 条与七个领域无关或证据不足。`:'';
 for(const [axis,field] of [['personal_growth','growthInput'],['self_realization','realizationInput']]){
   const all=ctx.axis_drafts?.[axis]?.insights||[];
   const proposals=all.filter(x=>x.kind==='cross_event_inference');
   const picked=proposals.length?proposals:all;
   if(picked.length)$(field).value=picked.slice(0,4).map(x=>x.summary).join('\n');
 }
 const selected=new Set((ctx.domain_cards||[]).flatMap(card=>(card.evidence||[])
   .filter(e=>e.classification==='agent_compiled').map(e=>e.source_type+'::'+e.source_ref)));
 for(const group of Object.values(ctx.axis_drafts||{})){
   for(const insight of group.insights||[]){
     for(const ref of insight.evidence_refs||[])selected.add(ref.source_type+'::'+ref.source_ref);
   }
 }
 document.querySelectorAll('#evidenceList input[data-evidence]').forEach(el=>{
   const e=ctx.evidence[Number(el.dataset.evidence)];
   el.checked=!el.disabled&&selected.has(e.source_type+'::'+e.source_ref);
 });
 ['new','stable','receding'].forEach((type,index)=>{
  $(['changeNew','changeStable','changeReceding'][index]).value=(ctx.change_candidates[type]||[]).slice(0,3).map(e=>e.summary).join('\n');
 });
}
async function loadContext(){
 try{
  const start=$('startDate').value,end=$('endDate').value;
  if(!start||!end||start>end)throw Error('请选择有效的开始和结束日期');
  const ctx=await api('/api/context?'+new URLSearchParams({start,end}));
  state.ratings={};state.revisionOf=null;$('revisionNotice').hidden=true;$('reviewConfirm').checked=false;
  for(const id of ['growthInput','realizationInput','reviewNote'])$(id).value='';
  renderContext(ctx);
  if(state.snapshot)renderOverview();
  return ctx;
 }catch(e){toast(e.message,true);return null}
}
const lines=id=>$(id).value.split('\n').map(s=>s.trim()).filter(Boolean);
async function saveReview(){
 if(!$('reviewConfirm').checked){toast('请先确认评分和解释由本人认可。',true);return}
 if(!state.context){toast('请先读取复盘区间。',true);return}
 const refs=Array.from(document.querySelectorAll('#evidenceList input:checked')).map(el=>{
  const e=state.context.evidence[Number(el.dataset.evidence)];
  return {source_type:e.source_type,source_ref:e.source_ref};
 });
 const data={period_start:$('startDate').value,period_end:$('endDate').value,
  domain_scores:state.ratings,change_band:{new:lines('changeNew'),stable:lines('changeStable'),receding:lines('changeReceding')},
  evidence_refs:refs,personal_growth:$('growthInput').value,self_realization:$('realizationInput').value,
  user_notes:$('reviewNote').value,user_confirmed:true};
 if(state.revisionOf)data.revision_of=state.revisionOf;
 try{await post('/api/reviews',data);toast('复盘已保存，历史不会被静默修改。');state.revisionOf=null;await reload();nav('history')}
 catch(e){toast(e.message,true)}
}
function renderGoalOptions(){
 $('goalDomains').innerHTML=domainMeta.map(([id,name])=>`<label><input type="checkbox" value="${id}"> ${name}</label>`).join('');
}
function resetGoal(){
 state.goalId=null;state.goalVersion=null;$('goalForm').reset();$('goalFormTitle').textContent='设定一个真正重要的目标';
 $('goalDomains').querySelectorAll('input').forEach(el=>el.checked=false);
}
function editGoal(id){
 const g=state.snapshot.goals.find(x=>x.goal_id===id);if(!g)return;
 state.goalId=g.goal_id;state.goalVersion=g.version;
 $('goalTitle').value=g.title;$('goalEnough').value=g.enough_condition;$('goalStatus').value=g.status;
 $('goalDomains').querySelectorAll('input').forEach(el=>el.checked=g.domain_ids.includes(el.value));
 $('goalFormTitle').textContent='修改目标 · 当前版本 '+g.version;
  $('goalOutcome').value=(g.indicators?.outcome||[]).join('\n');
  $('goalDriver').value=(g.indicators?.driver||[]).join('\n');
  $('goalGuardrail').value=(g.indicators?.guardrail||[]).join('\n');
  nav('goals');
}
function renderGoals(){
 const goals=state.snapshot.goals,states={building:'建设',maintaining:'维持',reflecting:'反思',simplifying:'精简'};
 $('goalCount').textContent=goals.length+' 个目标';
 $('goalList').innerHTML=goals.length?goals.map(g=>
  `<article class="panel goal-card"><div class="state">${states[g.status]||g.status} · V${g.version}</div><h3>${escapeHtml(g.title)}</h3><p><b>怎样算够了：</b>${escapeHtml(g.enough_condition)}</p><div class="tags">${g.domain_ids.map(d=>`<span>${dname(d)}</span>`).join('')}</div>
  <div class="indicator-summary">${[['outcome','结果'],['driver','驱动'],['guardrail','护栏']].map(([kind,label])=>
   (g.indicators?.[kind]||[]).length?`<div><b>${label}：</b>${escapeHtml(g.indicators[kind].join('；'))}</div>`:'').join('')}</div><div class="card-foot"><small class="soft">最后修改：${escapeHtml(g.updated_at.slice(0,10))}</small><button data-edit="${escapeHtml(g.goal_id)}">修改目标 / 状态</button></div></article>`).join(''):
  '<div class="empty">暂时没有目标，不必强行为每个领域安排任务。</div>';
 document.querySelectorAll('[data-edit]').forEach(el=>el.addEventListener('click',()=>editGoal(el.dataset.edit)));
}
async function saveGoal(e){
 e.preventDefault();
 const domains=Array.from($('goalDomains').querySelectorAll('input:checked')).map(el=>el.value);
 if(!domains.length){toast('至少关联一个领域。',true);return}
 const indicators={};
  for(const [key,id] of [['outcome','goalOutcome'],['driver','goalDriver'],['guardrail','goalGuardrail']]){
    const parts=lines(id);if(parts.length)indicators[key]=parts;
  }
  const payload={title:$('goalTitle').value,enough_condition:$('goalEnough').value,
  domain_ids:domains,status:$('goalStatus').value,indicators,user_confirmed:true};
 if(state.goalId){payload.goal_id=state.goalId;payload.expected_version=state.goalVersion}
 try{await post('/api/goals',payload);resetGoal();await reload();toast('目标已更新。')}
 catch(err){toast(err.message,true)}
}
function renderTrend(){
 const id=$('trendDomain').value;
 const unique=new Map();
 for(const review of state.history){
   const key=review.period_start+'|'+review.period_end;
   if(!unique.has(key))unique.set(key,review);
 }
 const points=[...unique.values()].sort((a,b)=>a.period_end.localeCompare(b.period_end)).slice(-12);
 if(!points.length){$('trendChart').innerHTML='<div class="empty">暂无已确认的评分记录。</div>';return}
 const W=760,H=230,margin={left:48,right:25,top:20,bottom:43};
 const plot=W-margin.left-margin.right,plotHeight=H-margin.top-margin.bottom;
 const x=i=>margin.left+plot*(points.length===1?.5:i/(points.length-1));
 const y=v=>margin.top+(5-v)*plotHeight/4;
 const grid=[1,2,3,4,5].map(v=>`<line x1="${margin.left}" y1="${y(v)}" x2="${W-margin.right}" y2="${y(v)}" stroke="#e5eee8"/><text x="${margin.left-18}" y="${y(v)+4}" text-anchor="middle" font-size="12" fill="#8da596">${v}</text>`).join('');
 const bars=points.map((p,i)=>{
  const value=p.domain_scores[id],px=x(i),label=p.period_end.slice(5),base=y(1);
  const dot=Number.isInteger(value)?`<line x1="${px}" y1="${base}" x2="${px}" y2="${y(value)}" stroke="#8fbea3" stroke-width="7" stroke-linecap="round" opacity=".8"/><circle cx="${px}" cy="${y(value)}" r="5" fill="#397d62"/><text x="${px}" y="${y(value)-13}" text-anchor="middle" font-size="12" font-weight="700" fill="#386b58">${value}</text>`: `<circle cx="${px}" cy="${base}" r="3" fill="#d1dbd3"/>`;
  return dot+`<text x="${px}" y="${H-15}" text-anchor="middle" font-size="10.5" fill="#82958b">${escapeHtml(label)}</text>`;
 }).join('');
 $('trendChart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="${escapeHtml(dname(id))}的阶段评分图">${grid}${bars}</svg>`;
}
function renderHistory(){
 renderTrend();
 $('historyList').innerHTML=state.history.length?state.history.map(r=>
 `<article class="panel history-card"><div class="eyebrow">${escapeHtml(r.period_start)} — ${escapeHtml(r.period_end)}</div><h3>阶段快照 ${r.revision_of?'· 修订版':''}</h3>
 <div class="tags">${domainMeta.filter(d=>Number.isInteger(r.domain_scores[d[0]])).map(d=>`<span>${d[1]} ${r.domain_scores[d[0]]}/5</span>`).join('')||'<span>叙事复盘</span>'}</div>
 ${r.personal_growth?`<blockquote>成长：${escapeHtml(r.personal_growth)}</blockquote>`:''}
 ${r.self_realization?`<blockquote>实现：${escapeHtml(r.self_realization)}</blockquote>`:''}
 ${r.user_notes?`<blockquote>${escapeHtml(r.user_notes)}</blockquote>`:''}
 <div class="card-foot"><small class="soft">${escapeHtml(r.confirmed_at.slice(0,10))} · ${r.evidence_refs.length} 条来源引用</small><button data-revise="${escapeHtml(r.review_id)}">修订这份快照（保留原版）</button></div>
 </article>`).join(''):'<div class="empty">没有历史快照。完成第一次复盘后，这里会保留真实轨迹。</div>';
 document.querySelectorAll('[data-revise]').forEach(el=>el.addEventListener('click',()=>correctReview(el.dataset.revise)));
}
async function correctReview(id){
 const r=state.history.find(item=>item.review_id===id);if(!r)return;
 $('startDate').value=r.period_start;$('endDate').value=r.period_end;
 if(!await loadContext())return;
 state.revisionOf=r.review_id;state.ratings={...r.domain_scores};refreshRatingState();
 $('growthInput').value=r.personal_growth;$('realizationInput').value=r.self_realization;$('reviewNote').value=r.user_notes;
 ['new','stable','receding'].forEach((name,i)=>$( ['changeNew','changeStable','changeReceding'][i]).value=(r.change_band[name]||[]).join('\n'));
 const refs=new Set(r.evidence_refs.map(e=>e.source_type+'::'+e.source_ref));
 document.querySelectorAll('[data-evidence]').forEach(el=>{
  const e=state.context.evidence[Number(el.dataset.evidence)];
  el.checked=!el.disabled&&refs.has(e.source_type+'::'+e.source_ref);
 });
 $('reviewConfirm').checked=false;$('revisionNotice').hidden=false;nav('review');
}
async function reload(){
 state.snapshot=await api('/api/snapshot');
 state.history=(await api('/api/history?limit=100')).reviews;
 renderOverview();renderGoals();renderHistory();
}
async function init(){
 try{
  const bootstrap=await api('/api/bootstrap');state.token=bootstrap.token;
  $('sourceStatus').textContent='数据源：'+bootstrap.source;$('appVersion').textContent=bootstrap.version;
  const now=new Date(),from=new Date(now.getFullYear(),now.getMonth(),now.getDate()-29);
  const dateText=d=>[d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-');
  $('startDate').value=dateText(from);$('endDate').value=dateText(now);
  renderGoalOptions();renderRatingRows();
  $('trendDomain').innerHTML=domainMeta.map(([id,name])=>`<option value="${id}">${name}</option>`).join('');
  $('trendDomain').addEventListener('change',renderTrend);
  document.querySelectorAll('[data-page]').forEach(el=>el.addEventListener('click',()=>nav(el.dataset.page)));
  document.querySelectorAll('[data-go]').forEach(el=>el.addEventListener('click',()=>nav(el.dataset.go)));
  $('loadContext').addEventListener('click',loadContext);
  $('saveReview').addEventListener('click',saveReview);
  $('goalForm').addEventListener('submit',saveGoal);
  $('resetGoal').addEventListener('click',resetGoal);
  $('cancelRevision').addEventListener('click',()=>{state.revisionOf=null;$('revisionNotice').hidden=true});
  await reload();
 }catch(e){toast('无法连接本地服务：'+e.message,true)}
}
window.addEventListener('DOMContentLoaded',init);
