#!/usr/bin/env python3
"""Copy the bundled review profile into a workspace without overwriting a runtime."""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile

TEMPLATE = Path(__file__).resolve().parent.parent / 'assets' / 'runtime'


def initialize(workspace, directory, manifest_path):
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise ValueError(f'Workspace does not exist: {workspace}')
    destination = (workspace / directory).resolve()
    if destination == workspace or not destination.is_relative_to(workspace):
        raise ValueError('Runtime directory must be inside the workspace')
    if destination.exists():
        return f'Existing runtime preserved: {destination}. No files changed; inspect its manifest and overrides before reuse.'
    if manifest_path is None:
        raise ValueError(f'A fresh runtime requires --manifest with selected full SHAs. Example structure: {TEMPLATE / "stack.example.json"}')
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or set(manifest) != {'app', 'portal', 'services'}:
        raise ValueError('This reference profile requires app, portal and services entries; adapt its launch scope for other stacks')
    for name, entry in manifest.items():
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or not entry['path']:
            raise ValueError(f'{name}: provide a source path')
        if not isinstance(entry.get('commit'), str) or not re.fullmatch(r'[0-9a-fA-F]{40}', entry['commit']):
            raise ValueError(f'{name}: provide a pinned full commit SHA')
        if 'pr' not in entry or (entry['pr'] is not None and (type(entry['pr']) is not int or entry['pr'] < 1)):
            raise ValueError(f'{name}: pr must be a positive PR number, or null for a compatible base revision')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Build the complete directory before making it the selected runtime.
    staging = Path(tempfile.mkdtemp(prefix='.local-review-init-', dir=destination.parent))
    try:
        for source in TEMPLATE.iterdir():
            if source.is_file():
                shutil.copy2(source, staging / source.name)
        (staging / 'stack.json').write_text(json.dumps(manifest, indent=2) + '\n')
        for name in ('state', 'logs', 'bin', 'tmp'):
            (staging / name).mkdir(mode=0o700)
        staging.rename(destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return f'Created runtime: {destination}. Verify source pins and adapt the profile before prepare/start. No services started.'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--directory', default='booking-local')
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    try:
        print(initialize(args.workspace, args.directory, args.manifest))
    except (OSError, ValueError) as error:
        parser.exit(1, f'Runtime initialization failed: {error}\n')


if __name__ == '__main__':
    main()

