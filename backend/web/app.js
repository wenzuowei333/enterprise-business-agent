const $ = (id) => document.getElementById(id);
let csrf = '', user = null, selected = null, detail = null, epoch = 0, busy = false;
const names = {open:'待核实',processing:'诊断中',blocked:'证据不足 / 需处理',resolved:'已解决',queued:'排队中',completed:'已完成',failed:'失败',cancelled:'已取消',manual_review:'待人工复核',actionable:'需人工处理'};
function text(tag, value, className) { const n = document.createElement(tag); n.textContent = value; if(className) n.className=className; return n; }
function message(value,error=false){ $('notice').textContent=value; $('notice').className=error?'error':''; }
function clearIdentity(){epoch++;csrf='';user=null;selected=null;detail=null;$('cases').replaceChildren();$('count').textContent='0';$('who').textContent='尚未登录';$('logout').disabled=true;renderDetail();}
async function api(path,options={}){
  const stamp=epoch;const response=await fetch(path,{credentials:'same-origin',...options,headers:{'Content-Type':'application/json',...(csrf?{'X-CSRF-Token':csrf}:{}),...options.headers}});
  const payload=await response.json();
  if(!response.ok){ if(response.status===401&&stamp===epoch)clearIdentity(); throw new Error(payload.detail?.message||`请求失败 (${response.status})`); }
  return payload;
}
function canDiagnose(){return user?.permissions.includes('exception.diagnose');}
function controls(){const active=detail?.jobs?.some(j=>['queued','processing'].includes(j.status));$('diagnose').disabled=busy||!selected||!canDiagnose()||active||['resolved','ignored'].includes(detail?.case?.status);$('recheck').disabled=busy||!selected||!canDiagnose();$('logout').disabled=!user; }
async function loadCases(){const stamp=epoch;const response=await api('/api/cases');if(stamp!==epoch)return;
  $('count').textContent=String(response.total);$('cases').replaceChildren();
  for(const c of response.cases){const button=text('button','',`case-button${selected===c.id?' selected':''}`);button.append(text('strong',c.case_no),text('span',`${c.warehouse} · ${c.rule_code==='negative_stock'?'负库存':'锁定库存'}`),text('span',`${c.product_code} / ${names[c.status]||c.status}`));button.onclick=()=>selectCase(c.id);$('cases').append(button);}
}
async function selectCase(id){const stamp=epoch;selected=id;detail=null;renderDetail();try{await loadCases();if(stamp!==epoch||id!==selected)return;await loadDetail();}catch(error){if(stamp===epoch&&id===selected)message(error.message,true);}}
async function loadDetail(){if(!user||!selected)return;const stamp=epoch,id=selected;const result=await api(`/api/cases/${id}`);if(stamp!==epoch||id!==selected)return;const changed=detail?.case?.status!==result.case.status||detail?.jobs?.[0]?.status!==result.jobs[0]?.status;detail=result;renderDetail();const job=detail.jobs[0];if(job){const states={queued:'任务已入队，等待 Worker。',processing:'Worker 正在处理，结果写入前会再次核对证据与租约。',completed:job.scenario==='missing_evidence'?'诊断已完成；证据不足，结论已阻止。':'诊断已完成，请结合证据人工核实。',failed:'本次诊断失败，未产生新结论；可查看失败说明后重新提交。',cancelled:'任务已取消，请核对当前证据与权限。'};message(states[job.status]||job.status,job.status==='failed');}if(changed)await loadCases();}
function renderDetail(){controls();$('case-summary').replaceChildren();$('result').replaceChildren();$('jobs').replaceChildren();$('events').replaceChildren();
  if(!detail){$('case-status').textContent='等待选择';$('case-summary').textContent='选择一条案件后查看规则与原始事实。';$('evidence').textContent='尚无证据';$('result').textContent='尚无诊断结果';$('jobs').textContent='尚无任务';return;}
  const c=detail.case;$('case-status').textContent=names[c.status]||c.status;
  const facts=text('div','','case-facts');for(const [label,value] of [['案件',c.case_no],['仓库',c.warehouse],['商品',c.product_code],['规则',c.rule_code]])facts.append(text('span',`${label}：${value}`));$('case-summary').append(facts);
  if(c.source_changed)$('case-summary').append(text('p','来源已变化，请先复检证据。','warning'));
  $('evidence').textContent=JSON.stringify(detail.evidence,null,2);
  const result=detail.diagnosis;$('result').className=result?'':'empty';$('jobs').className=detail.jobs.length?'':'empty';
  if(!result)$('result').append(text('p','提交任务后，独立 Worker 会领取并处理。','empty'));
  else{if(!result.current)$('result').append(text('p','以下是历史证据的诊断，不能当作当前结论。','warning'));
    $('result').append(text('p',`有效诊断来自任务 #${result.job_id}；失败任务不会生成新结论。`,'muted'),text('p',result.summary,'result-title'),text('span',`${names[result.disposition]||result.disposition} · Mock · 置信度 ${Math.round(Number(result.confidence)*100)}%`,'pill'));
    const grid=text('div','','result-grid');for(const [label,items] of [['建议核实步骤',result.recommended_steps],['尚缺的证据',result.missing_evidence]]){const box=text('div','');box.append(text('h3',label));const list=text('ul','');items.forEach(item=>list.append(text('li',item)));box.append(list);grid.append(box);}$('result').append(grid,text('h3','引用依据','muted'));for(const ref of result.evidence_refs)$('result').append(text('code',ref),document.createTextNode(' '));if(!result.evidence_refs.length)$('result').append(text('p','没有可用引用，本次结论被阻止。','muted'));
  }
  for(const job of detail.jobs){const box=text('div','','job'),top=text('div','','job-top');top.append(text('span',job.job_no),text('strong',names[job.status]||job.status));box.append(top,text('div',`执行代次 ${job.generation} · ${job.worker_id||'当前无执行者'} · ${job.scenario}`,'job-meta'));if(job.error_code)box.append(text('div',`处理说明：${job.error_code}`,'job-meta'));$('jobs').append(box);}if(!detail.jobs.length)$('jobs').textContent='尚无任务';
  for(const event of detail.events){const row=text('div','','event');row.append(text('strong',event.type),text('div',JSON.stringify(event.detail||{})));$('events').append(row);}
}
$('login-form').onsubmit=async(event)=>{event.preventDefault();busy=true;controls();try{
  if(user)await api('/api/auth/logout',{method:'POST'});clearIdentity();const stamp=epoch;
  const result=await api('/api/auth/login',{method:'POST',body:JSON.stringify({username:$('account').value,password:$('password').value})});if(stamp!==epoch)return;
  user=result.user;csrf=result.csrf_token;$('who').textContent=`已登录：${user.username}`;message(canDiagnose()?'已按当前账号范围载入案件。':'当前为只读账号，可查看证据，不能提交诊断。');await loadCases();
}catch(error){message(error.message,true);}finally{busy=false;controls();}};
$('logout').onclick=async()=>{try{await api('/api/auth/logout',{method:'POST'});clearIdentity();message('已退出，页面中的案件与结果已清空。');}catch(error){message(error.message,true);}};
$('diagnose').onclick=async()=>{if(!detail)return;busy=true;controls();const stamp=epoch,id=selected;try{const response=await api(`/api/cases/${id}/diagnose`,{method:'POST',body:JSON.stringify({expected_evidence_version:detail.case.evidence_version,scenario:$('scenario').value,force:true})});if(stamp!==epoch)return;message(response.reused?'已复用当前执行任务。':'任务已进入数据库队列，等待 Worker。');await loadDetail();await loadCases();}catch(error){message(error.message,true);}finally{busy=false;controls();}};
$('recheck').onclick=async()=>{busy=true;controls();try{await api(`/api/cases/${selected}/recheck`,{method:'POST'});await loadDetail();await loadCases();message('已根据库存来源重新检查证据。');}catch(error){message(error.message,true);}finally{busy=false;controls();}};
setInterval(async()=>{if(user&&selected&&!busy){try{await loadDetail();}catch(error){message(error.message,true);}}},1000);
(async()=>{try{const result=await api('/api/auth/session');user=result.user;csrf=result.csrf_token;$('who').textContent=`已登录：${user.username}`;$('account').value=user.username;controls();await loadCases();}catch{clearIdentity();}finally{document.body.dataset.ready='true';}})();
