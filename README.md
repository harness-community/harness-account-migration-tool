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

- `--source-api-key`: Source account API key (required)

### Optional Arguments

- `--dest-api-key`: Destination account API key (required for migration, not for dry-run)
- `--org-identifier`: Filter to specific organization
- `--project-identifier`: Filter to specific project
- `--resource-types`: List of resource types to migrate (default: all)
- `--exclude-resource-types`: List of resource types to exclude (takes precedence over `--resource-types`)
- `--base-url`: Harness API base URL (default: `https://app.harness.io/gateway`)
- `--dry-run`: List and export resources without migrating

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

At the end, a summary shows:
- **Success**: Number of successfully migrated resources
- **Failed**: Number of failed migrations
- **Skipped**: Number of skipped resources (defaults, built-ins, etc.)

In dry-run mode, the summary shows "Found/Exported" instead of "Success".

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
