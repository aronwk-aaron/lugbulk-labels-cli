// Regenerates tests/fixtures/packing_golden.json from the web app's
// static/js/packing.js, the reference the CLI's packing.py must match:
//   node tools/packing_golden.mjs ../lugbulk-labels-web/static/js/packing.js
// Instances are random but seeded (invented data: sizes and part ids only).
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const packing = await import(pathToFileURL(resolve(process.argv[2])).href);
let seed = 20260930;
const rand = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
const int = (lo, hi) => lo + Math.floor(rand() * (hi - lo + 1));
const big = { timeBoxMs: 60000 };

const sizes = [];
for (let n = 0; n < 300; ++n) {
  const C = [4, 10, 14, 20, 30][int(0, 4)];
  const m = int(1, n < 250 ? 12 : 40);
  const s = Array.from({ length: m }, () => int(1, C));
  sizes.push({ C, sizes: s, out: packing.packSizes(s, C, big) });
}
const records = [];
for (let n = 0; n < 120; ++n) {
  const per = [2, 10, 14, 30][int(0, 3)];
  const parts = int(1, 25);
  const recs = [];
  for (let p = 0; p < parts; ++p) {
    const k = int(1, Math.max(2, Math.floor(per * (n % 5 === 0 ? 2.5 : 0.9))));
    for (let j = 0; j < k; ++j) recs.push({ element_id: String(4000000 + p) });
  }
  const out = packing.packRecords(recs, per, big);
  records.push({ per, ids: recs.map((r) => r.element_id), out,
                 flow: packing.flowSummary(recs, per),
                 split: packing.splitParts(packing.slotsOf(recs, out.layout), per) });
}
writeFileSync(new URL('../tests/fixtures/packing_golden.json', import.meta.url),
              JSON.stringify({ sizes, records }));
console.log('wrote', sizes.length, 'size cases and', records.length, 'record cases');
