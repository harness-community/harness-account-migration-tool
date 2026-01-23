# API Notes - Harness Account Migration Tool

This file contains detailed API endpoint information for the Harness Account Migration Tool. For generic implementation guidance, see `AGENTS.md`.

## API Endpoints Used

### Organizations
- `GET /ng/api/organizations` - List organizations
- `POST /ng/api/organizations` - Create organization
  - Request body: `{ "organization": {...} }`

### Projects
- `GET /ng/api/projects` - List projects (all orgs when no org_identifier)
- `POST /ng/api/projects` - Create project
  - Request body: `{ "project": {...} }`

### Connectors
- `GET /ng/api/connectors` - List connectors
- `GET /ng/api/connectors/{identifier}` - Get connector
- `POST /ng/api/connectors` - Create connector
  - Content-Type: `text/yaml`
  - Request body: YAML content directly (not JSON-wrapped)

### Secrets
- **API Version**: Uses v2 API endpoints (https://apidocs.harness.io/secrets)
- `POST /ng/api/v2/secrets/list/secrets` - List secrets
  - Request body: Filter criteria with pagination (`pageIndex`, `pageSize`)
  - Query parameters: `routingId` (account identifier), `sortOrders`
- `GET /ng/api/v2/secrets/{identifier}` - Get secret by ID and scope
- `POST /ng/api/v2/secrets` - Create secret at given scope
  - Request body: Secret data in JSON format
- **Pagination**: Uses `pageIndex` and `pageSize` parameters (not `page` and `size`)

### Environments
- `GET /ng/api/environmentsV2` - List environments
- `GET /ng/api/environmentsV2/{identifier}` - Get environment
- `POST /ng/api/environmentsV2` - Create environment (for inline resources)
  - Request body: JSON with `yaml`, `identifier`, `type`, `name`, `orgIdentifier`, `projectIdentifier`
- `POST /ng/api/environmentsV2/import` - Import environment from GitX
  - Query parameters: `accountIdentifier`, `environmentIdentifier`, `connectorRef`, `repoName`, `branch`, `filePath`
  - No request body

### Infrastructures
- `GET /ng/api/infrastructures` - List infrastructures
- `GET /ng/api/infrastructures/{identifier}` - Get infrastructure
  - Query parameters: `environmentIdentifier` (required)
- `POST /ng/api/infrastructures` - Create infrastructure (for inline resources)
  - Request body: JSON with `yaml`, `accountId`, `environmentIdentifier`, `orgIdentifier`, `projectIdentifier`
- `POST /ng/api/infrastructures/import` - Import infrastructure from GitX
  - Query parameters: `accountIdentifier`, `repoName`, `branch`, `filePath`
  - No request body

### Services
- `GET /ng/api/servicesV2` - List services
- `GET /ng/api/servicesV2/{identifier}` - Get service
- `POST /ng/api/servicesV2` - Create service (for inline resources)
  - Request body: JSON with `yaml`, `identifier`, `name`, `accountId`, `orgIdentifier`, `projectIdentifier`
- `POST /ng/api/servicesV2/import` - Import service from GitX
  - Query parameters: `accountIdentifier`, `serviceIdentifier`, `connectorRef`, `repoName`, `branch`, `filePath`
  - No request body

### Overrides
- **Scope**: Account, Organization, and Project levels
- `POST /ng/api/serviceOverrides/v2/list` - List overrides
  - Request body: `null` (POST with null body)
  - Query parameters: `routingId` (account identifier), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional), `type` (optional), `size`, `page`
  - Response: Paginated with `data.content` array
