# Harness Account Migration Script

This Python script migrates resources from one Harness account to another using the Harness API. It uses the "Import from YAML" APIs where available to transfer resources.

## Features

- Migrates multiple resource types:
  - Connectors
  - Environments
  - Infrastructures
  - Services
  - Pipelines
- Exports resources to YAML files for backup
- Uses Harness "Import from YAML" APIs for reliable migration
- Supports organization and project-scoped resources
- Provides detailed migration summary
- **Dry-run mode**: List and export resources without migrating (no destination account required)

## Prerequisites

1. Python 3.7 or higher
2. API key for the source Harness account (required - account ID is automatically extracted from the API key)
3. API key for destination account (only required for actual migration, not for dry-run - account ID is automatically extracted)

## Installation

1. Install required dependencies:
```bash
pip install -r requirements.txt
```

## Getting API Keys

1. Log in to your Harness account
2. Navigate to your user profile
3. Go to "API Key" section
4. Generate a new API key
5. Save the token securely (it's only shown once)

**Note**: The account ID is automatically extracted from your API key. Harness API keys contain the account ID in the format: `sat.ACCOUNT_ID.rest.of.key`. You don't need to provide the account ID separately.

## Usage

### Dry Run Mode (List and Export Only)

Use dry-run mode to see what resources exist in your source account without migrating them. This is useful for:
- Auditing what resources exist
- Reviewing YAML configurations before migration
- Testing API connectivity

```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dry-run
```

In dry-run mode:
- Resources are listed and exported to YAML files
- No migration to destination account occurs
- Destination API key and account ID are not required
- All output is clearly marked with `[DRY RUN]`

### Basic Usage (Account-level resources)

```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY
```

### Organization-scoped Resources

```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY \
  --org-identifier YOUR_ORG_ID
```

### Project-scoped Resources

```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY \
  --org-identifier YOUR_ORG_ID \
  --project-identifier YOUR_PROJECT_ID
```

### Migrate Specific Resource Types

```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --dest-api-key YOUR_DEST_API_KEY \
  --resource-types connectors services pipelines
```

### Available Resource Types

- `connectors` - Connectors (e.g., Git, Docker, Kubernetes)
- `environments` - Environments
- `infrastructures` - Infrastructure definitions
- `services` - Services
- `pipelines` - Pipelines

## Output

The script will:
1. Create a `harness_exports/` directory containing all exported YAML files
2. Display progress for each resource being processed
3. Print a summary at the end showing:
   - Number of successful operations (migrations in normal mode, exports in dry-run mode)
   - Number of failed operations
   - Number of skipped resources

In dry-run mode, the summary will show "Found/Exported" instead of "Success" to indicate resources were discovered and exported but not migrated.

## Error Handling

The script includes error handling for:
- API authentication failures
- Missing resources
- Invalid YAML content
- Network errors

Failed migrations will be reported in the summary, and the exported YAML files will still be available in the `harness_exports/` directory for manual review or retry.

## Notes

- The script includes rate limiting (0.5 second delay between requests) to avoid overwhelming the API
- Resources are migrated in dependency order (connectors → environments → infrastructures → services → pipelines)
- If a resource already exists in the destination account, the import may fail. You may need to delete existing resources first or modify the YAML identifiers
- Some resources may have dependencies on others. Ensure all dependencies are migrated before migrating dependent resources
- The script uses the Harness NextGen (NG) API endpoints. For FirstGen resources, you may need to modify the endpoints

## Troubleshooting

### Authentication Errors

- Verify your API keys are correct and have not expired
- Ensure the API keys have the necessary permissions to read from source and write to destination

### Import Failures

- Check if the resource already exists in the destination account
- Verify that all dependencies (connectors, environments, etc.) exist in the destination
- Review the exported YAML files in `harness_exports/` for any issues
- Check the error messages in the console output

### Missing Resources

- Some resources may be account-level, organization-level, or project-level
- Ensure you're using the correct `--org-identifier` and `--project-identifier` flags
- Some resources may require specific permissions

## API Documentation

For more information about the Harness API, visit:
- [Harness API Documentation](https://apidocs.harness.io/)
- [Harness Developer Hub](https://developer.harness.io/)

## License

This script is provided as-is for account migration purposes.
