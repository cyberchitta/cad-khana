// Builds the page `khana view --page` copies out: ours and the renderer in
// one script, the two stylesheets, and the renderer's licence beside them.
import { cp, mkdir, rm } from "node:fs/promises";

const out = new URL("../src/cad_khana/_page/", import.meta.url).pathname;
const renderer = new URL("./node_modules/three-cad-viewer/", import.meta.url).pathname;

await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });
const built = await Bun.build({
  entrypoints: ["src/page.ts"],
  outdir: out,
  target: "browser",
  format: "esm",
  minify: true,
});
if (!built.success) {
  for (const log of built.logs) console.error(log);
  process.exit(1);
}
await cp("src/index.html", `${out}index.html`);
await cp("src/page.css", `${out}page.css`);
await cp("src/accepts.yaml", `${out}accepts.yaml`);
await cp(`${renderer}dist/three-cad-viewer.css`, `${out}three-cad-viewer.css`);
await cp(`${renderer}LICENSE`, `${out}three-cad-viewer.LICENSE`);
