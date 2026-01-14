# Implementation Notes - Harness Account Migration Tool

This file contains implementation-specific details, quirks, and special handling cases for the Harness Account Migration Tool. For generic implementation guidance, see `AGENTS.md`. For API endpoint details, see `api-notes.md`.

## Data Extraction Patterns

### List Response Structure
**Critical Pattern**: Most Harness list APIs return resources nested under a key matching the resource name (singular form).

**Pattern**:
```json
[
  {
    "resourceName": {
      "identifier": "...",
      "name": "...",
      // ... other fields
    }
  }
]
```

**Resources Using This Pattern**:
- Connectors: `item.get('connector', item)`
- Environments: `item.get('environment', item)`
- Infrastructures: `item.get('infrastructure', item)`
- Services: `item.get('service', item)`
- Pipelines: `item.get('pipeline', item)`
- Projects: `item.get('project', item)`
- Organizations: `item.get('organization', item)`
- Secrets: `item.get('secret', item)` (v2 API)
- Input Sets: `item.get('inputSet', item)`
- Webhooks: `item.get('webhook', item)`
- Policies: `item.get('policy', item)`
- Policy Sets: `item.get('policySet', item)` (or directly in list if not nested)

**Exceptions**:
- **Templates**: May return flat objects (check response structure)
- **Triggers**: NOT nested - data is directly in list items (no `trigger` key)
- **Overrides**: NOT nested - data is directly in list items (no `override` key)

### Get Response Structure
When getting individual resource data, extract from nested structure:
```python
data.get('data', {}).get('resourceName', data.get('data', {}))
```

**Common nested keys**:
- Environments: `data.environment`
- Services: `data.service`
- Projects: `data.project`
- Organizations: `data.organization`
- Connectors: `data.connector` (or directly in `data`)
- Pipelines: `data.pipeline`
- Templates: `data.template`
- Triggers: Directly in `data` (not nested under `trigger`)
- Overrides: Directly in `data` (not nested under `override`)
- Webhooks: `data.webhook` (or directly in `data` if not nested)
- Policies: `data.policy` (or directly in `data` if not nested)

## Field Name Variations

### YAML Content Fields
Different resources use different field names for YAML content:
- Most resources: `yaml`
- Pipelines: `yamlPipeline` (in response), `pipeline_yaml` (in create request)
- Templates: `yaml` or `templateYaml`
- Input Sets: `inputSetYaml` (in get response)
- Triggers: `yaml`

### Git Details Fields
- Environments and Services: `entityGitDetails`
- Templates: `gitDetails` or `entityGitDetails`
- Other resources: `gitDetails`
- **Always check both**: `resource_data.get('entityGitDetails', {}) or resource_data.get('gitDetails', {})`

### Identifier Fields
- Most resources: `identifier`
- Triggers: Use `targetIdentifier` (not `pipelineIdentifier`) in query parameters for all endpoints

### Version Fields
- Templates: `versionLabel` (not `version`)

## Special Handling Cases

### Secrets
- **API Version**: Uses v2 API endpoints
- **Pagination**: Uses `pageIndex` and `pageSize` (not `page` and `size`)
- **Query Parameters**: Requires `routingId` (account identifier) and `sortOrders` for listing
- **Storage Method**: Always Inline (not tracked via GitX)
- **harnessSecretManager Identification**:
  - Field location: `spec.secretManagerIdentifier` (not at top level)
  - Variants: `harnessSecretManager`, `account.harnessSecretManager`, `org.harnessSecretManager`
  - Value handling: Set `spec.value` to "changeme" for harnessSecretManager secrets
  - Check: `cleaned_data.get('spec', {}).get('secretManagerIdentifier', '')`
- **Data Extraction**: Extract from `secret` key in list response (may also be in `resource` or directly in `data`)
- **Export**: Secrets are exported as JSON files (sensitive values are redacted)

### Infrastructures
- Require `environmentIdentifier` parameter when getting individual infrastructure data
- Require `environmentIdentifier` in both query parameters and JSON body when creating

### Pipelines
- **Scope**: Project-level only
- Use `yamlPipeline` field name when extracting YAML from response data
- Use `pipeline_yaml` field name (not `yaml`) when sending YAML content in create API
- Extract `tags` from parsed YAML document (from `pipeline.tags` or root `tags` field) and include in create API
- Extract `description` or `pipelineDescription` from pipeline data for GitX imports

