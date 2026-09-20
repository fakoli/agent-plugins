// Pure, offline components. Content is plain text, never HTML or executable code.
import assert from 'node:assert/strict';

export const colors = { bg:'#10242E', ink:'#F8F6F0', muted:'#B7C8CA', teal:'#71D4C1', orange:'#FFAE78', panel:'#193B46' };
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const copy = value => escape(value).replace(/\n/g, '<br>');
const string = (v, label, max=12000) => assert(typeof v === 'string' && v.trim() && v.length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(v), `Invalid ${label}`);
const array = (v, label, min=1, max=100) => assert(Array.isArray(v) && v.length >= min && v.length <= max, `Invalid ${label}`);
const id = v => assert(typeof v === 'string' && /^[a-z][a-z0-9-]{0,63}$/.test(v), 'Invalid identifier');
const fields = (v, allowed) => {
  assert(v && typeof v === 'object' && !Array.isArray(v), 'Expected object');
  for (const key of Object.keys(v)) assert(allowed.includes(key), `Unknown field: ${key}`);
};

export function validateReview(data) {
  fields(data, ['version','title','date','headline','summary','notice','sections','footer','slides']);
  assert.equal(data.version, 1, 'Unsupported review version');
  for (const key of ['title','date','headline','summary','notice','footer']) string(data[key], key);
  array(data.sections, 'sections', 1, 30);
  const ids = new Set();
  for (const section of data.sections) {
    fields(section, ['id','label','title','blocks']);
    id(section.id); assert(!ids.has(section.id), 'Duplicate section identifier'); ids.add(section.id);
    string(section.label, 'section label'); string(section.title, 'section title');
    array(section.blocks, 'blocks', 1, 30);
    for (const block of section.blocks) {
      switch (block.kind) {
        case 'paragraph': case 'callout':
          fields(block, ['kind','text']); string(block.text, 'paragraph'); break;
        case 'details':
          fields(block, ['kind','summary','text']); string(block.summary, 'summary'); string(block.text, 'details'); break;
        case 'list':
          fields(block, ['kind','items']); array(block.items, 'list');
          for (const item of block.items) { fields(item, ['label','text']); string(item.label, 'item label'); string(item.text, 'item text'); } break;
        case 'table':
          fields(block, ['kind','caption','headers','rows']); string(block.caption, 'table caption'); array(block.headers, 'headers', 1, 6); array(block.rows, 'table rows');
          block.headers.forEach(v => string(v, 'header'));
          for (const row of block.rows) { array(row, 'cells', block.headers.length, block.headers.length); row.forEach(v => string(v, 'cell')); } break;
        case 'flow':
          validateFlow(block);
          assert(!ids.has(block.id), 'Duplicate diagram identifier'); ids.add(block.id); break;
        default: throw new Error('Unknown block kind');
      }
    }
  }
  if (data.slides !== undefined) {
    array(data.slides, 'slides', 1, 50);
    for (const slide of data.slides) {
      fields(slide, ['title','notes','elements']); string(slide.title, 'slide title', 100); string(slide.notes, 'speaker notes'); array(slide.elements, 'elements');
      for (const element of slide.elements) validateElement(element);
    }
  }
  return data;
}

function validateFlow(flow) {
  fields(flow, ['kind','id','title','description','caption','paths']);
  assert.equal(flow.kind, 'flow'); id(flow.id);
  for (const key of ['title','description','caption']) string(flow[key], key);
  array(flow.paths, 'paths', 1, 3);
  for (const route of flow.paths) {
    fields(route, ['title','nodes','response','proof']); string(route.title, 'path title');
    if (route.proof !== undefined) assert.equal(typeof route.proof, 'boolean');
    array(route.nodes, 'nodes', 2, 4);
    for (const node of [...route.nodes, ...(route.response !== undefined ? [route.response] : [])]) {
      fields(node, ['label','detail']);
      for (const key of ['label','detail']) {
        string(node[key], 'node '+key, 64);
        assert(node[key].split('\n').length <= 2 && node[key].split('\n').every(line => line.length <= 30), 'Node copy must fit two lines of 30 characters');
      }
    }
  }
}

