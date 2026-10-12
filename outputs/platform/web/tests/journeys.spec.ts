import {test,expect,Page} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import path from 'node:path';
const shots=path.resolve('../screenshots');
async function shot(page:Page,name:string){await page.evaluate(()=>document.fonts.ready);await page.screenshot({path:path.join(shots,name+'.png'),fullPage:true});}
async function login(page:Page,app:string,account?:string){await page.goto('/'+app);if(app==='rider'){await expect(page.getByRole('button',{name:'Skip',exact:true})).toBeVisible();await page.getByRole('button',{name:'Skip',exact:true}).click();}if(account)await page.getByLabel('Choose a demo account').selectOption(account);await shot(page,app+'-login');await page.getByRole('button',{name:'Use demo '+app+' account'}).click();}
async function access(page:Page){const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(result.violations.map(v=>({id:v.id,description:v.description,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);}

test('Visual airport workspace and interactive mobile/laptop preview',async({page})=>{
  await page.setViewportSize({width:1440,height:1000});await login(page,'rider');
  await expect(page.getByRole('heading',{name:'My flights',exact:true})).toBeVisible();
  await expect(page.getByRole('img',{name:'Illustration of travellers sharing a cab from an airport to the city'})).toBeVisible();
  await shot(page,'refresh-laptop');await access(page);
  await page.getByRole('button',{name:'Mobile',exact:true}).click();
  const phone=page.frameLocator('iframe[title="Hoppr rider mobile preview"]');
  await expect(phone.getByRole('heading',{name:'My flights',exact:true})).toBeVisible();
  await expect(phone.getByRole('button',{name:/6E410/}).first()).toBeVisible();
  await shot(page,'refresh-mobile-preview');
  await page.getByRole('button',{name:'Laptop',exact:true}).click();
  await expect(page.getByRole('heading',{name:'My flights',exact:true})).toBeVisible();
});

test('Rider secondary screens and Driver desk fit phones and laptops',async({page,context})=>{
  await login(page,'rider');
  for(const width of [360,390,768,1440]){
    await page.setViewportSize({width,height:900});
    for(const [label,name] of [['Trips','trips'],['Wallet','wallet'],['More','profile']]){
      await page.getByRole('navigation',{name:'Rider navigation'}).getByRole('button',{name:label,exact:true}).click();
      await expect(page.locator('.rider-content')).toBeVisible();
      expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
      await shot(page,`polish-rider-${name}-${width}`);
      if(width===390||width===1440)await access(page);
    }
  }
  const driver=await context.newPage();await login(driver,'driver');
  for(const width of [360,390,768,1440]){
    await driver.setViewportSize({width,height:900});
    await driver.getByRole('navigation',{name:'Driver navigation'}).getByRole('button',{name:'Home',exact:true}).click();
    await expect(driver.locator('.driver-desk')).toBeVisible();
    expect(await driver.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    await shot(driver,`polish-driver-home-${width}`);await access(driver);
  }
});
test('Rider full journey and matching across Driver app',async({page,context})=>{
  await page.setViewportSize({width:390,height:844});await page.goto('/rider');
  for(let i=0;i<4;i++){await expect(page.getByRole('button',{name:i===3?'Get started':'Next',exact:true})).toBeVisible();await shot(page,'rider-0'+i+'-story');await page.getByRole('button',{name:i===3?'Get started':'Next',exact:true}).click();}
  await shot(page,'rider-04-login');await page.getByRole('button',{name:'Use demo rider account'}).click();await expect(page.getByRole('heading',{name:'My flights',exact:true})).toBeVisible();await shot(page,'rider-05-flights');await access(page);
  await page.getByRole('button',{name:/Import demo itinerary/}).click();await page.getByRole('button',{name:/6E410/}).first().click();await shot(page,'rider-06-flight-detail');await page.getByRole('button',{name:/Book an airport cab/}).click();await shot(page,'rider-07-booking-flight');await page.getByRole('button',{name:/Choose drop-off/}).click();await shot(page,'rider-08-destination');await page.getByRole('button',{name:/Review preferences/}).click();await shot(page,'rider-09-options');await page.getByRole('button',{name:/Find my flight-mates/}).click();await expect(page.getByRole('button',{name:/Book & lock/})).toBeVisible();await shot(page,'rider-10-matching');await access(page);
  await page.getByRole('button',{name:/Book & lock/}).click();await expect(page.getByRole('button',{name:/View trip status/})).toBeVisible();await shot(page,'rider-11-confirmed');await page.getByRole('button',{name:/View trip status/}).click();await shot(page,'rider-12-trip');
  const session=await page.evaluate(()=>localStorage.getItem('hoppr-v2-rider'));
  const me=await (await page.request.get('/v2/me',{headers:{Authorization:'Bearer '+session}})).json();const booking=me.bookings.find((b:any)=>b.status==='booked');expect(booking).toBeTruthy();
  const driver=await context.newPage();await driver.setViewportSize({width:390,height:844});await login(driver,'driver',booking.driver_id);await expect(driver.getByRole('heading',{name:/Good evening/})).toBeVisible();await shot(driver,'driver-00-home');await access(driver);await driver.getByRole('button',{name:/Review offer/}).first().click();await shot(driver,'driver-01-offer');await driver.getByRole('button',{name:'Accept trip',exact:true}).click();await shot(driver,'driver-02-accepted');await driver.getByRole('button',{name:'Navigate to pickup',exact:true}).click();await shot(driver,'driver-03-en-route');await driver.getByRole('button',{name:'I’m at the pickup point',exact:true}).click();await shot(driver,'driver-04-arrived');await driver.getByLabel(/Pickup code for/).fill(booking.pickup_code);await driver.getByRole('button',{name:'Verify codes & board',exact:true}).click();await shot(driver,'driver-05-boarded');await driver.getByRole('button',{name:'All passengers dropped',exact:true}).click();await expect(driver.getByRole('heading',{name:'Trip complete.'})).toBeVisible();await shot(driver,'driver-06-summary');await driver.getByRole('button',{name:'View earnings',exact:true}).click();await shot(driver,'driver-07-earnings');await driver.getByRole('button',{name:'Account',exact:true}).click();await shot(driver,'driver-08-account');
  await page.reload();await expect(page.getByRole('heading',{name:'My flights',exact:true})).toBeVisible();await page.getByRole('button',{name:'Trips',exact:true}).click();await page.getByRole('button',{name:/View ride & receipt/}).last().click();await expect(page.getByRole('heading',{name:'How was the last leg?'})).toBeVisible();await shot(page,'rider-13-rating');await page.getByRole('button',{name:'Save rating & view receipt'}).click();await expect(page.getByRole('heading',{name:'Your receipt.'})).toBeVisible();await shot(page,'rider-14-receipt');await page.getByRole('button',{name:'Wallet',exact:true}).click();await shot(page,'rider-15-wallet');await page.getByRole('button',{name:'More',exact:true}).click();await shot(page,'rider-16-more');await access(page);
});
test('Ops modules, filtering, sorting, export and audited resolution',async({page})=>{
  await page.setViewportSize({width:1440,height:1000});await login(page,'ops');await expect(page.getByRole('heading',{name:'The arrivals picture.'})).toBeVisible();await shot(page,'ops-00-command');await access(page);
  const labels=['Flights & health','Demand','Pools','Riders & Drivers','Safety','Support','Finance','Pricing','Growth','Roles'];
  for(let i=0;i<labels.length;i++){await page.getByRole('button',{name:labels[i],exact:true}).click();await expect(page.getByRole('heading',{level:1})).toBeVisible();await shot(page,'ops-'+String(i+1).padStart(2,'0')+'-'+labels[i].replaceAll(' ','-'));}
  await page.getByRole('button',{name:'Riders & Drivers',exact:true}).click();await page.getByRole('textbox',{name:/Search \/ filter/}).fill('R0001');await expect(page.getByRole('button',{name:'View R0001',exact:true})).toBeVisible();await page.getByRole('button',{name:/first name/}).first().click();const download=page.waitForEvent('download');await page.getByRole('button',{name:'Export CSV',exact:true}).click();expect((await download).suggestedFilename()).toContain('riders');
  await page.getByRole('button',{name:'Support',exact:true}).click();await page.getByRole('button',{name:/^View T/}).first().click();await page.getByRole('button',{name:'Resolve case',exact:true}).click();await expect(page.getByRole('status').filter({hasText:'Saved'})).toBeVisible();await expect(page.getByRole('status',{name:'Loading table'})).toHaveCount(0);await shot(page,'ops-11-resolved');await access(page);
});
test('Responsive shell, native support dialog, PWA and offline state',async({page,context})=>{
  await page.setViewportSize({width:390,height:844});await login(page,'rider','R0004');await expect(page.getByRole('heading',{name:'My flights',exact:true})).toBeVisible();
  for(const width of [360,390,768,1280]){await page.setViewportSize({width,height:900});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();}
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'More',exact:true}).click();await page.getByRole('button',{name:'Support & ticket history'}).click();await expect(page.getByRole('dialog')).toBeVisible();await page.getByLabel('What happened?').fill('Please explain the demo pickup point.');await page.getByRole('button',{name:'Save support request',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Saved');await access(page);await shot(page,'rider-17-support');await page.keyboard.press('Escape');await expect(page.getByRole('dialog')).toHaveCount(0);
  const manifest=await (await page.request.get('/manifest-rider.webmanifest')).json();expect(manifest.id).toBe('/rider');expect(manifest.icons[0].sizes).toBe('192x192');
  await page.evaluate(()=>navigator.serviceWorker.ready);await page.reload();await expect(page.getByRole('heading',{name:'My flights',exact:true})).toBeVisible();await context.setOffline(true);await page.reload();await expect(page.getByRole('status').filter({hasText:'You’re offline'})).toBeVisible();await shot(page,'rider-18-offline');await context.setOffline(false);
});