- `GET /ng/api/serviceOverrides/{identifier}` - Get override data
  - Query parameters: `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional), `repoName` (optional, for GitX), `loadFromFallbackBranch` (optional, for GitX)
  - Response: Override data in `data` field (not nested under 'override' key)
  - For GitX overrides: Includes `entityGitInfo` with git details (`repoName`, `branch`, `filePath`)
- `POST /ng/api/serviceOverrides/upsert` - Create/upsert override (for inline resources)
  - Query parameters: `routingId` (account identifier)
  - Request body: JSON with `type`, `environmentRef`, `identifier`, `spec`, `yaml`, `orgIdentifier` (optional), `projectIdentifier` (optional), `infraIdentifier` (optional), `serviceRef` (optional)
- `POST /ng/api/serviceOverrides/import` - Import override from GitX
  - Query parameters: `accountIdentifier`, `connectorRef`, `isHarnessCodeRepo`, `repoName`, `branch`, `filePath`
  - Request body: JSON with `type`, `environmentRef`, `orgIdentifier` (optional), `projectIdentifier` (optional), `infraIdentifier` (optional), `serviceRef` (optional)
  - **Note**: Does NOT include `identifier`, `spec`, or `yaml` in request body (only metadata)

### Webhooks
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses v1 API endpoints (not ng/api)
- **Account Level**:
  - `POST /v1/webhooks/list` - List webhooks
  - `GET /v1/webhooks/{identifier}` - Get webhook data
  - `POST /v1/webhooks` - Create webhook
- **Organization Level**:
  - `POST /v1/orgs/{org}/webhooks/list` - List webhooks
  - `GET /v1/orgs/{org}/webhooks/{identifier}` - Get webhook data
  - `POST /v1/orgs/{org}/webhooks` - Create webhook
- **Project Level**:
  - `POST /v1/orgs/{org}/projects/{project}/webhooks/list` - List webhooks
  - `GET /v1/orgs/{org}/projects/{project}/webhooks/{identifier}` - Get webhook data
  - `POST /v1/orgs/{org}/projects/{project}/webhooks` - Create webhook
- **Common Parameters**:
  - Query parameters (for list): `limit`, `page`
  - Request body (for list): Empty JSON object `{}`
  - Request body (for create): JSON with `webhook_identifier`, `webhook_name`, `spec` (object with `webhook_type`, `connector_ref`, `repo_name`, `folder_paths`), optional `is_enabled`
  - Headers: `harness-account` (account identifier)
  - Response: Direct array/object (not nested under `data`)
  - **Note**: Webhooks use JSON structure with `spec` object (not YAML)

### Policies
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Can be GitX or Inline in source, but always created as Inline on target (GitX import not supported)
- **API Version**: Uses pm/api/v1 endpoints (not ng/api)
- **Data Format**: Uses `rego` field (not `yaml`) - contains Rego policy code
- `GET /pm/api/v1/policies` - List policies
  - Query parameters: `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional), `per_page`, `page`, `sort`, `searchTerm`, `excludeRegoFromResponse`, `includePolicySetCount`
  - Response: Direct array of policy objects (not nested)
  - **Note**: List response excludes rego content by default (`excludeRegoFromResponse=true`)
- `GET /pm/api/v1/policies/{identifier}` - Get policy data
  - Query parameters: `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Response: Direct policy object with `identifier`, `name`, `rego`, etc. (not nested under `data`)
- `POST /pm/api/v1/policies` - Create policy
  - Query parameters: `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Request body: JSON with `identifier`, `name`, `rego` (Rego policy code)
  - **Note**: GitX import not supported - policies stored in GitX in source are created as inline on target

### Policy Sets
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses pm/api/v1 endpoints (not ng/api)
- **Data Format**: Uses JSON structure with `policies` array (not YAML)
- `GET /pm/api/v1/policysets` - List policy sets
  - Query parameters: `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional), `per_page`, `page`
  - Response: Direct array of policy set objects (not nested)
- `GET /pm/api/v1/policysets/{identifier}` - Get policy set data
  - Query parameters: `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Response: Direct policy set object with `identifier`, `name`, `policies` array, etc. (not nested under `data`)
