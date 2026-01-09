#!/usr/bin/env python3
"""
Harness Account Migration Script

This script migrates resources from one Harness account to another using the Harness API.
It uses the "Import from YAML" APIs where available to transfer resources.
"""

import requests
import json
import yaml
import os
import sys
from typing import Dict, List, Optional, Any
from pathlib import Path
import time
import argparse


def remove_none_values(data: Any) -> Any:
    """Recursively remove keys with None/null values from dictionaries"""
    if isinstance(data, dict):
        return {k: remove_none_values(v) for k, v in data.items() if v is not None}
    elif isinstance(data, list):
        return [remove_none_values(item) for item in data if item is not None]
    else:
        return data


def clean_for_creation(data: Dict) -> Dict:
    """Remove read-only fields that shouldn't be sent in create requests"""
    read_only_fields = {
        'createdAt', 'lastModifiedAt', 'lastModifiedBy', 'createdBy',
        'version', 'harnessManaged', 'deleted', 'accountId'
    }
    cleaned = {k: v for k, v in data.items() if k not in read_only_fields}
    return cleaned


class HarnessAPIClient:
    """Client for interacting with Harness API"""
    
    def __init__(self, api_key: str, account_id: str, base_url: str = "https://app.harness.io/gateway"):
        self.api_key = api_key
        self.account_id = account_id
        self.base_url = base_url
        self.headers = {
            'x-api-key': api_key,
            'Content-Type': 'application/json'
        }
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None, params: Optional[Dict] = None) -> requests.Response:
        """Make an API request"""
        url = f"{self.base_url}{endpoint}"
        if params is None:
            params = {}
        params['accountIdentifier'] = self.account_id
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=self.headers, params=params, json=data)
            elif method.upper() == 'POST':
                response = requests.post(url, headers=self.headers, params=params, json=data)
            elif method.upper() == 'PUT':
                response = requests.put(url, headers=self.headers, params=params, json=data)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            return response
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            raise
    
    def list_organizations(self) -> List[Dict]:
        """List all organizations"""
        endpoint = "/ng/api/organizations"
        params = {}
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('content', [])
        else:
            print(f"Failed to list organizations: {response.status_code} - {response.text}")
            return []
    
    def create_organization(self, org_data: Dict, dry_run: bool = False) -> bool:
        """Create organization using the create API"""
        # Remove read-only fields that shouldn't be sent in create request
        cleaned_data = clean_for_creation(org_data)
        
        # Prepare the request body according to the API spec
        # The API expects: { "organization": { "identifier": "...", "name": "...", ... } }
        request_body = {
            'organization': cleaned_data
        }
        
        if dry_run:
            org_name = cleaned_data.get('name', cleaned_data.get('identifier', 'Unknown'))
            org_id = cleaned_data.get('identifier', 'Unknown')
            print(f"  [DRY RUN] Would create organization: {org_name} ({org_id})")
            print(f"  [DRY RUN] Organization data: {json.dumps(cleaned_data, indent=2)}")
            return True
        
        endpoint = "/ng/api/organizations"
        params = {}
        
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created organization")
            return True
        else:
            print(f"Failed to create organization: {response.status_code} - {response.text}")
            return False
    
    def list_projects(self, org_identifier: Optional[str] = None) -> List[Dict]:
        """List all projects"""
        endpoint = "/ng/api/projects"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('content', [])
        else:
            print(f"Failed to list projects: {response.status_code} - {response.text}")
            return []
    
    def get_project_data(self, project_identifier: str, org_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get project data"""
        endpoint = f"/ng/api/projects/{project_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            project_data = data.get('data', {}).get('project', data.get('data', {}))
            # Remove null values
            project_data = remove_none_values(project_data)
            return project_data
        else:
            print(f"Failed to get project data: {response.status_code} - {response.text}")
            return None
    
    def create_project(self, project_data: Dict, org_identifier: Optional[str] = None, dry_run: bool = False) -> bool:
        """Create project using the create API"""
        # Ensure orgIdentifier is set in project data
        if org_identifier and 'orgIdentifier' not in project_data:
            project_data['orgIdentifier'] = org_identifier
        
        # Remove read-only fields that shouldn't be sent in create request
        cleaned_data = clean_for_creation(project_data)
        
        # Prepare the request body according to the API spec
        # The API expects: { "project": { "orgIdentifier": "...", "identifier": "...", "name": "...", ... } }
        request_body = {
            'project': cleaned_data
        }
        
        if dry_run:
            project_name = cleaned_data.get('name', cleaned_data.get('identifier', 'Unknown'))
            project_id = cleaned_data.get('identifier', 'Unknown')
            org_id = cleaned_data.get('orgIdentifier', org_identifier or 'Unknown')
            print(f"  [DRY RUN] Would create project: {project_name} ({project_id}) in org {org_id}")
            print(f"  [DRY RUN] Project data: {json.dumps(cleaned_data, indent=2)}")
            return True
        
        endpoint = "/ng/api/projects"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created project")
            return True
        else:
            print(f"Failed to create project: {response.status_code} - {response.text}")
            return False
    
    def list_pipelines(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all pipelines"""
        endpoint = "/pipeline/api/pipelines/list"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('POST', endpoint, params=params, data={
            'filterType': 'PipelineSetup',
            'page': 0,
            'size': 1000
        })
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('content', [])
        else:
            print(f"Failed to list pipelines: {response.status_code} - {response.text}")
            return []
    
    def get_pipeline_yaml(self, pipeline_identifier: str, org_identifier: Optional[str] = None, 
                         project_identifier: Optional[str] = None) -> Optional[str]:
        """Get pipeline YAML"""
        endpoint = f"/pipeline/api/pipelines/{pipeline_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('yamlPipeline', '')
        else:
            print(f"Failed to get pipeline YAML: {response.status_code} - {response.text}")
            return None
    
    def import_pipeline_yaml(self, yaml_content: str, org_identifier: Optional[str] = None,
                             project_identifier: Optional[str] = None) -> bool:
        """Import pipeline from YAML"""
        endpoint = "/pipeline/api/pipelines/import-pipeline"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        data = {
            'pipelineYaml': yaml_content,
            'isForceImport': False
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported pipeline")
            return True
        else:
            print(f"Failed to import pipeline: {response.status_code} - {response.text}")
            return False
    
    def list_services(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all services"""
        endpoint = "/ng/api/servicesV2"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('content', [])
        else:
            print(f"Failed to list services: {response.status_code} - {response.text}")
            return []
    
    def get_service_yaml(self, service_identifier: str, org_identifier: Optional[str] = None,
                        project_identifier: Optional[str] = None) -> Optional[str]:
        """Get service YAML"""
        endpoint = f"/ng/api/servicesV2/{service_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('yaml', '')
        else:
            print(f"Failed to get service YAML: {response.status_code} - {response.text}")
            return None
    
    def import_service_yaml(self, yaml_content: str, org_identifier: Optional[str] = None,
                           project_identifier: Optional[str] = None) -> bool:
        """Import service from YAML"""
        endpoint = "/ng/api/servicesV2/import"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        data = {
            'yaml': yaml_content
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported service")
            return True
        else:
            print(f"Failed to import service: {response.status_code} - {response.text}")
            return False
    
    def list_environments(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all environments"""
        endpoint = "/ng/api/environmentsV2"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('content', [])
        else:
            print(f"Failed to list environments: {response.status_code} - {response.text}")
            return []
    
    def get_environment_yaml(self, environment_identifier: str, org_identifier: Optional[str] = None,
                           project_identifier: Optional[str] = None) -> Optional[str]:
        """Get environment YAML"""
        endpoint = f"/ng/api/environmentsV2/{environment_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('yaml', '')
        else:
            print(f"Failed to get environment YAML: {response.status_code} - {response.text}")
            return None
    
    def import_environment_yaml(self, yaml_content: str, org_identifier: Optional[str] = None,
                               project_identifier: Optional[str] = None) -> bool:
        """Import environment from YAML"""
        endpoint = "/ng/api/environmentsV2/import"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        data = {
            'yaml': yaml_content
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported environment")
            return True
        else:
            print(f"Failed to import environment: {response.status_code} - {response.text}")
            return False
    
    def list_connectors(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all connectors"""
        endpoint = "/ng/api/connectors"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            content = data.get('data', {}).get('content', [])
            # Extract connector data from the "connector" key in each item
            connectors = []
            for item in content:
                connector = item.get('connector', item)  # Fallback to item itself if no "connector" key
                connectors.append(connector)
            return connectors
        else:
            print(f"Failed to list connectors: {response.status_code} - {response.text}")
            return []
    
    def get_connector_yaml(self, connector_identifier: str, org_identifier: Optional[str] = None,
                          project_identifier: Optional[str] = None) -> Optional[str]:
        """Get connector YAML"""
        endpoint = f"/ng/api/connectors/{connector_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            connector_data = data.get('data', {})
            # Extract connector from nested structure if present
            if 'connector' in connector_data:
                connector_data = connector_data['connector']
            # Remove null/None values recursively
            connector_data = remove_none_values(connector_data)
            # Ensure the data is wrapped in a connector key for Harness YAML format
            # If the top-level key is already 'connector', use as-is; otherwise wrap it
            if not connector_data or (isinstance(connector_data, dict) and 'connector' not in connector_data):
                connector_data = {'connector': connector_data}
            # Convert the connector data to YAML
            try:
                yaml_content = yaml.dump(connector_data, default_flow_style=False, sort_keys=False)
                return yaml_content
            except Exception as e:
                print(f"Failed to convert connector data to YAML: {e}")
                return None
        else:
            print(f"Failed to get connector YAML: {response.status_code} - {response.text}")
            return None
    
    def import_connector_yaml(self, yaml_content: str, org_identifier: Optional[str] = None,
                             project_identifier: Optional[str] = None) -> bool:
        """Import connector from YAML"""
        endpoint = "/ng/api/connectors/import"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        data = {
            'yaml': yaml_content
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported connector")
            return True
        else:
            print(f"Failed to import connector: {response.status_code} - {response.text}")
            return False
    
    def list_infrastructures(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all infrastructures"""
        endpoint = "/ng/api/infrastructures"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('content', [])
        else:
            print(f"Failed to list infrastructures: {response.status_code} - {response.text}")
            return []
    
    def get_infrastructure_yaml(self, infrastructure_identifier: str, environment_identifier: str,
                               org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> Optional[str]:
        """Get infrastructure YAML"""
        endpoint = f"/ng/api/infrastructures/{infrastructure_identifier}"
        params = {
            'environmentIdentifier': environment_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {}).get('yaml', '')
        else:
            print(f"Failed to get infrastructure YAML: {response.status_code} - {response.text}")
            return None
    
    def import_infrastructure_yaml(self, yaml_content: str, org_identifier: Optional[str] = None,
                                  project_identifier: Optional[str] = None) -> bool:
        """Import infrastructure from YAML"""
        endpoint = "/ng/api/infrastructures/import"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        data = {
            'yaml': yaml_content
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported infrastructure")
            return True
        else:
            print(f"Failed to import infrastructure: {response.status_code} - {response.text}")
            return False


class HarnessMigrator:
    """Main migration class"""
    
    def __init__(self, source_client: HarnessAPIClient, dest_client: Optional[HarnessAPIClient],
                 org_identifier: Optional[str] = None, project_identifier: Optional[str] = None,
                 dry_run: bool = False):
        self.source_client = source_client
        self.dest_client = dest_client
        self.org_identifier = org_identifier
        self.project_identifier = project_identifier
        self.dry_run = dry_run
        self.export_dir = Path("harness_exports")
        self.export_dir.mkdir(exist_ok=True)
    
    def _get_all_scopes(self) -> List[tuple]:
        """Get all scopes (account, orgs, projects) as (org_identifier, project_identifier) tuples"""
        scopes = []
        
        # Account level (None, None)
        scopes.append((None, None))
        
        # Organization level - get all organizations
        organizations = self.source_client.list_organizations()
        for org in organizations:
            org_data = org.get('organization', org)
            org_id = org_data.get('identifier', '')
            if org_id:
                scopes.append((org_id, None))
        
        # Project level - get all projects
        projects = self.source_client.list_projects()
        for project in projects:
            project_data = project.get('project', project)
            org_id = project_data.get('orgIdentifier', '')
            project_id = project_data.get('identifier', '')
            if org_id and project_id:
                scopes.append((org_id, project_id))
        
        return scopes
    
    def migrate_organizations(self) -> Dict[str, Any]:
        """Migrate organizations"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Organizations ===")
        organizations = self.source_client.list_organizations()
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        for org in organizations:
            org_data = org.get('organization', '')
            identifier = org_data.get('identifier', '')
            name = org_data.get('name', identifier)
            print(f"\nProcessing organization: {name} ({identifier})")
            
            if not org_data:
                print(f"  Failed to get data for organization {name}")
                results['failed'] += 1
                continue
            
            # Save exported data as JSON and YAML for backup
            yaml_file = self.export_dir / f"organization_{identifier}.yaml"
            yaml_file.write_text(yaml.dump(org_data, default_flow_style=False, sort_keys=False))
            print(f"  Exported data to {yaml_file}")
            
            # Create in destination (use dry_run parameter)
            if self.dry_run and self.dest_client is None:
                # In dry run mode without dest client, just show what would be created
                cleaned_data = clean_for_creation(org_data)
                org_name = cleaned_data.get('name', cleaned_data.get('identifier', 'Unknown'))
                org_id = cleaned_data.get('identifier', 'Unknown')
                print(f"  [DRY RUN] Would create organization: {org_name} ({org_id})")
                results['success'] += 1
            elif self.dest_client:
                if self.dest_client.create_organization(org_data, dry_run=self.dry_run):
                    results['success'] += 1
                else:
                    results['failed'] += 1
            else:
                print(f"  Error: No destination client available")
                results['failed'] += 1
            
            time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_projects(self) -> Dict[str, Any]:
        """Migrate projects"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Projects ===")
        
        # List all projects across all organizations (API fetches all when no org_identifier is provided)
        projects = self.source_client.list_projects()
        
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        for project in projects:
            # Extract project data from the response structure
            project_data = project.get('project', project)
            identifier = project_data.get('identifier', '')
            name = project_data.get('name', identifier)
            org_id = project_data.get('orgIdentifier', '')
            print(f"\nProcessing project: {name} ({identifier})" + (f" in org {org_id}" if org_id else ""))
            
            if not project_data:
                print(f"  Failed to get data for project {name}")
                results['failed'] += 1
                continue
            
            # Remove null values
            project_data = remove_none_values(project_data)
            
            # Save exported data as YAML for backup
            yaml_file = self.export_dir / f"project_{identifier}.yaml"
            yaml_file.write_text(yaml.dump(project_data, default_flow_style=False, sort_keys=False))
            print(f"  Exported data to {yaml_file}")
            
            # Create in destination (use dry_run parameter)
            if self.dry_run and self.dest_client is None:
                # In dry run mode without dest client, just show what would be created
                cleaned_data = clean_for_creation(project_data)
                project_name = cleaned_data.get('name', cleaned_data.get('identifier', 'Unknown'))
                project_id = cleaned_data.get('identifier', 'Unknown')
                org_id_display = cleaned_data.get('orgIdentifier', org_id or 'Unknown')
                print(f"  [DRY RUN] Would create project: {project_name} ({project_id}) in org {org_id_display}")
                results['success'] += 1
            elif self.dest_client:
                if self.dest_client.create_project(project_data, org_id, dry_run=self.dry_run):
                    results['success'] += 1
                else:
                    results['failed'] += 1
            else:
                print(f"  Error: No destination client available")
                results['failed'] += 1
            
            time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_connectors(self) -> Dict[str, Any]:
        """Migrate connectors at all scopes (account, org, project)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Connectors ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing connectors at {scope_label} ---")
            
            connectors = self.source_client.list_connectors(org_id, project_id)
            
            for connector in connectors:
                connector_data = connector.get('connector', connector)
                identifier = connector_data.get('identifier', '')
                name = connector_data.get('name', identifier)
                print(f"\nProcessing connector: {name} ({identifier}) at {scope_label}")
                
                yaml_content = self.source_client.get_connector_yaml(
                    identifier, org_id, project_id
                )
                
                if not yaml_content:
                    print(f"  Failed to get YAML for connector {name}")
                    results['failed'] += 1
                    continue
                
                # Save exported YAML with scope in filename
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                export_file = self.export_dir / f"connector_{identifier}{scope_suffix}.yaml"
                export_file.write_text(yaml_content)
                print(f"  Exported YAML to {export_file}")
                
                # Import to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would import connector to destination account")
                    results['success'] += 1
                else:
                    if self.dest_client.import_connector_yaml(
                        yaml_content, org_id, project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_environments(self) -> Dict[str, Any]:
        """Migrate environments at all scopes (account, org, project)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Environments ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing environments at {scope_label} ---")
            
            environments = self.source_client.list_environments(org_id, project_id)
            
            for env in environments:
                identifier = env.get('identifier', '')
                name = env.get('name', identifier)
                print(f"\nProcessing environment: {name} ({identifier}) at {scope_label}")
                
                yaml_content = self.source_client.get_environment_yaml(
                    identifier, org_id, project_id
                )
                
                if not yaml_content:
                    print(f"  Failed to get YAML for environment {name}")
                    results['failed'] += 1
                    continue
                
                # Save exported YAML with scope in filename
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                export_file = self.export_dir / f"environment_{identifier}{scope_suffix}.yaml"
                export_file.write_text(yaml_content)
                print(f"  Exported YAML to {export_file}")
                
                # Import to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would import environment to destination account")
                    results['success'] += 1
                else:
                    if self.dest_client.import_environment_yaml(
                        yaml_content, org_id, project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_infrastructures(self) -> Dict[str, Any]:
        """Migrate infrastructures at all scopes (account, org, project)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Infrastructures ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing infrastructures at {scope_label} ---")
            
            infrastructures = self.source_client.list_infrastructures(org_id, project_id)
            
            for infra in infrastructures:
                identifier = infra.get('identifier', '')
                env_identifier = infra.get('envIdentifier', '')
                name = infra.get('name', identifier)
                print(f"\nProcessing infrastructure: {name} ({identifier}) at {scope_label}")
                
                yaml_content = self.source_client.get_infrastructure_yaml(
                    identifier, env_identifier, org_id, project_id
                )
                
                if not yaml_content:
                    print(f"  Failed to get YAML for infrastructure {name}")
                    results['failed'] += 1
                    continue
                
                # Save exported YAML with scope in filename
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                export_file = self.export_dir / f"infrastructure_{identifier}{scope_suffix}.yaml"
                export_file.write_text(yaml_content)
                print(f"  Exported YAML to {export_file}")
                
                # Import to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would import infrastructure to destination account")
                    results['success'] += 1
                else:
                    if self.dest_client.import_infrastructure_yaml(
                        yaml_content, org_id, project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_services(self) -> Dict[str, Any]:
        """Migrate services at all scopes (account, org, project)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Services ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing services at {scope_label} ---")
            
            services = self.source_client.list_services(org_id, project_id)
            
            for service in services:
                identifier = service.get('identifier', '')
                name = service.get('name', identifier)
                print(f"\nProcessing service: {name} ({identifier}) at {scope_label}")
                
                yaml_content = self.source_client.get_service_yaml(
                    identifier, org_id, project_id
                )
                
                if not yaml_content:
                    print(f"  Failed to get YAML for service {name}")
                    results['failed'] += 1
                    continue
                
                # Save exported YAML with scope in filename
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                export_file = self.export_dir / f"service_{identifier}{scope_suffix}.yaml"
                export_file.write_text(yaml_content)
                print(f"  Exported YAML to {export_file}")
                
                # Import to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would import service to destination account")
                    results['success'] += 1
                else:
                    if self.dest_client.import_service_yaml(
                        yaml_content, org_id, project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_pipelines(self) -> Dict[str, Any]:
        """Migrate pipelines at all scopes (account, org, project)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Pipelines ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing pipelines at {scope_label} ---")
            
            pipelines = self.source_client.list_pipelines(org_id, project_id)
            
            for pipeline in pipelines:
                identifier = pipeline.get('identifier', '')
                name = pipeline.get('name', identifier)
                print(f"\nProcessing pipeline: {name} ({identifier}) at {scope_label}")
                
                yaml_content = self.source_client.get_pipeline_yaml(
                    identifier, org_id, project_id
                )
                
                if not yaml_content:
                    print(f"  Failed to get YAML for pipeline {name}")
                    results['failed'] += 1
                    continue
                
                # Save exported YAML with scope in filename
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                export_file = self.export_dir / f"pipeline_{identifier}{scope_suffix}.yaml"
                export_file.write_text(yaml_content)
                print(f"  Exported YAML to {export_file}")
                
                # Import to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would import pipeline to destination account")
                    results['success'] += 1
                else:
                    if self.dest_client.import_pipeline_yaml(
                        yaml_content, org_id, project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_all(self, resource_types: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """Migrate all resources"""
        if resource_types is None:
            resource_types = ['organizations', 'projects', 'connectors', 'environments', 'infrastructures', 'services', 'pipelines']
        
        all_results = {}
        
        # Migrate in dependency order - organizations and projects first
        if 'organizations' in resource_types:
            all_results['organizations'] = self.migrate_organizations()
        
        if 'projects' in resource_types:
            all_results['projects'] = self.migrate_projects()
        
        # Then migrate other resources
        if 'connectors' in resource_types:
            all_results['connectors'] = self.migrate_connectors()
        
        if 'environments' in resource_types:
            all_results['environments'] = self.migrate_environments()
        
        if 'infrastructures' in resource_types:
            all_results['infrastructures'] = self.migrate_infrastructures()
        
        if 'services' in resource_types:
            all_results['services'] = self.migrate_services()
        
        if 'pipelines' in resource_types:
            all_results['pipelines'] = self.migrate_pipelines()
        
        return all_results


def main():
    parser = argparse.ArgumentParser(description='Migrate Harness account resources')
    parser.add_argument('--source-api-key', required=True, help='Source account API key')
    parser.add_argument('--source-account-id', required=True, help='Source account ID')
    parser.add_argument('--dest-api-key', help='Destination account API key (not required for dry-run)')
    parser.add_argument('--dest-account-id', help='Destination account ID (not required for dry-run)')
    parser.add_argument('--org-identifier', help='Organization identifier (optional)')
    parser.add_argument('--project-identifier', help='Project identifier (optional)')
    parser.add_argument('--resource-types', nargs='+', 
                       choices=['organizations', 'projects', 'connectors', 'environments', 'infrastructures', 'services', 'pipelines'],
                       default=['organizations', 'projects', 'connectors', 'environments', 'infrastructures', 'services', 'pipelines'],
                       help='Resource types to migrate')
    parser.add_argument('--base-url', default='https://app.harness.io/gateway',
                       help='Harness API base URL')
    parser.add_argument('--dry-run', action='store_true',
                       help='Dry run mode: list and export resources without migrating')
    
    args = parser.parse_args()
    
    # Validate arguments
    if not args.dry_run:
        if not args.dest_api_key:
            parser.error("--dest-api-key is required when not using --dry-run")
        if not args.dest_account_id:
            parser.error("--dest-account-id is required when not using --dry-run")
    
    # Create API clients
    source_client = HarnessAPIClient(args.source_api_key, args.source_account_id, args.base_url)
    dest_client = None
    if not args.dry_run:
        dest_client = HarnessAPIClient(args.dest_api_key, args.dest_account_id, args.base_url)
    
    # Create migrator
    migrator = HarnessMigrator(
        source_client, dest_client, args.org_identifier, args.project_identifier, args.dry_run
    )
    
    # Perform migration
    mode = "DRY RUN - Listing" if args.dry_run else "Migrating"
    print(f"Starting Harness account {mode.lower()}...")
    print(f"Source Account: {args.source_account_id}")
    if not args.dry_run:
        print(f"Destination Account: {args.dest_account_id}")
    if args.org_identifier:
        print(f"Organization: {args.org_identifier}")
    if args.project_identifier:
        print(f"Project: {args.project_identifier}")
    print(f"Resource Types: {', '.join(args.resource_types)}")
    if args.dry_run:
        print("\n[DRY RUN MODE] Resources will be listed and exported but NOT migrated")
    
    results = migrator.migrate_all(args.resource_types)
    
    # Print summary
    print("\n" + "="*50)
    summary_title = "DRY RUN SUMMARY" if args.dry_run else "MIGRATION SUMMARY"
    print(summary_title)
    print("="*50)
    for resource_type, result in results.items():
        print(f"\n{resource_type.upper()}:")
        if args.dry_run:
            print(f"  Found/Exported: {result['success']}")
        else:
            print(f"  Success: {result['success']}")
        print(f"  Failed: {result['failed']}")
        print(f"  Skipped: {result['skipped']}")
    
    total_success = sum(r['success'] for r in results.values())
    total_failed = sum(r['failed'] for r in results.values())
    
    print(f"\nTOTAL:")
    if args.dry_run:
        print(f"  Found/Exported: {total_success}")
    else:
        print(f"  Success: {total_success}")
    print(f"  Failed: {total_failed}")
    print(f"\nExported YAML files saved to: {migrator.export_dir.absolute()}")


if __name__ == "__main__":
    main()
