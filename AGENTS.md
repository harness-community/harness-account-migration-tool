# AGENTS.md - Harness Account Migration Tool

## Project Overview

This is a Python-based tool for migrating Harness account resources from one Harness account to another using the Harness API. The tool supports migrating multiple resource types at different scopes (account, organization, and project levels) and includes a dry-run mode for safe testing.

## Key Features

- **Multi-scope Migration**: Migrates resources at account, organization, and project levels
- **Multiple Resource Types**: Supports organizations, projects, connectors, secrets, environments, infrastructures, services, pipelines, templates, input sets, and triggers
- **YAML Import APIs**: Uses Harness "Import from YAML" APIs where available for reliable migration
- **Direct API Creation**: Uses create APIs for organizations and projects (not YAML-based)
- **Dry-run Mode**: Test migrations without making changes to destination account
- **Automatic Account ID Extraction**: Extracts account IDs from API keys automatically
- **Comprehensive Export**: Exports all resources to YAML files for backup and review

## Architecture

### Core Components

1. **HarnessAPIClient** (`HarnessAPIClient` class)
   - Handles all API interactions with Harness
   - Manages authentication via API keys
   - Extracts account ID from API key format: `sat.ACCOUNT_ID.rest.of.key`
   - Provides methods for listing, getting, and importing resources

2. **HarnessMigrator** (`HarnessMigrator` class)
   - Orchestrates the migration process
   - Manages resource migration at all scopes
   - Handles dry-run logic
   - Exports resources to YAML files

3. **Helper Functions**
   - `extract_account_id_from_api_key()`: Extracts account ID from API key
   - `remove_none_values()`: Recursively removes null values from data structures
   - `clean_for_creation()`: Removes read-only fields before creating resources

## Resource Storage Methods

### Critical Understanding

Not all resources in Harness use YAML documents to store their contents. The migration approach must match the resource's storage method:

1. **GitX (Git Experience) Resources**: Stored in Git repositories
   - Use "Import from YAML" APIs
   - Resources have YAML representations
   - Migration: Get YAML → Export → Import via YAML API

2. **Inline Resources**: Stored directly in Harness database
   - Use Create API endpoints with data fields
   - Migration: Get data → Clean → Create via Create API

3. **Hybrid Resources**: Some resource types support both methods
   - Must detect storage method before migration
   - Use appropriate API based on storage method

### Storage Method Detection

The `is_gitx_resource()` method automatically detects storage method by checking:
1. `storeType` field (REMOTE = GitX, INLINE = Inline)
2. Presence of `gitDetails` or `entityGitDetails` field
3. Git-related fields (`repo`, `branch`)
4. Defaults to Inline if no indicators found

### Resource-Specific Storage Methods

- **Organizations and Projects**: Always Inline (not YAML-based)
- **Connectors**: Always Inline (not stored in GitX)
  - **Custom Secret Manager Connectors**: Type "customsecretmanager" only, migrated early
  - **Secret Manager Connectors**: Other types (Vault, AwsSecretManager, AzureKeyVault, GcpKms, etc.), migrated after harnessSecretManager secrets
- **Secrets**: Always Inline (not tracked via GitX)
  - **harnessSecretManager Secrets**: Migrated separately before other secrets, uses dummy value "changeme"
  - **Other Secrets**: Migrated after harnessSecretManager secrets
- **Environments, Infrastructures, Services, Pipelines, Templates, Overrides**: Can be GitX or Inline (varies by resource and account configuration)
- **Policies**: Can be GitX or Inline in source, but always created as Inline on target (GitX import not supported)
- **Webhooks**: Always Inline (NOT stored in GitX)
- **Input Sets**: Can be GitX or Inline (inherits from parent pipeline)
- **Triggers**: Always Inline (NOT stored in GitX, even for GitX pipelines)

### Default Resources

The following default resources are automatically skipped during migration:
- Organization with identifier "default"
- Project with identifier "default_project"
- Connector "harnessImage" at account level
- Connector "harnessSecretManager" at all scopes (account, org, and project levels)

Skipped resources are logged and counted in the migration results.

## Scope Handling

The tool migrates resources at three levels:

1. **Account Level**: No `orgIdentifier`, no `projectIdentifier`
2. **Organization Level**: `orgIdentifier` specified, no `projectIdentifier`
3. **Project Level**: Both `orgIdentifier` and `projectIdentifier` specified

The `_get_all_scopes()` method automatically discovers all scopes:
- Gets account level (None, None)
- Gets all organizations and creates (org_id, None) scopes
- Gets all projects and creates (org_id, project_id) scopes

Each migration method iterates through all scopes to ensure complete migration.

