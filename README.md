# Harness Account Migration Tool

A Python script to migrate resources from one Harness account to another using the Harness API.

## Quick Start

### Installation

```bash
pip install -r requirements.txt
```

### Basic Usage

**Dry-run mode** (recommended first step - no destination account needed):
```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dry-run
```

**Full migration**:
```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY
```

## Prerequisites

- Python 3.7 or higher
- API key for source Harness account (account ID is automatically extracted)
- API key for destination account (only required for actual migration, not dry-run)

## Getting API Keys

1. Log in to your Harness account
2. Create an account level Service Account
3. Add a Role Binding for "Account Admin" on "All Resources Including Child Scopes" ("Account Viewer" can also be used for the source account instead)
3. Generate a new API key
4. Save the token securely (it's only shown once)

## Command-Line Options

### Required Arguments

- `--source-api-key`: Source account API key (required for migration mode, not required for import mode)

### Optional Arguments

- `--dest-api-key`: Destination account API key (required for migration/import, not for dry-run)
- `--org-identifier`: Filter to specific organization
- `--project-identifier`: Filter to specific project
- `--resource-types`: List of resource types to migrate (default: all)
- `--exclude-resource-types`: List of resource types to exclude (takes precedence over `--resource-types`)
- `--base-url`: Harness API base URL (default: `https://app.harness.io/gateway`). Used for both source and destination unless specific URLs are provided.
- `--source-base-url`: Source Harness API base URL (overrides `--base-url` for source). Use for different Harness instances like `https://prod7.harness.io/gateway`.
- `--dest-base-url`: Destination Harness API base URL (overrides `--base-url` for destination). Use for different Harness instances like `https://prod7.harness.io/gateway`.
- `--dry-run`: List and export resources without migrating (or preview import without creating)
- `--config`: Path to YAML configuration file for HTTP settings (proxy, custom headers, etc.)
- `--import-from-exports`: Import resources from previously exported JSON files instead of migrating from source account
- `--debug`: Enable detailed API request/response logging for troubleshooting

## Usage Examples

### Scope Filtering

**Account-level only:**
```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY
```

**Organization-scoped:**
```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY \
  --org-identifier YOUR_ORG_ID
```

**Project-scoped:**
```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY \
  --org-identifier YOUR_ORG_ID \
  --project-identifier YOUR_PROJECT_ID
```

### Resource Type Selection

**Migrate specific types:**
```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY \
  --resource-types connectors services pipelines
```

**Exclude specific types:**
```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY \
  --exclude-resource-types pipelines triggers
```

**Note**: `--exclude-resource-types` always takes precedence. If a type is in both lists, it will be excluded.

### Using a Configuration File

**Migrate with proxy and custom headers:**
```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY \
  --config config.yaml
```

### Import from Export Files

The tool supports importing resources from previously exported JSON files. This allows you to:
- Export resources from a source account
- Review and modify the exported files if needed
- Import the resources into a destination account

**Preview import (dry-run):**
```bash
python harness_migration.py \
  --import-from-exports ./harness_exports \
  --dry-run \
  --resource-types users
```

**Import users from export files:**
```bash
python harness_migration.py \
  --import-from-exports ./harness_exports \
  --dest-api-key YOUR_DEST_API_KEY \
  --resource-types users
```

**Notes:**
- When using `--import-from-exports`, the `--source-api-key` is not required
- Currently supports importing `users` (additional resource types planned for future releases)
- Export files must follow the naming convention used by the export process (e.g., `user_{email}_account.json`)

### Available Resource Types

- `organizations` - Organizations
- `projects` - Projects
- `connectors` - Connectors (Git, Docker, Kubernetes, etc.)
- `secrets` - Secrets
- `environments` - Environments
- `infrastructures` - Infrastructure definitions
- `services` - Services
- `overrides` - Harness CD overrides
- `pipelines` - Pipelines
- `templates` - Templates (all versions)
- `input-sets` - Input sets
- `triggers` - Triggers
- `webhooks` - Webhooks
- `policies` - Governance policies
- `policy-sets` - Policy sets
- `roles` - Access control roles
- `resource-groups` - Resource groups
- `settings` - Account/org/project settings
- `ip-allowlists` - IP allowlist configurations
- `users` - Users with role bindings
- `service-accounts` - Service accounts with role bindings

## Output

The script creates a `harness_exports/` directory containing:
- Exported YAML/JSON files for all resources
- Files named with resource identifier and scope information
- These files can be used with `--import-from-exports` to import resources into another account

### Export File Naming Convention

Files are named with the resource type, identifier, and scope:
- **Account level**: `{resource}_{identifier}_account.json`
- **Organization level**: `{resource}_{identifier}_org_{org_id}.json`
- **Project level**: `{resource}_{identifier}_org_{org_id}_project_{project_id}.json`

For users, the email address has `@` replaced with `_at_` in the filename.

### Summary

At the end, a summary shows:
- **Success**: Number of successfully migrated resources
- **Failed**: Number of failed migrations
- **Skipped**: Number of skipped resources (defaults, built-ins, already exists, etc.)

In dry-run mode, the summary shows "Found/Exported" instead of "Success".
In import mode, the summary shows "Would Import" (dry-run) or "Success" (actual import).

## Important Notes

### Resource Already Exists

If a resource already exists in the destination account, the migration will not migrate the resource and return an error message. You may need to delete existing resources first or modify identifiers.

### Secrets in harnessSecretManager

Secrets stored in `harnessSecretManager` cannot have their values migrated. The script creates them with a placeholder value of "changeme" - you must update these manually after migration.

### Migration Order

Resources are automatically migrated in dependency order. For example:
- Organizations and projects are migrated first
- Templates are migrated before pipelines (pipelines can reference templates)
- Input sets are migrated before triggers (triggers can reference input sets)

### Default Resources

The following default resources are automatically skipped:
- Organization "default"
- Project "default_project"
- Connector "harnessImage" (account level)
- Connector "harnessSecretManager" (all scopes)
- Built-in example policies and roles

## HTTP Configuration

The tool supports proxy servers and custom HTTP headers through a YAML configuration file. This is useful for environments behind corporate firewalls or when custom headers are required.

### Setup

1. Copy the example configuration file:
   ```bash
   cp config.example.yaml config.yaml
   ```

2. Edit `config.yaml` with your settings

3. Run the migration with the config file:
   ```bash
   python harness_migration.py \
     --source-api-key YOUR_SOURCE_API_KEY \
     --dest-api-key YOUR_DEST_API_KEY \
     --config config.yaml
   ```

### Configuration Options

```yaml
# Proxy Configuration
proxy:
  http: "http://proxy.example.com:8080"    # HTTP proxy URL
  https: "http://proxy.example.com:8080"   # HTTPS proxy URL
  no_proxy: "localhost,127.0.0.1,.internal.company.com"  # Hosts to bypass proxy

# Custom Headers (added to all API requests)
headers:
  X-Custom-Header: "custom-value"
  X-Correlation-ID: "migration-job-001"

# SSL/TLS Settings
verify_ssl: true  # Set to false to disable SSL verification (not recommended)

# Custom SSL CA Certificate (path to PEM file)
ssl_ca_cert: "/path/to/ca-bundle.crt"  # Takes precedence over verify_ssl if set

# Request Timeout (seconds)
timeout: 30
```

### Common Use Cases

- **Corporate Proxy**: Configure HTTP/HTTPS proxy for environments behind firewalls
- **Request Tracing**: Add correlation IDs or tracing headers for debugging
- **Authentication Proxies**: Add custom headers required by authentication proxies
- **Custom CA Certificates**: Use custom CA bundle for internal/private certificate authorities
- **Self-Signed Certificates**: Disable SSL verification for development environments (not recommended for production)

## Troubleshooting

### Authentication Errors

- Verify API keys are correct and not expired
- Ensure API keys have necessary permissions (read from source, write to destination)

### Import Failures

- Check if resource already exists in destination (see "Resource Already Exists" above)
- Verify all dependencies exist in destination (connectors, environments, etc.)
- Review exported YAML files in `harness_exports/` directory
- Check console error messages for details

### Missing Resources

- Some resources are account-level, organization-level, or project-level
- Use `--org-identifier` and `--project-identifier` to target specific scopes
- Verify you have permissions to access the resources

### Resources Not Migrating

- Check the migration summary for skipped resources
- Verify the resource type is included (not excluded)
- Ensure the resource exists in the source account at the specified scope

### Proxy/Network Issues

- Verify proxy URL is correct and accessible
- Check if proxy requires authentication (add credentials to proxy URL: `http://user:pass@proxy:8080`)
- Ensure `no_proxy` is configured for any hosts that should bypass the proxy

### Debugging API Issues

Use the `--debug` flag to see detailed information about every API call:

```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dry-run \
  --debug \
  --resource-types connectors
```

Debug mode shows:
- Full request URL, method, and query parameters
- Request headers (API key is redacted)
- Request body (JSON formatted, truncated if large)
- Response status code and headers
- Response body (JSON formatted, truncated if large)

**Warning**: Debug output may contain sensitive data. Do not share debug logs publicly.

### SSL Certificate Issues

- **Custom CA**: If your organization uses a private CA, set `ssl_ca_cert` to your CA bundle file path
- **Certificate errors**: Ensure the CA bundle includes all certificates in the chain (root and intermediate)
- **Self-signed certificates**: As a last resort, set `verify_ssl: false` (not recommended for production)
- **Bundle format**: The CA certificate file should be in PEM format
