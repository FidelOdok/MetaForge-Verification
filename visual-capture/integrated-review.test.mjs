import { readFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const result=JSON.parse(await readFile(process.argv[2],'utf8'));
const browser=await chromium.launch({headless:true,
  executablePath:process.env.VERIFICATION_CHROMIUM_EXECUTABLE || undefined,
  args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
try {
  const page=await browser.newPage({viewport:{width:1360,height:1000}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(result.base_url+'/review?job='+result.failed_job);
  assert.equal(await page.getByLabel('Verification ID').inputValue(),result.failed_job);
  await page.getByLabel('API bearer token').fill('local-testing-agent-token');
  await page.getByRole('button',{name:'Load report',exact:true}).click();
  await page.waitForFunction(()=>document.querySelectorAll('#captures canvas').length===4);
  assert.equal(await page.locator('#gate').textContent(),'fail');
  assert.match(await page.locator('#findings').textContent(),/CAD_INTERFERENCE/);
  assert.match(await page.locator('#captures').textContent(),/pixels changed/);
  assert.deepEqual(errors,[]);
  if(process.env.VERIFICATION_UI_CAPTURE_DIR){
    await mkdir(process.env.VERIFICATION_UI_CAPTURE_DIR,{recursive:true});
    await page.screenshot({path:resolve(process.env.VERIFICATION_UI_CAPTURE_DIR,'integrated-review.png'),fullPage:true});
  }
  console.log('Integrated review: four authenticated previews, differences and CAD findings: PASS');
} finally {await browser.close();}