**Important Exception**: Pipelines, input sets, and triggers only exist at the project level in Harness. These resources use `_get_project_scopes()` instead of `_get_all_scopes()` to only process project-level scopes.

## API Key Format

Harness API keys contain the account ID in the format:
```
sat.ACCOUNT_ID.rest.of.key
```

Example: `sat.TEyxLP87RquOEab_GrbYvQ.342324324324a23432f21231.adf4AdadD44344Afdaf4`
- Account ID: `TEyxLP87RquOEab_GrbYvQ` (second segment)

The tool automatically extracts the account ID from the API key, so users don't need to provide it separately.

## Migration Order

Resources are migrated in dependency order:

1. **Organizations** (first - required for other resources)
2. **Projects** (second - required for project-scoped resources)
3. **SecretManager Templates** (third - must be migrated early, right after projects/orgs)
4. **Custom Secret Manager Connectors** (fourth - type "customsecretmanager" only, migrated right after secret manager templates)
5. **Secrets stored in harnessSecretManager** (fifth - must be migrated before connectors, uses dummy value "changeme")
6. **Secret Manager Connectors** (sixth - Vault, AwsSecretManager, AzureKeyVault, GcpKms, etc., excluding "customsecretmanager", migrated after harnessSecretManager secrets)
7. **Remaining Secrets** (seventh - excluding harnessSecretManager secrets, migrated before regular connectors)
8. **Connectors** (eighth - excluding custom secret manager connectors and secret manager connectors)
9. **Deployment Template and Artifact Source Templates** (ninth - must be migrated before services and environments)
10. **Environments** (tenth - may be referenced by infrastructures)
11. **Infrastructures** (eleventh - depend on environments)
12. **Services** (twelfth - may reference connectors and environments)
13. **Overrides** (thirteenth - may reference environments, infrastructures, and services)
14. **Other Templates** (fourteenth - Pipeline, Stage, Step, StepGroup, MonitoredService, and other types - must be migrated before pipelines)
15. **Pipelines** (fifteenth - may reference all other resources including templates)
16. **Input Sets** (sixteenth - child entities of pipelines, must be migrated after pipelines)
17. **Triggers** (seventeenth - child entities of pipelines, must be migrated after input sets as triggers may reference input sets)
18. **Webhooks** (eighteenth - may be used by triggers, migrated after triggers)
19. **Policies** (last - can reference other resources, migrated after all other resources)

**Note**: Environments, infrastructures, services, pipelines, templates, and overrides automatically detect their storage type (inline vs GitX) and use the appropriate migration method for each individual resource. Templates are versioned - all versions of each template are migrated. Webhooks are always inline and do not support GitX storage. Policies can be stored in GitX in source but are always created as inline on target (GitX import API not available).

**Default Resources**: The following default resources are automatically skipped during migration:
- Organization with identifier "default"
- Project with identifier "default_project"
- Connector "harnessImage" at account level
- Connector "harnessSecretManager" at all scopes (account, org, and project levels)

**Template Migration Order**: Templates are migrated in a specific dependency order (referenced templates must be migrated first):
- **SecretManager templates**: Migrated first (right after projects/orgs, before Pipeline templates)
- **Deployment Template** and **Artifact Source templates**: Migrated second (before services and environments)
- **Step templates** and **MonitoredService templates**: Migrated third (no dependencies, can be referenced by Stage templates)
- **Step Group templates**: Migrated fourth (can be referenced by Stage templates)
- **Stage templates**: Migrated fifth (can reference Step, MonitoredService, and StepGroup templates)
- **Pipeline templates**: Migrated sixth (can reference Stage and SecretManager templates)
- **Other template types**: Migrated last (in any order)

## Migration Process

### For Inline Resources
1. Get resource data from source account (using `get_*_data()` method)
2. Extract YAML content from resource data (from `yaml` field, or `yamlPipeline` for pipelines, `inputSetYaml` for input sets)
3. Extract additional metadata (identifier, type, name, etc.) from resource data
4. Export YAML to file for backup
5. Create in destination using **create API** with JSON body containing YAML content and metadata

### For GitX Resources
1. Get resource data from source account (using `get_*_data()` method)
2. Extract git details from `entityGitDetails` or `gitDetails` field
3. Extract additional metadata (identifier, connectorRef, etc.) from resource data
4. Export YAML to file for backup (if available)
5. Import to destination using **import API** with query parameters (and optionally JSON body for some resources)

## Common Patterns

### Harness API List Response Pattern

**Critical Pattern**: Most Harness API list endpoints return resources in a nested structure where each item in the list contains the resource data under a key matching the resource name.

