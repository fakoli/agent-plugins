// Checks local link targets in a review package. No network access or publication.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import os from 'node:os';

export function checkPackage(root) {
  const failures = [];
  let checked = 0;
  function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.isSymbolicLink()) continue;
      const file = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(file);
      else if (/\.(md|html)$/.test(entry.name)) {
        const source = fs.readFileSync(file, 'utf8');
        const links = [...source.matchAll(/\[[^\]]*\]\(([^)]+)\)|href="([^"]+)"|src="([^"]+)"/g)];
        for (const match of links) {
          const target = (match[1] ?? match[2] ?? match[3]).split('#')[0];
          if (!target || /^[a-z][a-z\d+.-]*:/i.test(target)) continue;
          checked++;
          const resolved = path.resolve(path.dirname(file), decodeURIComponent(target));
          if (!fs.existsSync(resolved)) failures.push(`${file}: missing ${target}`);
        }
      }
    }
  }
  walk(path.resolve(root));
  return { checked, failures };
}

if (process.argv[2] === '--self-test') {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), 'feature-retro-links-'));
  try {
    fs.writeFileSync(path.join(fixture, 'exists.md'), '# Evidence\n');
    fs.writeFileSync(path.join(fixture, 'README.md'), '[valid](exists.md#evidence)\n[external](https://example.org)\n');
    assert.deepEqual(checkPackage(fixture), { checked: 1, failures: [] });
    fs.writeFileSync(path.join(fixture, 'board.html'), '<a href="missing.pptx">Deck</a>');
    assert.equal(checkPackage(fixture).failures.length, 1);
    console.log('Self-test passed: valid targets pass, missing artifact fails, external links skipped.');
  } finally {
    // Only this function's new, uniquely named temporary fixture is removed.
    fs.rmSync(fixture, { recursive: true });
  }
} else {
  if (!process.argv[2]) throw new Error('Usage: node check-package.mjs <package-directory>');
  const result = checkPackage(process.argv[2]);
  for (const failure of result.failures) console.error(failure);
  console.log(`${result.checked} local link targets checked, ${result.failures.length} missing.`);
  process.exitCode = result.failures.length ? 1 : 0;
}
