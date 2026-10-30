import { createRequire } from "node:module";
const req = createRequire(import.meta.url);
const PWDIR = "C:/Users/BJH/AppData/Local/OpenAI/Codex/runtimes/cua_node/b2c4f0c90eadfac4/bin/node_modules/playwright-core";
const pw = req(PWDIR + "/index.js");
export default pw;
export const CHROME = { headless: true, channel: "chrome" };
