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

## Prerequisites

1. Python 3.7 or higher
2. API keys for both source and destination Harness accounts
3. Account IDs for both accounts

## Installation

1. Install required dependencies:
```bash
pip install -r requirements.txt
```

## Getting API Keys and Account IDs

### API Keys

1. Log in to your Harness account
2. Navigate to your user profile
3. Go to "API Key" section
4. Generate a new API key
5. Save the token securely (it's only shown once)

### Account IDs

The account identifier can be found in the URL when logged into your Harness account:
- Example: `https://app.harness.io/ng/account/ACCOUNT_ID/settings/overview`
- The `ACCOUNT_ID` is the account identifier

## Usage

### Basic Usage (Account-level resources)

```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --source-account-id YOUR_SOURCE_ACCOUNT_ID \
  --dest-api-key YOUR_DEST_API_KEY \
  --dest-account-id YOUR_DEST_ACCOUNT_ID
```

### Organization-scoped Resources

```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --source-account-id YOUR_SOURCE_ACCOUNT_ID \
  --dest-api-key YOUR_DEST_API_KEY \
  --dest-account-id YOUR_DEST_ACCOUNT_ID \
  --org-identifier YOUR_ORG_ID
```

### Project-scoped Resources

```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --source-account-id YOUR_SOURCE_ACCOUNT_ID \
  --dest-api-key YOUR_DEST_API_KEY \
  --dest-account-id YOUR_DEST_ACCOUNT_ID \
  --org-identifier YOUR_ORG_ID \
  --project-identifier YOUR_PROJECT_ID
```

### Migrate Specific Resource Types

```bash
python harness_migration.py \
  --source-api-key YOUR_SOURCE_API_KEY \
  --source-account-id YOUR_SOURCE_ACCOUNT_ID \
  --dest-api-key YOUR_DEST_API_KEY \
  --dest-account-id YOUR_DEST_ACCOUNT_ID \
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
2. Display progress for each resource being migrated
3. Print a summary at the end showing:
   - Number of successful migrations
   - Number of failed migrations
   - Number of skipped resources

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
