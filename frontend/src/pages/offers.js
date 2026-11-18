import{title,grade,options,input,money,button,isViewer,isSupervisor}from'../components/tickets.js';
import{esc,data}from'../utils/format.js';
import{perform,bindActions,toast}from'../utils/actions.js';
import{api}from'../api.js';
import{LOT_STATES}from'../constants.js';

// 寿命保守下界把关面板：挂场页可查下界、用到哪些留样、拦截原因与主管签字
export async function guardPanel(s,sampleId){
  let g=null,error='';
  if(sampleId){try{g=await api('/samples/'+sampleId+'/life-guard')}catch(e){error=e.message}}
  if(!g)return `<section class="paper guard"><h2>寿命保守下界把关</h2><p class="note">选择本批已核级留样后，按同品种其他到场批已封存实测与原估值计算本次寿命的九成保守下界。</p></section>`;
  let status;
  if(g.block_reasons&&g.block_reasons.length){
    status=`<p class="error"><b>拦截占筐：</b>${g.block_reasons.map(esc).join('；')}</p>`;
  }else if(g.need_signature&&g.approval_valid){
    status=`<p class="guard-ok">主管已签字放行，可占筐挂场。</p>`;
  }else{
    status=`<p class="guard-ok">配对数量与保守下界均满足核定等级，可直接挂场。</p>`;
  }
  let approval=g.latest_approval?`<p class="note">最近签字：${esc(g.latest_approval.supervisor_email)} · ${esc(g.latest_approval.at.replace('T',' '))} · ${g.approval_valid?'有效':'已失效'}<br>${esc(g.latest_approval.note)}</p>`:'<p class="note">尚无主管签字记录。</p>';
  let signForm=(g.need_signature&&!g.approval_valid)?`<form class="sign-form" data-id="${g.sample_id}"><label>主管签字说明</label><input name="note" value="确认样本不足/下界偏差风险，同意挂场" required><button class="primary" ${!isSupervisor(s)?'disabled':''}>主管签字放行</button>${!isSupervisor(s)?'<small>仅拍卖主管可签署</small>':''}</form>`:'';
  return `<section class="paper guard"><h2>寿命保守下界把关</h2>
  <div class="guard-metrics">
    <div><small>本次原估值</small><b>${g.estimate_days??'—'} 天</b></div>
    <div><small>保守系数（误差P10）</small><b>${g.factor_days??'—'}</b></div>
    <div><small>九成保守下界</small><b class="guard-lb">${g.lower_bound_days??'—'} 天</b></div>
    <div><small>${g.approved_grade?esc(g.approved_grade)+'级门槛':'未核级'}</small><b>${g.grade_min_days??'—'} 天</b></div>
  </div>
  <p class="note">同品种其他到场批封存配对 <b>${g.pair_count}</b> / 要求 ${g.min_pairs} 对；取实测÷估值误差分布的第${Math.round(g.conservative_quantile*100)}百分位（最近秩）为系数。</p>
  ${status}
  <details class="guard-pairs"><summary>用到哪些留样（${g.pair_count}对）</summary><table><thead><tr><th>留样签</th><th>到场批</th><th>原估值</th><th>封存实测</th><th>误差比</th></tr></thead><tbody>${
    g.pairs.map(p=>`<tr><td>${esc(p.sample_code)}</td><td>${esc(p.consignment_code)}</td><td>${p.estimate_days}</td><td>${p.observed_days}</td><td>${p.ratio}</td></tr>`).join('')||'<tr><td colspan="5">暂无可用封存配对</td></tr>'
  }</tbody></table></details>
  ${approval}${signForm}${error?`<p class="error">${esc(error)}</p>`:''}</section>`;
}

