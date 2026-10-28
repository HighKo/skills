# Bundled Chaanz review runtime

The runnable source is bundled in [../assets/runtime](../assets/runtime): `booking.py`, `local_http.py`, `fixtures.sql`, `verify.py`, `seed_applicants.py`, the original runbook and runtime ignore rules. It contains no captured messages, databases, credentials, keys, original-file backups, binaries or installed dependencies.

Use `scripts/init_runtime.py` to materialize it into a workspace with an explicit selected manifest. The template's null SHAs/PRs are deliberately not runnable pins. A null PR with a real SHA represents a compatible base revision. Existing runtimes are never overwritten automatically; update an older runtime's source only after inspecting its local adaptations and ownership.

The full runner is a Linux/Highfield booking reference profile. It assumes existing service development configuration and container/toolchain layout. Its synthetic fixtures deliberately modify only the isolated guarded review database and opt its test event into the booking feature bit. Adapt these choices for another feature; do not run the booking verifier or seed against an arbitrary database. Credentials and machine-specific history are excluded from this public bundle; supply the local settings documented in the bundled runbook.

Paths and ports below describe the existing laptop setup; verify them against current files/processes before reuse.

## Source of truth

- Workspace `booking-local/README.md` (or the bundled `assets/runtime/README.md` on first setup): service layout, accounts, switching procedure, disk budgets and Android troubleshooting. Read “Preparing or reviewing another PR stack” before replacing sources.
- `booking-local/booking.py`: runner behavior and supported commands. It does not fetch PRs or switch branches automatically.
- `booking-local/stack.json`: input paths (relative to workspace), PR numbers and pinned full SHAs. Compare with actual worktree HEADs and live GitHub heads; it has previously lagged behind subsequent pushed booking commits.
- `revisions.json`: generated output, not the manifest to edit.
- `state/runtime.json`: runner-owned processes and containers; use this ownership when stopping.
- `state/overrides.json` and `originals/`: recorded local source overrides. Restoration checks hashes and refuses to overwrite additional edits.

Existing review source directories are `booking-evidence-portal`, `booking-sanitize-services`, and `booking-evidence-app`. They may currently contain a different stack than the manifest names imply. Root repositories `portal`, `services`, and `app` also have other worktrees. Inspect Git status/worktree inventories before selecting a destination.

## Reconcile a previous review first

The workspace may already contain an adapted runner and live review. Inspect its
manifest, Git status, `state/overrides.json`, `state/runtime.json`, dependency
records and health before using any command sequence. Existing state is useful:
reuse compatible services, test data, SDKs and caches. The initializer preserving
an existing directory is intentional, not a reason to delete that directory.

For an unchanged stack, verify actual sources and running code and resume. For a
compatible PR switch, change only affected sources, restore or retain overrides
as appropriate, and rebuild/restart only affected components. For an incompatible
schema, preserve the old database and create another database in the same container.

The stock `prepare` path rebuilds media/auth/platform and resolves portal/app
dependencies; stock `start` can launch Android. Use those full paths for fresh
setup when their scope fits. Do not run them automatically for a small portal
change or an already prepared compatible stack. Adapt the runner or invoke its
existing targeted restart/build functions when a narrower refresh suffices.

Before handing off, update selected pins and record actual running revisions,
build/dependency fingerprints, active override checksums, process ownership and
database choice in the runtime's existing records or `state/review.json`. A stale
manifest or a binary built before the latest source changes must be reconciled
rather than accepted because it still serves HTTP 200.

## Runtime operations

For a switch that requires stopping the existing review and restoring overrides,
these commands run from the workspace root:

```sh
python3 booking-local/booking.py status
python3 booking-local/booking.py stop
python3 booking-local/booking.py restore-overrides
```

Inspect/reconcile first if override restoration refuses. Do not throw away feature edits to satisfy an old override checksum.

For a fresh or deliberately rebuilt reference stack, after selecting sources and adapting the manifest, configuration, fixtures and services:

```sh
python3 booking-local/booking.py prepare
python3 booking-local/booking.py start
```

`start --no-app` is the existing runner's mode for leaving Flutter ownership to an IDE; it can still start an emulator. Do not assume it is a minimal browser-only mode. Inspect/adapt launch scope when Android is unnecessary.

Reuse the existing runtime without these full prepare/start steps when compatibility is established. Reconfigure and refresh only the changed components.

The runner has `restart-portal`, `restart-auth`, `restart-platform`, `reload`, `restart-app`, and `stop-app` actions. Portal source normally hot-reloads; changed environment/configuration needs a portal restart. Go changes require rebuilding/restarting the affected service. Read current command implementation before relying on it.

## Data and dependencies

The reference profile uses PostgreSQL container `chaanz-dev-db`, database `chaanz_booking_local`, S3Mock, and a local mail capture server. Other stacks can use another database in the same container. The database name and guard in `fixtures.sql` must agree with the runner; there is no automatic database reset command. Startup applies pending migrations, not schema downgrades.

`verify.py` and `seed_applicants.py` are booking-specific. The former creates synthetic verification sessions by default; `--configure-manual` deliberately changes manual scenarios. Replace/adapt verification for another feature.

The installed Flutter SDK/Android tools, existing AVD, Go toolchains, Docker images and npm/pub/build caches should be reused. Preparation currently prefers offline caches. The runner has a free-space floor and growth budget; inspect their current values. `/tmp` is memory-backed on this setup, so large temporary builds consume RAM. No broad Docker/cache pruning is part of switching a review.

## Access and common pitfalls

| Surface | Existing local address |
| --- | --- |
| Customer portal | `http://localhost:3000/en/login` |
| Separate Admin login | `http://localhost:3000/en/admin-login` |
| Admin home | `http://localhost:3000/en/admin` |
| API gateway | `http://localhost:8082` |
| Captured email/OTP inbox | `http://localhost:8090` |

Use `localhost` for the portal; development CORS is configured for that origin, not arbitrary LAN addresses. Admin and customer logins use separate sessions and privileges. Read fixture-account credentials from local auth development configuration; the public bundle contains no password defaults. Do not infer Admin access from a manager role.

A previous relative Admin redirect generated `/en/en/admin-login`. If an older PR exhibits that failure, diagnose the route and apply the smallest necessary local fix; do not bring the entire booking feature branch into an unrelated review just for that fix. Record and separate compatibility overrides from PR changes.

For Android, the existing runner uses `medium_phone` / `emulator-5554`, an x86-64 debug APK, `adb install -r -t`, and `flutter attach`. Do not uninstall the app on install failure or run simultaneous IDE and runner attach sessions. Preserve emulator/app state unless the user requests its reset.

## Run the inbox independently

For a review that only needs mail capture, use the materialized `local_http.py`:

```sh
mkdir -p /path/to/local-runtime/state
python3 /path/to/local-runtime/local_http.py 8090
```

It binds to `127.0.0.1`, receives mail JSON at `POST /send`, renders the inbox at
`GET /`, and exposes messages at `GET /messages`. Point the local services'
`LAMBDA_MAILER_URL` at `http://127.0.0.1:8090/send`. Captures live under that
runtime's `state/mail.jsonl`, not in this skill. Check port ownership before
starting a second inbox; do not displace an existing review's listener.

