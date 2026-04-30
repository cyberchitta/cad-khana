---
name: cad-khana-setup
description: Install cad-khana from GitHub. Run this once before using cad-khana. Removes itself after successful installation.
allowed-tools: [Bash]
---

# cad-khana-setup

Installs the `cad-khana` Python tool, which provides the `khana` CLI used by the cad-khana skill.

## Instructions

Run the following steps in order:

**1. Install the tool:**

```bash
uv tool install git+https://github.com/cyberchitta/cad-khana
```

**2. Verify the install:**

```bash
khana --version
```

**3. Remove this setup skill** (no longer needed):

```bash
rm -rf ~/.claude/skills/cad-khana-setup .claude/skills/cad-khana-setup
```

Report success and tell the user that cad-khana is ready to use.
