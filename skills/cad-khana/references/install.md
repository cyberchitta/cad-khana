# Installing cad-khana

Run once on a machine that doesn't yet have the `khana` CLI. The main
SKILL.md points here when `khana --version` fails.

**1. Install the tool:**

```bash
uv tool install git+https://github.com/cyberchitta/cad-khana
```

**2. Verify the install:**

```bash
khana --version
```

Report success and continue with whatever the user originally asked for.

## Updating later

To upgrade the CLI to the latest commit on `main`:

```bash
uv tool upgrade cad-khana
```

The skill files (`SKILL.md`, `references/`) don't auto-update — re-run
the `cp -r` from the README's install section to refresh them.
