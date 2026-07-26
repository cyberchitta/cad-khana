---
name: ck-notes
description: >-
  cad-khana's delta on the shared notes machinery — which `_notes/` file plays
  which role in the demand-driven loop (worklist, field-notes, slice briefs,
  two-way handoffs, adoption inventory), the bookkeeping a session owes when a
  slice closes, and the traps that have actually bitten (stale commit SHAs after
  a history rewrite, consolidating shipped `ideas.md` rows, deleting a
  field-note that still backs an open row, promoting at f×1 on a rationale the
  policy doesn't name). Invoke before updating the worklist, triaging
  field-notes, closing a shipped `ideas.md` row, or writing/closing a slice
  brief or cross-repo handoff.
---

# cad-khana working notes — the delta

Two shared skills already cover most of this and are **not** repeated here:

- **`working-notes`** — the `_notes/` symlink mechanism, why `Grep`/`Glob`
  find nothing, the `rg` forms, the leave-it-uncommitted cadence.
- **`repo-research`** — signal doctrine, the promotion policy and its two
  exemptions, dispositions, the closing-a-shipped-idea workflow, filing
  formats.

Load whichever applies; this file is only what those two don't say about
this corpus. `CLAUDE.md` §"Working notes" lists the files; §"Field-notes
promotion policy" maps a promoted fix to its code/doc surface.

## The loop these notes serve

cad-khana is demand-driven: a feature starts from an observed consumer need
and **closes only when the consumer actually converts its sites**. The notes
are the two halves of that loop.

| File | Role in the loop |
|---|---|
| `field-notes.md` | Consumer-written friction, unfiltered. The demand side's raw input. |
| `adoption-inventory.md` | The *stock* of friction already priced into the consumer's code — workaround sites mapped to the call shape they wish they could write. Each section is a feature's ready-made exercise slice. |
| `worklist.md` | **Continuing-state file.** Sequencing and status for the cad-khana side only. |
| `research/ideas.md` | Authoritative for provenance and scoring. The worklist points at it, never duplicates it. |
| `implementation-log.md` | Why each thing shipped; the durable record when a source note is deleted. |
| `sorted-studs-<slice>.md` | A one-way **slice brief**: cad-khana ships, the consumer exercises, the row closes on results. |
| `sorted-studs/<topic>.md` | A two-way **handoff**: both repos edit the same file in place. Gate block at the top, Results filled by the consumer, Close-out filled here. |

**A row is not closed when the code ships.** It is closed when the slice
brief comes back with results and the sites are converted. Write the
outcome into the `ideas.md` row, the log entry and the worklist row in the
same pass — a row that says "code shipped, slice open" for two sessions is
how the loop silently stops being demand-driven.

## Slice briefs and handoffs

- A slice brief is **spent** the moment its results land. Mark it spent at
  the top with the outcome in a paragraph, keep the original brief below
  under *"kept for the record"*, and don't move or delete the file — the
  briefs are how a later session reconstructs why a feature landed in the
  shape it did.
- A two-way handoff is closed by **filling its Close-out from this side**,
  even when the consumer already wrote "DONE" throughout. The Close-out is
  where cross-repo consequences get named: a caveat the consumer's work
  retired, a field-note that came back, a decision now gated.
- **Re-verify an inventory before trusting it.** Every handoff that carried
  a per-file inventory has had it drift between authoring and execution —
  files already fixed by an earlier item, sites the grep shape couldn't see.
  Anchor inventories to a commit and say so.

## Bookkeeping traps that have actually bitten

- **A history rewrite orphans every SHA in these notes.** 2026-07-26: the
  day's last three commits were rewritten to fix co-author trailers, and
  `944e37c` — already written into the log and into a handoff's gate block
  — stopped resolving. After any amend/rebase/filter-branch, `rg` the notes
  for the old SHAs and correct them *with a parenthetical saying they were
  rewritten*, so a reader who saw the old value isn't left doubting.
- **Don't leave `*(pending)*` / `*(this slice)*` in a log entry.** Both are
  written before the commit exists and nothing prompts you to come back.
  Fill the SHA in the same session, or the entry silently loses the link
  `git log` was supposed to provide. (Nine entries had gone stale this way.)
- **Don't consolidate several shipped `ideas.md` rows into one.** It reads
  better and defeats the table's only job: an idea whose row title no longer
  appears verbatim can be re-proposed by the next rescrape. Move each row
  separately, even when one commit shipped all of them; the shared log
  pointer is what ties them together.
- **A field-note may back more than one row.** Delete-on-promotion fires per
  *note*, not per row — check every row the note sources before deleting.
  The 2026-05-21 arc-math note sources both the shipped sampling substrate
  and the still-open union-bbox row, so it stays.
- **Say which exemption you are using when you promote at f×1** — and if
  it is neither of the two the policy names (field-note resonance with an
  existing row; the bug exception), name it as what it is: an
  **owner-discretion override**. The owner may override any threshold; the
  point of the record is that overrides stay *visible as overrides* instead
  of accreting into doctrine, so a growing pile of them is legible as
  overreach rather than as precedent. Practically: write the rationale into
  the row, label it an override, date the ratification, and never
  generalize one into a new standing rule — the next f×1 needs its own
  override, not a citation of this one. (First use: 2026-07-26, the two
  SKILL.md doc rows. If a *kind* of override recurs often enough to earn
  standing status, that belongs in the shared `repo-research` policy, not
  here.)
- **Parked ≠ waiting for a decision.** A parked note unparks on another
  occurrence, not on someone choosing. When two notes turn out to be the
  same question from different directions, that is the second occurrence —
  unpark them as one row and state the question at the level both share,
  rather than building the first shape either note suggested.

## What "update the notes" owes

When a session ends with work that changed the loop's state, the sweep is:

1. `worklist.md` — the state that changed, and the *next-session* pointer
   rewritten (a stale one is worse than none; it sends the next session at a
   slice that already closed).
2. `ideas.md` — rows moved to ✅ (row per idea, reduced columns), new rows
   for anything the slice opened, backlog sections left holding open work
   only.
3. `implementation-log.md` — one entry, newest at the top, with both-way
   provenance pointers.
4. `field-notes.md` — a triage verdict inline on each new entry; deletion
   only when every row a note backs has shipped.
5. Slice briefs and handoffs — spent / Close-out filled.
6. Anything the work *falsified* — a spec caveat the consumer's refactor
   retired, a row that named a CLI verb the surface no longer supports.

Leave it all uncommitted; the housekeeping sweep picks it up.
