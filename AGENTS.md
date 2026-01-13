# AGENTS.md - Harness Account Migration Tool

## Project Overview

This is a Python-based tool for migrating Harness account resources from one Harness account to another using the Harness API. The tool supports migrating multiple resource types at different scopes (account, organization, and project levels) and includes a dry-run mode for safe testing.

## Key Features

- **Multi-scope Migration**: Migrates resources at account, organization, and project levels
- **Multiple Resource Types**: Supports organizations, projects, connectors, environments, infrastructures, services, pipelines, and templates
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

### Connectors
- **Storage Method**: Always Inline (not stored in GitX)
- **Migration Approach**: Create API with YAML content directly in request body
- **API Endpoint**: `POST /ng/api/connectors` with YAML content
- **Content-Type**: `text/yaml` header
- **Data Extraction**: Extract from `connector` key in list response
- **Note**: Connectors use create API, not import API

### Other Resources (Environments, Infrastructures, Services, Pipelines, Templates)
- **Storage Method**: Can be GitX or Inline (varies by resource and account configuration)
- **Automatic Detection**: The script detects storage method using `is_gitx_resource()` method
- **Detection Logic**:
  - Checks `storeType` field (REMOTE = GitX, INLINE = Inline)
  - Checks for `gitDetails` or `entityGitDetails` field
  - Checks for git-related fields (`repo`, `branch`)
  - Defaults to Inline if no indicators found
- **Export Format**: Resources are exported as YAML files (for both GitX and Inline)
- **Migration Process for Inline Resources**: 
  1. Get resource data from source account (using `get_*_data()` method)
  2. Extract YAML content from resource data (from `yaml` field, or `yamlPipeline` for pipelines)
  3. Extract additional metadata (identifier, type, name, etc.) from resource data
  4. Export YAML to file for backup
  5. Create in destination using **create API** (`POST /ng/api/{resource}` or resource-specific endpoint) with JSON body containing:
     - `yaml`: The YAML content (or `pipeline_yaml` for pipelines)
     - `accountId`: Account identifier
     - `identifier`: Resource identifier (required for environments, services, and pipelines)
     - `type`: Resource type (required for environments only)
     - `name`: Resource name (required for environments, services, and pipelines)
     - `orgIdentifier`: Organization identifier (always included, may be None)
     - `projectIdentifier`: Project identifier (always included, may be None)
     - Additional resource-specific fields (e.g., `environmentIdentifier` for infrastructures, `tags` for pipelines)
- **Migration Process for GitX Resources**:
  1. Get resource data from source account (using `get_*_data()` method)
  2. Extract git details from `entityGitDetails` or `gitDetails` field
  3. Extract additional metadata (identifier, connectorRef, etc.) from resource data
  4. Export YAML to file for backup (if available)
  5. Import to destination using **import API** (`POST /ng/api/{resource}/import` or resource-specific endpoint) with query parameters and optionally a JSON body:
     - **Query parameters**:
       - `accountIdentifier`: Account identifier (required for most resources)
       - `{resource}Identifier`: Resource identifier (required for environments)
       - `orgIdentifier`: Organization identifier (if applicable)
       - `projectIdentifier`: Project identifier (if applicable)
       - `connectorRef`: Connector reference (for environments and pipelines, if present in source)
       - `repoName`: Repository name (from git details)
       - `branch`: Branch name (from git details)
       - `filePath`: File path (from git details)
     - **JSON body** (for pipelines only):
       - `pipelineDescription`: Pipeline description (always included, may be empty string)

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
3. **SecretManager Templates** (third - must be migrated early, right after projects/orgs)
4. **Connectors** (fourth - may be referenced by other resources)
5. **Environments** (fifth - may be referenced by infrastructures)
6. **Infrastructures** (sixth - depend on environments)
7. **Services** (seventh - may reference connectors and environments)
8. **Other Templates** (eighth - Pipeline, Stage, Step, MonitoredService, and other types - must be migrated before pipelines)
9. **Pipelines** (last - may reference all other resources including templates)

