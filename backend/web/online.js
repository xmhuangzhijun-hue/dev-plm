(() => {
 'use strict';
 const $=id=>document.getElementById(id), esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const names={logs:'项目日志',sources:'需求与文档',discussions:'讨论与回复',claims:'认领与进度',notifications:'我的通知',history:'保存记录',operations:'运行与备份'};
 const sectionNames={overview:'项目总览',requirements:'需求与迭代',ui:'UI与页面',fields:'字段与数据',api:'API接口',development:'开发实现',tests:'测试与验收',operations:'运维与发布',audit:'审计与安全'};
 let projects=[],actor,project,view='logs',generation=0,dirty=false,currentFile=null;
 const pending=new WeakMap();
 function notice(text,error=false){$('notice').textContent=text;$('notice').classList.toggle('error',error);}
 async function api(path,options={}){
  const response=await fetch(path,{credentials:'same-origin',...options});
  const data=await response.json().catch(()=>({message:'服务未返回有效结果。'}));
  if(!response.ok){if(response.status===401)throw Error('登录已过期。请在新标签页重新登录，再回来重试；当前未保存内容仍保留。');throw Error(data.message||'操作未完成，请核对后重试。');}return data;
 }
 const v1=path=>'/private/api/v1'+path, base=()=>'/private/projects/'+encodeURIComponent(project);
 async function write(path,body,method,element){
  const signature=JSON.stringify([path,body,method]);let operation=pending.get(element);
  if(!operation||operation.signature!==signature){operation={signature,key:crypto.randomUUID()};pending.set(element,operation);}
  const result=await api(path,{method,headers:{'Content-Type':'application/json','Idempotency-Key':operation.key},body:JSON.stringify(body)});
  pending.delete(element);return result;
 }
 function guard(){return !dirty||window.confirm('有未保存的内容。确定离开并放弃这些修改吗？');}
 function selectOptions(items,value='id',label='title'){return items.map(r=>`<option value="${esc(r[value])}">${esc(r[label]||r[value])}</option>`).join('');}
 async function targets(){return (await api(v1('/projects/'+encodeURIComponent(project)+'/requirements'))).items;}
 function writable(){return actor.role!=='viewer';}
 function sourceButton(label){return `<button class="primary" ${actor.role==='owner'?'':'disabled'}>${label}</button>`;}
 function formButton(label){return `<button class="primary" ${writable()?'':'disabled'}>${label}</button>`;}
 async function render(){
  const external=projects.find(p=>p.id===project)?.log_only;
  const menu=external?{...sectionNames,logs:'全过程日志'}:names;
  if(!(view in menu))view=external?'overview':'logs';
  document.querySelector('nav').innerHTML=Object.entries(menu).map(([id,title])=>`<button data-view="${id}">${esc(title)}</button>`).join('');
  $('read-view').hidden=!!external;const epoch=++generation;dirty=false;currentFile=null;$('title').textContent=menu[view];
  document.querySelectorAll('nav button').forEach(b=>b.setAttribute('aria-current',b.dataset.view===view?'page':'false'));
  $('read-view').href='/site/index.html#p/'+encodeURIComponent(project)+'/overview';
  $('content').innerHTML='<p class="empty">正在读取…</p>';
  try{const html=await (external&&view!=='logs'?projectSection():views[view]());if(epoch!==generation)return;$('content').innerHTML=html;if(view==='logs')logRows();notice(external?'直接读取项目原资料；全过程日志自动更新。':writable()?'已读取最新数据。':'当前是只读账号，可查看资料与协作记录。');}
  catch(e){if(epoch===generation){$('content').innerHTML='<p class="empty">未能读取。请重新选择页面重试。</p>';notice(e.message,true);}}
 }
 async function projectSection(){
  const data=await api(base()+'/sections/'+encodeURIComponent(view));
  const cards=view==='overview'?`<div class="section-grid">${data.sections.filter(s=>s.id!=='overview').map(s=>`<button class="card section-card" data-view="${esc(s.id)}"><strong>${esc(s.title)}</strong><span>${s.count?`${s.count} 份资料`:'待补独立资料'}</span></button>`).join('')}</div>`:'';
  return `<section class="card"><h2>${esc(data.title)}</h2><p>${esc(data.note)}</p><div class="actions"><button data-view="logs">查看全过程日志</button><button data-view="overview">返回项目总览</button></div></section>${cards}<div class="split"><section class="card"><h2>原项目资料</h2><div class="file-list">${data.items.map(d=>`<button data-document="${esc(d.key)}" ${d.available?'':'disabled'}>${esc(d.title)}${d.available?'':'（来源暂不可用）'}<small>${esc(d.source)}</small></button>`).join('')||'<p class="muted">尚无独立资料。该栏目保留，已有工作经过可从全过程日志查看。</p>'}</div></section><section class="card" id="document-reader"><h2>选择资料查看</h2><p class="muted">读取原文件，保留设计状态、测试结果和来源，不复制成另一份文档。</p></section></div>`;
 }
 async function openDocument(key){
  const requested=project,epoch=generation;
  try{const d=await api(base()+'/documents/'+encodeURIComponent(key));if(project!==requested||epoch!==generation)return;
   $('document-reader').innerHTML=`<h2>${esc(d.title)}</h2><p class="meta">来源：${esc(d.source)} · 原文件只读</p><div class="body document-body">${esc(d.body)}</div>`;
  }catch(e){notice(e.message,true);}
 }
 let logData=null,logProject=null,logBusy=false;
 function logRows(){
  if(!logData||!$('log-rows'))return;
  for(const [id,key] of [['log-stage','stage'],['log-env','env']]){
   const select=$(id),selected=select.value;
   const values=[...new Set(logData.items.map(r=>r[key]).filter(Boolean))].sort();
   if(selected&&!values.includes(selected))values.push(selected);
   select.innerHTML=`<option value="">${key==='stage'?'全部环节':'全部环境'}</option>`+values.map(v=>`<option>${esc(v)}</option>`).join('');select.value=selected;
  }
  const stage=$('log-stage').value,env=$('log-env').value,q=$('log-search').value.toLowerCase();
  const rows=logData.items.filter(r=>(!stage||r.stage===stage)&&(!env||r.env===env)&&(!q||JSON.stringify(r).toLowerCase().includes(q)));
  $('log-count').textContent=`${rows.length} 条记录 · 按文件更新时间排列`;
  $('log-rows').innerHTML=rows.map(r=>`<article class="entry"><p><span class="pill">${esc(r.stage||'未分类')}</span> <span class="pill">${esc(r.env||'未注明环境')}</span></p><h2>${esc(r.title||r.id||r.path)}</h2><p class="meta">${esc(r.time)} · ${esc(r.actor)}</p><p><strong>${esc(r.result)}</strong></p>${r.before?`<p>之前：${esc(r.before)}</p>`:''}${r.after?`<p>之后：${esc(r.after)}</p>`:''}<p>${r.reqs.map(id=>`<a href="/site/index.html#p/${encodeURIComponent(project)}/requirements/${encodeURIComponent(id)}">${esc(id)}</a>`).join(' · ')}</p><details ${r.record_key?`data-log-key="${esc(r.record_key)}"`:""}><summary>查看记录原文</summary><div class="body">${esc(r.record_key?"展开时读取原文…":r.body||"无附加正文")}</div><p class="meta">${esc(r.path)}</p></details></article>`).join('')||'<p class="empty">没有符合条件的记录。</p>';
  $('log-errors').textContent=logData.errors.map(e=>typeof e==='string'?e:e.path+'：'+e.message).join('；');
 }
 async function refreshLogs(){
  if(view!=='logs'||!project||document.hidden||logBusy||!$('log-rows'))return;
  logBusy=true;const requested=project,epoch=generation;
  try{const data=await api(base()+'/logs?revision='+encodeURIComponent(logProject===project?logData?.revision||'':''));
   if(project!==requested||epoch!==generation||view!=='logs')return;
   if(!data.unchanged){logData=data;logProject=project;logRows();}
   $('log-status').textContent='已自动检查 · '+new Date().toLocaleTimeString();
  }catch(e){if(view==='logs'&&$('log-status'))$('log-status').textContent='更新暂未成功，保留当前记录：'+e.message;}finally{logBusy=false;}
 }
 document.addEventListener('input',e=>{if(['log-search','log-stage','log-env'].includes(e.target.id))logRows();});
 document.addEventListener('toggle',async e=>{
  const el=e.target;if(!el.open||!el.dataset.logKey||el.dataset.loaded||el.dataset.loading)return;
  el.dataset.loading='true';const requested=project;
  try{const result=await api(base()+'/logs/'+encodeURIComponent(el.dataset.logKey));if(requested!==project||!el.isConnected)return;el.querySelector('.body').textContent=result.body;el.dataset.loaded='true';}
  catch(error){el.querySelector('.body').textContent=error.message+' 关闭后重新展开可重试。';}finally{delete el.dataset.loading;}
 },true);
 document.addEventListener('visibilitychange',refreshLogs);
 setInterval(refreshLogs,15000);
 const views={
  async logs(){logData=await api(base()+'/logs');logProject=project;
   const options=key=>[...new Set(logData.items.map(r=>r[key]).filter(Boolean))].sort().map(x=>`<option>${esc(x)}</option>`).join('');
   return `<section class="card"><h2>工作发生后，记录自动出现在这里</h2><p class="muted" id="log-status">页面打开时每15秒检查更新，无需导入或同步。</p><div class="form-grid"><label>环节<select id="log-stage"><option value="">全部环节</option>${options('stage')}</select></label><label>环境<select id="log-env"><option value="">全部环境</option>${options('env')}</select></label><label>查找记录<input id="log-search" type="search" placeholder="标题、编号、结果…"></label></div><p id="log-count"></p><p id="log-errors" role="status"></p></section><section id="log-rows"></section>`;},
  async sources(){const files=(await api(base()+'/files')).items;return `<div class="actions"><button id="new-requirement" ${actor.role==='owner'?'':'disabled'}>＋ 记录新需求</button><a href="/site/index.html#p/${encodeURIComponent(project)}/requirements">查看需求视图 ↗</a></div><div class="split"><section class="card"><h2>项目文档</h2><p class="muted">选择文件后直接编辑。保存会检查引用、同步并更新工作台。</p><div class="file-list">${files.map(f=>`<button data-file="${esc(f.path)}">${esc(f.path)}</button>`).join('')}</div></section><section class="card" id="editor"><h2>选择一份文档</h2><p class="muted">需求、字段、接口、测试与过程记录集中在这里。每次保存会保留之前的版本。</p></section></div>`;},
  async discussions(){const [requirements,result]=await Promise.all([targets(),api(v1('/projects/'+encodeURIComponent(project)+'/discussions'))]);return `<section class="card"><h2>发起讨论</h2><form id="discussion-form"><label>关联需求<select name="target_id" required>${selectOptions(requirements)}</select></label><label>讨论内容<textarea name="body" required maxlength="20000"></textarea></label>${formButton('发布讨论')}</form></section><section class="card"><h2>已有讨论</h2>${result.items.length?result.items.map(d=>`<article class="entry"><span class="pill">${esc(d.target_id)}</span><div class="body">${esc(d.body)}</div><p class="meta">${esc(d.created_by)} · ${esc(d.updated_at)} · 版本 ${d.revision}</p><button data-discussion="${esc(d.id)}">查看回复与编辑</button></article>`).join(''):'<p class="empty">还没有讨论，记录第一个需要确认的问题。</p>'}</section>`;},
  async claims(){const [requirements,principals,result]=await Promise.all([targets(),api(v1('/principals')),api(v1('/projects/'+encodeURIComponent(project)+'/claims'))]);return `<section class="card"><h2>分配处理人</h2><form id="claim-form"><div class="form-grid"><label>需求<select name="target_id">${selectOptions(requirements)}</select></label><label>处理人<select name="claimant_id">${selectOptions(principals.items,'id','display_name')}</select></label></div>${formButton('确认认领')}</form></section><section class="card"><h2>认领记录</h2>${result.items.map(c=>`<article class="entry"><strong>${esc(c.target_id)}</strong><p>${esc(c.claimant_id)} <span class="pill">${esc({active:'处理中',released:'已释放',expired:'已过期'}[c.state])}</span></p>${c.state==='active'&&writable()?`<button data-release="${esc(c.id)}" data-revision="${c.revision}">释放认领</button>`:''}</article>`).join('')||'<p class="empty">还没有认领记录。</p>'}</section>`;},
  async notifications(){const result=await api(v1('/notifications'));return `<section class="card"><h2>我的通知</h2>${result.items.map(n=>`<article class="entry"><pre>${esc(JSON.stringify(n.payload,null,2))}</pre><p class="meta">${esc(n.created_at)}</p>${n.read_at?'<span class="pill">已读</span>':`<button data-read="${esc(n.id)}" data-revision="${n.revision}" ${writable()?'':'disabled'}>标记已读</button>`}</article>`).join('')||'<p class="empty">暂无通知。</p>'}</section>`;},
  async history(){const result=await api(base()+'/history');return `<section class="card"><h2>文件保存记录</h2><p class="muted">冲突或失败不会伪装成保存成功。历史版本由本机备份保留。</p>${result.items.map(r=>`<article class="entry"><strong>${esc(r.path)}</strong><p>${esc(r.message)}</p><p class="meta">${esc(r.actor)} · ${esc(r.updated_at)} · ${esc(r.state)}</p><details><summary>版本与回执</summary><pre>${esc(JSON.stringify({id:r.id,before:r.before,after:r.after},null,2))}</pre></details></article>`).join('')||'<p class="empty">还没有从网页保存的记录。</p>'}</section>`;},
  async operations(){const r=await api('/private/operations');return `<section class="card"><h2>运行与备份</h2><p>${esc(r.message||r.state)}</p><dl>${[['最近检查',r.checked_at],['最近成功备份',r.backup_at],['最近恢复验证',r.restore_verified_at]].map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v||'尚无记录')}</dd>`).join('')}</dl><p class="muted">电脑需要开机并登录Windows。私网访问还需要Tailscale连接。备份留在本机专用目录。</p></section><section class="card"><h2>协作快照</h2><p>将当前讨论、认领、通知与审计导出为项目文件，供离线查阅和恢复。</p><button id="export" ${writable()?'':'disabled'}>导出当前项目协作数据</button></section>`;}
 };
 async function openFile(path){if(!guard())return;const result=await api(base()+'/source?path='+encodeURIComponent(path));currentFile=result;dirty=false;$('editor').innerHTML=`<h2>${esc(path)}</h2><form id="source-form"><label for="source-content">内容</label><textarea id="source-content" class="source-editor" spellcheck="false" ${actor.role==='owner'?'':'readonly'}></textarea><p class="muted">保留已有编号和字段结构。保存前会校验；版本冲突时不会覆盖他人的修改。</p>${sourceButton('保存并更新工作台')}</form>`;$('source-content').value=result.content;}
 function newRequirement(){if(!guard())return;currentFile=null;dirty=false;$('editor').innerHTML=`<h2>记录新需求</h2><form id="requirement-form"><label>标题<input name="title" required maxlength="180"></label><label>你的原话<textarea name="original" required maxlength="20000"></textarea></label><label>当前理解（可空）<textarea name="understanding" maxlength="20000"></textarea></label><label>下一步<input name="next" value="确认需求并制作页面毛坯" required></label>${sourceButton('保存新需求')}</form>`;}
 function requirementDocument(form){const f=new FormData(form),title=f.get('title'),original=f.get('original'),date=new Date().toISOString(),id='REQ-'+date.slice(0,10).replaceAll('-','')+'-'+crypto.randomUUID().slice(0,8);const quote=v=>JSON.stringify(String(v));return {path:'requirements/'+id+'.md',revision:null,content:`---\nid: ${id}\ntitle: ${quote(title)}\nstatus: 待确认\npriority: 中\nraised: ${quote(date)}\nupdated: ${quote(date)}\nowner: 项目维护者\nversion: 初始记录\nnext: ${quote(f.get('next'))}\nchecks:\n  - ["需求已由提出者确认", false]\nsteps:\n  - 原话已记录，待确认\n  - 页面待设计\n  - 字段待设计\n  - 接口待设计\n  - 开发未开始\n  - 测试未开始\n  - 未发布\n---\n\n# ${String(title).replaceAll('\n',' ')}\n\n## 用户原话\n\n${String(original).split('\n').map(l=>'> '+l).join('\n')}\n\n## 当前理解\n\n${f.get('understanding')||'待确认。'}\n`};}
 async function openDiscussion(id){
  const [d,result]=await Promise.all([api(v1('/discussions/'+id)),api(v1('/discussions/'+id+'/posts'))]);dirty=false;
  $('content').innerHTML=`<div class="actions"><button id="back-discussions">返回讨论列表</button></div><section class="card"><span class="pill">${esc(d.target_id)}</span><h2>讨论</h2><div class="body">${esc(d.body)}</div>${d.created_by===actor.id&&writable()?`<details><summary>编辑我的讨论</summary><form data-edit-discussion="${esc(id)}" data-revision="${d.revision}"><textarea name="body" required>${esc(d.body)}</textarea>${formButton('保存讨论')}</form><button class="danger" data-delete-discussion="${esc(id)}" data-revision="${d.revision}">删除讨论并保留记录</button></details>`:''}</section><section class="card"><h2>回复</h2>${result.items.filter(p=>!p.deleted_at).map(p=>`<article class="entry"><div class="body">${esc(p.body)}</div><p class="meta">${esc(p.created_by)} · ${esc(p.updated_at)}</p>${p.created_by===actor.id&&writable()?`<details><summary>编辑我的回复</summary><form data-edit-post="${esc(p.id)}" data-discussion-id="${esc(id)}" data-revision="${p.revision}"><textarea name="body" required>${esc(p.body)}</textarea>${formButton('保存回复')}</form><button class="danger" data-delete-post="${esc(p.id)}" data-discussion-id="${esc(id)}" data-revision="${p.revision}">删除回复并保留记录</button></details>`:''}</article>`).join('')||'<p>还没有回复。</p>'}<form id="reply-form" data-discussion-id="${esc(id)}"><label>回复内容<textarea name="body" required maxlength="20000"></textarea></label>${formButton('发送回复')}</form></section>`;
 }
 document.addEventListener('input',e=>{if(e.target.closest('main form'))dirty=true;});
 document.addEventListener('submit',async e=>{
  const form=e.target;if(!form.closest('main'))return;e.preventDefault();const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);notice('正在保存，请等待回执…');
  try{let result;const data=Object.fromEntries(new FormData(form));
   if(form.id==='source-form'||form.id==='requirement-form'){const body=form.id==='source-form'?{path:currentFile.path,content:$('source-content').value,revision:currentFile.revision}:requirementDocument(form);
    // Preserve the generated identifier on a network retry.
    if(form.id==='requirement-form'){if(form._newBody&&form._input===JSON.stringify(data))Object.assign(body,form._newBody);else{form._newBody=body;form._input=JSON.stringify(data);}}
    result=await write(base()+'/source',body,'PUT',form);dirty=false;await openFile(body.path);notice(result.message);return;}
   if(form.id==='discussion-form'){await write(v1('/projects/'+encodeURIComponent(project)+'/discussions'),data,'POST',form);await render();}
   else if(form.id==='claim-form'){await write(v1('/projects/'+encodeURIComponent(project)+'/claims'),data,'POST',form);await render();}
   else if(form.id==='reply-form'){await write(v1('/discussions/'+form.dataset.discussionId+'/posts'),data,'POST',form);await openDiscussion(form.dataset.discussionId);}
   else if(form.dataset.editDiscussion){await write(v1('/discussions/'+form.dataset.editDiscussion),{body:data.body,revision:Number(form.dataset.revision)},'PATCH',form);await openDiscussion(form.dataset.editDiscussion);}
   else if(form.dataset.editPost){await write(v1('/discussion-posts/'+form.dataset.editPost),{body:data.body,revision:Number(form.dataset.revision)},'PATCH',form);await openDiscussion(form.dataset.discussionId);}
   dirty=false;notice('已保存，并重新读取确认。');
  }catch(error){notice(error.message,true);}finally{buttons.forEach(b=>b.disabled=!writable());}
 });
 document.addEventListener('click',async e=>{
  const button=e.target.closest('button');if(!button)return;
  try{
   if(button.dataset.view){if(!guard())return;view=button.dataset.view;await render();return;}
   if(button.dataset.document){await openDocument(button.dataset.document);return;}
   if(button.dataset.file){await openFile(button.dataset.file);return;}
   if(button.id==='new-requirement'){newRequirement();return;}
   if(button.dataset.discussion){if(guard())await openDiscussion(button.dataset.discussion);return;}
   if(button.id==='back-discussions'){if(guard())await render();return;}
   let path,body,method='PATCH';
   if(button.dataset.release){path='/claims/'+button.dataset.release;body={state:'released',revision:Number(button.dataset.revision)};}
   if(button.dataset.read){path='/notifications/'+button.dataset.read;body={read:true,revision:Number(button.dataset.revision)};}
   if(button.dataset.deleteDiscussion||button.dataset.deletePost){if(!window.confirm('确定删除这条自己的发言？审计记录会保留。'))return;path=button.dataset.deleteDiscussion?'/discussions/'+button.dataset.deleteDiscussion:'/discussion-posts/'+button.dataset.deletePost;body={revision:Number(button.dataset.revision)};method='DELETE';}
   if(button.id==='export'){path='/projects/'+encodeURIComponent(project)+'/collaboration-exports';body={scope:['discussions','claims','audit','notifications']};method='POST';}
   if(path){button.disabled=true;const result=await write(v1(path),body,method,button);if(button.dataset.discussionId)await openDiscussion(button.dataset.discussionId);else await render();notice(result.message||'操作已保存并重新读取。');}
  }catch(error){notice(error.message,true);}finally{if(button.isConnected&&button.type!=='submit')button.disabled=!writable();}
 });
 $('projects').addEventListener('change',()=>{if(!guard()){$('projects').value=project;return;}project=$('projects').value;render();});
 window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
 (async()=>{try{const workspace=await api('/private/workspace');actor=workspace.actor;projects=workspace.projects;const requested=new URL(location.href).searchParams.get('project');project=workspace.projects.find(p=>p.id===requested)?.id||workspace.projects[0]?.id;$('projects').innerHTML=selectOptions(workspace.projects,'id','name');$('projects').value=project||'';$('identity').textContent=actor.id+' · '+({owner:'维护者',maintainer:'编辑者',viewer:'只读'}[actor.role]);if(!project){notice('当前账号没有可用真实项目，请核对项目权限。',true);return;}await render();}catch(e){notice(e.message,true);}})();
})();
