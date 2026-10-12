import fs from 'node:fs/promises';
import path from 'node:path';
import {chromium} from 'playwright';
import lighthouse from 'lighthouse';
import * as chromeLauncher from 'chrome-launcher';
process.env.PLAYWRIGHT_BROWSERS_PATH=path.resolve('../../../work/pw-browsers');
const base=process.env.HOPPR_AUDIT_URL||'http://127.0.0.1:8010';
const results=[];
const browserRoot=path.resolve('../../../work/pw-browsers');
const chromeFolder=(await fs.readdir(browserRoot)).find(name=>/^chromium-\d+$/.test(name));
const chromePath=path.join(browserRoot,chromeFolder,'chrome-win64','chrome.exe');
for(const app of ['rider','driver','ops']){
  const chrome=await chromeLauncher.launch({chromePath,chromeFlags:['--headless','--no-sandbox']});
  try{
    const browser=await chromium.connectOverCDP(`http://127.0.0.1:${chrome.port}`);
    const context=browser.contexts()[0];const page=await context.newPage();
    await page.goto(base+'/'+app);
    const login=await page.request.post(base+'/v2/auth/demo',{data:{app}});const session=await login.json();
    await page.evaluate(({app,token})=>{localStorage.setItem('hoppr-v2-'+app,token);localStorage.setItem('hoppr-v2-story','1');},{app,token:session.token});
    await page.reload();
    const desktop=app==='ops';
    const result=await lighthouse(base+'/'+app,{port:chrome.port,output:'json',disableStorageReset:true,formFactor:desktop?'desktop':'mobile',screenEmulation:desktop?{mobile:false,width:1440,height:1000,deviceScaleFactor:1,disabled:false}:{mobile:true,width:390,height:844,deviceScaleFactor:1,disabled:false},onlyCategories:['performance','accessibility','best-practices','seo']});
    await fs.writeFile(path.resolve('../lighthouse-'+app+'.json'),result.report);
    const scores=Object.fromEntries(Object.entries(result.lhr.categories).map(([key,c])=>[key,Math.round(c.score*100)]));results.push({app,form_factor:desktop?'desktop':'mobile',scores});console.log(app,JSON.stringify(scores));
    try{const cdp=await context.newCDPSession(page);await cdp.send('Browser.close');}catch{}
    await browser.close();
  }finally{await chrome.kill();}
}
await fs.writeFile(path.resolve('../lighthouse-summary.json'),JSON.stringify(results,null,2));
