# The viewer page, open beside the owner

`khana view <target>` writes the assembly as a web page (`cli.md` says
where). When the owner has that page open in a host, you and they can
point at the same part. You cannot see the page. Everything below is
how you ask it, and what it cannot tell you.

**The commands need a host that carries them to the page. Today that
host is Shala**, the app the owner keeps beside the editor. A page
opened from a plain file server shows the assembly and takes no
commands. The last section is everything that is Shala's; the rest
holds for any host.

## Ask the page, or change it: `khana viewer`

Run these from inside the project's repository. Each prints `page:`
and the target the open page was written from, with the time its files
were written, then its answer. **Read that line.** If it is not the
target you mean, or the build is older than your last change, run
`khana view` again and ask the owner to reload.

```
khana viewer parts                       # the page's parts, one dotted path a line
khana viewer state                       # JSON: picked, view (camera, toggles, hidden), frame (panes)
khana viewer show f2.baskets.basket_315_12        # select a part
khana viewer show --direction top                 # iso, front, rear, left, right, top, bottom
khana viewer show --only f2.baskets               # hide everything else
khana viewer show --hide frame --hide f1          # hide these, show the rest
khana viewer show --all                           # hide nothing
khana viewer show --transparent --perspective     # or --opaque, --ortho, --[no-]black-edges, --[no-]axes
khana viewer show f2.rail --only f2 --direction front   # any of these together
khana viewer panes --no-tree --no-info            # the page's own panes and toolbar
```

- **A part is named by its dotted tree path**, the name `khana check`
  reports. Use what the page gives you as it is in `--only`, `khana
  show --grep`, an `assert_*`.
- **`picked` in `khana viewer state` is the part the owner last
  double-clicked**, or the one you last selected. `view.camera` is
  where the page is looking from (`position`, `target`, `quaternion`,
  `zoom`): use it when the owner asks for a render or a drawing "from
  here".
- **`--only` and `--hide` take part or sub-assembly paths**: a path
  names a part or every part under a sub-assembly (`s1` never matches
  `s10`), checked against the page's own parts. Together they are
  the whole of what is hidden: a part neither one hides is shown, so a
  second `--hide` does not add to the first.
- **A command the page cannot do in full changes nothing** and exits 1
  with the reason: an unknown part, a page that is not open. Exit 2 is
  a usage error, or a host that is not running.
- **A direction frames what is shown, roughly.** It turns the view,
  aims at the parts that are not hidden and zooms to them, so isolate
  first and turn in the same command (`--only … --direction front`).
  The framing is a starting point: the owner orbits and zooms by hand
  from there. Nothing else moves the camera. Hiding, selecting and the
  toggles leave a view the owner set by hand where it is, so do not
  add a direction to a command unless turning the view is the point.
- **The owner zooms with the mouse wheel or trackpad and orbits by
  dragging**; the page has no zoom button. Its status line shows the
  picked part and the zoom (`f2.ramp · zoom 2.43`), the same number as
  `view.camera.zoom`, so the owner can read you a zoom they like.
- The camera has no option of its own here: an exact camera comes
  from the owner's pick and goes back through the host (below).
- **The toolbar is hidden unless asked for** (`khana viewer panes
  --toolbar`). Its buttons are the view toggles and preset directions
  these commands set, with the renderer's reset and fit. The owner
  does not use it: when they want the view changed, change it for them
  with a command, and do not send them to a button.

## What the page cannot know

- **Whether the owner is looking.** A command that exits 0 changed the
  page; it does not say the page is on screen.
- **A pane the owner opened or closed by hand.** `frame` in `khana
  viewer state` is what was last set by a command.
- **Who picked.** `picked` reads the same after the owner's
  double-click and after your own `show`.
- **Anything about the design.** The page shows the assembly as it was
  when `khana view` ran. It holds no claim and runs no check: a part
  that looks right there has not been checked. That is `khana check`.
- **Another target.** One project has one page open. If the owner
  wants a different assembly, write that one with `khana view` into
  the folder the host shows.

If `khana viewer` says the page takes another `khana:` number, the
page was written by another version of `khana`: run `khana view` again.

## In Shala

Shala is where the page is hosted today, and it adds the owner's
selection, which says who picked.

**The owner points at a part: `shala selection`.** A double-click on a
part makes it the owner's selection in Shala; a part you select with
`khana viewer show` does not. When they say "this part" or "this
view", run `shala selection` (the `shala` skill) and do not guess:

```
cad/m03/assembly.py:41
label: f2.baskets.basket_315_12
state: {"part":"f2.baskets.basket_315_12","view":{"camera":{…},"ortho":true,…,"hidden":[]}}
```

- **`label` is the part.**
- **The reference is the target's module, at the line that defines the
  member the page was written from**: `def build_exhibit(`, or
  `assembly = …`. It is the same line for every part on the page. It
  says which assembly the owner is looking at, not where the part is
  made; find that from the label.
- **`state`** is the part and the view as they were at the pick.
- If the label ends `(N hidden parts not in state)`, the list of
  hidden parts was too long to carry. `khana viewer state` has it.
- Picking the part that is already picked posts nothing new. The
  selection still reads that part, with the view as it was at the pick.

**Bring a selection back**, the part and the view both, camera
included:

```
shala reveal --state '<the state JSON>' cad/m03/assembly.py:41
```

The page answers with what it put back. A part that is no longer on the
page is refused, and nothing changes.

**"its app is not open in Shala"** means what it says: ask the owner to
open it. The command cannot. A page written outside a git repository
has no file to anchor to, so its picks are not selections; `khana
viewer state` still reads them.
