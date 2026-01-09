# AGENTS.md - Harness Account Migration Tool

## Project Overview

This is a Python-based tool for migrating Harness account resources from one Harness account to another using the Harness API. The tool supports migrating multiple resource types at different scopes (account, organization, and project levels) and includes a dry-run mode for safe testing.

## Key Features

- **Multi-scope Migration**: Migrates resources at account, organization, and project levels
- **Multiple Resource Types**: Supports organizations, projects, connectors, environments, infrastructures, services, and pipelines
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

## Resource Types and Handling

### Important: Not All Resources Use YAML Documents

**Critical Understanding**: Not all resources in Harness use YAML documents to store their contents. The migration approach must match the resource's storage method:

1. **GitX (Git Experience) Resources**: Stored in Git repositories
   - Use "Import from YAML" APIs
   - Resources have YAML representations
   - Migration: Get YAML → Export → Import via YAML API

2. **Inline Resources**: Stored directly in Harness database
   - Use Create API endpoints with data fields
   - No YAML representation available
   - Migration: Get data → Clean → Create via Create API

3. **Hybrid Resources**: Some resource types support both methods
   - Must detect storage method before migration
   - Use appropriate API based on storage method

### Organizations and Projects
- **Storage Method**: Always Inline (not YAML-based)
- **Migration Approach**: Direct API calls with data fields
- **API Endpoints**: 
  - Organizations: `POST /ng/api/organizations` with `{ "organization": {...} }`
  - Projects: `POST /ng/api/projects` with `{ "project": {...} }`
- **Data Extraction**: Data is extracted directly from list responses
- **Read-only Field Removal**: Automatically removes fields like `createdAt`, `lastModifiedAt`, etc.

### Other Resources (Connectors, Environments, Infrastructures, Services, Pipelines)
- **Storage Method**: Can be GitX or Inline (varies by resource and account configuration)
- **Current Implementation**: Assumes GitX and uses "Import from YAML" APIs
- **Future Enhancement Needed**: Detect storage method and use appropriate API
  - **GitX Resources**: Use "Import from YAML" APIs (current approach)
  - **Inline Resources**: Should use Create API endpoints (not yet implemented)
- **Export Format**: Resources are exported as YAML files (for GitX) or JSON files (for Inline)
- **Import Process for GitX**: 
  1. Get resource YAML from source account
  2. Export to file for backup
  3. Import to destination using YAML import API
- **Import Process for Inline** (to be implemented):
  1. Get resource data from source account
  2. Clean read-only fields
  3. Create in destination using Create API

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
3. **Connectors** (third - may be referenced by other resources)
4. **Environments** (fourth - may be referenced by infrastructures)
5. **Infrastructures** (fifth - depend on environments)
6. **Services** (sixth - may reference connectors and environments)
7. **Pipelines** (last - may reference all other resources)

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
AGENTS.md              # This file (agent documentation)
harness_exports/       # Directory for exported YAML files (created at runtime)
```

## Dependencies

- `requests>=2.31.0`: HTTP library for API calls
- `pyyaml>=6.0`: YAML parsing and generation

## Important Implementation Details

### API Request Pattern
- All requests include `accountIdentifier` in query parameters
- Authentication via `x-api-key` header
- Content-Type: `application/json`

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

## API Endpoints Used

### Organizations
- `GET /ng/api/organizations` - List organizations
- `POST /ng/api/organizations` - Create organization

### Projects
- `GET /ng/api/projects` - List projects (all orgs when no org_identifier)
- `POST /ng/api/projects` - Create project

### Connectors
- `GET /ng/api/connectors` - List connectors
- `GET /ng/api/connectors/{identifier}` - Get connector
- `POST /ng/api/connectors/import` - Import connector from YAML

### Environments
- `GET /ng/api/environmentsV2` - List environments
- `GET /ng/api/environmentsV2/{identifier}` - Get environment
- `POST /ng/api/environmentsV2/import` - Import environment from YAML

### Infrastructures
- `GET /ng/api/infrastructures` - List infrastructures
- `GET /ng/api/infrastructures/{identifier}` - Get infrastructure
- `POST /ng/api/infrastructures/import` - Import infrastructure from YAML

### Services
- `GET /ng/api/servicesV2` - List services
- `GET /ng/api/servicesV2/{identifier}` - Get service
- `POST /ng/api/servicesV2/import` - Import service from YAML

### Pipelines
- `POST /pipeline/api/pipelines/list` - List pipelines
- `GET /pipeline/api/pipelines/{identifier}` - Get pipeline
- `POST /pipeline/api/pipelines/import-pipeline` - Import pipeline from YAML

## Common Patterns

### Adding a New Resource Type

**Important**: First determine if the resource uses GitX (YAML) or Inline (data fields) storage.

#### For GitX (YAML-based) Resources:

1. Add list method to `HarnessAPIClient`:
   ```python
   def list_new_resource(self, org_id=None, project_id=None):
       endpoint = "/ng/api/new-resource"
       # ... implementation
   ```

2. Add get YAML method:
   ```python
   def get_new_resource_yaml(self, identifier, org_id=None, project_id=None):
       # ... implementation
   ```

3. Add import method:
   ```python
   def import_new_resource_yaml(self, yaml_content, org_id=None, project_id=None):
       # ... implementation
   ```

4. Add migration method to `HarnessMigrator`:
   ```python
   def migrate_new_resources(self):
       scopes = self._get_all_scopes()
       for org_id, project_id in scopes:
           # ... iterate and migrate using YAML import
   ```

#### For Inline (Data-based) Resources:

1. Add list method to `HarnessAPIClient`:
   ```python
   def list_new_resource(self, org_id=None, project_id=None):
       endpoint = "/ng/api/new-resource"
       # ... implementation
   ```

2. Add get data method:
   ```python
   def get_new_resource_data(self, identifier, org_id=None, project_id=None):
       # ... implementation - returns dict, not YAML
   ```

3. Add create method:
   ```python
   def create_new_resource(self, resource_data, org_id=None, project_id=None, dry_run=False):
       # ... implementation - uses Create API, not Import API
   ```

4. Add migration method to `HarnessMigrator`:
   ```python
   def migrate_new_resources(self):
       scopes = self._get_all_scopes()
       for org_id, project_id in scopes:
           # ... iterate and migrate using Create API
   ```

5. Add to `migrate_all()` and command-line choices

### Handling Special Cases

- **Connectors**: Extract from `connector` key in list response
- **Projects**: Extract from `project` key in list response
- **Organizations**: Extract from `organization` key in list response
- **Infrastructures**: Require `environmentIdentifier` parameter

### Detecting GitX vs Inline Storage

**Future Implementation**: To properly support both storage methods, check resource metadata:

1. **Check for `storeType` field** in resource response:
   - `storeType: "REMOTE"` or `storeType: "INLINE"` indicates storage method
   - `storeType: "REMOTE"` = GitX (use YAML Import API)
   - `storeType: "INLINE"` = Inline (use Create API)

2. **Check for `yaml` field** in resource response:
   - Presence of `yaml` field suggests GitX resource
   - Absence suggests Inline resource

3. **Check for Git-related fields**:
   - Fields like `gitDetails`, `repo`, `branch` indicate GitX
   - Absence suggests Inline

4. **API Response Patterns**:
   - GitX resources: GET endpoint returns `yaml` field
   - Inline resources: GET endpoint returns data fields but no `yaml` field

**Example Detection Logic** (to be implemented):
```python
def is_gitx_resource(resource_data: Dict) -> bool:
    """Determine if resource is stored in GitX or Inline"""
    # Check storeType field
    if resource_data.get('storeType') == 'REMOTE':
        return True
    if resource_data.get('storeType') == 'INLINE':
        return False
    
    # Check for yaml field
    if 'yaml' in resource_data:
        return True
    
    # Check for git-related fields
    if 'gitDetails' in resource_data or 'repo' in resource_data:
        return True
    
    # Default: assume Inline if no indicators found
    return False
