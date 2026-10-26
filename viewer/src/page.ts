// The khana viewer page: three-cad-viewer over the shapes.json beside it.
// page.json beside it says where the assembly was declared (its `origin`):
// the target, and the moniker that names it, khana://<project>/<target>.
//
// The page reaches its host through pair-ui's page client, which speaks to
// a framing host (Shala) over postMessage and to the pair-ui host over HTTP,
// so one build runs under either. It is driven two ways, neither by hand:
// - Pointing. The owner's own pick is the page's `picked`: the part and the
//   moniker naming it, <origin's moniker>#part=<dotted path>. A part a
//   command or a reveal selects is not what the owner picked, so it leaves
//   `picked` alone. A reveal of a moniker puts the part and the view back.
//   index.html claims the `khana` scheme, which is how Shala knows to send
//   it here.
// - The `khana viewer` commands (cad_khana/drive.py), whose bodies arrive
//   as tells.
// Every answer carries a message, which pair-ui requires.
//
// A body is {khana: PROTOCOL} and exactly one of
//   show: {part?, view?}            select a part, set any of the view
//   set:  {tree?, info?, toolbar?}  show or hide the page's own panes
//   get:  [parts|picked|view|frame] ask what the page holds; `picked`
//         is {part, moniker} or null
// One the page cannot do in full changes nothing. Every answer's `result`
// names the origin's target. A body with another protocol number is refused:
// the command and the page were built apart.
//
// `part` is the dotted tree path `khana check` names the part by. A `view`
// is what decides the picture: the camera, the toolbar's toggles, and which
// parts are hidden. A `show` may give any subset of it, and `direction` in
// place of a camera: a direction also aims at and zooms to the parts shown.
// The toolbar starts hidden.
//
// The page comes back as it was left: the view and the panes are kept in
// the browser's storage, one entry per target, and put back on load. Of a
// view kept before a rebuild, what still fits is put back and a part that is
// gone is dropped, unlike a `show`. Storage the browser refuses keeps nothing.
// Shala's WebKit keeps a frame's storage only while Shala runs, so the entry
// also goes to the host to keep, and a load that finds no entry takes the
// host's copy. Under the pair-ui host the page's origin changes with each
// run, so its copy is the only one that lasts.
//
// A host other than Shala that frames the page posts the same bodies bare,
// hears {khana, done: {ok, message?, result?}}, {khana, ready: {parts}} once
// and {khana, pick: {part, view}} for each pick.
import { connect } from "pair-ui/page";
import type { Host } from "pair-ui/page";
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
  message: string;
  result?: object;
}
type Handle = (body: unknown) => Done;
// The renderer's bounding box, as far as this page uses it: its three.js
// methods are not in the types it ships.
interface Box {
  clone(): Box;
  makeEmpty(): Box;
  isEmpty(): boolean;
  expandByObject(group: object): Box;
  max_dist_from_center(): number;
}
interface Group {
  getVisibility?: () => boolean;
}
interface Origin {
  target: string;
  moniker: string | null;
}
type Change = { lastPick?: { new: PickInfo | null }; zoom?: { new: number } };
interface Kept {
  view: View;
  frame: Frame;
}
// Whether each pane is open, as the renderer's own toggles left it.
interface Panes {
  tools_shown: boolean;
  info_shown: boolean;
}

const PROTOCOL = 2; // cad_khana/drive.py carries the same number
const TREE = 260;
const TOOLBAR = 54;
const STATUS = 22;
const NARROW = 700; // below this the tree and info panes float over the view, collapsed
const SHOWN: VisibilityState = [1, 1];
const HIDDEN: VisibilityState = [0, 0];
const SETTLE = 400; // ms a camera stays still before its view is kept
const KEEP_LIMIT = 64000; // Shala holds a kept value up to 64 KB