- `POST /pm/api/v1/policysets` - Create/upsert policy set
  - Query parameters: `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Request body: JSON with `identifier`, `name`, `type`, `action`, `description`, `enabled`, optional `policies` (array of policy references with `identifier` and `severity`)
  - **Note**: Policy sets reference policies, so policies must be migrated first. Uses POST method (not PATCH), identifier in request body (not URL path).

### Roles
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses authz/api endpoints (not ng/api)
- **Data Format**: Uses JSON structure with `permissions` array (not YAML)
- `GET /authz/api/roles` - List roles
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional), `pageIndex`, `pageSize`
  - Response: Nested under `data.content` array, each item has `role` key containing role data
  - **Note**: Pagination uses `pageIndex` and `pageSize` (not `page` and `size`)
- `GET /authz/api/roles/{identifier}` - Get role data
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Response: Nested under `data.role` (may vary)
- `POST /authz/api/roles` - Create role (without permissions)
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Request body: JSON with `identifier`, `name`, optional `description`, `tags` (NO permissions or allowedScopeLevels)
- `PUT /authz/api/roles/{identifier}` - Update role (with permissions)
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Request body: JSON with `identifier`, `name`, `permissions` (array), `allowedScopeLevels` (array), optional `description`, `tags`
  - **Note**: Harness requires a two-step process: first create with POST (without permissions), then update with PUT (with permissions). Roles can reference organizations and projects, so they should be migrated after organizations and projects are created.

### Resource Groups
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses publicly documented Harness Resource Group API (non-beta) - see https://apidocs.harness.io/harness-resource-group
- **Data Format**: Uses JSON structure with camelCase field names and nested `resourceGroup` object (not YAML)
- **Endpoints**:
  - `GET /authz/api/v2/resourcegroup` - List resource groups (see https://apidocs.harness.io/harness-resource-group/getresourcegrouplistv2)
    - Query parameters: `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional), `pageIndex`, `pageSize`
    - Response: Nested under `data.content` array, each item has `resourceGroup` key
    - Pagination uses `pageIndex` and `pageSize`
  - `GET /authz/api/v2/resourcegroup/{identifier}` - Get resource group
    - Query parameters: `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
    - Response: Nested under `data.resourceGroup`
  - `POST /authz/api/v2/resourcegroup` - Create resource group
    - Query parameters: `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
    - Request body: JSON with nested `resourceGroup` object containing `accountIdentifier` (required), `orgIdentifier` (optional), `projectIdentifier` (optional), `identifier`, `name`, `description` (optional), `color` (optional), `tags` (optional), `includedScopes` (optional), `resourceFilter` (optional), `allowedScopeLevels` (optional)
    - **Note**: `accountIdentifier` must be included in the request body, not just as a query parameter
  - `PUT /authz/api/v2/resourcegroup/{identifier}` - Update resource group
  - `DELETE /authz/api/v2/resourcegroup/{identifier}` - Delete resource group
- **Note**: Resource groups can reference organizations and projects, so they should be migrated after organizations and projects are created. Do NOT use the Beta scoped endpoints (`/v1/resource-groups`, `/v1/orgs/{org}/resource-groups`, etc.).

