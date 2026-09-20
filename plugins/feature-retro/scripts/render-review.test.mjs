import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {validateReview,renderBoard,renderFlow,createDeck} from './render-review.mjs';
import {buildReview} from './build-review.mjs';

const fixture=JSON.parse(await fs.readFile(new URL('../examples/review.json',import.meta.url),'utf8'));
test('repeatable components, escaping, validation and exclusive output', async () => {
  const root=await fs.mkdtemp(path.join(os.tmpdir(),'retro-test-'));
  try {
    const data=structuredClone(fixture);
    data.sections[1].blocks[0].items[0].text='<script>alert("secret")</script> & text';
    const html=renderBoard(data);
    assert(html.includes('&lt;script&gt;')); assert(!html.includes('<script>'));
    assert(html.includes('Content-Security-Policy')); assert(html.includes('scope="col"')); assert(html.includes('<details>'));
    assert(html.includes('aria-labelledby="diagram-architecture-title diagram-architecture-desc"'));
    assert.equal(html,renderBoard(data));
    const hostileFlow=structuredClone(fixture.sections[0].blocks[0]);
    hostileFlow.id='bad" onload="alert(1)'; assert.throws(()=>renderFlow(hostileFlow));
    for (const mutate of [
      d=>{d.sections[0].id='../escape';},
      d=>{d.sections[0].blocks[0].id='../../escape';},
      d=>{d.sections[1].id=d.sections[0].id;},
      d=>{d.sections[0].blocks[0].paths[0].nodes[0].label='x'.repeat(31);},
      d=>{d.sections[0].blocks[0].paths[0].nodes.push(...d.sections[0].blocks[0].paths[0].nodes);},
      d=>{d.sections[2].blocks[0].rows[0].pop();},
      d=>{d.sections[1].blocks[0].kind='rawHTML';},
      d=>{d.runtime='untrusted-module.mjs';},
      d=>{d.title='bad\u0001control';},
      d=>{d.slides[0].elements[0].y=700;},
      d=>{d.slides[0].elements[1].x='0';},
      d=>{d.slides[0].elements[3].color='url(https://example.invalid)';},
      d=>{d.slides[0].elements[4].value=2;},
    ]) {const bad=structuredClone(fixture); mutate(bad); assert.throws(()=>validateReview(bad));}
    // Exercise every deck primitive without needing the optional runtime.
    const shapes=[]; const notes=[];
    const fake={create:()=>({slides:{add:()=>({background:{},shapes:{add:spec=>{const shape={...spec,text:{}}; Object.defineProperty(shape,'text',{get:()=>shape.frame,set:value=>{shape.frame={value};}}); shapes.push(shape); return shape;}},speakerNotes:{textFrame:{setText:n=>notes.push(n)}}})}})};
    createDeck(fixture,fake,'Test font');
    assert.equal(shapes.length,10); assert.equal(notes[0],fixture.slides[0].notes);
    assert.equal(shapes.filter(s=>s.geometry==='rightArrow').length,1);
    const input=path.join(root,'review.json'); await fs.writeFile(input,JSON.stringify(data));
    const first=path.join(root,'first'); const second=path.join(root,'second');
    await buildReview(input,first); await buildReview(input,second);
    for (const name of await fs.readdir(first)) assert.deepEqual(await fs.readFile(path.join(first,name)),await fs.readFile(path.join(second,name)));
    await assert.rejects(buildReview(input,first),/EEXIST/);
    assert.equal(await fs.readFile(path.join(first,'review-board.html'),'utf8'),html);
    await fs.symlink(first,path.join(root,'link')); await assert.rejects(buildReview(input,path.join(root,'link')),/EEXIST/);
    const file=path.join(root,'keep.txt'); await fs.writeFile(file,'keep');
    await assert.rejects(buildReview(input,file),/EEXIST/); assert.equal(await fs.readFile(file,'utf8'),'keep');
    await fs.writeFile(input,'{"version":2}');
    await assert.rejects(buildReview(input,path.join(root,'invalid')));
    await assert.rejects(fs.access(path.join(root,'invalid')));
  } finally { await fs.rm(root,{recursive:true,force:true}); }
});