// The status line: what the page last had to say, then the zoom, which the
// renderer shows nowhere.
const status = document.getElementById("status") as HTMLElement;
const line = { text: "", zoom: null as number | null };
const write = (): void => {
  status.textContent = line.zoom === null ? line.text : `${line.text} · zoom ${line.zoom.toFixed(2)}`;
};
const say = (text: string): void => {
  line.text = text;
  write();
};
const host = window.parent === window ? null : window.parent;
const tell = (message: object): void => host?.postMessage({ khana: PROTOCOL, ...message }, "*");

const narrow = (): boolean => window.innerWidth < NARROW;
// The panes dock beside the view only when both show and there is room.
const floating = (frame: Frame): boolean => narrow() || !(frame.tree && frame.info);
// `bar` is the height the toolbar itself gives up when hidden: less than
// TOOLBAR, whose margins stay, and the status line sits below them.
const size = (frame: Frame, bar = TOOLBAR) => ({
  cadWidth: Math.max(window.innerWidth - (floating(frame) ? 0 : TREE + 14), 240),
  treeWidth: TREE,
  height: Math.max(window.innerHeight - STATUS - TOOLBAR + (frame.toolbar ? 0 : bar), 160),
  glass: floating(frame),
});
const leaves = (node: Shapes): string[] => (node.parts ? node.parts.flatMap(leaves) : [node.id]);
// A kept view given to the renderer before it first draws, so the page
// does not draw the default and then turn: the hidden leaves in the
// shapes, the camera and toggles as the renderer's own options.
const hiding = (node: Shapes, hidden: Set<string>): Shapes =>
  node.parts ? { ...node, parts: node.parts.map((child) => hiding(child, hidden)) } : hidden.has(node.id) ? { ...node, state: HIDDEN } : node;
const starting = ({ camera, hidden: _hidden, direction: _direction, ...toggles }: View): object => ({ ...camera, ...toggles });

// A message that comes before the assembly has drawn is answered, not dropped.
const early = (): Done => ({ ok: false, message: "the assembly has not drawn yet; send it again" });
let handle: Handle = early;
// The host pair-ui's client found, asked for at once so its kept view can
// arrive while the page loads; null when the page has none.
const paired: Promise<Host | null> = connect().catch(() => null);
window.addEventListener("message", (event: MessageEvent) => {
  if (event.source === host && typeof event.data?.khana === "number") tell({ done: handle(event.data) });
});

const bytes = (value: unknown): number => new TextEncoder().encode(JSON.stringify(value)).length;
const unknownOrigin: Origin = { target: "", moniker: null };
const PART = "#part=";

// What a view set, for an answer's message: a toggle says which way.
const said = (view: object): string[] => Object.entries(view).map(([key, value]) => (typeof value === "boolean" ? `${key} ${value ? "on" : "off"}` : key));

// The browser's storage, which a private window or a strict host may refuse.
const stored = {
  read: (key: string): string | null => {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  write: (key: string, value: string): void => {
    try {
      localStorage.setItem(key, value);
    } catch {
      // nothing is kept, and the page opens as it would have anyway
    }
  },
};

// What of a kept entry still fits the page: written by another build of
// it, or by hand, so every field is checked and anything else dropped.
const isBool = (value: unknown): value is boolean => typeof value === "boolean";
const isNumbers = (value: unknown, length: number): boolean =>
  Array.isArray(value) && value.length === length && value.every((n) => typeof n === "number" && Number.isFinite(n));
const record = (value: unknown): Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Record<string, unknown>) : {};
const fittedCamera = (raw: Record<string, unknown>): Camera => ({
  ...(isNumbers(raw.position, 3) ? { position: raw.position as Vec3 } : {}),
  ...(isNumbers(raw.quaternion, 4) ? { quaternion: raw.quaternion as Quat } : {}),
  ...(isNumbers(raw.target, 3) ? { target: raw.target as Vec3 } : {}),
  ...(typeof raw.zoom === "number" && raw.zoom > 0 ? { zoom: raw.zoom } : {}),
});
const TOGGLES = ["ortho", "transparent", "blackEdges", "axes", "axes0"] as const;
const fittedView = (raw: Record<string, unknown>, parts: string[]): View => ({
  ...(raw.camera === undefined ? {} : { camera: fittedCamera(record(raw.camera)) }),
  ...Object.fromEntries(TOGGLES.filter((key) => isBool(raw[key])).map((key) => [key, raw[key]])),
  ...(Array.isArray(raw.grid) && raw.grid.length === 3 && raw.grid.every(isBool) ? { grid: raw.grid as Grids } : {}),
  ...(Array.isArray(raw.hidden) ? { hidden: raw.hidden.filter((part): part is string => parts.includes(part)) } : {}),
});
const fittedFrame = (raw: Record<string, unknown>, frame: Frame): Frame =>
  Object.fromEntries(FRAME.map((key) => [key, isBool(raw[key]) ? raw[key] : frame[key]])) as Frame;
