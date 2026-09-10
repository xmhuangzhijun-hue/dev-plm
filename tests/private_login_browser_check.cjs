// Real HTTPS form navigation regression. Credentials are supplied via stdin only;
// never save traces, screenshots, response bodies or credentials.
const {chromium}=require(process.env.PLAYWRIGHT_PATH || 'playwright');
const assert=require('node:assert/strict');
async function main(){
 let stage='read-input';
 const deadline=setTimeout(()=>{console.error('Acceptance timeout at '+stage);process.exit(1);},60000);
 let input='';for await(const chunk of process.stdin)input+=chunk;
 const {url,identifier,credential}=JSON.parse(input);input='';
 const origin=new URL(url).origin;assert.equal(new URL(url).protocol,'https:');
 stage='launch';const browser=await chromium.launch({headless:true});
 try{
  const context=await browser.newContext({viewport:{width:390,height:844}});
  const page=await context.newPage();
  stage='load-login';const login=await page.goto(origin+'/login');
  assert.equal(login.status(),200);
  assert.equal(login.headers()['referrer-policy'],'same-origin');
  stage='boundary-checks';for(const foreign of ['https://other.invalid','null']){
   const rejected=await context.request.post(origin+'/session',{headers:{Origin:foreign},form:{identifier:'invalid',credential:'invalid'}});
   assert.equal(rejected.status(),403);
  }
  const missing=await context.request.get(origin+'/site/assets/project-data.js',{maxRedirects:0});
  assert.equal(missing.status(),303);
  stage='form-submit';await page.locator('[name=identifier]').fill(identifier);
  await page.locator('[name=credential]').fill(credential);
  const requestPromise=page.waitForRequest(r=>new URL(r.url()).pathname==='/session');
  const responsePromise=page.waitForResponse(r=>new URL(r.url()).pathname==='/session');
  await page.getByRole('button',{name:'登录并查看'}).click();
  const request=await requestPromise;const response=await responsePromise;
  assert.equal((await request.allHeaders()).origin,origin);
  assert.equal(response.status(),303);
  stage='workbench';await page.waitForURL(u=>u.pathname==='/site/index.html');
  await page.waitForLoadState('networkidle');
  assert.ok((await page.locator('body').innerText()).length>100);
  const data=await context.request.get(origin+'/site/assets/project-data.js');
  assert.equal(data.status(),200);
  const api=await context.request.get(origin+'/v1/projects');
  assert.equal(api.status(),401);
  const cookie=(await context.cookies()).find(c=>c.name==='devplm_session');
  assert.ok(cookie && cookie.secure && cookie.httpOnly && cookie.sameSite==='Strict');
  console.log(JSON.stringify({ok:true,real_https_browser_login:303,workbench_loaded:true,authenticated_data:200,anonymous_data:303,cookie_not_api_auth:401,foreign_and_null_origin:403,mobile_viewport_width:390}));
 }finally{stage='browser-close';await browser.close();clearTimeout(deadline);}
}
main().catch(()=>{console.error('Private browser login acceptance failed; no sensitive diagnostics emitted.');process.exitCode=1;});