**Note**: Environments, infrastructures, services, pipelines, and templates automatically detect their storage type (inline vs GitX) and use the appropriate migration method for each individual resource. Templates are versioned - all versions of each template are migrated. **Important**: Templates must be migrated before pipelines because pipelines can be built from templates and depend on them.

**Template Migration Order**: Templates are migrated in a specific dependency order (referenced templates must be migrated first):
- **SecretManager templates**: Migrated first (right after projects/orgs, before Pipeline templates)
- **Step templates** and **MonitoredService templates**: Migrated second (no dependencies, can be referenced by Stage templates)
- **Stage templates**: Migrated third (can reference Step and MonitoredService templates)
- **Pipeline templates**: Migrated fourth (can reference Stage and SecretManager templates)
- **Other template types**: Migrated last (in any order)

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
- Content-Type: `application/json` (most endpoints)
- **Exceptions**: 
  - Connector creation uses `Content-Type: text/yaml` with YAML content in request body
  - Template creation uses `Content-Type: application/yaml` with raw YAML content in request body

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
- `POST /ng/api/connectors` - Create connector (with YAML content in body, `Content-Type: text/yaml`)

### Environments
- `GET /ng/api/environmentsV2` - List environments
- `GET /ng/api/environmentsV2/{identifier}` - Get environment
- `POST /ng/api/environmentsV2` - Create environment (for inline resources, JSON body with yaml, identifier, type, name, etc.)
- `POST /ng/api/environmentsV2/import` - Import environment from GitX (query parameters only: accountIdentifier, environmentIdentifier, connectorRef, repoName, branch, filePath)

### Infrastructures
- `GET /ng/api/infrastructures` - List infrastructures
- `GET /ng/api/infrastructures/{identifier}` - Get infrastructure (requires environmentIdentifier parameter)
- `POST /ng/api/infrastructures` - Create infrastructure (for inline resources, JSON body with yaml, accountId, etc.)
- `POST /ng/api/infrastructures/import` - Import infrastructure from GitX (query parameters only: accountIdentifier, repoName, branch, filePath)

### Services
- `GET /ng/api/servicesV2` - List services
- `GET /ng/api/servicesV2/{identifier}` - Get service
- `POST /ng/api/servicesV2` - Create service (for inline resources, JSON body with yaml, identifier, name, accountId, orgIdentifier, projectIdentifier)
- `POST /ng/api/servicesV2/import` - Import service from GitX (query parameters only: accountIdentifier, serviceIdentifier, connectorRef, repoName, branch, filePath)

### Pipelines
- `POST /pipeline/api/pipelines/list` - List pipelines
- `GET /pipeline/api/pipelines/{identifier}` - Get pipeline
- `POST /v1/orgs/{org}/projects/{project}/pipelines` - Create pipeline (for inline resources, JSON body with pipeline_yaml, identifier, name, accountId, orgIdentifier, projectIdentifier, tags)
- `POST /pipeline/api/pipelines/import` - Import pipeline from GitX (query parameters: orgIdentifier, projectIdentifier, repoName, branch, filePath, connectorRef; JSON body: pipelineDescription)

