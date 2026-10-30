import fs from "node:fs"; import os from "node:os";
const t = os.tmpdir();
console.log("node os.tmpdir():", t);
try { const p = t + "\\aiedu_node_probe.bin"; fs.writeFileSync(p, "x"); fs.unlinkSync(p); console.log("node write TEMP: OK"); }
catch(e){ console.log("node write TEMP: FAIL", e.code, e.message); }
