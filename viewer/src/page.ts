// The khana viewer page: three-cad-viewer over the shapes.json beside it.
//
// A host that frames this page hears {khana: 1, ready: {parts}} once, then
// {khana: 1, pick: {part, view}} for each part picked. It may post
// {khana: 1, show: {part?, view?}} to put a pick or a view back, or
// {khana: 1, set: {tree?, info?, toolbar?}} to show or hide the page's own
// panes and toolbar, or {khana: 1, get: [...]} to ask what the page holds.
// Each is answered with {khana: 1, done: {ok, message?, result?}}, and one
// the page cannot do in full changes nothing. accepts.yaml beside this page
// lists the bodies with examples.
//
// `part` is the dotted tree path `khana check` names the part by. A `view`
// is what decides the picture: the camera, the toolbar's toggles, and which
// parts are hidden. A `show` may give any subset of it, and `direction` in
// place of a camera.
//
// Shala carries the same bodies wrapped: {shala: 1, tell: {id, body}} in,
// {shala: 1, told: {id, ok, message?, result?}} out.
import { Display, Viewer, version } from "three-cad-viewer";
import type { PickInfo, Shapes, VisibilityState } from "three-cad-viewer";

type Vec3 = [number, number, number];
type Quat = [number, number, number, number];
type Grids = [boolean, boolean, boolean];
const DIRECTIONS = ["iso", "front", "rear", "left", "right", "top", "bottom"] as const;
type Direction = (typeof DIRECTIONS)[number];
interface Camera {
  position?: Vec3;
  quaternion?: Quat;
  target?: Vec3;
  zoom?: number;
}
interface View {
  camera?: Camera;
  direction?: Direction;
  ortho?: boolean;
  transparent?: boolean;
  blackEdges?: boolean;
  axes?: boolean;
  axes0?: boolean;
  grid?: Grids;
  hidden?: string[];
}
interface Show {
  part?: string;
  view?: View;
}
const FRAME = ["tree", "info", "toolbar"] as const;
type Frame = Record<(typeof FRAME)[number], boolean>;
const GETS = ["parts", "picked", "view", "frame"] as const;
interface Done {
  ok: boolean;
  message?: string;
  result?: object;
}
type Handle = (body: unknown) => Done;
type Change = { lastPick?: { new: PickInfo | null } };

const TREE = 260;
const TOOLBAR = 54;
const STATUS = 22;
const NARROW = 700; // below this the tree and info panes float over the view, collapsed
const SHOWN: VisibilityState = [1, 1];
const HIDDEN: VisibilityState = [0, 0];

const status = document.getElementById("status") as HTMLElement;
const say = (text: string): void => {
  status.textContent = text;
};
const host = window.parent === window ? null : window.parent;
const tell = (message: object): void => host?.postMessage({ khana: 1, ...message }, "*");

const narrow = (): boolean => window.innerWidth < NARROW;
// The panes dock beside the view only when both show and there is room.
const floating = (frame: Frame): boolean => narrow() || !(frame.tree && frame.info);
const size = (frame: Frame) => ({
  cadWidth: Math.max(window.innerWidth - (floating(frame) ? 0 : TREE + 14), 240),
  treeWidth: TREE,
  height: Math.max(window.innerHeight - STATUS - (frame.toolbar ? TOOLBAR : 0), 160),
  glass: floating(frame),
});
const leaves = (node: Shapes): string[] => (node.parts ? node.parts.flatMap(leaves) : [node.id]);

// A message that comes before the assembly has drawn is answered, not dropped.
let handle: Handle = () => ({ ok: false, message: "the assembly has not drawn yet; send it again" });
window.addEventListener("message", (event: MessageEvent) => {
  if (event.source !== host) return;
  const told = event.data?.shala === 1 ? event.data.tell : undefined;
  if (told) return host?.postMessage({ shala: 1, told: { id: told.id, ...handle(told.body) } }, "*");
  if (event.data?.khana === 1) tell({ done: handle(event.data) });
});

