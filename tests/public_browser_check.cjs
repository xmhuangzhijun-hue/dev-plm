const {chromium}=require(process.env.PLAYWRIGHT_PATH || 'playwright');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const root=path.resolve(__dirname,'..'),site=path.join(root,'site');
(async()=>{
 const errors=[],missing=[],requests=[];let fetches=0;
 const server=http.createServer((req,res)=>{
  const suffix=decodeURIComponent(req.url.split('?')[0]).replace(/^\/preview\/dev-plm\//,'');
  const file=path.resolve(site,suffix||'index.html');
  if(!file.startsWith(site+path.sep)||!fs.existsSync(file)){missing.push(req.url);res.writeHead(404);return res.end();}
  res.setHeader('Content-Type',file.endsWith('.js')?'application/javascript':file.endsWith('.css')?'text/css':'text/html');res.end(fs.readFileSync(file));
 });
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const browser=await chromium.launch({headless:true});
 try{
  const context=await browser.newContext();
  await context.exposeFunction('countFetch',()=>fetches++);
  await context.addInitScript(()=>{const original=window.fetch;window.fetch=(...args)=>{window.countFetch();return original(...args)};});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>requests.push(r.url()));
  const outputs=[];
  for(const base of [pathToFileURL(path.join(site,'index.html')).href,`http://127.0.0.1:${server.address().port}/preview/dev-plm/index.html`]){
   const before=requests.length;
   await page.goto(base+'#projects');await page.locator('.project-card').first().waitFor();
   assert.equal(await page.locator('.project-card').count(),5);
   assert.equal(await page.evaluate(()=>window.DEVPLM_DATA.build.publication),'public');
   await page.goto(base+'#p/dev-plm/changes/CHG-002');await page.locator('#main h1').waitFor();
   const facts=await page.evaluate(()=>window.DEVPLM_DATA.projects.find(p=>p.id==='dev-plm').changes);
   for(const change of facts)for(const commit of change.git.commits||[])for(const file of commit.files||[]){assert.equal(file.patch,'');assert.equal(file.publication_omitted,true);}
   const attributes=await page.locator('script[src],link[href]').evaluateAll(els=>els.map(e=>e.getAttribute('src')||e.getAttribute('href')));
   assert.ok(attributes.every(s=>!s.startsWith('/')&&!/^https?:/.test(s)));
   outputs.push({mode:base.startsWith('file:')?'offline':'subpath',httpRequests:requests.slice(before).filter(u=>/^https?:/.test(u)).length});
  }
  assert.equal(outputs[0].httpRequests,0);assert.equal(fetches,0);assert.deepEqual(errors,[]);assert.deepEqual(missing,[]);
  assert.ok(requests.filter(u=>/^http/.test(u)).every(u=>u.startsWith(`http://127.0.0.1:${server.address().port}/preview/dev-plm/`)));
  const result={ok:true,outputs,fetches,errors,missing};
  fs.writeFileSync(path.join(root,'.work/round5-public-browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1});
