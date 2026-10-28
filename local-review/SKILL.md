---
name: local-review
description: Prepare, switch, run, and troubleshoot Chaanz pull-request stacks locally for hands-on browser or Android review. Use for requests to try a PR locally or replace the current review stack; ordinary code review and production deployment are separate tasks.
---

# Local PR review

Leave the requested PR running against compatible local services and representative data, with exact URLs and practical review steps. Discover the stack from the requested feature; a portal PR does not automatically require Flutter, every backend service, or the previous review's companions.

## Discover the requested stack

- Read the live PR head, base, diff, discussion and linked contracts to identify backend/app companions and required API versions. Pin full SHAs; distinguish required companion PRs from compatible base branches. Use the connected GitHub tools when available.
- In `/path/to/chaanz` (or the user's chosen workspace), inspect applicable `AGENTS.md`, selected worktrees, running review ownership and local changes. The optional read-only helper reports source pins, dirty files, disk headroom and existing containers:

  ```sh
  python3 <skill-dir>/scripts/inventory.py --workspace /path/to/chaanz
  ```

- This skill bundles the runner, loopback gateway/mail inbox, synthetic booking fixtures, verifier and applicant seeder in [assets/runtime](assets/runtime). Read [references/chaanz-runtime.md](references/chaanz-runtime.md) before using them. They are a reference profile to adapt, not a generic launcher that automatically switches PRs.
- Reuse an existing workspace runtime when suitable. For a fresh runtime, supply the chosen source paths and full SHAs in a manifest (structure: [assets/runtime/stack.example.json](assets/runtime/stack.example.json)):

  ```sh
  python3 <skill-dir>/scripts/init_runtime.py --workspace /path/to/chaanz --manifest /path/to/selected-stack.json
  ```

  The initializer copies the bundled source into workspace `booking-local/` and preserves an existing directory unchanged. Use `--directory` for a different local destination. Run the copied scripts there; keep process state, captured messages, environment configuration and build artifacts outside the installed skill. Preparation still requires source checkouts, compatible local configuration/keys, containers and installed toolchains; they are not embedded in the bundle.
- Treat manifests as claims: compare each pin with actual Git HEAD and the live PR. A later pushed commit does not update `stack.json` automatically. Decide the desired new revisions before launching anything.

## Resume, reuse, or switch an existing review

Assume another task may already have been reviewed here. Reconcile that state before selecting a launch path; the user should not have to clean up manually first.

- Discover existing runtime directories, manifests, process ownership, selected worktrees, override records, database/schema and test data. Compare actual source revisions and dirty changes with the requested stack. A folder name, recorded PID or old manifest alone is not evidence that the running code matches the requested PR.
- Choose per component, rather than rebuilding or replacing the whole stack:

  | Situation | Action |
  | --- | --- |
  | Same selected sources, compatible overrides/configuration, healthy matching processes | Resume in place; retain data and caches, then verify the requested behavior. |
  | Different PR, but a service/toolchain/database remains compatible | Reuse that component. Switch only affected sources and update their local configuration; rebuild/restart only what changed. |
  | Old source overrides are obsolete, incompatible or obstruct checkout | Stop affected processes, restore the recorded originals safely, switch sources, then apply the new PR's required overrides. Reuse compatible dependencies and caches. |
  | Schema, fixtures or source changes cannot coexist with the old review | Preserve the old review and use another database or source-only worktree; reuse the existing container/toolchains where appropriate. |

- Inspect dirty files and distinguish feature work from local runtime overrides. Keep the previous configuration/revisions recoverable. Compatible overrides can stay; verify both their current content/checksum and their applicability to the new source revision. Do not blindly replay an old patch or copy the installed skill's template over a locally adapted runner.
- When restoring overrides, use the runner's recorded originals/checks; reconcile any refusal rather than bypassing it with reset/clean. A clean baseline means the selected revision plus intentional documented local configuration, not a blanket hard reset of all repositories. Reusing or creating a source-only Git worktree is preferable to overwriting uncommitted work or cloning repositories again.
- Stop only processes whose sources/configuration/ports are changing or which are no longer needed. Keep compatible services running when safe. An IDE-owned Flutter session may need separate handling; do not kill unrelated processes or containers. If an override changes what a server serves, coordinate its restoration with stopping/restarting that server.
- A request to “clear/switch the review” does not by itself mean deleting databases, mail, emulator state or caches. Honor an explicitly requested data reset within its stated local scope. Otherwise retain the prior dataset, and use another database in the same PostgreSQL container when an unrelated stack needs isolation or has incompatible migrations. Back up data that a requested migration/reset could lose.
- Reuse installed SDKs, Docker images, AVDs and build caches. Check current free space and existing runner budgets before a large build. Start only needed services. If cached dependencies are insufficient, identify the particular missing package or tool before downloading another toolchain or whole stack. Reuse dependency directories only when their lockfile/configuration is compatible.

## Configure and launch

- Configure the selected source paths, PRs/base revisions, full SHAs, local service URLs, database/schema, storage and runtime overrides together. Compare lockfiles, build inputs and relevant environment/configuration before reusing installed dependencies or running binaries. If a running binary's source provenance is unknown, rebuild that affected service rather than treating its healthy port as proof of the right code. Keep the previous working configuration recoverable. Do not disable source-pin, override-integrity or disk checks just to make startup proceed; update their inputs to the intended stack.
- Match frontend/backend contracts, auth keys, app/platform/event identities, migrations and test-account relationships. Apply migrations only to the chosen local database; schema downgrades are not implied by checking out older code.
- Use real local authentication and authorization. A customer manager is not an Admin. Verify login routes and role-specific access before directing the user to gated controls. Read test credentials from the local runbook/fixtures; keep tokens and private environment files out of output.
- Keep mail in the local capture service. For gated functionality, explicitly enable the needed capability only on the chosen local test app/event and distinguish that from global defaults. A customer capability and a session/event configuration toggle can be separate controls.
- Use the least disruptive valid refresh: portal hot reload for ordinary source changes; server restart for environment/config changes; rebuild/restart changed Go services; Flutter reload/restart or replace-install according to what changed. The bundled full `prepare` path builds the reference stack and is not required for every switch. Start the appropriate development servers and verify required API routes, not just a process PID or HTTP page shell. For browser-only work, leave Android stopped unless needed. If Android is needed, preserve app data and use the documented replace-install/attach workflow rather than an uninstall fallback.

## Verify the feature and hand off

- Run checks relevant to the actual diff and a real local HTTP/database flow where useful. Adapt feature-specific fixtures and verification; do not run the old booking verifier against an unrelated PR merely because it is available.
- Seed enough representative local data to exercise the requested behavior. For exports, check downloaded file content and the intended scope/status/page handling, rather than treating HTTP 200 as sufficient. Do not silently reset a user's current manual scenario for a test.
- When browser/device control is available, exercise the real UI and inspect the result. Otherwise state what was verified through tests/API calls and leave a concrete manual checklist; do not claim a walkthrough from a successful build or widget test.
- Leave a concise handoff: running URL(s), login role and local code-inbox location, how to open the feature, a few meaningful checks, relevant refresh/restart/stop commands, selected PRs and exact revisions, local-only changes, and material blockers. Record which components were reused, restored, rebuilt or isolated, and why. Refresh the runner's manifest/runbook and runtime state (or a `state/review.json` checkpoint) with actual source SHAs, relevant dependency/build fingerprints, active override records, selected database and process ownership. Do not store secrets in that checkpoint. The next invocation should be able to reconcile and resume the review without relying on conversation history.
- Local review does not itself authorize merges, deployment, remote comments, commits or pushes. Perform those only when the user has requested them. Finish setup and verification within the authorized local scope without adding routine approval checkpoints.