function validateElement(e) {
  const definitions = {
    text: ['value','x','y','w','h','size','color','bold'],
    row: ['heading','body','y'], box: ['label','x','y','w','h','color'], arrow: ['x','y','w','color'],
  };
  assert(Object.hasOwn(definitions, e.kind), 'Unknown slide element'); fields(e, ['kind', ...definitions[e.kind]]);
  for (const key of definitions[e.kind]) {
    const v = e[key];
    if (v === undefined && ['size','color','bold'].includes(key)) continue;
    if (['value','heading','body','label'].includes(key)) string(v, key);
    else if (key === 'color') assert(Object.values(colors).includes(v), 'Unknown palette color');
    else if (key === 'bold') assert.equal(typeof v, 'boolean');
    else assert(Number.isFinite(v) && v >= 0 && v <= 1280, 'Invalid geometry');
  }
  const { x=72, y, w=1136, h=e.kind === 'row' ? 100 : 20 } = e;
  assert(w > 0 && h > 0 && x+w <= 1280 && y+h <= 720, 'Element outside slide');
  if (e.kind === 'box') assert(w > 32 && h > 41, 'Box has no room for its label');
  if (e.kind === 'text') assert((e.size ?? 30) >= 17 && (e.size ?? 30) <= 76, 'Invalid text size');
}

export function renderFlow(flow) {
  // Also validate direct library calls, not just the complete-document renderer.
  validateFlow(flow);
  let y = 0;
  const lines = (text,x,top,css) => text.split('\n').map((line,i) => `<text class="${css}" x="${x}" y="${top+i*22}">${escape(line)}</text>`).join('');
  const content = flow.paths.map((route, index) => {
    const color = route.proof ? 'var(--accent)' : 'var(--teal)';
    const marker = `diagram-${flow.id}-arrow-${index}`;
    const width = (1070-(route.nodes.length-1)*44)/route.nodes.length;
    const node = (n,x,top) => `<rect class="node" x="${x}" y="${top}" width="${width}" height="120" rx="5"/>${lines(n.label,x+14,top+30,'label')}${lines(n.detail,x+14,top+83,'small')}`;
    let result = `<defs><marker id="${marker}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10Z" fill="${color}"/></marker></defs>${lines(route.title,15,y+28,'heading')}`;
    route.nodes.forEach((n,i) => {
      const x=15+i*(width+44); result += node(n,x,y+55);
      if (i) result += `<path fill="none" stroke="${color}" stroke-width="2.5" marker-end="url(#${marker})" d="M${x-44} ${y+115}H${x-5}"/>`;
    });
    if (route.response) {
      result += node(route.response,15,y+210);
      result += `<path fill="none" stroke="${color}" stroke-width="2.5" marker-end="url(#${marker})" d="M${1085-width/2} ${y+175}V${y+270}H${width+20}"/>`;
      y += 155;
    }
    y += 205; return result;
  }).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1100 ${y}" role="img" aria-labelledby="diagram-${flow.id}-title diagram-${flow.id}-desc"><title id="diagram-${flow.id}-title">${escape(flow.title)}</title><desc id="diagram-${flow.id}-desc">${escape(flow.description)}</desc><style>${diagramCSS}</style>${content}</svg>`;
}

const diagramCSS = `svg{--ink:#172b35;--muted:#465d65;--line:#95aaa9;--accent:#a94917;--teal:#08786f;--panel:#e7eeea;background:#f8f6f0}svg text{fill:var(--ink);font-family:system-ui,sans-serif}.node{fill:var(--panel);stroke:var(--line);stroke-width:1.5}.label{font-size:17px}.small{font-size:14px;fill:var(--muted)}.heading{font-size:22px;font-weight:650}@media(prefers-color-scheme:dark){svg{--ink:#f8f6f0;--muted:#b7c8ca;--line:#527077;--accent:#ffae78;--teal:#71d4c1;--panel:#193b46;background:#10242e}}`;
const css = `:root{--bg:#f8f6f0;--ink:#172b35;--muted:#465d65;--line:#95aaa9;--accent:#a94917;--teal:#08786f;color-scheme:light}@media(prefers-color-scheme:dark){:root{--bg:#10242e;--ink:#f8f6f0;--muted:#b7c8ca;--line:#527077;--accent:#ffae78;--teal:#71d4c1;color-scheme:dark}}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:18px/1.6 Georgia,serif;overflow-wrap:anywhere}main{max-width:1180px;margin:auto;padding:60px 36px 90px}header{padding:25px 0 65px;border-bottom:2px solid var(--ink)}.eyebrow{font:700 14px/1.4 system-ui,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}h1{font-size:clamp(40px,6vw,76px);line-height:1.08;max-width:900px;font-weight:500;margin:24px 0}h2{font-size:34px;line-height:1.2;font-weight:500}.lead{font-size:24px;max-width:800px}.note,figcaption{font:16px/1.55 system-ui,sans-serif;color:var(--muted)}section{padding:35px 0;border-bottom:1px solid var(--line)}a,summary{color:var(--teal)}a:focus-visible,summary:focus-visible,.diagram:focus-visible,.table-scroll:focus-visible{outline:3px solid var(--accent);outline-offset:5px}nav{font:16px/2 system-ui,sans-serif;display:flex;gap:26px;flex-wrap:wrap;margin-top:28px}figure{margin:28px 0}.diagram,.table-scroll{overflow:auto;padding:12px 0}svg{display:block;width:100%;min-width:720px;height:auto}table{border-collapse:collapse;width:100%;min-width:640px;font:16px/1.55 system-ui,sans-serif}th,td{text-align:left;vertical-align:top;padding:16px 15px 16px 0;border-bottom:1px solid var(--line)}th{color:var(--teal)}ol{padding-left:28px}li{padding:10px 0}summary{cursor:pointer}.boundary{border-left:4px solid var(--accent);padding-left:24px;max-width:860px}footer{padding-top:40px;font:16px/1.6 system-ui,sans-serif}@media(max-width:600px){main{padding:30px 20px}header{padding-bottom:35px}.lead{font-size:21px}h2{font-size:29px}nav{gap:16px}}`;