### Input Sets
- **Scope**: Project-level only (child entities of pipelines)
- **Storage Method**: Can be GitX or Inline (inherits from parent pipeline)
- YAML field: `inputSetYaml` in get response (located in `data.inputSetYaml`)
- Get response returns full data dict (not just YAML string) for GitX/Inline detection
- For GitX: Use import endpoint with git details and JSON body containing `inputSetName` and `inputSetDescription`
- For Inline: Parse YAML and use create endpoint with JSON body containing `{"inputSet": {...}}`

### Triggers
- **Scope**: Project-level only (child entities of pipelines)
- **Storage Method**: Always Inline (NOT stored in GitX, even when parent pipeline is GitX)
- YAML field: `yaml` in get response (located in `data.yaml`)
- Use `targetIdentifier` (not `pipelineIdentifier`) in query parameters for all endpoints
- Get endpoint requires `/details` suffix: `/pipeline/api/triggers/{identifier}/details`
- List endpoint requires `routingId` and `accountIdentifier` query parameters
- Create endpoint uses raw YAML with `Content-Type: application/yaml` and requires:
  - Query parameters: `storeType: INLINE`, `ignoreError`, `routingId`, `accountIdentifier`, `targetIdentifier`
- **List Response**: NOT nested under a `trigger` key - access fields directly from list items

### Overrides
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Can be GitX or Inline (varies by override and account configuration)
- YAML field: `yaml` in get response (located in `data.yaml`)
- List endpoint: `POST /ng/api/serviceOverrides/v2/list` with `null` body (POST method, not GET)
- List pagination: Uses `page` and `size` query parameters (not `pageIndex`/`pageSize`)
- Get endpoint: For GitX overrides, requires `repoName` and `loadFromFallbackBranch` query parameters
- GitX detection: Check for `entityGitInfo` field in get response (not `gitDetails` or `entityGitDetails`)
- GitX git details: Extract from `entityGitInfo` field (`repoName`, `branch`, `filePath`)
- Create endpoint (inline): `POST /ng/api/serviceOverrides/upsert` with `routingId` query parameter
- Import endpoint (GitX): `POST /ng/api/serviceOverrides/import` (different from create endpoint)
- Import request body: Only includes metadata (`type`, `environmentRef`, `orgIdentifier`, `projectIdentifier`, optional `infraIdentifier`, `serviceRef`) - does NOT include `identifier`, `spec`, or `yaml`
- Import query parameters: `accountIdentifier`, `connectorRef`, `isHarnessCodeRepo`, `repoName`, `branch`, `filePath`
- **List Response**: NOT nested under an `override` key - access fields directly from list items
- **Get Response**: Data is directly in `data` field (not nested under `override` key)

### Webhooks
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX, even when used by GitX pipelines)
- **API Version**: Uses v1 API endpoints (not ng/api)
- **Data Format**: JSON structure with `spec` object (not YAML)
- List endpoint: `POST /v1/webhooks/list` with `limit` and `page` query parameters, empty JSON body `{}`
- List pagination: Uses `limit` and `page` query parameters
- Get endpoint: `GET /v1/webhooks/{identifier}` (no query parameters needed)
- Create endpoint: `POST /v1/webhooks` with JSON body containing `webhook_identifier`, `webhook_name`, `spec` object
- **Headers**: Requires `harness-account` header (account identifier) in addition to `x-api-key`
- **List Response**: Direct array (not nested) - access fields directly from list items
- **Get Response**: Direct object (not nested under `data` or `webhook` key)
- **Field Names**: Uses `webhook_identifier` and `webhook_name` (not `identifier` and `name`)
- **Spec Object**: Contains `webhook_type`, `connector_ref`, `repo_name`, `folder_paths` array