const parsed = (text: string | null): unknown => {
  try {
    return text === null ? null : JSON.parse(text);
  } catch {
    return null;
  }
};
const kept = (value: unknown, parts: string[], frame: Frame): Kept | null => {
  if (value === null || typeof value !== "object") return null;
  const raw = record(value);
  return { view: fittedView(record(raw.view), parts), frame: fittedFrame(record(raw.frame), frame) };
};
// Shala holds one value per project, so it names the target it was kept for.
const keptFor = (value: unknown, target: string): unknown => (record(value).target === target ? value : null);

async function main(): Promise<void> {
  const shapes = (await (await fetch("./shapes.json")).json()) as Shapes;
  const origin = (await fetch("./page.json").then(
    (found) => (found.ok ? found.json() : unknownOrigin),
    () => unknownOrigin,
  )) as Origin;
  const pairHost = await paired;
  const root = shapes.id;
  // "/assembly/unit/cube" <-> "unit.cube"
  const dotted = (id: string): string => id.slice(root.length + 1).replaceAll("/", ".");
  const slashed = (part: string): string => `${root}/${part.replaceAll(".", "/")}`;
  const parts = leaves(shapes).map(dotted);

  // The owner's own pick; a part a command or a reveal selects is not it.
  let picked: { part: string; moniker: string | null } | null = null;
  let forHost = false; // a part being selected for a host, not by the owner
  const key = `khana-view:${origin.target}`;
  let settling: ReturnType<typeof setTimeout> | undefined;
  // Whether anything changed since load: a page that missed Shala's copy
  // must not keep its default over it as it closes.
  let changed = false;
  const keep = (): void => {
    clearTimeout(settling);
    const entry = { view: view(), frame: shownFrame() };
    stored.write(key, JSON.stringify(entry));
    const whole = { target: origin.target, ...entry };
    const { hidden: _hidden, ...rest } = entry.view;
    pairHost?.keep(bytes(whole) < KEEP_LIMIT ? whole : { ...whole, view: rest });
  };
  const keepSoon = (): void => {
    changed = true;
    clearTimeout(settling);
    settling = setTimeout(keep, SETTLE);
  };
  const keepIfChanged = (): void => {
    if (changed) keep();
  };
  const onChange = (change: Change): void => {
    keepSoon();
    if (change.zoom) {
      line.zoom = change.zoom.new;
      write();
    }
    const pick = change.lastPick?.new;
    if (!pick) return;
    const part = dotted(`${pick.path}/${pick.name}`);
    say(part);
    tell({ pick: { part, view: view() } });
    if (!forHost) picked = { part, moniker: origin.moniker === null ? null : `${origin.moniker}${PART}${encodeURIComponent(part)}` };
  };

  // At phone width the panes start collapsed whatever was kept.
  const initial: Frame = { tree: !narrow(), info: !narrow(), toolbar: false };
  const local = parsed(stored.read(key));
  const before = kept(local ?? keptFor(pairHost?.kept ?? null, origin.target), parts, initial);
  let frame: Frame = before ? { ...before.frame, tree: before.frame.tree && !narrow(), info: before.frame.info && !narrow() } : initial;
  const options = { ...size(frame), theme: "browser", pinning: false, up: "Z" };
  type DisplayOptions = ConstructorParameters<typeof Display>[1];
  type ViewerOptions = ConstructorParameters<typeof Viewer>[1];
  const display = new Display(document.getElementById("cad_view") as HTMLElement, options as unknown as DisplayOptions);
  const viewer = new Viewer(display, options as unknown as ViewerOptions, onChange as never);
  const drawn = before ? hiding(shapes, new Set((before.view.hidden ?? []).map(slashed))) : shapes;
  viewer.render(drawn, {}, { up: "Z", ...(before ? starting(before.view) : {}) } as Parameters<typeof viewer.render>[2]);

  const toolbar = document.querySelector(".tcv_cad_toolbar") as HTMLElement;
  const bar = toolbar.getBoundingClientRect().height;
  const layout = (): void => {
    const { cadWidth, treeWidth, height, glass } = size(frame, bar);
    // The renderer's own `tools` switch takes the panes with the toolbar.
    toolbar.style.display = frame.toolbar ? "" : "none";
    viewer.resizeCadView(cadWidth, treeWidth, height, glass);
    if (glass) {
      viewer.showToolsPanel(frame.tree);
      viewer.showInfoPanel(frame.info);
    }
  };
  layout();
  // The first draw's own notices are not the owner's: nothing to keep yet.
  clearTimeout(settling);
  changed = false;
  let wasNarrow = narrow();
  window.addEventListener("resize", () => {
    // Crossing into phone width collapses the panes; the owner reopens them.
    if (narrow() && !wasNarrow) frame = { ...frame, tree: false, info: false };
    wasNarrow = narrow();
    layout();
  });

  // A floating pane is opened and closed by the renderer's own toggle,
  // which tells the page nothing; a docked one is as `frame` says.
  const panes = display as unknown as Panes;
  const shownFrame = (): Frame => (floating(frame) ? { ...frame, tree: panes.tools_shown, info: panes.info_shown } : frame);
  // Nor do the toolbar's toggles, so any click is kept, and so is the
  // page as it is when the host takes it away.
  document.addEventListener("click", keepSoon, true);
  window.addEventListener("pagehide", keepIfChanged);
  document.addEventListener("visibilitychange", () => document.visibilityState === "hidden" && keepIfChanged());

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

  // A turned view is aimed at the parts that are shown and zoomed to them,
  // roughly: the renderer centres on what is visible and leaves the zoom, so
  // the zoom is the whole assembly's extent over the shown parts'. Only a
  // direction does this, so a view the owner set by hand is never moved by a
  // command that did not ask to turn it.
  const frameShown = (): void => {
    const whole = viewer.bbox as unknown as Box | null;
    if (whole === null) return;
    const shown = whole.clone().makeEmpty();
    for (const group of Object.values(viewer.rendered.nestedGroup.groups) as Group[]) {
      if (group.getVisibility?.()) shown.expandByObject(group);
    }
    const extent = shown.isEmpty() ? 0 : shown.max_dist_from_center();
    if (extent === 0) return;
    viewer.centerVisibleObjects();
    viewer.setCameraZoom(whole.max_dist_from_center() / extent);
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
    if (to.direction !== undefined) {
      viewer.presetCamera(to.direction);
      frameShown();
    }
    const c = to.camera;
    if (c) viewer.setCameraLocationSettings(c.position, c.quaternion, c.target, c.zoom);
  };

  const show = (asked: Show): Done => {
    const message = refusal(asked);
    if (message !== null) return { ok: false, message };
    if (asked.view) apply(asked.view);
    const did = [...(asked.part === undefined ? [] : [`selected ${asked.part}`]), ...said(asked.view ?? {})];
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
    return { ok: true, message: did.join(", ") || "nothing to change" };
  };

  const set = (asked: Partial<Frame>): Done => {
    const known: readonly string[] = FRAME;
    const bad = Object.entries(asked).filter(([key, value]) => !known.includes(key) || typeof value !== "boolean");
    if (bad.length) return { ok: false, message: `set takes booleans for ${FRAME.join(", ")}; not ${bad.map(([key]) => key).join(", ")}` };
    frame = { ...shownFrame(), ...asked };
    layout();
    keepSoon();
    return {
      ok: true,
      message: Object.entries(asked)
        .map(([pane, on]) => `${pane} ${on ? "shown" : "hidden"}`)
        .join(", "),
    };
  };

  const get = (asked: unknown): Done => {
    const known: readonly unknown[] = GETS;
    const bad = Array.isArray(asked) ? asked.filter((key) => !known.includes(key)) : null;
    if (bad === null || bad.length) return { ok: false, message: `get takes a list from ${GETS.join(", ")}; not ${JSON.stringify(bad ?? asked)}` };
    const all = { parts, picked, view: view(), frame: shownFrame() };
    // A reading's message is empty, so the commands print only what was read.
    return { ok: true, message: "", result: Object.fromEntries((asked as (typeof GETS)[number][]).map((key) => [key, all[key]])) };
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
      return {
        ok: false,
        message: `this page takes khana: ${PROTOCOL} and was sent ${JSON.stringify(asked?.khana)}; the page and the khana command were built apart, so run \`khana view\` again to rewrite the page`,
      };
    const done = does(asked);
    return done.ok ? { ...done, result: { target: origin.target, ...done.result } } : done;
  };

  // A moniker put back: the part it names, and whatever of the view its
  // state carried. One for another target, or for a part that is gone,
  // changes nothing.
  const reveal = (moniker: string, state: unknown): Done => {
    const named = resolved(String(moniker));
    if (typeof named === "string") return { ok: false, message: named };
    const done = show({ ...named, ...(state === null ? {} : { view: state as View }) });
    if (!done.ok) return done;
    const put = [...(named.part === undefined ? [] : [`part ${named.part}`]), ...said(record(state))];
    return { ok: true, message: `${origin.target}: put back ${put.join(", ") || "nothing"}` };
  };
  // The part a moniker of this page names, or why it names none here.
  const resolved = (moniker: string): { part?: string } | string => {
    if (origin.moniker === null) return "this page was written outside a repository, so nothing names it";
    const cut = moniker.indexOf("#");
    const [base, fragment] = cut < 0 ? [moniker, ""] : [moniker.slice(0, cut), moniker.slice(cut)];
    const same = (a: string, b: string): boolean => {
      try {
        return decodeURI(a) === decodeURI(b);
      } catch {
        return false;
      }
    };
    if (!same(base, origin.moniker)) return `this page shows ${origin.moniker}; run \`khana view\` on the target ${moniker} names`;
    if (fragment === "") return {};
    if (!fragment.startsWith(PART) || fragment.length === PART.length) return `after # a moniker names a part (${PART}<dotted path>), not ${fragment}`;
    try {
      return { part: decodeURIComponent(fragment.slice(PART.length)) };
    } catch {
      return `the part in ${moniker} is not readable`;
    }
  };

  say(`${parts.length} parts · three-cad-viewer ${version} · ${before ? "the view as it was left" : "double-click a part to name it"}`);
  tell({ ready: { parts } });
  // The host holds reveals until this, and the kept view is drawn by now.
  pairHost?.start({ tell: handle, reveal });
  Object.assign(window, { khana: { viewer, parts, view, handle } });
}

main().catch(async (error: unknown) => {
  handle = () => ({ ok: false, message: `the page failed to load its assembly: ${error}` });
  say(`failed: ${error}`);
  (await paired)?.start({ tell: handle, reveal: () => handle(null) });
});
