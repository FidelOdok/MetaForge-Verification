import { test } from 'node:test';
import assert from 'node:assert/strict';
import { assetPath, sha256 } from './capture.mjs';
test('only bundled required assets can be served',()=>{
  assert.ok(assetPath('/three/build/three.module.js'));
  for(const value of ['/etc/passwd','/three/../../package.json','/three/examples/evil.js'])
    assert.equal(assetPath(value),null);
});
test('hashes actual artifact bytes',()=>{
  assert.equal(sha256(Buffer.from('abc')),
    'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad');
});
