# Local review reference runtime

This Linux/Highfield reference profile bundles a loopback API gateway, captured-mail inbox, runner, synthetic booking fixtures and verification tools. Adapt it for the PR being reviewed. It does not include SDKs, dependencies, databases, captured mail, signing keys or credentials.

## Setup

Read the skill and runtime reference first. Select source worktrees and full commit SHAs from the live PRs, then initialize a workspace runtime with `scripts/init_runtime.py --workspace /path/to/workspace --manifest /path/to/selected-stack.json`. Existing runtime directories are preserved.

The full runner expects compatible app/portal/services checkouts, their local development configuration, PostgreSQL/S3Mock containers, and installed Go/Node/Flutter/Android toolchains. It does not fetch or change source branches. For browser-only reviews, narrow the launch scope before preparing the profile; the full prepare/start flow includes Android.

Supply credentials through local configuration, never this repository:

- `CHAANZ_LOCAL_DATABASE_URL`: connection URL to the selected isolated database on loopback. Its database name must match the runner and fixture guard.
- `CHAANZ_LOCAL_S3_ACCESS_KEY_ID` and `CHAANZ_LOCAL_S3_SECRET_ACCESS_KEY`: local storage credentials.
- `CHAANZ_LOCAL_MEDIA_ACCESS_TOKEN`: local media-service credential.
- `CHAANZ_LOCAL_ANDROID_KEY_PROPERTIES`: path to local signing properties if the Android checkout does not already have them.
- `CHAANZ_LOCAL_PORTAL_PASSWORD`: local fixture-account password used by `verify.py`.

Auth key material and Admin Basic Auth configuration are read from the selected service checkout's local development configuration. Verify compatible local keys across services. Do not use production credentials.

## Operate

Run `python3 booking-local/booking.py --help` for actions. Confirm current pins, override records, process ownership, schema and port availability before prepare/start. Resume or reuse compatible components; stop/rebuild only components that change. Existing adaptations are not overwritten automatically.

The inbox is served on loopback port 8090. Point local mail delivery to `/send`; read messages through `/` or `/messages`. The gateway uses port 8082; the portal uses localhost port 3000. Confirm current paths and CORS when adapting these defaults.

Generated state, captured mail, backups, binaries and caches stay in the workspace runtime. The synthetic booking fixture targets only its explicitly guarded review database and reshapes that dataset. It is not appropriate for a shared or production database. The verifier and applicant seeder are booking-specific; adapt verification for unrelated PRs.

For Android, reuse the SDK/AVD and replace-install/attach workflow; preserve app data. Do not run concurrent IDE and runner attach sessions or uninstall the app as an automatic install fallback.