### Policies
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Can be GitX or Inline in source, but always created as Inline on target (GitX import not supported)
- **API Version**: Uses pm/api/v1 endpoints (not ng/api)
- **Data Format**: Uses `rego` field (not `yaml`) - contains Rego policy code
- Rego field: `rego` in get response (located directly in policy object)
- List endpoint: `GET /pm/api/v1/policies` with `per_page` and `page` query parameters (not `size` and `page`)
- List pagination: Uses `per_page` and `page` query parameters
- Get endpoint: `GET /pm/api/v1/policies/{identifier}`
- Create endpoint: `POST /pm/api/v1/policies` with JSON body containing `identifier`, `name`, `rego` (not `yaml`)
- **List Response**: Direct array (not nested) - access fields directly from list items
- **Get Response**: Direct object (not nested under `data` or `policy` key)
- **GitX Handling**: Policies stored in GitX in source are detected but created as inline on target (GitX import API not available)
- **Export Format**: Policies are exported as `.rego` files (not `.yaml`)

### Policy Sets
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses pm/api/v1 endpoints (not ng/api)
- **Data Format**: Uses JSON structure with `policies` array (not YAML)
- List endpoint: `GET /pm/api/v1/policysets` with `per_page` and `page` query parameters (not `size` and `page`)
- List pagination: Uses `per_page` and `page` query parameters
- Get endpoint: `GET /pm/api/v1/policysets/{identifier}`
- Create endpoint: `POST /pm/api/v1/policysets` with JSON body containing `identifier`, `name`, `type`, `action`, `description`, `enabled`, optional `policies` array (not PATCH, no identifier in URL path, no `id` field)
- **List Response**: Direct array (not nested) - access fields directly from list items
- **Get Response**: Direct object (not nested under `data` or `policySet` key)
- **Export Format**: Policy sets are exported as `.json` files (not `.yaml`)
- **Dependencies**: Policy sets reference policies, so policies must be migrated first

### Roles
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses authz/api endpoints (not ng/api)
- **Data Format**: Uses JSON structure with `permissions` array (not YAML)
- List endpoint: `GET /authz/api/roles` with `pageIndex` and `pageSize` query parameters (not `page` and `size`)
- List pagination: Uses `pageIndex` and `pageSize` query parameters
- List response: Nested under `data.content` array, each item has `role` key containing role data
- Get endpoint: `GET /authz/api/roles/{identifier}` (response may be nested under `data.role`)
- Create endpoint: Two-step process required:
  1. `POST /authz/api/roles` (no identifier in path) with JSON body containing `identifier`, `name`, optional `description`, `tags` (NO permissions)
  2. `PUT /authz/api/roles/{identifier}` (identifier in path) with JSON body containing `identifier`, `name`, `permissions` array, `allowedScopeLevels` array, optional `description`, `tags`
- **List Response**: Nested structure - extract from `data.content` array, then from `role` key in each item
- **Get Response**: May be nested under `data.role`
- **Required Parameter**: `routingId` (account identifier) is required for all role API calls
- **Export Format**: Roles are exported as `.json` files (not `.yaml`)
- **Dependencies**: Roles can reference organizations and projects, so they should be migrated after organizations and projects are created

### Resource Groups
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses resourcegroup/api/v2 endpoints (not ng/api)
- **Data Format**: Uses JSON structure with nested `resourceGroup` object (not YAML)
- List endpoint: `GET /resourcegroup/api/v2/resourcegroup` with `pageIndex` and `pageSize` query parameters (not `page` and `size`)
- List pagination: Uses `pageIndex` and `pageSize` query parameters
- List response: Nested under `data.content` array, each item has `resourceGroup` key containing resource group data
- Get endpoint: `GET /resourcegroup/api/v2/resourcegroup/{identifier}`
- Get response: Nested under `data.resourceGroup`
- Create endpoint: `PUT /resourcegroup/api/v2/resourcegroup/{identifier}` with JSON body containing nested `resourceGroup` object
- **List Response**: Nested structure - extract from `data.content` array, then from `resourceGroup` key in each item
- **Get Response**: Nested under `data.resourceGroup`
- **Request Body**: Must have nested `resourceGroup` structure (not flat)
- **Required Parameter**: `routingId` (account identifier) is required for all resource group API calls
- **Export Format**: Resource groups are exported as `.json` files (not `.yaml`)
- **Dependencies**: Resource groups can reference organizations and projects, so they should be migrated after organizations and projects are created

