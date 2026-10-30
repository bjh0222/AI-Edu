import pw, { CHROME } from "./pw.mjs";
const b = await pw.chromium.launch(CHROME);
const page = await b.newPage();
await page.goto("http://127.0.0.1:3001/", { waitUntil: "domcontentloaded" });
console.log("TITLE:", await page.title());
console.log("BODY:\n" + (await page.locator("body").innerText()).slice(0, 2000));
await b.close();
