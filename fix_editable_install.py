#!/usr/bin/env python3
"""Replace the annoying .pth file with a symlink for hassle-free editable install.

Python 3.14+ on macOS skips .pth files with the UF_HIDDEN flag, which is set
on the .venv directory and propagates to files created inside it.

This script removes the .pth file and creates a symlink instead — no hidden
flags, no site.py processing order issues, no nonsense.

Usage:
    uv pip install -e .
    python fix_editable_install.py
"""
import os
import stat
from pathlib import Path

PROJECT = Path(__file__).resolve().parent
SITE_PACKAGES = PROJECT / ".venv" / "lib" / "python3.14" / "site-packages"
SOURCE = PROJECT / "src" / "lxradio"
TARGET = SITE_PACKAGES / "lxradio"

def main() -> None:
    if not SOURCE.is_dir():
        print(f"Source package not found: {SOURCE}")
        return

    if not SITE_PACKAGES.is_dir():
        print(f"Site-packages not found: {SITE_PACKAGES}")
        print("Run `uv pip install -e .` first.")
        return

    # Remove any lxradio .pth files
    removed = 0
    for pth in SITE_PACKAGES.glob("*lxradio*.pth"):
        try:
            os.chflags(pth, 0)  # clear all flags so we can remove
        except AttributeError:
            pass
        pth.unlink(missing_ok=True)
        print(f"Removed: {pth.name}")
        removed += 1

    # Remove any existing package dir/symlink
    if TARGET.is_symlink() or TARGET.exists():
        if TARGET.is_symlink():
            TARGET.unlink()
        else:
            import shutil
            shutil.rmtree(TARGET)
        print(f"Removed: {TARGET.name}")

    # Create symlink
    TARGET.symlink_to(SOURCE, target_is_directory=True)
    print(f"Created symlink: {TARGET.name} -> {SOURCE}")

    # Verify
    if TARGET.is_symlink() and TARGET.resolve() == SOURCE:
        print("✓ Symlink valid")
    else:
        print("✗ Symlink invalid — check manually")
        return

    # Test import
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-c", "from lxradio.__main__ import main; print('✓ Import OK')"],
        capture_output=True, text=True, cwd=PROJECT,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print(result.stderr.strip())

    if removed:
        print(f"\nReplaced {removed} .pth file(s) with a symlink. No more .pth nonsense.")


if __name__ == "__main__":
    main()
