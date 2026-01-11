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
from typing import Dict, List, Optional, Any, Union
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


def extract_account_id_from_api_key(api_key: str) -> str:
    """Extract account ID from Harness API key format: sat.ACCOUNT_ID.rest.of.key"""
    try:
        parts = api_key.split('.')
        if len(parts) >= 2:
            return parts[1]
        else:
            raise ValueError("Invalid API key format. Expected format: sat.ACCOUNT_ID.rest.of.key")
    except Exception as e:
        raise ValueError(f"Failed to extract account ID from API key: {e}")


class HarnessAPIClient:
    """Client for interacting with Harness API"""
    
    def __init__(self, api_key: str, account_id: Optional[str] = None, base_url: str = "https://app.harness.io/gateway"):
        self.api_key = api_key
        # Extract account ID from API key if not provided
        if account_id:
            self.account_id = account_id
        else:
            self.account_id = extract_account_id_from_api_key(api_key)
        self.base_url = base_url
        self.headers = {
            'x-api-key': api_key,
            'Content-Type': 'application/json'
        }
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Union[Dict, str]] = None, 
                     params: Optional[Dict] = None, headers: Optional[Dict] = None) -> requests.Response:
        """Make an API request"""
        url = f"{self.base_url}{endpoint}"
        if params is None:
            params = {}
        params['accountIdentifier'] = self.account_id
        
        # Merge custom headers with default headers
        request_headers = self.headers.copy()
        if headers:
            request_headers.update(headers)
        
        try:
            if method.upper() == 'GET':
                response = requests.get(url, headers=request_headers, params=params, json=data if isinstance(data, dict) else None)
            elif method.upper() == 'POST':
                # If data is a string, send it as raw data; otherwise send as JSON
                if isinstance(data, str):
                    response = requests.post(url, headers=request_headers, params=params, data=data)
                else:
                    response = requests.post(url, headers=request_headers, params=params, json=data)
            elif method.upper() == 'PUT':
                response = requests.put(url, headers=request_headers, params=params, json=data if isinstance(data, dict) else None)
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
    
    def get_pipeline_data(self, pipeline_identifier: str, org_identifier: Optional[str] = None, 
                         project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get pipeline data (for both GitX and Inline detection)"""
        endpoint = f"/pipeline/api/pipelines/{pipeline_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Extract from nested 'pipeline' key if present, fallback to 'data' itself
            pipeline_data = data.get('data', {}).get('pipeline', data.get('data', {}))
            return pipeline_data
        else:
            print(f"Failed to get pipeline data: {response.status_code} - {response.text}")
            return None
    
    def get_pipeline_yaml(self, pipeline_identifier: str, org_identifier: Optional[str] = None, 
                         project_identifier: Optional[str] = None) -> Optional[str]:
        """Get pipeline YAML"""
        pipeline_data = self.get_pipeline_data(pipeline_identifier, org_identifier, project_identifier)
        if pipeline_data:
            return pipeline_data.get('yamlPipeline', '')
        return None
    
    def create_pipeline(self, yaml_content: str, identifier: str, name: str,
                       org_identifier: Optional[str] = None, project_identifier: Optional[str] = None,
                       tags: Optional[Dict[str, str]] = None) -> bool:
        """Create pipeline from YAML content (for inline resources)"""
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        endpoint = "/v1/orgs/{org}/projects/{project}/pipelines"
        endpoint = endpoint.format(org=org_identifier, project=project_identifier)

        # Build JSON payload with YAML content and identifiers
        data = {
            'pipeline_yaml': yaml_content,
            'accountId': self.account_id,
            'identifier': identifier,
            'name': name,
            'orgIdentifier': org_identifier,
            'projectIdentifier': project_identifier
        }
        
        # Add tags if provided
        if tags:
            data['tags'] = tags
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created pipeline")
            return True
        else:
            print(f"Failed to create pipeline: {response.status_code} - {response.text}")
            return False
    
    def import_pipeline_yaml(self, git_details: Dict, org_identifier: Optional[str] = None,
                             project_identifier: Optional[str] = None) -> bool:
        """Import pipeline from Git location (for GitX resources only)"""
        endpoint = "/pipeline/api/pipelines/import-pipeline"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Add git details fields to query parameters
        if 'repoName' in git_details:
            params['repoName'] = git_details['repoName']
        if 'branch' in git_details:
            params['branch'] = git_details['branch']
        if 'filePath' in git_details:
            params['filePath'] = git_details['filePath']
        
        # No data body for GitX import
        response = self._make_request('POST', endpoint, params=params, data=None)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported pipeline from GitX")
            return True
        else:
            print(f"Failed to import pipeline from GitX: {response.status_code} - {response.text}")
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
    
    def get_service_data(self, service_identifier: str, org_identifier: Optional[str] = None,
                        project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get service data (for both GitX and Inline detection)"""
        endpoint = f"/ng/api/servicesV2/{service_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Extract from nested 'service' key if present, fallback to 'data' itself
            service_data = data.get('data', {}).get('service', data.get('data', {}))
            return service_data
        else:
            print(f"Failed to get service data: {response.status_code} - {response.text}")
            return None
    
    def get_service_yaml(self, service_identifier: str, org_identifier: Optional[str] = None,
                        project_identifier: Optional[str] = None) -> Optional[str]:
        """Get service YAML"""
        service_data = self.get_service_data(service_identifier, org_identifier, project_identifier)
        if service_data:
            return service_data.get('yaml', '')
        return None
    
    def create_service(self, yaml_content: str, identifier: str, name: str,
                      org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Create service from YAML content (for inline resources)"""
        endpoint = "/ng/api/servicesV2"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Build JSON payload with YAML content and identifiers
        data = {
            'yaml': yaml_content,
            'accountId': self.account_id,
            'identifier': identifier,
            'name': name,
            'orgIdentifier': org_identifier,
            'projectIdentifier': project_identifier
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created service")
            return True
        else:
            print(f"Failed to create service: {response.status_code} - {response.text}")
            return False
    
    def import_service_yaml(self, git_details: Dict, service_identifier: str,
                           connector_ref: Optional[str] = None,
                           org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Import service from Git location (for GitX resources only)"""
        endpoint = "/ng/api/servicesV2/import"
        params = {
            'accountIdentifier': self.account_id,
            'serviceIdentifier': service_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Add connector reference if provided
        if connector_ref:
            params['connectorRef'] = connector_ref
        
        # Add git details fields to query parameters
        if 'repoName' in git_details:
            params['repoName'] = git_details['repoName']
        if 'branch' in git_details:
            params['branch'] = git_details['branch']
        if 'filePath' in git_details:
            params['filePath'] = git_details['filePath']
        
        # No data body for GitX import
        response = self._make_request('POST', endpoint, params=params, data=None)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported service from GitX")
            return True
        else:
            print(f"Failed to import service from GitX: {response.status_code} - {response.text}")
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
    
    def get_environment_data(self, environment_identifier: str, org_identifier: Optional[str] = None,
                            project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get environment data (for both GitX and Inline detection)"""
        endpoint = f"/ng/api/environmentsV2/{environment_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Extract from nested 'environment' key if present, fallback to 'data' itself
            env_data = data.get('data', {}).get('environment', data.get('data', {}))
            return env_data
        else:
            print(f"Failed to get environment data: {response.status_code} - {response.text}")
            return None
    
    def get_environment_yaml(self, environment_identifier: str, org_identifier: Optional[str] = None,
                           project_identifier: Optional[str] = None) -> Optional[str]:
        """Get environment YAML"""
        env_data = self.get_environment_data(environment_identifier, org_identifier, project_identifier)
        if env_data:
            return env_data.get('yaml', '')
        return None
    
    def is_gitx_resource(self, resource_data: Dict) -> bool:
        """Determine if resource is stored in GitX or Inline"""
        # Check storeType field
        if resource_data.get('storeType') == 'REMOTE':
            return True
        if resource_data.get('storeType') == 'INLINE':
            return False
        
        # Check for gitDetails or entityGitDetails field
        if ('gitDetails' in resource_data and resource_data.get('gitDetails')) or \
            ('entityGitDetails' in resource_data and resource_data.get('entityGitDetails')):
            return True
        
        # Check for git-related fields
        if 'repo' in resource_data or 'branch' in resource_data:
            return True
        
        # Check for yaml field - if present and no storeType, might be inline with YAML
        # But if gitDetails exist, it's GitX
        if 'yaml' in resource_data and resource_data.get('yaml'):
            # If there's gitDetails or entityGitDetails, it's GitX
            if 'gitDetails' in resource_data or 'entityGitDetails' in resource_data:
                return True
            # Otherwise assume inline (YAML content stored inline)
            return False
        
        # Default: assume Inline if no indicators found
        return False
    
    def create_environment(self, yaml_content: str, identifier: str, type: str, name: str,
                          org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Create environment from YAML content (for inline resources)"""
        endpoint = "/ng/api/environmentsV2"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Build JSON payload with YAML content and identifiers
        data = {
            'yaml': yaml_content,
            'accountId': self.account_id,
            'identifier': identifier,
            'type': type,
            'name': name,
            'orgIdentifier': org_identifier,
            'projectIdentifier': project_identifier
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created environment")
            return True
        else:
            print(f"Failed to create environment: {response.status_code} - {response.text}")
            return False
    
    def import_environment_yaml(self, git_details: Dict, environment_identifier: str,
                               connector_ref: Optional[str] = None,
                               org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Import environment from Git location (for GitX resources only)"""
        endpoint = "/ng/api/environmentsV2/import"
        params = {
            'accountIdentifier': self.account_id,
            'environmentIdentifier': environment_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Add connector reference if provided
        if connector_ref:
            params['connectorRef'] = connector_ref
        
        # Add git details fields to query parameters
        if 'repoName' in git_details:
            params['repoName'] = git_details['repoName']
        if 'branch' in git_details:
            params['branch'] = git_details['branch']
        if 'filePath' in git_details:
            params['filePath'] = git_details['filePath']
        
        # No data body for GitX import
        response = self._make_request('POST', endpoint, params=params, data=None)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported environment from GitX")
            return True
        else:
            print(f"Failed to import environment from GitX: {response.status_code} - {response.text}")
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
    
    def create_connector_yaml(self, yaml_content: str, org_identifier: Optional[str] = None,
                             project_identifier: Optional[str] = None) -> bool:
        """Create connector from YAML document"""
        endpoint = "/ng/api/connectors"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Connectors are created by passing YAML directly in the request body
        # The Content-Type should be text/yaml or application/yaml
        headers = self.headers.copy()
        headers['Content-Type'] = 'text/yaml'
        
        url = f"{self.base_url}{endpoint}"
        params['accountIdentifier'] = self.account_id
        
        try:
            response = requests.post(url, headers=headers, params=params, data=yaml_content)
            
            if response.status_code in [200, 201]:
                print(f"Successfully created connector")
                return True
            else:
                print(f"Failed to create connector: {response.status_code} - {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            return False
    
    def list_infrastructures(self, environment_identifier: str, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all infrastructures for a specific environment"""
        endpoint = "/ng/api/infrastructures"
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
            return data.get('data', {}).get('content', [])
        else:
            print(f"Failed to list infrastructures: {response.status_code} - {response.text}")
            return []
    
    def get_infrastructure_data(self, infrastructure_identifier: str, environment_identifier: str,
                               org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get infrastructure data (for both GitX and Inline detection)"""
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
            # Extract from nested 'infrastructure' key if present, fallback to 'data' itself
            infra_data = data.get('data', {}).get('infrastructure', data.get('data', {}))
            return infra_data
        else:
            print(f"Failed to get infrastructure data: {response.status_code} - {response.text}")
            return None
    
    def get_infrastructure_yaml(self, infrastructure_identifier: str, environment_identifier: str,
                               org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> Optional[str]:
        """Get infrastructure YAML"""
        infra_data = self.get_infrastructure_data(infrastructure_identifier, environment_identifier, org_identifier, project_identifier)
        if infra_data:
            return infra_data.get('yaml', '')
        return None
    
    def create_infrastructure(self, yaml_content: str, environment_identifier: str,
                            org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Create infrastructure from YAML content (for inline resources)"""
        endpoint = "/ng/api/infrastructures"
        params = {
            'environmentIdentifier': environment_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Build JSON payload with YAML content and identifiers
        data = {
            'yaml': yaml_content,
            'accountId': self.account_id,
            'environmentIdentifier': environment_identifier
        }
        if org_identifier:
            data['organizationId'] = org_identifier
        if project_identifier:
            data['projectId'] = project_identifier
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created infrastructure")
            return True
        else:
            print(f"Failed to create infrastructure: {response.status_code} - {response.text}")
            return False
    
    def import_infrastructure_yaml(self, git_details: Dict, infrastructure_identifier: str,
                                  environment_identifier: str,
                                  connector_ref: Optional[str] = None,
                                  org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Import infrastructure from Git location (for GitX resources only)"""
        endpoint = "/ng/api/infrastructures/import"
        params = {
            'accountIdentifier': self.account_id,
            'infrastructureIdentifier': infrastructure_identifier,
            'environmentIdentifier': environment_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Add connector reference if provided
        if connector_ref:
            params['connectorRef'] = connector_ref
        
        # Add git details fields to query parameters
        if 'repoName' in git_details:
            params['repoName'] = git_details['repoName']
        if 'branch' in git_details:
            params['branch'] = git_details['branch']
        if 'filePath' in git_details:
            params['filePath'] = git_details['filePath']
        
        # No data body for GitX import
        response = self._make_request('POST', endpoint, params=params, data=None)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported infrastructure from GitX")
            return True
        else:
            print(f"Failed to import infrastructure from GitX: {response.status_code} - {response.text}")
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
                
                # Create connector in destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create connector to destination account")
                    results['success'] += 1
                else:
                    if self.dest_client.create_connector_yaml(
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
                # Extract environment data from nested structure if present
                env_item = env.get('environment', env)
                identifier = env_item.get('identifier', '')
                name = env_item.get('name', identifier)
                print(f"\nProcessing environment: {name} ({identifier}) at {scope_label}")
                
                # Get environment data to detect storage type
                env_data = self.source_client.get_environment_data(
                    identifier, org_id, project_id
                )
                
                if not env_data:
                    print(f"  Failed to get data for environment {name}")
                    results['failed'] += 1
                    continue
                
                # Detect if environment is GitX or Inline
                is_gitx = self.source_client.is_gitx_resource(env_data)
                storage_type = "GitX" if is_gitx else "Inline"
                print(f"  Environment storage type: {storage_type}")
                
                # Save exported data
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                yaml_content = None
                git_details = None
                
                if is_gitx:
                    # GitX: Get git details for import
                    git_details = env_data.get('entityGitDetails', {})
                    if not git_details:
                        print(f"  Failed to get git details for GitX environment {name}")
                        results['failed'] += 1
                        continue
                    # Also get YAML for export
                    yaml_content = env_data.get('yaml', '')
                    export_file = self.export_dir / f"environment_{identifier}{scope_suffix}.yaml"
                    if yaml_content:
                        export_file.write_text(yaml_content)
                        print(f"  Exported YAML to {export_file}")
                else:
                    # Inline: Get YAML content for import
                    yaml_content = env_data.get('yaml', '')
                    if not yaml_content:
                        print(f"  Failed to get YAML for inline environment {name}")
                        results['failed'] += 1
                        continue
                    export_file = self.export_dir / f"environment_{identifier}{scope_suffix}.yaml"
                    export_file.write_text(yaml_content)
                    print(f"  Exported YAML to {export_file}")
                
                # Import to destination (skip in dry-run mode)
                if self.dry_run:
                    if is_gitx:
                        print(f"  [DRY RUN] Would import environment (GitX) from git location")
                    else:
                        print(f"  [DRY RUN] Would create environment (Inline) with YAML content")
                    results['success'] += 1
                else:
                    if is_gitx:
                        # GitX: Use import endpoint with git details
                        connector_ref = env_data.get('connectorRef')
                        if self.dest_client.import_environment_yaml(
                            git_details=git_details, environment_identifier=identifier,
                            connector_ref=connector_ref,
                            org_identifier=org_id, project_identifier=project_id
                        ):
                            results['success'] += 1
                        else:
                            results['failed'] += 1
                    else:
                        # Inline: Use create endpoint with YAML content
                        env_type = env_data.get('type', 'Production')  # Default to Production if not specified
                        if self.dest_client.create_environment(
                            yaml_content=yaml_content, identifier=identifier, type=env_type, name=name,
                            org_identifier=org_id, project_identifier=project_id
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
            
            # First, get all environments for this scope
            environments = self.source_client.list_environments(org_id, project_id)
            
            if not environments:
                print(f"  No environments found at {scope_label}, skipping infrastructures")
                continue
            
            # Iterate through each environment to find infrastructures
            for env in environments:
                # Extract environment data from nested structure if present
                env_item = env.get('environment', env)
                env_identifier = env_item.get('identifier', '')
                env_name = env_item.get('name', env_identifier)
                
                if not env_identifier:
                    continue
                
                print(f"\n  Checking infrastructures for environment: {env_name} ({env_identifier})")
                
                # Get infrastructures for this environment
                infrastructures = self.source_client.list_infrastructures(env_identifier, org_id, project_id)
                
                if not infrastructures:
                    print(f"    No infrastructures found for environment {env_name}")
                    continue
                
                for infra in infrastructures:
                    # Extract infrastructure data from nested structure if present
                    infra_item = infra.get('infrastructure', infra)
                    identifier = infra_item.get('identifier', '')
                    name = infra_item.get('name', identifier)
                    print(f"\nProcessing infrastructure: {name} ({identifier}) in environment {env_name} at {scope_label}")
                    
                    # Get infrastructure data to detect storage type
                    infra_data = self.source_client.get_infrastructure_data(
                        identifier, env_identifier, org_id, project_id
                    )
                    
                    if not infra_data:
                        print(f"  Failed to get data for infrastructure {name}")
                        results['failed'] += 1
                        continue
                    
                    # Detect if infrastructure is GitX or Inline
                    is_gitx = self.source_client.is_gitx_resource(infra_data)
                    storage_type = "GitX" if is_gitx else "Inline"
                    print(f"  Infrastructure storage type: {storage_type}")
                    
                    # Save exported data
                    scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                    
                    yaml_content = None
                    git_details = None
                    
                    if is_gitx:
                        # GitX: Get git details for import
                        git_details = infra_data.get('entityGitDetails', {}) or infra_data.get('gitDetails', {})
                        if not git_details:
                            print(f"  Failed to get git details for GitX infrastructure {name}")
                            results['failed'] += 1
                            continue
                        # Also get YAML for export
                        yaml_content = infra_data.get('yaml', '')
                        export_file = self.export_dir / f"infrastructure_{identifier}{scope_suffix}.yaml"
                        if yaml_content:
                            export_file.write_text(yaml_content)
                            print(f"  Exported YAML to {export_file}")
                    else:
                        # Inline: Get YAML content for import
                        yaml_content = infra_data.get('yaml', '')
                        if not yaml_content:
                            print(f"  Failed to get YAML for inline infrastructure {name}")
                            results['failed'] += 1
                            continue
                        export_file = self.export_dir / f"infrastructure_{identifier}{scope_suffix}.yaml"
                        export_file.write_text(yaml_content)
                        print(f"  Exported YAML to {export_file}")
                    
                    # Import to destination (skip in dry-run mode)
                    if self.dry_run:
                        if is_gitx:
                            print(f"  [DRY RUN] Would import infrastructure (GitX) from git location")
                        else:
                            print(f"  [DRY RUN] Would create infrastructure (Inline) with YAML content")
                        results['success'] += 1
                    else:
                        if is_gitx:
                            # GitX: Use import endpoint with git details
                            connector_ref = infra_data.get('connectorRef')
                            if self.dest_client.import_infrastructure_yaml(
                                git_details=git_details, infrastructure_identifier=identifier,
                                environment_identifier=env_identifier,
                                connector_ref=connector_ref,
                                org_identifier=org_id, project_identifier=project_id
                            ):
                                results['success'] += 1
                            else:
                                results['failed'] += 1
                        else:
                            # Inline: Use create endpoint with YAML content
                            if self.dest_client.create_infrastructure(
                                yaml_content=yaml_content, environment_identifier=env_identifier,
                                org_identifier=org_id, project_identifier=project_id
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
                # Extract service data from nested structure if present
                service_item = service.get('service', service)
                identifier = service_item.get('identifier', '')
                name = service_item.get('name', identifier)
                print(f"\nProcessing service: {name} ({identifier}) at {scope_label}")
                
                # Get service data to detect storage type
                service_data = self.source_client.get_service_data(
                    identifier, org_id, project_id
                )
                
                if not service_data:
                    print(f"  Failed to get data for service {name}")
                    results['failed'] += 1
                    continue
                
                # Detect if service is GitX or Inline
                is_gitx = self.source_client.is_gitx_resource(service_data)
                storage_type = "GitX" if is_gitx else "Inline"
                print(f"  Service storage type: {storage_type}")
                
                # Save exported data
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                yaml_content = None
                git_details = None
                
                if is_gitx:
                    # GitX: Get git details for import
                    git_details = service_data.get('entityGitDetails', {}) or service_data.get('gitDetails', {})
                    if not git_details:
                        print(f"  Failed to get git details for GitX service {name}")
                        results['failed'] += 1
                        continue
                    # Also get YAML for export
                    yaml_content = service_data.get('yaml', '')
                    export_file = self.export_dir / f"service_{identifier}{scope_suffix}.yaml"
                    if yaml_content:
                        export_file.write_text(yaml_content)
                        print(f"  Exported YAML to {export_file}")
                else:
                    # Inline: Get YAML content for import
                    yaml_content = service_data.get('yaml', '')
                    if not yaml_content:
                        print(f"  Failed to get YAML for inline service {name}")
                        results['failed'] += 1
                        continue
                    export_file = self.export_dir / f"service_{identifier}{scope_suffix}.yaml"
                    export_file.write_text(yaml_content)
                    print(f"  Exported YAML to {export_file}")
                
                # Import to destination (skip in dry-run mode)
                if self.dry_run:
                    if is_gitx:
                        print(f"  [DRY RUN] Would import service (GitX) from git location")
                    else:
                        print(f"  [DRY RUN] Would create service (Inline) with YAML content")
                    results['success'] += 1
                else:
                    if is_gitx:
                        # GitX: Use import endpoint with git details
                        connector_ref = service_data.get('connectorRef')
                        if self.dest_client.import_service_yaml(
                            git_details=git_details, service_identifier=identifier,
                            connector_ref=connector_ref,
                            org_identifier=org_id, project_identifier=project_id
                        ):
                            results['success'] += 1
                        else:
                            results['failed'] += 1
                    else:
                        # Inline: Use create endpoint with YAML content
                        if self.dest_client.create_service(
                            yaml_content=yaml_content, identifier=identifier, name=name,
                            org_identifier=org_id, project_identifier=project_id
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
                # Extract pipeline data from nested structure if present
                pipeline_item = pipeline.get('pipeline', pipeline)
                identifier = pipeline_item.get('identifier', '')
                name = pipeline_item.get('name', identifier)
                print(f"\nProcessing pipeline: {name} ({identifier}) at {scope_label}")
                
                # Get pipeline data to detect storage type
                pipeline_data = self.source_client.get_pipeline_data(
                    identifier, org_id, project_id
                )
                
                if not pipeline_data:
                    print(f"  Failed to get data for pipeline {name}")
                    results['failed'] += 1
                    continue
                
                # Detect if pipeline is GitX or Inline
                is_gitx = self.source_client.is_gitx_resource(pipeline_data)
                storage_type = "GitX" if is_gitx else "Inline"
                print(f"  Pipeline storage type: {storage_type}")
                
                # Save exported data
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                yaml_content = None
                git_details = None
                
                if is_gitx:
                    # GitX: Get git details for import
                    git_details = pipeline_data.get('gitDetails', {})
                    if not git_details:
                        print(f"  Failed to get git details for GitX pipeline {name}")
                        results['failed'] += 1
                        continue
                    # Also get YAML for export
                    yaml_content = pipeline_data.get('yamlPipeline', '')
                    export_file = self.export_dir / f"pipeline_{identifier}{scope_suffix}.yaml"
                    if yaml_content:
                        export_file.write_text(yaml_content)
                        print(f"  Exported YAML to {export_file}")
                else:
                    # Inline: Get YAML content for import
                    yaml_content = pipeline_data.get('yamlPipeline', '')
                    if not yaml_content:
                        print(f"  Failed to get YAML for inline pipeline {name}")
                        results['failed'] += 1
                        continue
                    export_file = self.export_dir / f"pipeline_{identifier}{scope_suffix}.yaml"
                    export_file.write_text(yaml_content)
                    print(f"  Exported YAML to {export_file}")
                
                # Import to destination (skip in dry-run mode)
                if self.dry_run:
                    if is_gitx:
                        print(f"  [DRY RUN] Would import pipeline (GitX) from git location")
                    else:
                        print(f"  [DRY RUN] Would create pipeline (Inline) with YAML content")
                    results['success'] += 1
                else:
                    if is_gitx:
                        # GitX: Use import endpoint with git details
                        if self.dest_client.import_pipeline_yaml(
                            git_details=git_details, org_identifier=org_id, project_identifier=project_id
                        ):
                            results['success'] += 1
                        else:
                            results['failed'] += 1
                    else:
                        # Inline: Use create endpoint with YAML content
                        # Extract tags from YAML document
                        tags = None
                        if yaml_content:
                            try:
                                parsed_yaml = yaml.safe_load(yaml_content)
                                if parsed_yaml and isinstance(parsed_yaml, dict):
                                    # Tags are typically at pipeline.tags or directly at tags
                                    tags = parsed_yaml.get('pipeline', {}).get('tags') or parsed_yaml.get('tags')
                            except Exception as e:
                                print(f"  Warning: Failed to parse YAML for tags: {e}")
                        
                        if self.dest_client.create_pipeline(
                            yaml_content=yaml_content, identifier=identifier, name=name,
                            org_identifier=org_id, project_identifier=project_id, tags=tags
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
    parser.add_argument('--source-api-key', required=True, help='Source account API key (account ID will be extracted from key)')
    parser.add_argument('--dest-api-key', help='Destination account API key (not required for dry-run, account ID will be extracted from key)')
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
    
    # Extract account IDs from API keys
    try:
        source_account_id = extract_account_id_from_api_key(args.source_api_key)
    except ValueError as e:
        parser.error(f"Invalid source API key: {e}")
    
    dest_account_id = None
    if not args.dry_run:
        if not args.dest_api_key:
            parser.error("--dest-api-key is required when not using --dry-run")
        try:
            dest_account_id = extract_account_id_from_api_key(args.dest_api_key)
        except ValueError as e:
            parser.error(f"Invalid destination API key: {e}")
    
    # Create API clients (account ID will be extracted from API key if not provided)
    source_client = HarnessAPIClient(args.source_api_key, source_account_id, args.base_url)
    dest_client = None
    if not args.dry_run:
        dest_client = HarnessAPIClient(args.dest_api_key, dest_account_id, args.base_url)
    
    # Create migrator
    migrator = HarnessMigrator(
        source_client, dest_client, args.org_identifier, args.project_identifier, args.dry_run
    )
    
    # Perform migration
    mode = "DRY RUN - Listing" if args.dry_run else "Migrating"
    print(f"Starting Harness account {mode.lower()}...")
    print(f"Source Account: {source_account_id}")
    if not args.dry_run:
        print(f"Destination Account: {dest_account_id}")
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
