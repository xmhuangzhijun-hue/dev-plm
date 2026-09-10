const {chromium}=require(process.env.PLAYWRIGHT_PATH||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
(async()=>{
 const root=path.resolve(__dirname,'..'),receipt=JSON.parse(fs.readFileSync(path.join(root,'docs/rebuild-receipt.json'),'utf8'));
 const browser=await chromium.launch({headless:true});const errors=[],requests=[];
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}});
  await page.route(/^https?:/,route=>{requests.push(route.request().url());return route.abort()});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(pathToFileURL(path.join(root,receipt.offline_site)).href+'#p/dev-plm/collaboration');
  await page.getByRole('heading',{name:'讨论与认领',exact:true}).waitFor();
  const text=await page.locator('#main').innerText();assert.ok(text.includes('数据库恢复演练首帖'));assert.ok(text.includes('演练回复'));
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth));
  assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
  const result={ok:true,restored_discussion_visible:true,restored_reply_visible:true,width:390,errors,http_requests:requests.length};
  fs.writeFileSync(path.join(root,'docs/round6-recovery-browser.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
