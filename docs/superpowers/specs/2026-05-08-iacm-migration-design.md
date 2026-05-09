# IACM Account Migration Script — Design

**Date:** 2026-05-08
**Status:** Approved (pending user spec review)
**Author:** Brijesh Jagani

## Goal

Build a standalone Python script that clones IACM (Infrastructure as Code Management) resources from one Harness account to another, mirroring the architecture of `harness_migration.py` but kept in a separate file until proven working. The script must never delete or mutate existing resources in either account.

Validated against:
- **Source (Austin):** account `tjgVkyI9Sq63D6w9gUiVFQ` — 2 workspaces in `CSE_Labs/CSE_Lab_Project`, 2 modules (one account-scoped, one project-scoped).
- **Destination (Brijesh):** account `MGfvWo6NR5ygDfQpaYG4dA` — already has 2 modules from prior testing.

## Non-Goals

- Modifying `harness_migration.py`. Code is duplicated where needed; merge happens in a follow-up only after this script is verified.
- Migrating IACM-adjacent resources that already belong to the main script (orgs, projects, connectors, pipelines). Workspaces depend on those, but this script assumes they were migrated first by `harness_migration.py`.
- Implementing update/delete semantics. Conflicts ("already exists") are treated as `Skipped`.

## Architecture

A single new file at the repo root: `iacm_migration.py`.

### Components

1. **`IACMAPIClient`** — HTTP plumbing for one Harness account (source or destination).
   - Auth via `x-api-key` header.
   - Account ID extracted from PAT (format `pat.ACCOUNT_ID.rest...`).
   - 1-indexed pagination (`page` + `limit`) helper distinct from the main script's 0-indexed `pageIndex`/`pageSize`.
   - Optional proxy / SSL / custom headers / timeout / base-URL via shared YAML config (same shape as `config.example.yaml`).
   - 0.5s rate-limit delay between mutating requests.
   - Debug logging that redacts the API key.

2. **`IACMMigrator`** — orchestration.
   - Holds source + destination clients.
   - Walks scopes (account, org, project) using methods modeled on the main script's `_get_all_scopes()` / `_get_project_scopes()`.
   - Migrates resources in dependency order.
   - Tracks per-resource counters (`success`, `failed`, `skipped`) and prints a summary table at the end.

3. **CLI entry point** — `main()` with argparse.

### Resources & migration order

Order is dictated by dependencies:

1. **Modules** (account- and project-scoped).
   No dependencies on other IACM resources. Workspaces may reference modules, so modules go first.

2. **Variable sets** (project-scoped).
   List-only in this iteration: the `POST` endpoint returns HTTP 405 ("Method Not Allowed") in both accounts as of 2026-05-08, so create is not exposed via REST. Source is also empty, so the practical impact is zero. The script will still list and export them; if any are encountered it logs a warning and counts them as `skipped`.

3. **Workspaces** (project-scoped).
   Reference connectors (`provider_connector`, `repository_connector`, items in `provider_connectors[].connector_ref`), pipelines (`default_pipelines.{stage}.workspace_pipeline`), and may reference modules. Migrated last. Failures from missing referenced entities are caught and counted as `failed`, never fatal.

### Endpoints (validated against live accounts)

#### Modules

- `GET /iacm/api/modules?accountIdentifier=...&page=1&limit=50` — flat array; each item carries `org` and `project` (null = account scope), `name`, `system`, `repository`, `repository_branch`, `repository_connector`, `repository_path`, `versions`, `git_tag_style`, `storage_type`, `testing_enabled`.
- `POST /iacm/api/modules?accountIdentifier=...` — create. Body: `name`, `system`, `repository`, `repository_branch`, `repository_connector`, optional `repository_path`, `org`, `project`, `git_tag_style`, `storage_type`, `testing_enabled`.

#### Variable sets

- `GET /iacm/api/orgs/{org}/projects/{project}/variable-sets?accountIdentifier=...&page=1&limit=50` — empty source returns `{}`; non-empty source assumed to return an array (untested at create-side because POST returns 405).
- `POST` and `PUT` return 405 on every variant probed. Treated as list-only.

#### Workspaces

- `GET /iacm/api/orgs/{org}/projects/{project}/workspaces?accountIdentifier=...&page=1&limit=50` — list. Each item has core metadata; some fields are nulled in the list response.
- `GET /iacm/api/orgs/{org}/projects/{project}/workspaces/{id}?accountIdentifier=...` — full detail. Required for migration because it includes `terraform_variables`, `environment_variables`, `provider_connectors`, `default_pipelines`, `provisioner_version`, and full repo config.
- `POST /iacm/api/orgs/{org}/projects/{project}/workspaces?accountIdentifier=...` — create. Required body fields: `identifier`, `name`, `provider_connector`, `provisioner`, `terraform_variables`, `environment_variables`. Optional: `description`, `provisioner_version`, `repository`, `repository_branch`, `repository_connector`, `repository_path`, `repository_submodules`, `provider_connectors`, `default_pipelines`, `tags`, `cost_estimation_enabled`, `prune_sensitive_data`, `backend_locked`, `terraform_variable_files`, `variable_sets`.

