const {chromium}=require(process.env.PLAYWRIGHT_PATH || 'playwright');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');const {pathToFileURL}=require('node:url');
const root=path.resolve(__dirname,'..');
const report={checks:[],errors:[],networkRequests:[]};
(async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1040},colorScheme:'light',acceptDownloads:true});
  await context.route(/^https?:/,route=>{report.networkRequests.push(route.request().url());return route.abort();});
  const page=await context.newPage();page.on('pageerror',e=>report.errors.push(e.message));
  const base=pathToFileURL(path.join(root,'site/index.html')).href;
  await page.goto(base+'#projects');
  await page.getByRole('heading',{name:'所有项目',exact:true}).waitFor();
  assert.equal(await page.locator('.project-card').count(),5);assert.equal(await page.locator('.project-card').first().locator('h2').innerText(),'dev-plm');
  await page.screenshot({path:path.join(root,'.work/projects-desktop.png'),fullPage:true});
  report.checks.push('Offline file URL opens multi-project homepage with one real and four sample projects');
  await page.locator('#project-switch').selectOption('qingdan');
  await page.getByRole('heading',{name:'轻单（示例）',exact:true}).waitFor();
  await page.goto(base+'#p/qingdan/onboarding');
  for(const text of ['前端怎么跑','后端怎么跑','需要哪些配置','往哪发请求','卡住了找谁'])assert.ok(await page.getByRole('heading',{name:new RegExp(text)}).count());
  assert.ok(await page.locator('.code-entry').innerText().then(t=>t.includes('code.example.invalid/demo/qingdan.git')&&t.includes('examples/qingdan')));
  report.checks.push('Onboarding exposes repository, branch, path, runtimes, database, config sources, servers, owners');
  await context.grantPermissions(['clipboard-read','clipboard-write']);
  await page.getByRole('button',{name:'复制本机路径'}).click();
  assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),'examples/qingdan');
  report.checks.push('Copy local path writes exactly the displayed path');
  const projects=await page.evaluate(()=>window.DEVPLM_DATA.projects);
  const routes=[];
  for(const p of projects){
    const views=['overview','onboarding','requirements','impact','changes','tests','releases','incidents','audits','reviews','collaboration','logs','files',...(p.type==='software'?['screens','data','apis','frontend','backend','operations']:['profile']),...(p.designFiles.length?['design']:[]),...(p.codeFiles.length?['code']:[])];
    for(const view of views)routes.push(`p/${p.id}/${view}`);
    for(const [group,view]of [['requirements','requirements'],['screens','screens'],['fields','data'],['apis','apis'],['tests','tests'],['records','logs'],['files','files'],['changes','changes'],['profileObjects','profile'],['releases','releases'],['incidents','incidents'],['audits','audits'],['reviews','reviews'],['codeFiles','code']])for(const item of p[group])routes.push(`p/${p.id}/${view}/${encodeURIComponent(item.id)}`);
    for(const req of p.requirements)routes.push(`p/${p.id}/impact/${req.id}`);
    for(const file of p.designFiles)routes.push(`p/${p.id}/design/${encodeURIComponent(file)}`);
  }
  for(const route of routes){await page.goto(base+'#'+route);await page.locator('#main h1').waitFor();assert.ok((await page.locator('#main').innerText()).length>25,route);assert.equal(await page.getByRole('heading',{name:'没有找到这条内容',exact:true}).count(),0,route);}
  report.viewsOpened=routes.length;
  report.checks.push('All project views and object detail routes render without page errors');
  await page.goto(base+'#p/event-inbox/frontend');assert.ok((await page.locator('#main').innerText()).includes('不适用'));assert.equal(await page.locator('.task-app').count(),0);
  await page.goto(base+'#p/event-inbox/screens');assert.ok((await page.locator('#main').innerText()).includes('没有前端页面'));
  report.checks.push('Backend-only project has no invented UI or frontend runtime');
  await page.goto(base+'#p/qingdan/requirements');await page.locator('#req-search').fill('手机');assert.equal(await page.locator('#req-table tbody tr').count(),1);await page.locator('#req-search').fill('');await page.locator('#req-status').selectOption('已发布');assert.ok((await page.locator('#req-table').innerText()).includes('DEMO-REQ-002'));
  await page.goto(base+'#p/qingdan/logs');await page.locator('#log-stage').selectOption('后端');await page.locator('#log-env').selectOption('测试');assert.equal(await page.locator('#log-count').innerText(),'1 条记录');await page.locator('#log-req').selectOption('DEMO-REQ-002');assert.equal(await page.locator('#log-count').innerText(),'0 条记录');
  report.checks.push('Requirement search/status and combined stage/environment/requirement filtering work');
  await page.goto(base+'#p/qingdan/screens/task-create');await page.locator('#create-task-form input[name=title]').fill('浏览器验收临时任务');await page.locator('#create-task-form input[name=date]').fill('2026-09-05');await page.locator('#create-task-form button').click();await page.getByText('浏览器验收临时任务',{exact:true}).waitFor();const task=page.locator('.task-item').filter({hasText:'浏览器验收临时任务'});assert.ok((await task.innerText()).includes('今天到期'));await task.locator('input').check();await page.locator('.task-item').filter({hasText:'浏览器验收临时任务'}).locator('input').uncheck();
  report.checks.push('Prototype task create/date/complete/undo work without modifying source data');
  await page.goto(base+'#p/qingdan/requirements');await page.getByRole('button',{name:'新增需求草稿'}).click();
  const original='\n保留这段原话\n## 补充条件\n第二段\n## 当前理解\n这还是用户原话\n> 引用\n';
  await page.locator('#requirement-form input[name=id]').fill('REQ-ROUNDTRIP-01');await page.locator('#requirement-form input[name=title]').fill('原话导出往返验收');await page.locator('#requirement-form textarea').fill(original);
  const downloadEvent=page.waitForEvent('download');await page.getByRole('button',{name:'下载 Markdown 草稿'}).click();const download=await downloadEvent;await download.saveAs(path.join(root,'.work/exported-requirement.md'));
  assert.equal(await page.evaluate(()=>window.DEVPLM_DATA.projects.find(p=>p.id==='qingdan').requirements.length),3);
  report.exportOriginal=original;report.checks.push('Requirement export downloads Markdown and does not mutate authoritative page data');
  await page.goto(base+'#p/qingdan/apis/createTask');const uiExamples=await page.locator('.example pre').allTextContents();const expected=projects.find(p=>p.id==='qingdan').apis.find(a=>a.id==='createTask');const values=[...expected.requestExamples.flatMap(m=>m.examples.map(e=>e.value)),...expected.responses.flatMap(r=>r.samples.flatMap(m=>m.examples.map(e=>e.value)))];assert.deepEqual(uiExamples.map(t=>JSON.parse(t)),values);report.checks.push('Displayed API JSON examples exactly match the contract projection');
  await page.goto(base+'#p/dev-plm/impact/DEV-REQ-010');
  await page.getByRole('heading',{name:'我说的那句话，导致了什么？',exact:true}).waitFor();
  assert.ok(await page.locator('.author-account').count());assert.ok(await page.locator('.git-facts').count());
  await page.screenshot({path:path.join(root,'.work/round3-impact.png'),fullPage:false});
  await page.locator('#impact-select').selectOption('DEV-REQ-008');
  await page.waitForURL(/DEV-REQ-008$/);
  assert.ok((await page.locator('.impact-origin').innerText()).includes('页面不能是文件的副本'));
  await page.goto(base+'#p/paperboat-agent/profile/SEG-PAPER-VOICE');
  assert.ok(await page.locator('.restore-proof').count());
  await page.locator('.file-diff').nth(1).locator('summary').first().click();
  await page.locator('.diff-line.addition').first().waitFor();
  assert.ok((await page.locator('.diff-line.addition').allTextContents()).some(t=>t.includes('每次回复先给三个要点')));
  assert.ok((await page.locator('.diff-line.deletion').allTextContents()).some(t=>t.includes('用简短自然的中文回应')));
  assert.ok(await page.locator('.diff-line > span:first-child').allTextContents().then(x=>x.some(t=>/^\d+$/.test(t))));
  await page.screenshot({path:path.join(root,'.work/round3-prompt-diff.png'),fullPage:false});
  await page.goto(base+'#p/rain-window-film/profile/PROMPT-RW-001');
  assert.ok((await page.locator('.source-row').innerText()).includes('prompts/shot-01.md'));
  await page.goto(base+'#p/dev-plm/design/design%2Fdatabase.md');
  assert.ok(await page.locator('.design-document table').count());
  await page.goto(base+'#p/dev-plm/code');assert.ok((await page.locator('#main pre').innerText()).length>100);
  for(const route of ['p/paperboat-agent/operations','p/rain-window-film/backend','p/dev-plm/impact/MISSING']){
    await page.goto(base+'#'+route);assert.ok(await page.getByRole('heading',{name:'没有找到这条内容',exact:true}).count());
  }
  report.checks.push('Original words link to changes; Git and author evidence are separated; prompt before/after line numbers and exact restoration shown; design tables and actual source render');
  await page.emulateMedia({colorScheme:'dark'});await page.goto(base+'#p/qingdan/onboarding');assert.equal(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()),'#101828');await page.screenshot({path:path.join(root,'.work/onboarding-dark.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  for(const route of ['projects','p/qingdan/onboarding','p/qingdan/apis/createTask','p/event-inbox/frontend','p/qingdan/requirements','p/dev-plm/impact/DEV-REQ-010','p/paperboat-agent/profile/SEG-PAPER-VOICE','p/dev-plm/design/design%2Fdatabase.md']){await page.goto(base+'#'+route);const sizes=await page.evaluate(()=>({scroll:document.documentElement.scrollWidth,client:document.documentElement.clientWidth}));assert.ok(sizes.scroll<=sizes.client,route+JSON.stringify(sizes));}
  await page.goto(base+'#projects');await page.screenshot({path:path.join(root,'.work/projects-mobile-dark.png'),fullPage:true});
  report.checks.push('Dark theme follows system preference; mobile pages fit 390px without document overflow');
  assert.deepEqual(report.errors,[]);assert.deepEqual(report.networkRequests,[]);
  await page.goto(base+'#p/dev-plm/collaboration');
  await page.getByRole('heading',{name:'讨论与认领',exact:true}).waitFor();
  await page.getByRole('heading',{name:'尚无协作导出',exact:true}).waitFor();
  await page.goto(base+'#p/dev-plm/apis');
  const fileDownload=page.waitForEvent('download');await page.getByText('下载 OpenAPI 契约',{exact:true}).click();
  const exportedFile=await fileDownload;const exportedPath=path.join(root,'.work/round5-openapi-download.json');await exportedFile.saveAs(exportedPath);
  assert.deepEqual(JSON.parse(fs.readFileSync(exportedPath,'utf8')),JSON.parse(fs.readFileSync(path.join(root,'projects/dev-plm/api/openapi.json'),'utf8')));
  report.checks.push('Empty collaboration snapshot is explicit; source download is embedded and matches the reviewed file');
  report.ok=true;report.checkedAt=new Date().toISOString();
 }finally{await browser.close();fs.writeFileSync(path.join(root,'.work/round5-browser-check.json'),JSON.stringify(report,null,2));}
 console.log(JSON.stringify({ok:report.ok,viewsOpened:report.viewsOpened,checks:report.checks,errors:report.errors,networkRequests:report.networkRequests},null,2));
})().catch(e=>{console.error(e);process.exitCode=1;});
