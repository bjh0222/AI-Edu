export type ThemePreferences = { mode: "light" | "dark" | "system"; accent: string; readingSize: number };
export const themeDefaults: ThemePreferences = { mode: "system", accent: "#6d5dfc", readingSize: 16 };
export const themeKey = "aiedu-theme-v1";

export function readTheme(): ThemePreferences {
  try {
    const p = JSON.parse(localStorage.getItem(themeKey) || "{}");
    return {
      mode: ["light", "dark", "system"].includes(p.mode) ? p.mode : "system",
      accent: /^#[0-9a-f]{6}$/i.test(p.accent) ? p.accent : themeDefaults.accent,
      readingSize: [14, 16, 18, 20].includes(p.readingSize) ? p.readingSize : 16,
    };
  } catch { return themeDefaults; }
}

export function applyTheme(p: ThemePreferences) {
  const root = document.documentElement;
  root.dataset.theme = p.mode === "system" ? (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : p.mode;
  root.style.setProperty("--color-brand", p.accent);
  root.style.setProperty("--color-brand-dark", `color-mix(in srgb, ${p.accent} 80%, black)`);
  const rgb = p.accent.slice(1).match(/../g)!.map(v => parseInt(v, 16) / 255).map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4);
  const luminance = .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2];
  root.style.setProperty("--brand-on", luminance > .179 ? "#111827" : "#ffffff");
  root.style.setProperty("--reading-size", `${p.readingSize}px`);
}

export function saveTheme(p: ThemePreferences) {
  localStorage.setItem(themeKey, JSON.stringify(p));
  applyTheme(p);
  window.dispatchEvent(new Event("aiedu-theme"));
}

// Runs before the body is painted, preventing a light flash on dark reloads.
export const themeBootstrap = `(()=>{try{const p=JSON.parse(localStorage.getItem('${themeKey}')||'{}');const r=document.documentElement;const m=['light','dark','system'].includes(p.mode)?p.mode:'system';r.dataset.theme=m==='system'?(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light'):m;if(/^#[0-9a-f]{6}$/i.test(p.accent)){r.style.setProperty('--color-brand',p.accent);r.style.setProperty('--color-brand-dark','color-mix(in srgb, '+p.accent+' 80%, black)');const c=p.accent.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);r.style.setProperty('--brand-on',.2126*c[0]+.7152*c[1]+.0722*c[2]>.179?'#111827':'#ffffff')}r.style.setProperty('--reading-size',([14,16,18,20].includes(p.readingSize)?p.readingSize:16)+'px')}catch{}})()`;