### Templates
- **Storage Method**: Can be GitX or Inline (varies by template and account configuration)
- **Versioning**: Templates are versioned resources. Each template can have multiple versions, and all versions must be migrated.
- **List Templates**: `POST /template/api/templates/list-metadata` (query parameters: routingId, accountIdentifier, templateListType, page, size, sort, checkReferenced; JSON body: filterType)
- **Get Template Versions**: Uses same `list-metadata` endpoint with `templateIdentifiers` filter in JSON body (query parameters: routingId, accountIdentifier, module, templateListType, size)
- **Get Template Data**: `GET /template/api/templates/{identifier}` (query parameters: versionLabel, orgIdentifier, projectIdentifier)
- **Create Template**: `POST /template/api/templates` (for inline resources, query parameters: accountIdentifier, isNewTemplate, storeType, comments, orgIdentifier, projectIdentifier; Content-Type: application/yaml; body: raw YAML content)
- **Import Template**: `POST /template/api/templates/import/{identifier}` (query parameters: accountIdentifier, connectorRef, isHarnessCodeRepo, repoName, branch, filePath, orgIdentifier, projectIdentifier; JSON body: templateDescription, templateVersion, templateName)
- `POST /template/api/templates/list-metadata` - List templates (query parameters: routingId, accountIdentifier, templateListType, page, size, sort, checkReferenced; JSON body: filterType)
- `POST /template/api/templates/list-metadata` - Get template versions (query parameters: routingId, accountIdentifier, module, templateListType, size; JSON body: filterType, templateIdentifiers)
- `GET /template/api/templates/{identifier}` - Get template data for specific version (query parameters: versionLabel, orgIdentifier, projectIdentifier)
- `POST /template/api/templates` - Create template (for inline resources, query parameters: accountIdentifier, isNewTemplate, storeType, comments, orgIdentifier, projectIdentifier; Content-Type: application/yaml; body: raw YAML content)
- `POST /template/api/templates/import/{identifier}` - Import template from GitX (query parameters: accountIdentifier, connectorRef, isHarnessCodeRepo, repoName, branch, filePath, orgIdentifier, projectIdentifier; JSON body: templateDescription, templateVersion, templateName)

## Common Patterns

### Harness API List Response Pattern

**Critical Pattern**: Harness API list endpoints return resources in a nested structure where each item in the list contains the resource data under a key matching the resource name.

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

**Example**: For infrastructures, the response looks like:
```json
[
  {
    "infrastructure": {
      "identifier": "my-infra",
      "name": "My Infrastructure",
      "envIdentifier": "my-env"
    }
  }
]
```