### Scope iteration

- **Modules**: a single account-level `GET` returns modules across every scope. Each module's `org` / `project` fields drive create-time scope. No per-scope loop needed.
- **Workspaces**: iterate `_get_project_scopes()` — list source orgs, list source projects per org, yield `(org_id, project_id)` tuples. Same approach as pipelines in `harness_migration.py`.
- **Variable sets**: same project-scope iteration as workspaces.

`--org-identifier` and `--project-identifier` filters short-circuit scope discovery exactly like the main script.

### Pagination

IACM uses 1-indexed `page` (HTTP 400 on `page=0`) and `limit`. The list responses are flat arrays (not the `data.content` envelope used by ng/api). A new helper `_fetch_iacm_paginated(endpoint, params)` increments `page` until a page returns fewer items than `limit` or the response is empty/`{}`. Hard cap of 10,000 pages, mirroring the main script.

### Sensitive-value handling

For workspace `terraform_variables` and `environment_variables`:

- Copy values verbatim by default.
- If a variable's `value_type == "secret"` and the source response returns a redacted/empty value, substitute the placeholder `"changeme"` and emit a warning like `"WARNING: Secret variable {key} in workspace {id} is redacted; substituting 'changeme'. Update manually after migration."` (matches the convention used for `harnessSecretManager` secrets in the main script).
- Connector references (`provider_connector`, `repository_connector`, `provider_connectors[].connector_ref`) are copied as identifier strings; Harness resolves them in the destination account. Missing connectors cause a clean 4xx from the create call, which is logged and counted as `failed`.
- The `terraform_plan_json` field (a UUID pointing to ephemeral plan output) is intentionally dropped during migration — it's runtime state, not configuration.

### Export files

Separate output directory `iacm_exports/` (sibling to `harness_exports/` to keep the two scripts cleanly partitioned). Naming:

- Account-level module: `module_{name}_account.json`
- Project-level module: `module_{name}_org_{org}_project_{project}.json`
- Workspace: `workspace_{identifier}_org_{org}_project_{project}.json`
- Variable set (if non-empty): `variableset_{identifier}_org_{org}_project_{project}.json`

Files are written before any create attempt, so they survive failures and serve as a backup.

### Safety guarantees

- Source account: only `GET`.
- Destination account: only `POST` (create-only). No `PUT`, `PATCH`, or `DELETE` in the script.
- Conflict handling: when create returns a 4xx that indicates the resource already exists, log it and increment `skipped`. Never overwrite.
- Dry-run mode: skips all destination calls and writes export files only.
- Both accounts are identified by API-key extraction; no destructive default to "wrong account".

### Error handling & summary

Per-resource `try`/`except` around each create call. A failure does not abort the run. Final summary printed in the same shape as the main script:

```
=== IACM Migration Summary ===
Modules:        success=N  failed=N  skipped=N
Workspaces:     success=N  failed=N  skipped=N
Variable Sets:  exported=N skipped=N (read-only API)
```

In dry-run mode the headers say `exported` instead of `success`.

## CLI

Mirrors the main script's surface so a future merge is mechanical:

```
python iacm_migration.py \
  --source-api-key SOURCE_PAT \
  --dest-api-key DEST_PAT \
  [--org-identifier ORG] \
  [--project-identifier PROJ] \
  [--resource-types modules workspaces variable-sets] \
  [--exclude-resource-types ...] \
  [--base-url https://app.harness.io/gateway] \
  [--source-base-url ...] \
  [--dest-base-url ...] \
  [--config config.yaml] \
  [--dry-run] \
  [--debug]
```

`--import-from-exports` is **not** in scope for this iteration; it can be added later if needed.

## File layout after this work

```
iacm_migration.py        # New — standalone IACM migration script
harness_migration.py     # Untouched
docs/
  api-notes.md           # Untouched (will be extended in the merge follow-up, not now)
  implementation-notes.md
  superpowers/specs/2026-05-08-iacm-migration-design.md   # This doc
iacm_exports/            # Created at runtime
harness_exports/         # Created by harness_migration.py
```

## Out of scope (deferred)

- Merging the IACM logic into `harness_migration.py`.
- Updating top-level `README.md` and `AGENTS.md` to mention IACM.
- Variable-set creation (write API not exposed).
- Resyncing module versions across accounts (the create call registers the module; Harness pulls versions from git on demand).
- Migrating ephemeral runtime state: pipeline executions, plan outputs, workspace status.

## Open questions / risks

1. **Workspace `provisioner_version`** — source returns specific values (`"1.4.6"`) while list responses show `"latest"`. The script will use the value from the detail `GET`, which is the authoritative one.
2. **Provider connectors structure** — source returns `provider_connectors` as `[{connector_ref, type, created, updated}]`. The `created`/`updated` timestamps are dropped before posting.
3. **Module `versions`** — read-only field returned by list; not part of create body. Versions are pulled by Harness from the connected git repo after creation, which requires the destination account to have access to the same git repo. Cross-account git access is the user's responsibility.
4. **Variable-set 405** — if Harness exposes a write API later (different path or method), this design must be revisited. List code path is already in place to make that addition cheap.