async function main(): Promise<void> {
  const shapes = (await (await fetch("./shapes.json")).json()) as Shapes;
  const root = shapes.id;
  // "/assembly/unit/cube" <-> "unit.cube"
  const dotted = (id: string): string => id.slice(root.length + 1).replaceAll("/", ".");
  const slashed = (part: string): string => `${root}/${part.replaceAll(".", "/")}`;
  const parts = leaves(shapes).map(dotted);

  let picked: string | null = null;
  const onChange = (change: Change): void => {
    const pick = change.lastPick?.new;
    if (!pick) return;
    picked = dotted(`${pick.path}/${pick.name}`);
    say(picked);
    tell({ pick: { part: picked, view: view() } });
  };

  let frame: Frame = { tree: !narrow(), info: !narrow(), toolbar: true };
  const options = { ...size(frame), theme: "browser", pinning: false, up: "Z" };
  type DisplayOptions = ConstructorParameters<typeof Display>[1];
  type ViewerOptions = ConstructorParameters<typeof Viewer>[1];
  const display = new Display(document.getElementById("cad_view") as HTMLElement, options as unknown as DisplayOptions);
  const viewer = new Viewer(display, options as unknown as ViewerOptions, onChange as never);
  viewer.render(shapes, {}, { up: "Z" });

  const toolbar = document.querySelector(".tcv_cad_toolbar") as HTMLElement;
  const layout = (): void => {
    const { cadWidth, treeWidth, height, glass } = size(frame);
    // The renderer's own `tools` switch takes the panes with the toolbar.
    toolbar.style.display = frame.toolbar ? "" : "none";
    viewer.resizeCadView(cadWidth, treeWidth, height, glass);
    if (glass) {
      viewer.showToolsPanel(frame.tree);
      viewer.showInfoPanel(frame.info);
    }
  };
  layout();
  let wasNarrow = narrow();
  window.addEventListener("resize", () => {
    // Crossing into phone width collapses the panes; the owner reopens them.
    if (narrow() && !wasNarrow) frame = { ...frame, tree: false, info: false };
    wasNarrow = narrow();
    layout();
  });

  const view = (): View => {
    const states = viewer.getStates();
    return {
      camera: viewer.getCameraLocationSettings() as Camera,
      ortho: viewer.getOrtho(),
      transparent: viewer.getTransparent(),
      blackEdges: viewer.getBlackEdges(),
      axes: viewer.getAxes(),
      axes0: viewer.getAxes0(),
      grid: viewer.getGrids(),
      hidden: parts.filter((part) => {
        const state = states[slashed(part)];
        return state !== undefined && state[0] !== 1 && state[1] !== 1;
      }),
    };
  };

  // What a `show` asks for that this page cannot give, or null.
  const refusal = ({ part, view: to }: Show): string | null => {
    const unknown = [...(part === undefined ? [] : [part]), ...(to?.hidden ?? [])].filter((p) => !parts.includes(p));
    if (unknown.length) return `no part ${unknown.join(", ")}`;
    if (to?.direction !== undefined && !DIRECTIONS.includes(to.direction)) return `no direction ${to.direction}`;
    return null;
  };

  const apply = (to: View): void => {
    if (to.ortho !== undefined) viewer.setOrtho(to.ortho);
    if (to.transparent !== undefined) viewer.setTransparent(to.transparent);
    if (to.blackEdges !== undefined) viewer.setBlackEdges(to.blackEdges);
    if (to.axes !== undefined) viewer.setAxes(to.axes);
    if (to.axes0 !== undefined) viewer.setAxes0(to.axes0);
    if (to.grid !== undefined) viewer.setGrids(to.grid);
    if (to.hidden !== undefined) {
      const hidden = new Set(to.hidden);
      for (const part of parts) viewer.setState(slashed(part), hidden.has(part) ? HIDDEN : SHOWN);
    }
    if (to.direction !== undefined) viewer.presetCamera(to.direction);
    const c = to.camera;
    if (c) viewer.setCameraLocationSettings(c.position, c.quaternion, c.target, c.zoom);
  };

  const show = (asked: Show): Done => {
    const message = refusal(asked);
    if (message !== null) return { ok: false, message };
    if (asked.view) apply(asked.view);
    if (asked.part !== undefined) {
      const id = slashed(asked.part);
      const cut = id.lastIndexOf("/");
      viewer.handlePick(id.slice(0, cut), id.slice(cut + 1), false, false, false, null);
    }
    return { ok: true };
  };

  const set = (asked: Partial<Frame>): Done => {
    const known: readonly string[] = FRAME;
    const bad = Object.entries(asked).filter(([key, value]) => !known.includes(key) || typeof value !== "boolean");
    if (bad.length) return { ok: false, message: `set takes booleans for ${FRAME.join(", ")}; not ${bad.map(([key]) => key).join(", ")}` };
    frame = { ...frame, ...asked };
    layout();
    return { ok: true };
  };

  const get = (asked: unknown): Done => {
    const known: readonly unknown[] = GETS;
    const bad = Array.isArray(asked) ? asked.filter((key) => !known.includes(key)) : null;
    if (bad === null || bad.length) return { ok: false, message: `get takes a list from ${GETS.join(", ")}; not ${JSON.stringify(bad ?? asked)}` };
    const all = { parts, picked, view: view(), frame };
    return { ok: true, result: Object.fromEntries((asked as (typeof GETS)[number][]).map((key) => [key, all[key]])) };
  };

  handle = (body) => {
    const asked = body as { khana?: number; show?: Show; set?: Partial<Frame>; get?: unknown } | null;
    if (asked?.khana !== 1) return { ok: false, message: "not a khana message: no khana: 1" };
    const verbs = Object.keys(asked).filter((key) => key !== "khana");
    const [verb] = verbs;
    if (verbs.length !== 1) return { ok: false, message: `one of show, set, get; got ${verbs.join(", ") || "none"}` };
    if (verb === "show" && asked.show) return show(asked.show);
    if (verb === "set" && asked.set) return set(asked.set);
    if (verb === "get") return get(asked.get);
    return { ok: false, message: `one of show, set, get; got ${verb}` };
  };

  say(`${parts.length} parts · three-cad-viewer ${version} · double-click a part to name it`);
  tell({ ready: { parts } });
  Object.assign(window, { khana: { viewer, parts, view, handle } });
}

main().catch((error: unknown) => {
  handle = () => ({ ok: false, message: `the page failed to load its assembly: ${error}` });
  say(`failed: ${error}`);
});
