const fs=require('node:fs');const path=require('node:path');const {spawn}=require('node:child_process');
const db=path.resolve(__dirname,'../../../../work/platform-e2e.sqlite3');fs.copyFileSync(path.resolve(__dirname,'../../hoppr.sqlite3'),db);
const child=spawn('python',['-m','uvicorn','backend:app','--app-dir','..','--host','127.0.0.1','--port','8011','--no-proxy-headers'],{stdio:'inherit',env:{...process.env,HOPPR_V2_DB:db,AIRPOOL_OFFLINE:'1'}});process.on('SIGTERM',()=>child.kill());process.on('SIGINT',()=>child.kill());child.on('exit',code=>process.exit(code||0));
