import fs from 'node:fs/promises';import path from 'node:path';import {chromium} from 'playwright';
const root=path.resolve('../../../work/pw-browsers');const folder=(await fs.readdir(root)).find(n=>/^chromium-\d+$/.test(n));
const browser=await chromium.launch({executablePath:path.join(root,folder,'chrome-win64/chrome.exe'),headless:true});
try{const svg=await fs.readFile('public/icon.svg','utf8');for(const size of [192,512]){const page=await browser.newPage({viewport:{width:size,height:size}});await page.setContent(`<style>body{margin:0;padding:20px;background:#f3f7ff}svg{width:100%;height:100%}</style>${svg}`);await page.screenshot({path:`public/icon-${size}.png`});await page.close();}}finally{await browser.close();}
