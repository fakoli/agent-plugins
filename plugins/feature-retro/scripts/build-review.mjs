#!/usr/bin/env node
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { createHash } from 'node:crypto';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import { validateReview, renderBoard, renderFlow, createDeck } from './render-review.mjs';

export async function buildReview(input, output, runtimePath) {
  const source = await fs.readFile(input, 'utf8');
  const data = validateReview(JSON.parse(source));
  const board = renderBoard(data);
  let runtime;
  if (runtimePath) {
    runtime = JSON.parse(await fs.readFile(runtimePath, 'utf8'));
    for (const key of ['nodeModules','presentationSkill','python']) {
      if (!path.isAbsolute(runtime[key] ?? '')) throw new Error(`Runtime ${key} must be an absolute path`);
      await fs.access(runtime[key]);
    }
    if (!data.slides) throw new Error('Review has no slides');
  }
  // Exclusive directory creation: never replace an earlier review or follow its symlink.
  await fs.mkdir(output);
  await fs.writeFile(path.join(output,'review-board.html'), board, {flag:'wx'});
  for (const section of data.sections) for (const b of section.blocks) {
    if (b.kind === 'flow') await fs.writeFile(path.join(output,`${b.id}.svg`), renderFlow(b), {flag:'wx'});
  }
  if (runtime) await buildPresentation(data, output, runtime);
  await fs.writeFile(path.join(output,'build.json'), JSON.stringify({
    schemaVersion:1, sourceSha256:createHash('sha256').update(source).digest('hex'),
    presentation:Boolean(runtime), slides:runtime ? data.slides.length : 0,
    notice:'Generation receipt only. Content accuracy and visual review require separate checks.',
  },null,2)+'\n', {flag:'wx'});
}

async function buildPresentation(data, output, runtime) {
  // Only the explicitly selected, trusted runtime config can select local code.
  const require = createRequire(path.join(runtime.nodeModules,'feature-retro.cjs'));
  const {Presentation,PresentationFile,FileBlob} = await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
  const {resolvePresentationFont,finalizePresentation} = await import(pathToFileURL(path.join(runtime.presentationSkill,'container_tools/artifact_tool_utils.mjs')).href);
  const font=resolvePresentationFont({fontFamily:'Lato'});
  const deck=createDeck(data,Presentation,font);
  const workspace=await fs.mkdtemp(path.join(os.tmpdir(),'feature-retro-'));
  const staging=path.join(workspace,'build'); const final=path.join(workspace,'output');
  await fs.mkdir(staging); await fs.mkdir(final);
  const candidatePath=path.join(staging,'candidate.pptx'); const finalPath=path.join(final,'review.pptx');
  await (await PresentationFile.exportPptx(deck)).save(candidatePath);
  const previous=process.env.RUNTIME_NODE_MODULES;
  try {
    process.env.RUNTIME_NODE_MODULES=runtime.nodeModules;
    await finalizePresentation({workspaceDir:workspace,candidatePath,finalPath,
      pythonExecutable:runtime.python,
      integrityValidatorPath:path.join(runtime.presentationSkill,'container_tools/inspect_presentation_package_integrity.py'),
      layoutValidatorPath:path.join(runtime.presentationSkill,'container_tools/inspect_presentation_layout_geometry.py'),
      layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-heading-fit'],
      explicitTotalSlideCount:data.slides.length,
      fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,
      receiptPath:path.join(staging,'validation.json'),
    });
  } finally {
    if (previous === undefined) delete process.env.RUNTIME_NODE_MODULES;
    else process.env.RUNTIME_NODE_MODULES=previous;
  }
  const delivered=await PresentationFile.importPptx(await FileBlob.load(finalPath));
  for (let i=0;i<delivered.slides.items.length;i++) {
    const png=await delivered.export({slide:delivered.slides.items[i],format:'png',scale:1});
    await fs.writeFile(path.join(staging,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await png.arrayBuffer()));
  }
  await fs.copyFile(finalPath,path.join(output,'review.pptx'),fs.constants.COPYFILE_EXCL);
  console.log(`Presentation validation and renders: ${staging}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const {values,positionals} = parseArgs({allowPositionals:true,options:{runtime:{type:'string'}}});
    if (positionals.length !== 2) throw new Error('Usage: node build-review.mjs review.json NEW-OUTPUT-DIRECTORY [--runtime runtime.json]');
    await buildReview(positionals[0],positionals[1],values.runtime);
    console.log(`Created review artifacts in ${positionals[1]}`);
  } catch (error) {
    console.error(`Review build failed: ${error.message}. Existing output directories are never overwritten. A failed build may leave a partial new directory without build.json.`);
    process.exitCode=1;
  }
}