**List Response Format**:
```json
[
  {
    "resourceName": {
      "identifier": "...",
      "name": "...",
      // ... other resource fields
    }
  },
  // ... more resources
]
```

**Required Pattern for All List Iterations**:
When iterating through list responses, **always** extract the resource data from the nested key:

```python
for item in list_response:
    # Extract from key matching resource name, fallback to item itself
    resource_item = item.get('resourceName', item)  # e.g., 'connector', 'environment', 'infrastructure'
    identifier = resource_item.get('identifier', '')
    name = resource_item.get('name', identifier)
    # ... use resource_item for all data access
```

**Resources Using This Pattern**:
- Connectors, Environments, Infrastructures, Services, Pipelines, Projects, Organizations, Secrets, Input Sets

**Exceptions**:
- **Templates**: Template list responses may return flat objects (not nested). Check response structure and extract accordingly.
- **Triggers**: Triggers in list response are **NOT nested** - data is directly in the list item (no `trigger` key)

**Important**: Always use the fallback pattern `item.get('resourceName', item)` to handle cases where the API might return the data directly (for backward compatibility or different API versions).

### Extracting Nested Data from Get Responses

When implementing `get_*_data()` methods, always check for nested keys in the response:

```python
def get_new_resource_data(self, identifier, org_id=None, project_id=None):
    endpoint = f"/ng/api/new-resource/{identifier}"
    response = self._make_request('GET', endpoint, params=params)
    if response.status_code == 200:
        data = response.json()
        # Extract from nested key if present, fallback to 'data' itself
        resource_data = data.get('data', {}).get('newResource', data.get('data', {}))
        return resource_data
    return None
```

## Adding a New Resource Type

**Important**: First determine if the resource uses GitX (YAML) or Inline (data fields) storage. Many resources support both, so you'll need to detect and handle both cases.

### For Resources That Support Both GitX and Inline:

1. **Add list method** to `HarnessAPIClient`:
   - Use `_fetch_paginated()` helper for pagination support
   - Extract from nested key in list response (see Common Patterns)

2. **Add get data method** (for detection and data extraction):
   - Returns full resource data dict
   - Extract from nested key if present (see Common Patterns)

3. **Add get YAML method** (wrapper around get_data):
   - Extract YAML string from resource data (field name varies by resource)

4. **Add create method** (for inline resources):
   - Use `POST /ng/api/{resource}` endpoint (not the import endpoint)
   - Send JSON body with YAML content and metadata
   - Include `accountId`, `identifier`, `name`, `orgIdentifier`, `projectIdentifier`
   - Add resource-specific fields as needed

5. **Add import method** (for GitX resources):
   - Use `POST /ng/api/{resource}/import` endpoint
   - Send git details as query parameters (repoName, branch, filePath)
   - Include `accountIdentifier`, `orgIdentifier`, `projectIdentifier` as query parameters
   - Some resources require JSON body (see `api-notes.md` for details)

6. **Add migration method** to `HarnessMigrator`:
   - Use `_get_all_scopes()` or `_get_project_scopes()` as appropriate
   - Extract from nested key in list response
   - Detect storage type using `is_gitx_resource()`
   - Export YAML for backup
   - Call appropriate create or import method based on storage type

7. **Add to `migrate_all()` and command-line choices**

For detailed API endpoint information, see `api-notes.md`. For implementation-specific details and quirks, see `implementation-notes.md`.

## Dry-Run Mode

Dry-run mode allows testing without making changes:
- **No Destination Required**: Destination API key not needed
- **Export Only**: Resources are listed and exported to YAML files
- **No API Calls**: No create/import operations are performed
- **Clear Marking**: All output is marked with `[DRY RUN]`
- **Detailed Output**: Shows what would be created with data previews

## Command-Line Interface

### Required Arguments
- `--source-api-key`: Source account API key (account ID extracted automatically)

### Optional Arguments
- `--dest-api-key`: Destination account API key (required for actual migration, not for dry-run)
- `--org-identifier`: Filter to specific organization (optional)
- `--project-identifier`: Filter to specific project (optional)
- `--resource-types`: List of resource types to migrate (default: all)
- `--base-url`: Harness API base URL (default: `https://app.harness.io/gateway`)
- `--dry-run`: Enable dry-run mode

### Example Usage

```bash
# Dry-run to see what would be migrated
python harness_migration.py --source-api-key sat.ACCOUNT_ID.key --dry-run

# Full migration
python harness_migration.py \
  --source-api-key sat.SOURCE_ACCOUNT_ID.key \
  --dest-api-key sat.DEST_ACCOUNT_ID.key

# Migrate specific resource types
python harness_migration.py \
  --source-api-key sat.SOURCE_ACCOUNT_ID.key \
  --dest-api-key sat.DEST_ACCOUNT_ID.key \
  --resource-types connectors pipelines
```