```

## Testing and Validation

- Use dry-run mode to test without making changes
- Review exported YAML files in `harness_exports/` directory
- Check migration summary for success/failure counts
- Verify resources in destination account after migration

## Known Limitations

1. **GitX vs Inline Assumption**: Currently assumes all resources (except orgs/projects) are stored in GitX and uses YAML Import APIs. Inline resources stored directly in Harness database are not yet supported and will fail migration.
2. **FirstGen Resources**: Only supports NextGen (NG) API endpoints
3. **Resource Dependencies**: Some resources may have dependencies that need manual verification
4. **Existing Resources**: Import may fail if resource already exists in destination
5. **Rate Limiting**: Fixed 0.5s delay may need adjustment for large migrations
6. **Error Recovery**: Failed resources don't automatically retry
7. **Storage Method Detection**: Does not currently detect whether a resource is GitX or Inline before attempting migration

## Future Enhancements

### Planned Improvements

1. **GitX vs Inline Detection**
   - Detect resource storage method (GitX vs Inline) before migration
   - Automatically use appropriate API (YAML Import vs Create API)
   - Handle resources that may be stored differently in source vs destination

2. **Retry Logic**
   - Automatic retry for failed API calls
   - Exponential backoff for rate limiting
   - Configurable retry attempts and delays

3. **Dependency Graph Analysis**
   - Build dependency graph of resources
   - Validate dependencies before migration
   - Provide warnings for missing dependencies
   - Suggest migration order based on dependencies

4. **Incremental Migration Support**
   - Track already-migrated resources
   - Skip resources that already exist in destination
   - Support for partial migrations and resume capability

5. **Progress Persistence**
   - Save migration state to file
   - Resume interrupted migrations
   - Track success/failure per resource

6. **Parallel Migration**
   - Migrate independent resources in parallel
   - Respect dependency order while parallelizing
   - Configurable concurrency limits

7. **Validation of Migrated Resources**
   - Verify resources were created correctly
   - Compare source and destination resource configurations
   - Generate validation report

8. **Enhanced Error Reporting**
   - Detailed error messages with context
   - Suggestions for resolving common errors
   - Export error details to file

9. **Resource Filtering**
   - Filter by tags, labels, or metadata
   - Exclude specific resources from migration
   - Include only resources matching criteria

10. **Dry-Run Enhancements**
    - Show dependency graph in dry-run mode
    - Estimate migration time
    - Identify potential issues before migration

### Roadmap

#### Phase 1: Core Functionality (Current)
- ✅ Basic migration for multiple resource types
- ✅ Multi-scope support (account/org/project)
- ✅ Dry-run mode
- ✅ Automatic account ID extraction
- ⚠️ Currently assumes all resources are GitX (needs enhancement)

#### Phase 2: Storage Method Detection (Next Priority)
- Detect GitX vs Inline storage for each resource
- Implement Create API methods for Inline resources
- Support both migration methods based on detection

#### Phase 3: Reliability Improvements
- Retry logic with exponential backoff
- Progress persistence and resume capability
- Enhanced error handling and reporting

#### Phase 4: Advanced Features
- Dependency graph analysis
- Parallel migration support
- Resource validation
- Advanced filtering options

#### Phase 5: User Experience
- Interactive mode with progress bars
- Web UI or CLI improvements
- Migration templates and presets
- Comprehensive documentation and examples

## References

- [Harness API Documentation](https://apidocs.harness.io/)
- [Harness Developer Hub](https://developer.harness.io/)
