#!/usr/bin/env python3
"""Read-only inventory for selecting a Chaanz local PR-review stack."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"error": str(error)}
    if result.returncode:
        return {"error": (result.stderr or result.stdout).strip(), "exit_code": result.returncode}
    return result.stdout.strip()


def inventory(workspace):
    if not workspace.is_dir():
        raise ValueError(f"Workspace does not exist: {workspace}")
    usage = shutil.disk_usage(workspace)
    result = {
        "workspace": str(workspace),
        "free_gib": round(usage.free / 1024**3, 2),
        "selected_sources": [],
        "repositories": {},
    }
    manifest_path = workspace / "booking-local" / "stack.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if not isinstance(manifest, dict):
            raise ValueError(f"Expected an object in {manifest_path}")
        for component, entry in manifest.items():
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
                raise ValueError(f"Missing source path for {component} in {manifest_path}")
            path = (workspace / entry["path"]).resolve()
            head = command(["git", "-C", str(path), "rev-parse", "HEAD"])
            result["selected_sources"].append({
                "component": component,
                "path": str(path),
                "pr": entry.get("pr"),
                "manifest_sha": entry.get("commit"),
                "actual_head": head,
                "manifest_matches_head": isinstance(head, str) and head == entry.get("commit"),
                "status": command(["git", "-C", str(path), "status", "--short"]),
            })
    else:
        result["manifest"] = f"Not found: {manifest_path}; discover the current runner before launch."
    for name in ("portal", "services", "app"):
        path = workspace / name
        if path.is_dir():
            result["repositories"][name] = command(["git", "-C", str(path), "worktree", "list", "--porcelain"])
    result["containers"] = command(["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"])
    result["note"] = "Local inventory only: read live PR heads and runner ownership separately. No sources or runtime state were changed."
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        result = inventory(args.workspace.resolve())
    except (ValueError, OSError) as error:
        parser.exit(1, f"Inventory failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