export function renderBoard(data) {
  validateReview(data);
  const block = b => {
    switch (b.kind) {
      case 'paragraph': return `<p>${copy(b.text)}</p>`;
      case 'callout': return `<p class="boundary">${copy(b.text)}</p>`;
      case 'details': return `<details><summary>${copy(b.summary)}</summary><p>${copy(b.text)}</p></details>`;
      case 'list': return `<ol>${b.items.map(i => `<li><strong>${copy(i.label)}</strong> ${copy(i.text)}</li>`).join('')}</ol>`;
      case 'table': return `<div class="table-scroll" tabindex="0" role="region" aria-label="${escape(b.caption)}"><table><caption>${copy(b.caption)}</caption><thead><tr>${b.headers.map(h => `<th scope="col">${copy(h)}</th>`).join('')}</tr></thead><tbody>${b.rows.map(r => `<tr>${r.map(c => `<td>${copy(c)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
      case 'flow': return `<figure><div class="diagram" tabindex="0" role="region" aria-label="${escape(b.title)}">${renderFlow(b)}</div><figcaption>${copy(b.caption)} ${copy(b.description)}</figcaption></figure>`;
    }
  };
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"><meta name="color-scheme" content="light dark"><title>${escape(data.title)}</title><style>${css}</style></head><body>
<main><header><p class="eyebrow">Retrospective design review / ${copy(data.date)}</p><h1>${copy(data.headline)}</h1><p class="lead">${copy(data.summary)}</p><p class="note">${copy(data.notice)}</p><nav aria-label="Review sections">${data.sections.map(s=>`<a href="#section-${s.id}">${copy(s.label)}</a>`).join('')}</nav></header>
${data.sections.map(s => `<section id="section-${s.id}"><h2>${copy(s.title)}</h2>${s.blocks.map(block).join('\n')}</section>`).join('\n')}
<footer>${copy(data.footer)}</footer></main></body></html>\n`;
}

// The four existing slide primitives keep source geometry and editable shapes.
export function createDeck(data, Presentation, font) {
  validateReview(data); assert(data.slides, 'Review has no slides');
  const deck = Presentation.create({ slideSize:{width:1280,height:720} });
  function text(s,value,x,y,w,h,size=30,color=colors.ink,bold=false) {
    const shape=s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0}});
    shape.text=value; shape.text.style={typeface:font,fontSize:size,color,bold,autoFit:'none'};
  }
  data.slides.forEach((spec,i) => {
    const s=deck.slides.add(); s.background.fill=colors.bg;
    text(s,spec.title,72,56,1136,100,46,colors.ink,true);
    text(s,String(i+1).padStart(2,'0'),1140,657,64,30,18,colors.muted);
    s.speakerNotes.textFrame.setText(spec.notes);
    for (const e of spec.elements) {
      if(e.kind==='text') text(s,e.value,e.x,e.y,e.w,e.h,e.size,e.color,e.bold);
      else if(e.kind==='row') { text(s,e.heading,72,e.y,330,62,29,colors.teal,true); text(s,e.body,422,e.y,775,100,28); }
      else if(e.kind==='box') { s.shapes.add({geometry:'rect',position:{left:e.x,top:e.y,width:e.w,height:e.h},fill:e.color??colors.panel,line:{fill:colors.teal,width:1}}); text(s,e.label,e.x+16,e.y+19,e.w-32,e.h-22,24); }
      else s.shapes.add({geometry:'rightArrow',position:{left:e.x,top:e.y,width:e.w,height:20},fill:e.color??colors.teal,line:{fill:'none',width:0}});
    }
  });
  return deck;
}