export function render(s){
  let d=s.data;
  return title('03 / LOT BOOK','等级落价，余筐挂场。','挂场前按同品种已封存实测与原估值计算寿命九成保守下界；样本不足或下界撑不起核定等级，须主管签字，封存数据一变旧签字即失效。')
  +`<div class="offer-layout"><section><div class="session-band">${d.auction_sessions.map(x=>`<div><small>${esc(x.code)}</small><b>${x.opens_at.slice(11,16)}—${x.closes_at.slice(11,16)}</b><span>${x.closes_at.slice(0,10)}</span></div>`).join('')}</div>
  <table><thead><tr><th>拍卖签</th><th>等级</th><th>占筐</th><th>底价/筐</th><th>状态</th></tr></thead><tbody>${d.auction_lots.map(l=>`<tr><td><b>${esc(l.code)}</b><small>${esc(d.consignments.find(c=>c.id===l.consignment_id)?.variety)}</small></td><td>${grade(l.grade_snapshot)}</td><td>${l.crates}</td><td>${money(l.reserve_cents)}</td><td>${LOT_STATES[l.state]}${button('/lots/'+l.id+'/cancel','撤下未出价标的',!isSupervisor(s)||l.state!=='offered')}</td></tr>`).join('')}</tbody></table>
  <section class="paper clock"><h2>业务演练时钟</h2><p>${esc(d.clock[0].now.replace('T',' '))}</p><form id="clock-form">${input('now','只能向前推进','datetime-local',d.clock[0].now.slice(0,16),'required')}<button ${!isSupervisor(s)?'disabled':''}>推进时钟</button></form><small>所有开场、截标由这个可审计时钟统一判断，重启与seed不回拨。</small></section></section>
  <aside><section class="paper"><h2>挂一张拍卖签</h2><form id="offer-form">${input('code','标的签号','text','LOT-NEW','required')}<label>到场批次</label><select name="consignment_id">${options(d.consignments,c=>c.code+' / '+c.crates+'筐')}</select><label>本批已核级留样</label><select name="sample_id" id="offer-sample">${options(d.vase_samples,x=>x.code+' / '+(x.approved_grade||'待核级'))}</select><label>场次</label><select name="session_id">${options(d.auction_sessions,x=>x.code)}</select>${input('crates','挂场筐数','number',4,'min="1" required')}${input('reserve_cents','底价 / 分每筐','number',8000,'min="100" required')}<button class="primary" ${isViewer(s)?'disabled':''}>占筐挂场</button></form></section>
  <div id="guard-slot"></div>
  <section class="paper"><h2>安排场次</h2><form id="session-form">${input('code','场次号','text','MORNING-NEW','required')}${input('opens_at','开场','datetime-local','2026-11-18T08:00','required')}${input('closes_at','截止','datetime-local','2026-11-18T09:00','required')}<button ${!isSupervisor(s)?'disabled':''}>建立拍卖场次</button></form></section></aside></div>`;
}

export function bind(s,reload){
  bindActions(reload);
  let slot=document.getElementById('guard-slot');
  let sampleSelect=document.getElementById('offer-sample');
  let drawGuard=async()=>{slot.innerHTML=await guardPanel(s,Number(sampleSelect.value))};
  sampleSelect.onchange=drawGuard;drawGuard().catch(e=>toast(e.message));
  // 面板内签字表单为异步渲染，事件委托处理
  slot.addEventListener('submit',e=>{
    let f=e.target.closest('.sign-form');if(!f)return;e.preventDefault();
    perform('/samples/'+f.dataset.id+'/life-approval','POST',data(f),reload,'主管签字已记录，把关放行').then(drawGuard).catch(()=>{});
  });
  for(const[id,path,method,nums,msg]of[['offer-form','/lots','POST',['consignment_id','sample_id','session_id','crates','reserve_cents'],'拍卖签已挂场'],['session-form','/sessions','POST',[],'场次已建立'],['clock-form','/clock','PUT',[],'业务时钟已向前推进']])
    document.getElementById(id).onsubmit=e=>{e.preventDefault();perform(path,method,data(e.target,nums),reload,msg).then(drawGuard).catch(()=>{})};
}
