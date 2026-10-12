import {defineConfig} from '@playwright/test';
import fs from 'node:fs';import path from 'node:path';
const db=path.resolve('../../../work/platform-e2e.sqlite3');fs.copyFileSync(path.resolve('../hoppr.sqlite3'),db);
process.env.PLAYWRIGHT_BROWSERS_PATH=path.resolve('../../../work/pw-browsers');
export default defineConfig({testDir:'./tests',timeout:120000,workers:1,use:{baseURL:'http://127.0.0.1:8011',browserName:'chromium',trace:'retain-on-failure'},reporter:[['list'],['json',{outputFile:'../playwright-results.json'}]],...(process.env.HOPPR_E2E_EXTERNAL?{}:{webServer:{command:'python -m uvicorn backend:app --app-dir .. --host 127.0.0.1 --port 8011 --no-proxy-headers',env:{HOPPR_V2_DB:db,AIRPOOL_OFFLINE:'1'},url:'http://127.0.0.1:8011/v2/health',reuseExistingServer:false,timeout:60000}}),outputDir:'../../../work/playwright-artifacts'});