### Settings
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses ng/api endpoints
- **Data Format**: Uses JSON structure (not YAML)
- List endpoint: `GET /ng/api/settings` with optional `category` query parameter
- List response: Array of settings, each with `setting` key containing setting data
- Update endpoint: `PUT /ng/api/settings` with `routingId` parameter (required)
- Update request body: Array of setting updates with `identifier`, `value`, `allowOverrides`, `updateType`
- **List Response**: Array structure - extract from `data` array, then from `setting` key in each item
- **Required Parameter**: `routingId` (account identifier) is required for update API calls
- **Export Format**: Settings are exported as `.json` files (not `.yaml`), grouped by category
- **Filtering**: Only settings with `settingSource != "DEFAULT"` are migrated (only overridden settings)
- **Dependencies**: Settings can reference organizations and projects, so they should be migrated after organizations and projects are created

### IP Allowlists
- **Scope**: Account-level only (no org/project scoping)
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses v1 endpoints (not ng/api)
- **Data Format**: Uses JSON structure with nested `ip_allowlist_config` object (not YAML)
- List endpoint: `GET /v1/ip-allowlist`
- List response: Direct array, each item has `ip_allowlist_config` key containing allowlist data
- Create endpoint: `POST /v1/ip-allowlist` with JSON body containing nested `ip_allowlist_config` object
- **List Response**: Direct array - extract from `ip_allowlist_config` key in each item
- **Request Body**: Must have nested `ip_allowlist_config` structure (not flat)
- **Required Header**: `harness-account` (account identifier) is required for all IP allowlist API calls (like webhooks)
- **Export Format**: IP allowlists are exported as `.json` files (not `.yaml`)
- **Dependencies**: IP allowlists are account-level only, migrated after organizations and projects are created

### Users
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses ng/api/user endpoints
- **Data Format**: Uses JSON structure (not YAML)
- List endpoint: `POST /ng/api/user/aggregate` with `pageIndex` and `pageSize` query parameters (not GET, uses POST with empty body)
- List pagination: Uses `pageIndex` and `pageSize` query parameters
- List response: Nested under `data.content` array, each item has `user` key and `roleAssignmentMetadata` array
- Create endpoint: `POST /ng/api/user/users` with JSON body containing `emails` array, `userGroups` array, `roleBindings` array
- **List Response**: Nested structure - extract from `data.content` array, then from `user` key in each item, also include `roleAssignmentMetadata`
- **Request Body**: Contains `emails` (array), `userGroups` (array), `roleBindings` (array of objects with `resourceGroupIdentifier`, `roleIdentifier`, `roleName`, `resourceGroupName`, `managedRole`)
- **Required Parameter**: `routingId` (account identifier) is required for all user API calls
- **Export Format**: Users are exported as `.json` files (not `.yaml`), email is sanitized in filename (replaces @ with _at_)
- **Dependencies**: Users reference roles and resource groups via role bindings, so they must be migrated after roles and resource groups are created

