// Incrementally summarize verified Archive spectra for the static Signals graph.
const fs = require("node:fs/promises");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { spectra } = require("../assets/field-evidence.js");

function summarize(text) {
  const groups = new Map();
  for (const {range, average} of spectra(text)) {
    const key = JSON.stringify([range, average.length]);
    if (!groups.has(key)) groups.set(key, {range, sums: new Float64Array(average.length), counts: new Uint32Array(average.length)});
    const group = groups.get(key);
    average.forEach((db,i) => { if (Number.isFinite(db)) { group.sums[i] += db; group.counts[i]++; } });
  }
  return [...groups.values()].map(({range,sums,counts}) => ({
    range, db: Array.from(sums,(value,i) => counts[i] ? Number((value/counts[i]).toFixed(1)) : null)
  }));
}

async function run() {
  const catalog = JSON.parse(await fs.readFile("data/catalog.json","utf8"));
  const output = "assets/field-rf-profiles.json";
  const previous = await fs.readFile(output,"utf8").then(JSON.parse).catch(error => { if(error.code==="ENOENT") return {}; throw error; });
  const next = {};
  for (const observation of catalog.fieldObservations.observations) for (const bundle of observation.evidence) {
    const asset = bundle.assets.find(a => a.name==="rf.jsonl");
    if (!asset || next[asset.sha256]) continue;
    if (previous[asset.sha256]) { next[asset.sha256]=previous[asset.sha256]; continue; }
    const url = new URL(asset.url);
    if (url.origin !== "https://archive.org" || !/^\/download\/[\w.-]+\/rf\.jsonl$/.test(url.pathname)) throw Error("Unexpected RF archive URL");
    const matches = bytes => bytes.length===asset.bytes && createHash("sha256").update(bytes).digest("hex")===asset.sha256;
    let bytes;
    if (process.argv[2]) {
      const dir = path.join(process.argv[2],url.pathname.split("/")[2]);
      for (const version of await fs.readdir(dir).catch(()=>[])) {
        const file = await fs.readFile(path.join(dir,version,"rf.jsonl")).catch(()=>null);
        if (file && matches(file)) { bytes=file; break; }
      }
    }
    if (!bytes) {
      const response = await fetch(url,{signal:AbortSignal.timeout(90000)});
      if (!response.ok) throw Error(url+" returned "+response.status);
      bytes=Buffer.from(await response.arrayBuffer());
      if (!matches(bytes)) throw Error("RF checksum mismatch for "+url);
    }
    next[asset.sha256]=summarize(bytes.toString("utf8"));
  }
  await fs.writeFile(output,JSON.stringify(next)+"\n");
}
run().catch(error=>{console.error(error);process.exitCode=1;});