**Not**:
```json
[
  {
    "identifier": "my-infra",
    "name": "My Infrastructure",
    "envIdentifier": "my-env"
  }
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

**Why This Pattern Exists**:
- Harness API uses this structure to include metadata alongside resource data
- The nested key allows for future API extensions without breaking changes
- Some resources may include additional fields at the top level alongside the resource object

**Resources Using This Pattern**:
- **Connectors**: `item.get('connector', item)`
- **Environments**: `item.get('environment', item)`
- **Infrastructures**: `item.get('infrastructure', item)`
- **Services**: `item.get('service', item)`
- **Pipelines**: `item.get('pipeline', item)`
- **Templates**: `item.get('template', item)` (note: template list responses may not use nested structure)
- **Projects**: `item.get('project', item)`
- **Organizations**: `item.get('organization', item)`

**Important**: Always use the fallback pattern `item.get('resourceName', item)` to handle cases where the API might return the data directly (for backward compatibility or different API versions).

### Adding a New Resource Type

**Important**: First determine if the resource uses GitX (YAML) or Inline (data fields) storage. Many resources support both, so you'll need to detect and handle both cases.

#### For Resources That Support Both GitX and Inline:

1. Add list method to `HarnessAPIClient`:
   ```python
   def list_new_resource(self, org_id=None, project_id=None):
       endpoint = "/ng/api/new-resource"
       # ... implementation
   ```

2. Add get data method (for detection and data extraction):
   ```python
   def get_new_resource_data(self, identifier, org_id=None, project_id=None):
       endpoint = f"/ng/api/new-resource/{identifier}"
       # ... implementation - returns full resource data dict
       # IMPORTANT: Extract from nested key if present (e.g., data.get('data', {}).get('newResource', data.get('data', {})))
   ```

3. Add get YAML method (wrapper around get_data):
   ```python
   def get_new_resource_yaml(self, identifier, org_id=None, project_id=None):
       resource_data = self.get_new_resource_data(identifier, org_id, project_id)
       if resource_data:
           return resource_data.get('yaml', '')
       return None
   ```

4. Add create method (for inline resources):
   ```python
   def create_new_resource(self, yaml_content, identifier, name, type=None, org_id=None, project_id=None):
       endpoint = "/ng/api/new-resource"
       params = {}
       if org_id:
           params['orgIdentifier'] = org_id
       if project_id:
           params['projectIdentifier'] = project_id
       
       # Build JSON payload with YAML content and identifiers
       data = {
           'yaml': yaml_content,
           'accountId': self.account_id,
           'identifier': identifier,
           'name': name,
           'orgIdentifier': org_id,  # Always include, may be None
           'projectIdentifier': project_id  # Always include, may be None
       }
       # Add resource-specific fields if needed (e.g., type for environments)
       if type:
           data['type'] = type
       # Add additional resource-specific fields (e.g., environmentIdentifier for infrastructures)
       
       response = self._make_request('POST', endpoint, params=params, data=data)
       # ... implementation
   ```

5. Add import method (for GitX resources only - uses query parameters, not request body):
   ```python
   def import_new_resource_yaml(self, git_details, resource_identifier=None, connector_ref=None, org_id=None, project_id=None):
       endpoint = "/ng/api/new-resource/import"
       params = {
           'accountIdentifier': self.account_id
       }
       # Add resource identifier if required by API
       if resource_identifier:
           params['newResourceIdentifier'] = resource_identifier
       if org_id:
           params['orgIdentifier'] = org_id
       if project_id:
           params['projectIdentifier'] = project_id
       if connector_ref:
           params['connectorRef'] = connector_ref
       
       # Add git details fields to query parameters (required: repoName, branch, filePath)
       if 'repoName' in git_details:
           params['repoName'] = git_details['repoName']
       if 'branch' in git_details:
           params['branch'] = git_details['branch']
       if 'filePath' in git_details:
           params['filePath'] = git_details['filePath']
       
       # No data body for GitX import
       response = self._make_request('POST', endpoint, params=params, data=None)
       # ... implementation
   ```

6. Add migration method to `HarnessMigrator`:
   ```python
   def migrate_new_resources(self):
       scopes = self._get_all_scopes()
       for org_id, project_id in scopes:
           resources = self.source_client.list_new_resource(org_id, project_id)
           for resource in resources:
               # CRITICAL: Extract from nested key matching resource name (singular form)
               # Harness API always returns list items as: [{'resourceName': {<data>}}]
               resource_item = resource.get('newResource', resource)  # e.g., 'connector', 'environment', 'infrastructure'
               identifier = resource_item.get('identifier', '')
               name = resource_item.get('name', identifier)
               
               # Get full resource data
               resource_data = self.source_client.get_new_resource_data(identifier, org_id, project_id)
               
               if not resource_data:
                   print(f"  Failed to get data for {name}")
                   results['failed'] += 1
                   continue
               
               # Detect storage type
               is_gitx = self.source_client.is_gitx_resource(resource_data)
               storage_type = "GitX" if is_gitx else "Inline"
               
               # Export YAML for backup
               yaml_content = resource_data.get('yaml', '')  # or 'yamlPipeline' for pipelines
               # ... export logic
               
               if is_gitx:
                   # GitX: Extract git details and use import endpoint
                   git_details = resource_data.get('entityGitDetails', {}) or resource_data.get('gitDetails', {})
                   if not git_details:
                       print(f"  Failed to get git details for GitX {name}")
                       results['failed'] += 1
                       continue
                   connector_ref = resource_data.get('connectorRef')  # If applicable
                   # Import with git details via query parameters
                   if self.dest_client.import_new_resource_yaml(
                       git_details=git_details, resource_identifier=identifier,
                       connector_ref=connector_ref, org_id=org_id, project_id=project_id
                   ):
                       results['success'] += 1
                   else:
                       results['failed'] += 1
               else:
                   # Inline: Extract YAML and metadata, use create endpoint
                   if not yaml_content:
                       print(f"  Failed to get YAML for inline {name}")
                       results['failed'] += 1
                       continue
                   # Extract resource-specific fields (e.g., type for environments)
                   resource_type = resource_data.get('type')  # If applicable (e.g., for environments)
                   # Create with YAML content and metadata via JSON body
                   # Most resources require identifier and name; some may require additional fields
                   if self.dest_client.create_new_resource(
                       yaml_content=yaml_content, identifier=identifier, name=name,
                       type=resource_type,  # Pass None if not applicable
                       org_id=org_id, project_id=project_id
                   ):
                       results['success'] += 1
                   else:
                       results['failed'] += 1
   ```

7. Add to `migrate_all()` and command-line choices

### Important Implementation Details for Create Methods

**For Inline Resources (create endpoints)**:
- Use `POST /ng/api/{resource}` endpoint (not the import endpoint)
- Send JSON body with `Content-Type: application/json` (handled automatically by `_make_request`)
- Required fields in JSON body:
  - `yaml`: The YAML content as a string
  - `accountId`: Account identifier
  - Additional fields vary by resource type:
    - **Environments**: Requires `identifier`, `type`, `name`, `orgIdentifier`, `projectIdentifier` in JSON body
    - **Services**: Requires `identifier`, `name`, `orgIdentifier`, `projectIdentifier` in JSON body
    - **Infrastructures**: Requires `environmentIdentifier` in JSON body (and query params), plus `orgIdentifier`, `projectIdentifier` (check API docs for exact field names)
    - **Pipelines**: Requires `identifier`, `name`, `orgIdentifier`, `projectIdentifier` in JSON body. Uses `pipeline_yaml` field (not `yaml`) for YAML content. Optionally includes `tags` field extracted from YAML document.
    - **Templates**: Uses raw YAML content in request body (not JSON). Content-Type: `application/yaml`. Query parameters: `isNewTemplate`, `storeType`, `comments`. YAML content must include `identifier`, `name`, `versionLabel` in the YAML structure. Optionally includes `tags` extracted from YAML document.
    - Note: Some resources may have different field name conventions (e.g., `organizationId` vs `orgIdentifier`)

**Resource-Specific Notes**:
- **Environments**: Most complex - requires `identifier`, `type`, and `name` in addition to YAML
- **Services**: Requires `identifier` and `name` in addition to YAML (similar to environments but without `type`)
- **Infrastructures**: Require `environmentIdentifier` in both query parameters and JSON body when creating
- **Pipelines**: 
  - Use `yamlPipeline` field name when extracting YAML from response data
  - Use `pipeline_yaml` field name (not `yaml`) when sending YAML content in create API
  - Extract `tags` from parsed YAML document (from `pipeline.tags` or root `tags` field) and include in create API
  - Extract `description` or `pipelineDescription` from pipeline data for GitX imports
- **Templates**:
  - Use `yaml` or `templateYaml` field name when extracting YAML from response data
  - Send raw YAML content directly in request body (not wrapped in JSON) for create API
  - Use `Content-Type: application/yaml` header for create API (similar to connectors)
  - Extract `tags` from parsed YAML document (from `template.tags` or root `tags` field) - tags are included in YAML content itself
  - Extract `description` or `templateDescription` from template data for GitX imports
  - **Versioning**: Templates are versioned. Use `list-metadata` endpoint with `templateIdentifiers` filter to get all versions. Each version has a `versionLabel` field. Migrate all versions of each template.
  - **Get Template Data**: Requires `versionLabel` query parameter (not `version`)
  - **Import Endpoint**: Template identifier is in URL path: `/template/api/templates/import/{identifier}`
  - **Import Query Parameters**: Includes `isHarnessCodeRepo` (defaults to `false` if not present)
- **General Pattern**: Most inline resources require `identifier` and `name` fields extracted from source resource data

### Important Implementation Details for Import Methods (GitX)

**For GitX Resources (import endpoints)**:
- Use `POST /ng/api/{resource}/import` endpoint (or resource-specific endpoint like `/pipeline/api/pipelines/import`)
- **Most resources**: All data sent as query parameters (no request body)
- **Pipelines**: Uses both query parameters and JSON body
- Required query parameters:
  - `accountIdentifier`: Account identifier (required for most resources, not for pipelines)
  - `{resource}Identifier`: Resource identifier (required for environments)
  - `repoName`: Repository name (from git details)
  - `branch`: Branch name (from git details)
  - `filePath`: File path (from git details)
- Optional query parameters:
  - `orgIdentifier`: Organization identifier (if applicable)
  - `projectIdentifier`: Project identifier (if applicable)
  - `connectorRef`: Connector reference (for environments and pipelines, if present in source)
- **Pipelines JSON body**:
  - `pipelineDescription`: Pipeline description (always included, even if empty string)
- **Templates JSON body**:
  - `templateDescription`: Template description (always included, may be empty string)
  - `templateVersion`: Template version label (required)
  - `templateName`: Template name (required)

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

Common nested keys:
- Environments: `data.environment`
- Services: `data.service`
- Projects: `data.project`
- Organizations: `data.organization`
- Connectors: `data.connector` (or directly in `data`)
- Pipelines: `data.pipeline`
- Templates: `data.template`

#### Pattern for Extracting Nested Data from List Responses:

**This is a universal pattern for ALL Harness list APIs**. When iterating through list responses, **always** extract the actual resource data from nested keys:

```python
for item in list_response:
    # CRITICAL: Extract from key matching resource name, fallback to item itself
    # The key name matches the resource type (singular form)
    resource_data = item.get('resourceName', item)  # e.g., 'connector', 'environment', 'infrastructure', 'service', 'pipeline'
    identifier = resource_data.get('identifier', '')
    name = resource_data.get('name', identifier)
    # ... always use resource_data for all field access, never use item directly