### Service Accounts
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses ng/api/serviceaccount endpoints
- **Data Format**: Uses JSON structure (not YAML)
- List endpoint: `GET /ng/api/serviceaccount/aggregate` with `pageIndex` and `pageSize` query parameters
- List pagination: Uses `pageIndex` and `pageSize` query parameters (not `page` and `size`)
- List response: Nested under `data.content` array, each item has `serviceAccount` key and `roleAssignmentsMetadataDTO` array (note: it's `roleAssignmentsMetadataDTO`, not `roleAssignmentMetadata`)
- Get endpoint: `GET /ng/api/serviceaccount/{identifier}` with `routingId` parameter
- Get response: Nested under `data.serviceAccount`
- Create endpoint: `POST /ng/api/serviceaccount` with JSON body containing `identifier`, `name`, `description`, `tags`, `accountIdentifier`, `email`, `orgIdentifier` (optional), `projectIdentifier` (optional)
- **Note**: Service accounts are created WITHOUT role bindings. Role bindings must be added separately.
- Add role bindings endpoint: `POST /authz/api/roleassignments/multi` with JSON body containing `roleAssignments` array
- **List Response**: Nested structure - extract from `data.content` array, then from `serviceAccount` key in each item, also include `roleAssignmentsMetadataDTO` (normalized to `roleAssignmentMetadata` for consistency)
- **Create Request Body**: Contains `identifier`, `name`, `description`, `tags`, `accountIdentifier`, `email`, `orgIdentifier` (optional), `projectIdentifier` (optional)
- **Role Assignment Request Body**: Contains `roleAssignments` array, where each item has:
  - `resourceGroupIdentifier`: Identifier of the resource group
  - `roleIdentifier`: Identifier of the role
  - `principal`: Object with `identifier` (service account identifier), `type: "SERVICE_ACCOUNT"`, and `scopeLevel` ("account", "organization", or "project")
- **Required Parameter**: `routingId` (account identifier) is required for all service account API calls
- **Export Format**: Service accounts are exported as `.json` files (not `.yaml`)
- **Dependencies**: Service accounts reference roles and resource groups via role bindings, so they must be migrated after roles and resource groups are created

### Templates
- **Storage Method**: Can be GitX or Inline (varies by template and account configuration)
- **Versioning**: Templates are versioned - all versions must be migrated
- YAML field: `yaml` or `templateYaml` in response
- Version information: `versionLabel` field (not `version`)
- Use `list-metadata` endpoint with `templateIdentifiers` filter to get all versions (not a separate versions endpoint)
- Template identifier is included in import URL path: `/template/api/templates/import/{identifier}`
- Create API uses raw YAML with `Content-Type: application/yaml` (like connectors)
- Query parameter `isNewTemplate` should be `false` for updating existing templates
- Import query parameters include `isHarnessCodeRepo` (defaults to `false` if not present)
- Extract `tags` from parsed YAML document (tags are included in YAML content itself)
- Extract `description` or `templateDescription` from template data for GitX imports

### Connectors
- **Storage Method**: Always Inline (not stored in GitX)
- Use create API with YAML content directly in request body (not import API)
- Content-Type: `text/yaml` (not `application/json`)

## Storage Method Detection

The `is_gitx_resource()` method detects storage method by checking:
1. `storeType` field: `REMOTE` = GitX, `INLINE` = Inline
2. Presence of `gitDetails`, `entityGitDetails`, or `entityGitInfo` field
3. Git-related fields (`repo`, `branch`)
4. Default: Inline if no indicators found

**Resource-Specific GitX Detection**:
- **Overrides**: Check for `entityGitInfo` field (not `gitDetails`)

## Content-Type Exceptions

Default: `application/json`

**Exceptions**:
- Connector creation: `Content-Type: text/yaml`
- Template creation: `Content-Type: application/yaml`
- Trigger creation: `Content-Type: application/yaml`

## Pagination Implementation

- **Default page size**: 100 items per page
- **Parameter names**: Most use `page` and `size`, some use `pageIndex` and `pageSize`
- **Location**: Query parameters (most) or request body (e.g., pipelines)
- **Response structure**: Content at `data.content`, metadata at `data.totalPages`, `data.totalElements`
- **Safety limit**: Maximum 10,000 pages to prevent infinite loops
- **Custom pagination**: Some APIs (like secrets v2) require custom logic due to different parameter names

## Data Cleaning

- Null values are removed from data structures recursively
- Read-only fields are removed before creation (for orgs/projects): `createdAt`, `lastModifiedAt`, etc.
- Connector data is cleaned and wrapped in proper YAML structure

## File Naming Convention

Exported files include scope information:
- Account level: `resource_identifier_account.yaml`
- Org level: `resource_identifier_org_ORG_ID.yaml`
- Project level: `resource_identifier_org_ORG_ID_project_PROJECT_ID.yaml`
- **Templates**: Include version in filename: `template_identifier_vVERSION_scope_suffix.yaml`

## Rate Limiting

- 0.5 second delay between requests to avoid API throttling
- Applied after each resource operation

## Default Resources

The migration script automatically skips default resources that should not be migrated:

- **Default Organization**: Organization with identifier "default" is skipped
- **Default Project**: Project with identifier "default_project" is skipped
- **Default Connectors**:
  - Connector "harnessImage" at account level (when both `org_id` and `project_id` are None)
  - Connector "harnessSecretManager" at all scopes (account, org, and project levels)

**Implementation**: Helper methods `_is_default_organization()`, `_is_default_project()`, and `_is_default_connector()` check for these default resources. Skipped resources are logged and counted in the results summary.

## Error Handling

- API errors are caught and logged
- Failed resources are counted but don't stop the migration
- Exported YAML files are saved even if import fails
