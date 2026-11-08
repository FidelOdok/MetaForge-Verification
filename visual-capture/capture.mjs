import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createServer } from 'node:http';
import { dirname, resolve, extname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

export const sha256 = bytes => createHash('sha256').update(bytes).digest('hex');
export const root = dirname(fileURLToPath(import.meta.url));

export function assetPath(path) {
  const allowed = new Set(['/three/build/three.module.js', '/three/build/three.core.js',
    '/three/examples/jsm/loaders/GLTFLoader.js',
    '/three/examples/jsm/utils/BufferGeometryUtils.js']);
  return allowed.has(path) ? resolve(root,'node_modules',path.slice(1)) : null;
}

export async function capture(modelPath, output, revision) {
  if(!/^[A-Za-z0-9_-]{1,100}$/.test(revision)) throw new Error('Invalid revision ID');
  const model = await readFile(modelPath);
  if(model.length > 20*1024*1024 || model.subarray(0,4).toString() !== 'glTF')
    throw new Error('Expected GLB no larger than 20 MiB');
  const page = await readFile(resolve(root,'viewer.html'));
  const server = createServer(async (req,res) => {
    try {
      const path = new URL(req.url,'http://localhost').pathname;
      let data, type;
      if(path==='/') { data=page; type='text/html'; }
      else if(path==='/model.glb') { data=model; type='model/gltf-binary'; }
      else {
        const local=assetPath(path); if(!local){res.writeHead(404).end();return;}
        data=await readFile(local); type=extname(local)==='.js'?'text/javascript':'application/octet-stream';
      }
      res.writeHead(200,{'Content-Type':type});res.end(data);
    } catch {res.writeHead(500).end();}
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  let browser;
  try {
    browser=await chromium.launch({headless:true,
      executablePath:process.env.VERIFICATION_CHROMIUM_EXECUTABLE || undefined,
      args:['--use-angle=swiftshader',
      '--enable-unsafe-swiftshader','--ignore-gpu-blocklist']});
    const address=`http://127.0.0.1:${server.address().port}`;
    const context=await browser.newContext({viewport:{width:512,height:512},deviceScaleFactor:1,
                                           serviceWorkers:'block'});
    await context.route('**/*', route => {
      const url=new URL(route.request().url());
      return url.origin===address ? route.continue() : route.abort();
    });
    const tab=await context.newPage();
    const errors=[];tab.on('pageerror',e=>errors.push(e.message));
    await tab.goto(address,{waitUntil:'load',timeout:15000});
    await tab.waitForFunction(()=>window.renderReady===true,{},{timeout:15000});
    if(errors.length) throw new Error(errors.join('; '));
    const settings={viewer_sha256:sha256(page),browser:browser.version(),three:'0.172.0',
      width:512,height:512,projection:'orthographic',lighting:'hemisphere-v1',
      directions:{front:[0,0,1],side:[1,0,0],top:[0,1,0],iso:[1,1,1]}};
    await mkdir(output,{recursive:true});
    const views=[];
    for(const view of ['front','side','top','iso']) {
      const encoded=await tab.evaluate(name=>window.captureView(name),view);
      const bytes=Buffer.from(encoded.split(',')[1],'base64');
      await writeFile(resolve(output,`${view}.png`),bytes);
      views.push({view,file:`${view}.png`,sha256:sha256(bytes)});
    }
    const manifest={schema_version:'1.0',revision_id:revision,model_sha256:sha256(model),
      context_sha256:sha256(JSON.stringify(settings)),settings,views,
      bounds:await tab.evaluate(()=>window.modelBounds),
      limitations:['Mesh render only; no CAD dimensions or semantic feature validation.',
                   'Camera automatically frames each model; absolute scale comparisons need CAD evidence.']};
    await writeFile(resolve(output,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
    return manifest;
  } finally {
    if(browser) await browser.close();
    await new Promise(resolve=>server.close(resolve));
  }
}

if(process.argv[1] && resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  if(process.argv.length!==5) {
    console.error('Usage: node capture.mjs model.glb output-directory revision');process.exitCode=2;
  } else {
    try {console.log(JSON.stringify(await capture(process.argv[2],process.argv[3],process.argv[4])));}
    catch(error){console.error(error.message);process.exitCode=1;}
  }
}
