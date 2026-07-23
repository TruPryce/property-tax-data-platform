#!/usr/bin/env python3
"""Temporary, safe Bubblewrap executable-visibility diagnostic.

Prints only bounded, non-sensitive facts required to diagnose why sandboxed Python commands
fail on CI: ``shutil.which`` results, resolved symlink targets, whether each hop is under an
approved mounted root, the sandbox PATH, and the bounded Bubblewrap stderr/exit code for one
probe. It never prints environment values, credentials, or file contents. This script is
intended to be removed once the executable-path defect is fixed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

_APPROVED = ("/usr", "/usr/local", "/bin", "/lib", "/lib64", "/opt", "/etc")


def _classify(path: str) -> str | None:
    try:
        resolved = Path(path).resolve()
    except OSError:
        return None
    for root in (*_APPROVED, "/home", os.environ.get("RUNNER_TEMP", "/runner-temp")):
        try:
            if resolved == Path(root) or resolved.is_relative_to(root):
                return root
        except (OSError, ValueError):
            continue
    return "OTHER"


def main() -> int:
    which = shutil.which("python3")
    print(f"which(python3)={which}")
    if which is not None:
        print(f"resolve(python3)={Path(which).resolve()}")
        hop = which
        seen: set[str] = set()
        while hop and hop not in seen:
            seen.add(hop)
            kind = "link" if os.path.islink(hop) else "file"
            print(f"  hop[{kind}]={hop} approved_root={_classify(hop)}")
            if os.path.islink(hop):
                target = os.readlink(hop)
                hop = (
                    target if os.path.isabs(target) else os.path.join(os.path.dirname(hop), target)
                )
            else:
                break
    for name in ("python3", "python3.12", "find", "make"):
        found = shutil.which(name)
        root = _classify(found) if found else None
        print(f"which({name})={found} approved_root={root}")

    sandbox = shutil.which("bwrap")
    print(f"which(bwrap)={sandbox}")
    if sandbox is None or which is None:
        return 0
    workspace = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "cf-diag-ws"
    workspace.mkdir(parents=True, exist_ok=True)
    argv = [sandbox, "--die-with-parent", "--unshare-net", "--new-session", "--clearenv"]
    for root in _APPROVED:
        if Path(root).exists():
            argv += ["--ro-bind", root, root]
    argv += [
        "--tmpfs",
        "/home",
        "--tmpfs",
        "/root",
        "--tmpfs",
        "/run",
        "--tmpfs",
        "/var",
        "--tmpfs",
        "/tmp",
        "--dev",
        "/dev",
        "--proc",
        "/proc",
        "--dir",
        "/workspace",
        "--bind",
        str(workspace),
        "/workspace",
        "--setenv",
        "PATH",
        os.environ.get("PATH", ""),
        "--chdir",
        "/workspace",
    ]
    resolved = str(Path(which).resolve())
    for label, exe in (("bare", "python3"), ("resolved", resolved)):
        probe = subprocess.run([*argv, "--", exe, "-c", "print(1)"], capture_output=True, text=True)
        print(
            f"probe[{label}] exe={exe} exit={probe.returncode} "
            f"stderr={probe.stderr.strip()[:200]!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