```

**Common Mistakes to Avoid**:
- ❌ **Don't do**: `identifier = item.get('identifier', '')` - this will fail because the identifier is nested
- ✅ **Do**: `resource_item = item.get('infrastructure', item); identifier = resource_item.get('identifier', '')`
- ❌ **Don't assume**: The list contains flat objects
- ✅ **Always assume**: The list contains objects with nested resource data under a key matching the resource name

### Handling Special Cases

- **Nested Data Extraction in List Responses**: **ALL** Harness list APIs return resources nested under a key matching the resource name. This is a universal pattern:
  - **Connectors**: Extract from `connector` key: `connector.get('connector', connector)`
  - **Projects**: Extract from `project` key: `project.get('project', project)`
  - **Organizations**: Extract from `organization` key: `org.get('organization', org)`
  - **Environments**: Extract from `environment` key: `env.get('environment', env)`
  - **Infrastructures**: Extract from `infrastructure` key: `infra.get('infrastructure', infra)`
  - **Services**: Extract from `service` key: `service.get('service', service)`
  - **Pipelines**: Extract from `pipeline` key: `pipeline.get('pipeline', pipeline)`
  - **Templates**: Template list responses may return flat objects (not nested). Check response structure and extract accordingly.
  - **Always use fallback pattern**: `item.get('resourceName', item)` to handle cases where the key might not exist
  - **Never access fields directly** from the list item - always extract from the nested key first (except for templates which may be flat)
- **Nested Data Extraction in Get Responses**: When getting individual resource data, extract from nested structure:
  - Use pattern: `data.get('data', {}).get('resourceName', data.get('data', {}))`
  - Example: `data.get('data', {}).get('environment', data.get('data', {}))`
- **Infrastructures**: Require `environmentIdentifier` parameter when getting individual infrastructure data
- **Pipelines**: YAML field is named `yamlPipeline` instead of `yaml` in the response
- **Templates**: 
  - YAML field may be `yaml` or `templateYaml` in the response
  - Version information is in `versionLabel` field (not `version`)
  - Use `list-metadata` endpoint with `templateIdentifiers` filter to get all versions (not a separate versions endpoint)
  - Template identifier is included in import URL path: `/template/api/templates/import/{identifier}`
  - Create API uses raw YAML with `Content-Type: application/yaml` (like connectors)
  - Query parameter `isNewTemplate` should be `false` for updating existing templates
- **Git Details Field Names**: 
  - Environments and Services use `entityGitDetails` field
  - Templates may use `gitDetails` or `entityGitDetails` field
  - Other resources may use `gitDetails` field
  - Check both when extracting: `resource_data.get('entityGitDetails', {}) or resource_data.get('gitDetails', {})`

### Detecting GitX vs Inline Storage

The `is_gitx_resource()` method automatically detects storage method by checking resource metadata:

1. **Check for `storeType` field** in resource response:
   - `storeType: "REMOTE"` = GitX (use git details in import API)
   - `storeType: "INLINE"` = Inline (use YAML content in import API)

2. **Check for `gitDetails` field**:
   - Presence of `gitDetails` indicates GitX resource
   - Used to import from git location

3. **Check for git-related fields**:
   - Fields like `repo`, `branch` indicate GitX
   - Absence suggests Inline

4. **Check for `yaml` field**:
   - Both GitX and Inline resources may have YAML content
   - For Inline: YAML content is used directly in import
   - For GitX: git details are used, YAML is for export only

**Current Implementation**:
```python
def is_gitx_resource(self, resource_data: Dict) -> bool:
    """Determine if resource is stored in GitX or Inline"""
    # Check storeType field
    if resource_data.get('storeType') == 'REMOTE':
        return True
    if resource_data.get('storeType') == 'INLINE':
        return False
    
    # Check for gitDetails field
    if 'gitDetails' in resource_data and resource_data.get('gitDetails'):
        return True
    
    # Check for git-related fields
    if 'repo' in resource_data or 'branch' in resource_data:
        return True
    
    # Default: assume Inline if no indicators found
    return False