## File Structure

```
harness_migration.py    # Main script
requirements.txt        # Python dependencies
README.md              # User documentation
AGENTS.md              # This file (generic agent instructions)
api-notes.md           # Detailed API endpoint information
implementation-notes.md # Implementation-specific details and quirks
harness_exports/       # Directory for exported YAML files (created at runtime)
```

## Dependencies

- `requests>=2.31.0`: HTTP library for API calls
- `pyyaml>=6.0`: YAML parsing and generation

## Important Implementation Details

### API Request Pattern
- All requests include `accountIdentifier` in query parameters (or `routingId` for some endpoints)
- Authentication via `x-api-key` header
- Content-Type: `application/json` (most endpoints)
- **Exceptions**: See `implementation-notes.md` for Content-Type exceptions

### Pagination Support
- **All list methods support pagination**: The script automatically fetches all pages of results
- **Pagination Helper**: Uses `_fetch_paginated()` method to handle paginated responses
- **Pagination Parameters**: Vary by API (see `implementation-notes.md` for details)
- **Safety Limits**: Maximum 10,000 pages to prevent infinite loops

### Error Handling
- API errors are caught and logged
- Failed resources are counted but don't stop the migration
- Exported YAML files are saved even if import fails

### Rate Limiting
- 0.5 second delay between requests to avoid API throttling
- Applied after each resource operation

### Data Cleaning
- Null values are removed from data structures
- Read-only fields are removed before creation (for orgs/projects)
- Connector data is cleaned and wrapped in proper YAML structure

### File Naming Convention
Exported files include scope information:
- Account level: `resource_identifier_account.yaml`
- Org level: `resource_identifier_org_ORG_ID.yaml`
- Project level: `resource_identifier_org_ORG_ID_project_PROJECT_ID.yaml`
- **Templates**: Include version in filename: `template_identifier_vVERSION_scope_suffix.yaml`

## Testing and Validation

- Use dry-run mode to test without making changes
- Review exported YAML files in `harness_exports/` directory
- Check migration summary for success/failure counts
- Verify resources in destination account after migration

## Known Limitations

1. **FirstGen Resources**: Only supports NextGen (NG) API endpoints
2. **Resource Dependencies**: Some resources may have dependencies that need manual verification
3. **Existing Resources**: Import may fail if resource already exists in destination
4. **Rate Limiting**: Fixed 0.5s delay may need adjustment for large migrations
5. **Error Recovery**: Failed resources don't automatically retry
6. **Git Details Validation**: For GitX resources, assumes git details from source account are valid in destination account (same git repository access)

## Future Enhancements

### Planned Improvements

1. **Retry Logic**: Automatic retry for failed API calls with exponential backoff
2. **Dependency Graph Analysis**: Build dependency graph, validate dependencies, provide warnings
3. **Incremental Migration Support**: Track already-migrated resources, skip existing resources
4. **Progress Persistence**: Save migration state, resume interrupted migrations
5. **Parallel Migration**: Migrate independent resources in parallel while respecting dependencies
6. **Validation of Migrated Resources**: Verify resources were created correctly
7. **Enhanced Error Reporting**: Detailed error messages with context and suggestions
8. **Resource Filtering**: Filter by tags, labels, or metadata
9. **Dry-Run Enhancements**: Show dependency graph, estimate migration time, identify potential issues

### Roadmap

#### Phase 1: Core Functionality (Current)
- ✅ Basic migration for multiple resource types
- ✅ Multi-scope support (account/org/project)
- ✅ Dry-run mode
- ✅ Automatic account ID extraction
- ✅ Storage method detection (GitX vs Inline)
- ✅ Support for both inline and GitX resource migration

#### Phase 2: Reliability Improvements (Next Priority)
- Retry logic with exponential backoff
- Progress persistence and resume capability
- Enhanced error handling and reporting

#### Phase 3: Advanced Features
- Dependency graph analysis
- Parallel migration support
- Resource validation
- Advanced filtering options

#### Phase 4: User Experience
- Interactive mode with progress bars
- Web UI or CLI improvements
- Migration templates and presets
- Comprehensive documentation and examples

## References

- [Harness API Documentation](https://apidocs.harness.io/)
- [Harness Developer Hub](https://developer.harness.io/)
- See `api-notes.md` for detailed API endpoint information
- See `implementation-notes.md` for implementation-specific details and quirks
