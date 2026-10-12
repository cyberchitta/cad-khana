# The viewer page, open in Shala

`khana view <target>` writes the assembly as a web page (`cli.md` says
where). When the owner has that page open in Shala, the app they keep
beside the editor, you and they can point at the same part. You cannot
see the page. Everything below is how you ask it, and what it cannot
tell you.

## The owner points at a part: `shala selection`

A double-click on a part makes it the owner's selection in Shala. When
they say "this part" or "this view", run `shala selection` (the `shala`
skill) and do not guess:

```
cad/m03/assembly.py:41
label: f2.baskets.basket_315_12
state: {"part":"f2.baskets.basket_315_12","view":{"camera":{…},"ortho":true,…,"hidden":[]}}
```

- **`label` is the part**, by the dotted tree path `khana check` names
  it by. Use it as it is in `--only`, `khana show --grep`, an
  `assert_*`.
- **The reference is the target's module, at the line that defines the
  member the page was written from**: `def build_exhibit(`, or
  `assembly = …`. It is the same line for every part on the page. It
  says which assembly the owner is looking at, not where the part is
  made; find that from the label.
- **`state.view.camera`** is where the owner was looking from:
  `position`, `target`, `quaternion`, `zoom`. Use it when they ask for
  a render or a drawing "from here".
- If the label ends `(N hidden parts not in state)`, the list of
  hidden parts was too long to carry. `khana viewer state` has it.
- Picking the part that is already picked posts nothing new. The
  selection still reads that part, with the view as it was at the pick.

To bring a selection back later, the part and the view both:

```
shala reveal --state '<the state JSON>' cad/m03/assembly.py:41
```

The page answers with what it put back. A part that is no longer on the
page is refused, and nothing changes.

## You show the owner something: `khana viewer`

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

- **`--only` and `--hide` take part or sub-assembly paths**, as `khana
  view` does, checked against the page's own parts. Together they are
  the whole of what is hidden: a part neither one hides is shown, so a
  second `--hide` does not add to the first.
- **A command the page cannot do in full changes nothing** and exits 1
  with the reason: an unknown part, a page that is not open. Exit 2 is
  a usage error, or Shala not running.
- **A part you select becomes the owner's selection**, as if they had
  picked it.
- The camera has no option here. A camera comes from a selection and
  goes back through `shala reveal --state`.

## What the page cannot know

- **Whether the owner is looking.** A command that exits 0 changed the
  page; it does not say the page is on screen.
- **A pane the owner opened or closed by hand.** `frame` in `khana
  viewer state` is what was last set by a command.
- **Anything about the design.** The page shows the assembly as it was
  when `khana view` ran. It holds no claim and runs no check: a part
  that looks right there has not been checked. That is `khana check`.
- **Another target.** One project has one page open. If the owner
  wants a different assembly, write that one with `khana view` into
  the folder Shala hosts.

"its app is not open in Shala" means what it says: ask the owner to
open it. The command cannot.

## Outside Shala

Any static file server shows the page (`cli.md`), and the owner can
turn it and read a part's name off the status line. The commands and
the selection need Shala. If `khana viewer` says the page takes another
`khana:` number, the page was written by another version of `khana`:
run `khana view` again.
