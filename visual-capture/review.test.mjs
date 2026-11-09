import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { resolve } from 'node:path';
import { mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const service = spawn(process.env.VERIFICATION_PYTHON || 'python',
  [resolve(import.meta.dirname, '../scripts/serve_review_fixture.py')], {stdio:['ignore','pipe','inherit']});
let browser;
try {
  const line = await Promise.race([once(createInterface({input:service.stdout}), 'line'),
    once(service, 'exit').then(([code]) => {throw new Error(`Fixture exited: ${code}`);})]);
  const fixture = JSON.parse(line[0]);
  browser = await chromium.launch({headless:true,
    executablePath:process.env.VERIFICATION_CHROMIUM_EXECUTABLE || undefined,
    args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page = await browser.newPage({viewport:{width:1280,height:1000}});
  const errors=[]; page.on('pageerror', error=>errors.push(error.message));
  await page.goto(`http://127.0.0.1:${fixture.port}/review`);
  await page.getByLabel('API bearer token').fill('local-fixture-only');
  await page.getByLabel('Verification ID').fill(fixture.job_id);
  await page.getByRole('button',{name:'Load report',exact:true}).click();
  await page.locator('#result').waitFor({state:'visible'});
  assert.equal(await page.locator('#gate').textContent(), 'fail');
  assert.match(await page.locator('#findings').textContent(), /POWER/);
  await page.getByLabel('Requirement',{exact:true}).selectOption('POWER');
  await page.getByLabel('Rationale').fill('Fixture review; preserve measured power failure.');
  await page.getByRole('button',{name:'Record review',exact:true}).click();
  await page.waitForFunction(()=>document.getElementById('history').textContent.includes('Fixture review'));
  assert.equal(await page.locator('#gate').textContent(), 'fail');
  assert.deepEqual(errors,[]);
  if(process.env.VERIFICATION_UI_CAPTURE_DIR){
    await mkdir(process.env.VERIFICATION_UI_CAPTURE_DIR,{recursive:true});
    await page.screenshot({path:resolve(process.env.VERIFICATION_UI_CAPTURE_DIR,'review.png'),fullPage:true});
  }
  console.log('Review UI: report, criteria, evidence and append-only review passed.');
} finally {
  if(browser) await browser.close();
  service.kill('SIGTERM');
}