```

### Connectors (Special Case)

- **Storage Method**: Always Inline (not stored in GitX)
- **Migration Approach**: Create API with YAML content directly in request body
- **API Endpoint**: `POST /ng/api/connectors` with YAML content as request body
- **Content-Type**: `text/yaml` (not `application/json`)
- **Note**: Connectors do NOT use the import API, they use the create API with YAML content

### Templates (Special Case - Versioned Resources with Dependency Order)

- **Storage Method**: Can be GitX or Inline (varies by template and account configuration)
- **Versioning**: Templates are versioned resources. Each template can have multiple versions (identified by `versionLabel`), and all versions must be migrated.
- **Template Type Detection**: Templates have a `templateEntityType` field that indicates the type (e.g., "Pipeline", "Stage", "Step", "SecretManager", "MonitoredService")
- **Dependency Order**: Templates must be migrated in a specific order based on dependencies:
  - **SecretManager templates**: Migrated first (right after projects/orgs)
  - **Pipeline templates**: Migrated second (can reference SecretManager templates)
  - **Stage templates**: Migrated third (can reference Pipeline templates)
  - **Step templates** and **MonitoredService templates**: Can be migrated in any order (can reference Stage templates)
  - **Other template types**: Migrated last (in any order)
- **List Templates**: Uses `POST /template/api/templates/list-metadata` with `templateListType=LastUpdated` to get all templates
- **Get Versions**: Uses same `list-metadata` endpoint with `templateListType=All` and `templateIdentifiers` filter in JSON body to get all versions of a specific template
- **Version Extraction**: Extract `versionLabel` field from each entry in the list response (not a separate versions endpoint)
- **Get Template Data**: Requires `versionLabel` query parameter (not `version`) to get data for a specific version
- **Create Template**: 
  - Uses `POST /template/api/templates` with raw YAML content (not JSON-wrapped)
  - Content-Type: `application/yaml` (similar to connectors)
  - Query parameters: `isNewTemplate=false` (for updating existing templates), `storeType=INLINE`, `comments=`
  - YAML content must include `identifier`, `name`, `versionLabel` in the YAML structure itself
- **Import Template**:
  - Endpoint: `POST /template/api/templates/import/{identifier}` (template identifier in URL path)
  - Query parameters: `connectorRef`, `isHarnessCodeRepo` (defaults to `false`), `repoName`, `branch`, `filePath`
  - JSON body: `templateDescription`, `templateVersion` (version label), `templateName`
- **Migration Pattern**: 
  1. Group templates by `templateEntityType` field
  2. Migrate SecretManager templates first (via `migrate_secret_manager_templates()`)
  3. Migrate other templates in dependency order (Step/MonitoredService → Stage → Pipeline → Others)
  4. For each template, get all versions using `get_template_versions()`
  5. For each version, get template data and detect storage type
  6. Migrate each version separately (inline or GitX based on storage type)
  7. Export files include version in filename: `template_{identifier}_v{version}_...`

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

1. **Retry Logic**
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
