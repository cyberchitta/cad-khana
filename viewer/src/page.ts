// The khana viewer page: three-cad-viewer over the shapes.json beside it.
// page.json beside it says where the assembly was declared (its `origin`).
//
// In Shala the page is driven two ways, and neither by hand:
// - Pointing. A pick posts {shala: 1, select} anchored at the origin's line,
//   with the part and the view as `state`, and the page declares the origin's
//   file in `shows`. So a pick is the owner's selection, and a
//   {shala: 1, reveal} carrying that state puts the part and the view back.
//   Only the owner's own pick is posted: a part a command or a reveal
//   selects is not what the owner selected.
// - The `khana viewer` commands (cad_khana/drive.py), whose bodies arrive
//   wrapped as {shala: 1, tell: {id, body}} and are answered with
//   {shala: 1, told: {id, ok, message?, result?}}.
//
// A body is {khana: PROTOCOL} and exactly one of
//   show: {part?, view?}            select a part, set any of the view
//   set:  {tree?, info?, toolbar?}  show or hide the page's own panes
//   get:  [parts|picked|view|frame] ask what the page holds
// One the page cannot do in full changes nothing. Every answer's `result`
// names the origin's target. A body with another protocol number is refused:
// the command and the page were built apart.
//
// `part` is the dotted tree path `khana check` names the part by. A `view`
// is what decides the picture: the camera, the toolbar's toggles, and which
// parts are hidden. A `show` may give any subset of it, and `direction` in
// place of a camera.
//
// A host other than Shala that frames the page posts the same bodies bare,
// hears {khana, done: {ok, message?, result?}}, {khana, ready: {parts}} once
// and {khana, pick: {part, view}} for each pick.
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
interface Origin {
  target: string;
  path: string | null;
  anchor: string | null;
}
interface Reveal {
  state: Show | null;
}
type Change = { lastPick?: { new: PickInfo | null } };

const PROTOCOL = 2; // cad_khana/drive.py carries the same number
const STATE_LIMIT = 32000; // Shala takes a selection's state up to 32 KB
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
const tell = (message: object): void => host?.postMessage({ khana: PROTOCOL, ...message }, "*");
const shala = (message: object): void => host?.postMessage({ shala: 1, ...message }, "*");

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
const early = (): Done => ({ ok: false, message: "the assembly has not drawn yet; send it again" });
let handle: Handle = early;
let reveal: (asked: Reveal) => Done = early;
window.addEventListener("message", (event: MessageEvent) => {
  if (event.source !== host) return;
  const sent: { tell?: { id: unknown; body: unknown }; reveal?: Reveal } = event.data?.shala === 1 ? event.data : {};
  if (sent.tell) return shala({ told: { id: sent.tell.id, ...handle(sent.tell.body) } });
  if (sent.reveal) return shala({ revealed: reveal(sent.reveal) });
  if (typeof event.data?.khana === "number") tell({ done: handle(event.data) });
});

const bytes = (value: unknown): number => new TextEncoder().encode(JSON.stringify(value)).length;
const unknownOrigin: Origin = { target: "", path: null, anchor: null };

async function main(): Promise<void> {
  const shapes = (await (await fetch("./shapes.json")).json()) as Shapes;
  const origin = (await fetch("./page.json").then((found) => (found.ok ? found.json() : unknownOrigin), () => unknownOrigin)) as Origin;
  const root = shapes.id;
  // "/assembly/unit/cube" <-> "unit.cube"
  const dotted = (id: string): string => id.slice(root.length + 1).replaceAll("/", ".");
  const slashed = (part: string): string => `${root}/${part.replaceAll(".", "/")}`;
  const parts = leaves(shapes).map(dotted);

  let picked: string | null = null;
  let forHost = false; // a part being selected for a host, not by the owner
  const onChange = (change: Change): void => {
    const pick = change.lastPick?.new;
    if (!pick) return;
    picked = dotted(`${pick.path}/${pick.name}`);
    say(picked);
    tell({ pick: { part: picked, view: view() } });
    if (!forHost) point(picked);
  };

  // A pick as the owner's selection in Shala. A hidden list too long for
  // the state is left out of it, and the label says so.
  const point = (part: string): void => {
    if (origin.path === null || origin.anchor === null) return;
    const whole = { part, view: view() };
    const { hidden, ...rest } = whole.view;
    const fits = bytes(whole) < STATE_LIMIT;
    shala({
      select: {
        path: origin.path,
        anchor: origin.anchor,
        label: fits ? part : `${part} (${hidden?.length} hidden parts not in state)`,
        state: fits ? whole : { part, view: rest },
      },
    });
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
      forHost = true;
      try {
        viewer.handlePick(id.slice(0, cut), id.slice(cut + 1), false, false, false, null);
      } finally {
        forHost = false;
      }
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

  const does = (asked: { show?: Show; set?: Partial<Frame>; get?: unknown }): Done => {
    const verbs = Object.keys(asked).filter((key) => key !== "khana");
    const [verb] = verbs;
    if (verbs.length !== 1) return { ok: false, message: `one of show, set, get; got ${verbs.join(", ") || "none"}` };
    if (verb === "show" && asked.show) return show(asked.show);
    if (verb === "set" && asked.set) return set(asked.set);
    if (verb === "get") return get(asked.get);
    return { ok: false, message: `one of show, set, get; got ${verb}` };
  };

  handle = (body) => {
    const asked = body as { khana?: unknown; show?: Show; set?: Partial<Frame>; get?: unknown } | null;
    if (asked?.khana !== PROTOCOL)
      return { ok: false, message: `this page takes khana: ${PROTOCOL} and was sent ${JSON.stringify(asked?.khana)}; the page and the khana command were built apart, so run \`khana view\` again to rewrite the page` };
    const done = does(asked);
    return done.ok ? { ...done, result: { target: origin.target, ...done.result } } : done;
  };

  // A selection's state put back: the part and whatever of the view it carried.
  reveal = ({ state }) => {
    if (state === null) return { ok: true, message: `${origin.target}: ${parts.length} parts; no state to put back` };
    const done = show(state);
    if (!done.ok) return done;
    const put = [...(state.part === undefined ? [] : [`part ${state.part}`]), ...Object.keys(state.view ?? {})];
    return { ok: true, message: `${origin.target}: put back ${put.join(", ") || "nothing"}` };
  };

  say(`${parts.length} parts · three-cad-viewer ${version} · double-click a part to name it`);
  tell({ ready: { parts } });
  if (origin.path !== null) shala({ shows: [origin.path] });
  Object.assign(window, { khana: { viewer, parts, view, handle } });
}

main().catch((error: unknown) => {
  handle = () => ({ ok: false, message: `the page failed to load its assembly: ${error}` });
  say(`failed: ${error}`);
});
