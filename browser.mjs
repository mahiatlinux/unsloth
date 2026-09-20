import { chromium, firefox } from 'playwright';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const root='/home/masher/unsloth-work/temp/issue-11030';
const models = [
 ['unsloth/Atlas-4B-GGUF',4e9,32768],['unsloth/Atlas-8B-GGUF',8e9,131072],['unsloth/Atlas-70B-GGUF',70e9,131072],['unsloth/Atlas-short-GGUF',4e9,4096],['community/Atlas-4B-GGUF',4e9,32768],['unsloth/Atlas-checkpoint',4e9,null]
].map(([id,total,context])=>({_id:id,id,downloads:1000,likes:50,private:false,gated:false,pipeline_tag:'text-generation',lastModified:'2026-09-01T00:00:00Z',createdAt:'2026-09-01T00:00:00Z',tags:context?['gguf']:['safetensors'],library_name:context?'gguf':'transformers',...(context?{gguf:{total,context_length:context,architecture:'llama'}}:{safetensors:{total,parameters:{BF16:total}}})}));
const results=[];
for (const engine of (process.env.ENGINE ? [process.env.ENGINE] : ['chromium','firefox'])) {
 const browser=await ({chromium,firefox}[engine]).launch({headless:true});
 for (const side of (process.env.SIDE ? [process.env.SIDE] : ['before','after'])) {
 const ctx=await browser.newContext({viewport:{width:1440,height:1000},locale:'en-US',colorScheme:'light',reducedMotion:'reduce'});
 await ctx.addInitScript(()=>{
  localStorage.setItem('unsloth_auth_token','fixture.'+btoa(JSON.stringify({exp:4000000000,sub:'test'}))+'.fixture');
  localStorage.setItem('unsloth.hub.ownerScope','all');
  localStorage.setItem('unsloth.hub.allModelsView','two');
 });
 const requests=[];
 await ctx.route('**/*',async route=>{
  const u=new URL(route.request().url());
  const respond=(body,status=200,headers={})=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body),headers});
  if(u.hostname==='huggingface.co'){
   if(u.pathname==='/api/models'){
    requests.push(u.href);
    let rows=models.filter(m=>(!u.searchParams.get('author')||m.id.startsWith(u.searchParams.get('author')+'/'))&&(!u.searchParams.get('search')||m.id.toLowerCase().includes(u.searchParams.get('search').toLowerCase())));
    if(u.searchParams.get('search')==='Priority') rows=u.searchParams.get('author')==='unsloth'?[{...models[0],id:'unsloth/Priority-Unsloth-GGUF'}]:Array.from({length:200},(_,i)=>({...models[0],id:`community/Priority-${i}-GGUF`}));
    const range=u.searchParams.get('num_parameters');
    if(range){for(const bound of range.split(',')){const [key,value]=bound.split(':');rows=rows.filter(m=>key==='min'?(m.gguf?.total??m.safetensors.total)>=Number(value):(m.gguf?.total??m.safetensors.total)<=Number(value));}}
    return respond(rows);
   }
   if(u.pathname.includes('/api/organizations/')) return respond({isVerified:u.pathname.includes('/unsloth/')});
   if(u.pathname.endsWith('/config.json')) return respond({thinker_config:{text_config:{max_position_embeddings:32768}}});
   if(u.pathname.replace(/\/revision\/HEAD$/, '')==='/api/models/publisher/Atlas-pinned-GGUF') return respond({...models[0],id:'publisher/Atlas-pinned-GGUF',gguf:{total:4e9}});
   if(u.pathname.startsWith('/api/models/')) return respond(models.find(m=>u.pathname.replace(/\/revision\/HEAD$/, '')==='/api/models/'+m.id)??{});
   if(u.pathname==='/api/datasets') return respond([]);
   return respond({},404);
  }
  if(u.pathname.startsWith('/api/')||u.pathname.startsWith('/v1/')){
   if(u.pathname==='/api/health') return respond({status:'ok',version:'test',device_type:'cpu',chat_only:true,hardware_detecting:false});
   if(u.pathname==='/api/auth/status') return respond({initialized:true,requires_password_change:false,login_mode:'single',full_access:true});
   if(u.pathname.includes('/cached')) return respond({cached:[],scan_confirmed:true});
   if(u.pathname.includes('local-models')) return respond({models:[],models_dir:'',lmstudio_dirs:[]});
   if(u.pathname.includes('active-downloads')) return respond({downloads:[]});
   if(u.pathname.includes('scan-folders')) return respond({folders:[]});
   if(u.pathname.includes('status')) return respond({status:'idle',loaded:false});
   return respond({models:[],datasets:[],devices:[],accounts:[],items:[],entries:[]});
  }
  if(u.hostname!=='127.0.0.1')return route.abort();
  return route.continue();
 });
 const page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('console',m=>{if(m.type()==='error')console.log('CONSOLE',m.text())});
 await page.goto(`http://127.0.0.1:${side==='before'?5194:5193}/hub`,{waitUntil:'networkidle'});
 if(await page.getByText('Show Error',{exact:true}).count()) await page.getByText('Show Error',{exact:true}).click();

 const search=page.getByPlaceholder('Search all models');
 await search.fill('Atlas');
 await page.getByText('Results for "Atlas"',{exact:true}).waitFor();
 await page.getByText('Atlas-70B-GGUF',{exact:true}).first().waitFor();
 await page.screenshot({path:`${root}/artifacts/${engine}-${side}-initial.png`});
 if(side==='after'){
  const filters=page.getByRole('button',{name:'Model size and publisher filters'});
  await filters.click();
  await page.getByLabel('Minimum parameters (billions)',{exact:true}).fill('2');
  await page.getByLabel('Maximum parameters (billions)',{exact:true}).fill('8');
  await page.getByLabel('Minimum context length (tokens)',{exact:true}).fill('32768');
  await page.getByLabel('Maximum context length (tokens)',{exact:true}).fill('131072');
  await page.getByLabel('Verified organizations only').check();
  await page.screenshot({path:`${root}/artifacts/${engine}-after-filters.png`});
  await page.getByRole('button',{name:'Apply filters'}).click();
  await page.waitForTimeout(800);
  assert.equal(await page.getByText('Atlas-70B-GGUF',{exact:true}).count(),0);
  assert.equal(await page.getByText('Atlas-short-GGUF',{exact:true}).count(),0);
  assert.equal(await page.getByText('Atlas-4B-GGUF',{exact:true}).count(),1);
  assert.equal(await page.getByText('Atlas-8B-GGUF',{exact:true}).count(),1);
  assert(requests.some(r=>new URL(r).searchParams.get('num_parameters')==='min:2000000000,max:8000000000'));
  await page.screenshot({path:`${root}/artifacts/${engine}-after.png`});
  await filters.click();await page.getByLabel('Minimum parameters (billions)',{exact:true}).fill('9');
  assert.equal(await page.getByRole('button',{name:'Apply filters'}).isDisabled(),true);
  await page.getByRole('button',{name:'Clear',exact:true}).click();
  await page.getByText('Atlas-70B-GGUF',{exact:true}).first().waitFor();
  await filters.click();await page.getByLabel('Minimum context length (tokens)',{exact:true}).fill('999999');await page.getByRole('button',{name:'Apply filters'}).click();
  await page.waitForTimeout(800); assert.equal(await page.getByText('Atlas-4B-GGUF',{exact:true}).count(),0);
  await page.screenshot({path:`${root}/artifacts/${engine}-empty.png`});
  await filters.click();await page.getByRole('button',{name:'Clear',exact:true}).click();
  await search.fill('publisher/Atlas');
  await page.getByRole('button',{name:'Publisher scope'}).click();
  await page.getByRole('option',{name:'Unsloth',exact:true}).click();
  await filters.click();await page.getByLabel('Verified organizations only').check();await page.getByRole('button',{name:'Apply filters'}).click();
  await page.waitForTimeout(800);
  assert.equal(await page.getByText('Atlas-4B-GGUF',{exact:true}).count(),1);
  assert(requests.some(r=>{const u=new URL(r);return u.searchParams.get('author')==='unsloth'&&u.searchParams.get('search')==='Atlas'}));
  await filters.click();await page.getByRole('button',{name:'Clear',exact:true}).click();
  await page.getByRole('button',{name:'Publisher scope'}).click();await page.getByRole('option',{name:'All',exact:true}).click();
  await search.fill('publisher/Atlas-pinned-GGUF');
  await filters.click();await page.getByLabel('Maximum parameters (billions)',{exact:true}).fill('8');await page.getByLabel('Minimum context length (tokens)',{exact:true}).fill('32768');await page.getByRole('button',{name:'Apply filters'}).click();
  await page.getByText('Atlas-pinned-GGUF',{exact:true}).first().waitFor();
  await page.screenshot({path:`${root}/artifacts/${engine}-pinned.png`});
  await search.fill('Priority');
  await page.getByText('Priority-Unsloth-GGUF',{exact:true}).first().waitFor();
  await page.getByRole('radio',{name:'Datasets',exact:true}).click(); assert.equal(await filters.count(),0);
  await page.getByRole('radio',{name:'Models',exact:true}).click();
  await page.setViewportSize({width:390,height:844});await filters.click();
  await page.screenshot({path:`${root}/artifacts/${engine}-mobile.png`});
  const box=await page.locator('[data-slot="popover-content"]').boundingBox();assert(box.x>=0&&box.x+box.width<=391);
  await page.keyboard.press('Escape');
 } else {
  assert.equal(await page.getByRole('button',{name:'Model size and publisher filters'}).count(),0);
  await page.screenshot({path:`${root}/artifacts/${engine}-before.png`});
 }
 results.push({side,engine,browser:browser.version(),errors,listingRequests:requests.length});
 console.log(results.at(-1));await ctx.close();
 }
 await browser.close();
}
await fs.writeFile(root+'/artifacts/browser-results.json',JSON.stringify(results,null,2));