### Settings
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses ng/api endpoints
- **Data Format**: Uses JSON structure (not YAML)
- `GET /ng/api/settings` - List settings
  - Query parameters: `accountIdentifier`, `category` (optional), `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Response: Array of settings, each with `setting` key containing setting data
  - **Note**: Only settings with `settingSource != "DEFAULT"` should be migrated (i.e., only overridden settings)
- `PUT /ng/api/settings` - Update settings
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Request body: Array of setting updates, each with `identifier`, `value`, `allowOverrides`, `updateType` ("UPDATE")
  - **Note**: Settings can reference organizations and projects, so they should be migrated after organizations and projects are created. Only overridden settings (not DEFAULT) are migrated.

### IP Allowlists
- **Scope**: Account-level only (no org/project scoping)
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses v1 endpoints (not ng/api) - see https://apidocs.harness.io/ip-allowlist/get-ip-allowlist-configs
- **Data Format**: Uses JSON structure with nested `ip_allowlist_config` object (not YAML)
- **Pagination**: Uses `page` and `limit` parameters
- `GET /v1/ip-allowlist` - List IP allowlists
  - Headers: `x-api-key`, `harness-account` (account identifier, required)
  - Response: Direct array, each item has `ip_allowlist_config` key containing allowlist data
- `POST /v1/ip-allowlist` - Create IP allowlist
  - Headers: `x-api-key`, `harness-account` (account identifier, required)
  - Request body: JSON with nested `ip_allowlist_config` object containing `identifier`, `name`, `description`, `enabled`, `allowed_source_type` (array), `ip_address`, `tags`
  - **Note**: IP allowlists are account-level only. Uses `harness-account` header (like webhooks).

### Users
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses ng/api/user endpoints
- **Data Format**: Uses JSON structure (not YAML)
- `POST /ng/api/user/aggregate` - List users
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional), `pageIndex`, `pageSize`, `sortOrders`
  - Request body: Empty JSON object `{}`
  - Response: Nested under `data.content` array, each item has `user` key and `roleAssignmentMetadata` array
  - **Note**: Uses POST method (not GET), pagination uses `pageIndex` and `pageSize`
- `POST /ng/api/user/users` - Create/invite user
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Request body: JSON with `emails` (array), `userGroups` (array), `roleBindings` (array of role binding objects)
  - Response: `{"status":"SUCCESS","data":{"addUserResponseMap":{"email":"USER_INVITED_SUCCESSFULLY" or "USER_ADDED_SUCCESSFULLY"}}}`
  - **Note**: Users reference roles and resource groups via role bindings, so they must be migrated after roles and resource groups are created.

### Service Accounts
- **Scope**: Account, Organization, and Project levels
- **Storage Method**: Always Inline (NOT stored in GitX)
- **API Version**: Uses ng/api/serviceaccount endpoints
- **Data Format**: Uses JSON structure (not YAML)
- `GET /ng/api/serviceaccount/aggregate` - List service accounts
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional), `pageIndex`, `pageSize`, `sortOrders`
  - Response: Nested under `data.content` array, each item has `serviceAccount` key and `roleAssignmentsMetadataDTO` array
  - **Note**: Uses GET method, pagination uses `pageIndex` and `pageSize`
- `GET /ng/api/serviceaccount/{identifier}` - Get service account data
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Response: Nested under `data.serviceAccount`
- `POST /ng/api/serviceaccount` - Create service account
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Request body: JSON with `identifier`, `name`, `description`, `tags`, `accountIdentifier`, `email`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - **Note**: Service accounts are created without role bindings. Role bindings must be added separately using `POST /authz/api/roleassignments/multi`
- `POST /authz/api/roleassignments/multi` - Add role bindings to service account
  - Query parameters: `routingId` (account identifier, required), `accountIdentifier`, `orgIdentifier` (optional), `projectIdentifier` (optional)
  - Request body: JSON with `roleAssignments` array
  - Each role assignment object contains:
    - `resourceGroupIdentifier`: Identifier of the resource group
    - `roleIdentifier`: Identifier of the role
    - `principal`: Object with `identifier` (service account identifier), `type: "SERVICE_ACCOUNT"`, and `scopeLevel` ("account", "organization", or "project")
  - **Note**: Service accounts reference roles and resource groups via role bindings, so they must be migrated after roles and resource groups are created.

### Pipelines
- **Scope**: Project-level only
- `POST /pipeline/api/pipelines/list` - List pipelines
  - Request body: Pagination parameters
- `GET /pipeline/api/pipelines/{identifier}` - Get pipeline
- `POST /v1/orgs/{org}/projects/{project}/pipelines` - Create pipeline (for inline resources)
  - Request body: JSON with `pipeline_yaml`, `identifier`, `name`, `accountId`, `orgIdentifier`, `projectIdentifier`, `tags`
- `POST /pipeline/api/pipelines/import` - Import pipeline from GitX
  - Query parameters: `orgIdentifier`, `projectIdentifier`, `repoName`, `branch`, `filePath`, `connectorRef`
  - Request body: JSON with `pipelineDescription` (always included, may be empty string)

### Input Sets
- **Scope**: Project-level only (child entities of pipelines)
- `GET /pipeline/api/inputSets` - List input sets for a pipeline
  - Query parameters: `pipelineIdentifier`, `orgIdentifier`, `projectIdentifier`
- `GET /pipeline/api/inputSets/{identifier}` - Get input set data
  - Query parameters: `pipelineIdentifier`, `orgIdentifier`, `projectIdentifier`
- `POST /pipeline/api/inputSets` - Create input set (for inline resources)
  - Query parameters: `pipelineIdentifier`, `orgIdentifier`, `projectIdentifier`
  - Request body: JSON with `{"inputSet": {...}}`
- `POST /pipeline/api/inputSets/import/{identifier}` - Import input set from GitX
  - Query parameters: `accountIdentifier`, `pipelineIdentifier`, `orgIdentifier`, `projectIdentifier`, `connectorRef`, `isHarnessCodeRepo`, `repoName`, `branch`, `filePath`
  - Request body: JSON with `{"inputSetName": "...", "inputSetDescription": "..."}`

### Triggers
- **Scope**: Project-level only (child entities of pipelines)
- `GET /pipeline/api/triggers` - List triggers for a pipeline
  - Query parameters: `routingId`, `accountIdentifier`, `orgIdentifier`, `projectIdentifier`, `targetIdentifier` (pipeline identifier), `size`, `page`, `sort`
- `GET /pipeline/api/triggers/{identifier}/details` - Get trigger data
  - Query parameters: `routingId`, `accountIdentifier`, `orgIdentifier`, `projectIdentifier`, `targetIdentifier` (pipeline identifier)
- `POST /pipeline/api/triggers` - Create trigger
  - Query parameters: `routingId`, `accountIdentifier`, `targetIdentifier` (pipeline identifier), `orgIdentifier`, `projectIdentifier`, `ignoreError`, `storeType`
  - Content-Type: `application/yaml`
  - Request body: Raw YAML content
  - **Note**: Uses `targetIdentifier` (not `pipelineIdentifier`) in all endpoints

### Templates
- `POST /template/api/templates/list-metadata` - List templates
  - Query parameters: `routingId`, `accountIdentifier`, `templateListType`, `page`, `size`, `sort`, `checkReferenced`
  - Request body: JSON with `filterType`
- `POST /template/api/templates/list-metadata` - Get template versions
  - Query parameters: `routingId`, `accountIdentifier`, `module`, `templateListType`, `size`
  - Request body: JSON with `filterType`, `templateIdentifiers`
- `GET /template/api/templates/{identifier}` - Get template data for specific version
  - Query parameters: `versionLabel`, `orgIdentifier`, `projectIdentifier`
- `POST /template/api/templates` - Create template (for inline resources)
  - Query parameters: `accountIdentifier`, `isNewTemplate`, `storeType`, `comments`, `orgIdentifier`, `projectIdentifier`
  - Content-Type: `application/yaml`
  - Request body: Raw YAML content
- `POST /template/api/templates/import/{identifier}` - Import template from GitX
  - Query parameters: `accountIdentifier`, `connectorRef`, `isHarnessCodeRepo`, `repoName`, `branch`, `filePath`, `orgIdentifier`, `projectIdentifier`
  - Request body: JSON with `templateDescription`, `templateVersion` (version label), `templateName`
  - **Note**: Template identifier is in URL path

## Common API Patterns

### Authentication
- All requests use `x-api-key` header for authentication
- Account ID is extracted from API key format: `sat.ACCOUNT_ID.rest.of.key`

### Query Parameters
- Most endpoints require `accountIdentifier` in query parameters
- Scope parameters: `orgIdentifier`, `projectIdentifier` (when applicable)
- Some endpoints use `routingId` instead of `accountIdentifier` (e.g., secrets v2, triggers)

### Content Types
- Default: `application/json`
- Exceptions:
  - Connector creation: `text/yaml`
  - Template creation: `application/yaml`
  - Trigger creation: `application/yaml`

### Pagination
- Most APIs use `page` and `size` parameters
- Some APIs use `pageIndex` and `pageSize` (e.g., secrets v2)
- Pagination can be in query parameters (GET requests, most POST requests) or request body (e.g., pipelines)
- Response structure: Content at `data.content`, metadata at `data.totalPages`, `data.totalElements`

## Resource-Specific API Details

### Inline Resource Creation
Most inline resources use JSON body with:
- `yaml`: YAML content as string
- `accountId`: Account identifier
- `identifier`: Resource identifier
- `name`: Resource name
- `orgIdentifier`: Organization identifier (may be None)
- `projectIdentifier`: Project identifier (may be None)
- Additional resource-specific fields (e.g., `type` for environments, `environmentIdentifier` for infrastructures, `tags` for pipelines)

### GitX Resource Import
Most GitX imports use query parameters only (no request body):
- `accountIdentifier`: Account identifier
- `{resource}Identifier`: Resource identifier (if required, e.g., environments)
- `orgIdentifier`: Organization identifier (if applicable)
- `projectIdentifier`: Project identifier (if applicable)
- `connectorRef`: Connector reference (if applicable)
- `repoName`: Repository name (from git details)
- `branch`: Branch name (from git details)
- `filePath`: File path (from git details)

**Exceptions with JSON body:**
- **Pipelines**: JSON body with `pipelineDescription`
- **Templates**: JSON body with `templateDescription`, `templateVersion`, `templateName`
- **Input Sets**: JSON body with `inputSetName`, `inputSetDescription`

### User Journeys (SRM)
- **Scope**: Project-level only
- `GET /cv/api/user-journey` - List user journeys
  - Query parameters: `routingId` (account identifier), `accountId`, `orgIdentifier`, `projectIdentifier`, `offset`, `pageSize`
  - Response: Paginated with `data.content` array
- `POST /cv/api/user-journey/create` - Create user journey
  - Query parameters: `routingId` (account identifier), `accountId`, `orgIdentifier`, `projectIdentifier`
  - Request body: JSON with `identifier`, `name`
  - **Storage Method**: Always Inline (NOT stored in GitX)

### Monitored Services (SRM)
- **Scope**: Project-level only
- `GET /cv/api/monitored-service` - List monitored services
  - Query parameters: `routingId` (account identifier), `offset`, `pageSize`, `accountId`, `orgIdentifier`, `projectIdentifier`, `filter`, `servicesAtRiskFilter`
  - Response: Paginated with `data.content` array
- `GET /cv/api/monitored-service/{identifier}` - Get monitored service
  - Query parameters: `routingId` (account identifier), `accountId`, `orgIdentifier`, `projectIdentifier`
  - Response: Monitored service data in `data.monitoredService` or `data`
- `POST /cv/api/monitored-service` - Create monitored service
  - Query parameters: `routingId` (account identifier), `accountId`
  - Request body: JSON with `orgIdentifier`, `projectIdentifier`, `serviceRef`, `environmentRef`, `identifier`, `name`, `description`, `tags`, `sources` (with `healthSources`, `changeSources`), `dependencies`, `type`
- `PUT /cv/api/monitored-service/{identifier}` - Update monitored service (used to add health sources)
  - Query parameters: `routingId` (account identifier), `accountId`, `orgIdentifier`, `projectIdentifier`
  - Request body: JSON with full monitored service data including health sources
  - **Storage Method**: Always Inline (NOT stored in GitX)
  - **Health Sources**: Part of monitored services, added via PUT update to monitored service

