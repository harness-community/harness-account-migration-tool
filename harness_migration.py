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
    
    def _fetch_paginated(self, method: str, endpoint: str, params: Optional[Dict] = None,
                        data: Optional[Union[Dict, str]] = None, page_size: int = 100,
                        page_param_name: str = 'page', size_param_name: str = 'size',
                        content_path: str = 'data.content', total_pages_path: str = 'data.totalPages',
                        total_elements_path: str = 'data.totalElements',
                        pagination_in_body: bool = False) -> List[Dict]:
        """
        Fetch all pages of a paginated API endpoint
        
        Args:
            method: HTTP method ('GET' or 'POST')
            endpoint: API endpoint path
            params: Query parameters (will be updated with pagination params if pagination_in_body=False)
            data: Request body data (for POST requests, will be updated with pagination params if pagination_in_body=True)
            page_size: Number of items per page
            page_param_name: Name of the page parameter (default: 'page')
            size_param_name: Name of the size parameter (default: 'size')
            content_path: JSON path to the content array (default: 'data.content')
            total_pages_path: JSON path to total pages count (default: 'data.totalPages')
            total_elements_path: JSON path to total elements count (default: 'data.totalElements')
            pagination_in_body: If True, pagination params go in request body; if False, in query params (default: False)
        
        Returns:
            List of all items across all pages
        """
        all_items = []
        page = 0
        
        if params is None:
            params = {}
        
        while True:
            # Set pagination parameters in the appropriate location
            if pagination_in_body and isinstance(data, dict):
                # For POST requests where pagination goes in body
                request_data = data.copy()
                request_data[page_param_name] = page
                request_data[size_param_name] = page_size
                request_params = params.copy()
            else:
                # For GET requests or POST requests where pagination goes in query params
                request_params = params.copy()
                request_params[page_param_name] = page
                request_params[size_param_name] = page_size
                request_data = data
            
            response = self._make_request(method, endpoint, params=request_params, data=request_data)
            
            if response.status_code != 200:
                print(f"Failed to fetch page {page}: {response.status_code} - {response.text}")
                break
            
            response_data = response.json()
            
            # Extract content using the content_path
            content = response_data
            for key in content_path.split('.'):
                if isinstance(content, dict):
                    content = content.get(key, [])
                else:
                    content = []
                    break
            
            if not isinstance(content, list):
                content = []
            
            all_items.extend(content)
            
            # Check if there are more pages
            # Try to get total pages from response
            total_pages = None
            try:
                total_pages_obj = response_data
                for key in total_pages_path.split('.'):
                    if isinstance(total_pages_obj, dict):
                        total_pages_obj = total_pages_obj.get(key)
                    else:
                        total_pages_obj = None
                        break
                if isinstance(total_pages_obj, (int, float)):
                    total_pages = int(total_pages_obj)
            except Exception:
                pass
            
            # If we got fewer items than page_size, we're done
            if len(content) < page_size:
                break
            
            # If we have total_pages info, check if we've reached the last page
            if total_pages is not None and page >= total_pages - 1:
                break
            
            # If we got exactly page_size items, there might be more pages
            # Continue to next page
            page += 1
            
            # Safety limit to prevent infinite loops
            if page > 10000:  # Reasonable upper limit
                print(f"Warning: Reached pagination limit at page {page}")
                break
        
        return all_items
    
    def list_organizations(self) -> List[Dict]:
        """List all organizations with pagination support"""
        endpoint = "/ng/api/organizations"
        params = {}
        
        try:
            return self._fetch_paginated('GET', endpoint, params=params)
        except Exception as e:
            print(f"Failed to list organizations: {e}")
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
        """List all projects with pagination support"""
        endpoint = "/ng/api/projects"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        
        try:
            return self._fetch_paginated('GET', endpoint, params=params)
        except Exception as e:
            print(f"Failed to list projects: {e}")
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
        """List all pipelines with pagination support"""
        endpoint = "/pipeline/api/pipelines/list"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            # Pipelines API uses pagination in request body
            return self._fetch_paginated('POST', endpoint, params=params, data={
                'filterType': 'PipelineSetup'
            }, pagination_in_body=True)
        except Exception as e:
            print(f"Failed to list pipelines: {e}")
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
    
    def import_pipeline_yaml(self, git_details: Dict, pipeline_description: Optional[str] = None,
                             org_identifier: Optional[str] = None,
                             project_identifier: Optional[str] = None) -> bool:
        """Import pipeline from Git location (for GitX resources only)"""
        endpoint = "/pipeline/api/pipelines/import"
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
        
        # Add connector reference if present in git details
        if 'connectorRef' in git_details:
            params['connectorRef'] = git_details['connectorRef']
        
        # Build JSON body with pipeline description (always include, even if empty)
        data = {
            'pipelineDescription': pipeline_description if pipeline_description else ''
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported pipeline from GitX")
            return True
        else:
            print(f"Failed to import pipeline from GitX: {response.status_code} - {response.text}")
            return False
    
    def list_input_sets(self, pipeline_identifier: str, org_identifier: Optional[str] = None, 
                       project_identifier: Optional[str] = None) -> List[Dict]:
        """List all input sets for a pipeline"""
        endpoint = "/pipeline/api/inputSets"
        params = {
            'pipelineIdentifier': pipeline_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            return self._fetch_paginated('GET', endpoint, params=params)
        except Exception as e:
            print(f"Failed to list input sets: {e}")
            return []
    
    def get_input_set_data(self, input_set_identifier: str, pipeline_identifier: str,
                          org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get input set data - returns full data dict (for both GitX and Inline detection)"""
        endpoint = f"/pipeline/api/inputSets/{input_set_identifier}"
        params = {
            'pipelineIdentifier': pipeline_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Return full data dict for GitX/Inline detection
            return data.get('data', {})
        else:
            print(f"Failed to get input set data: {response.status_code} - {response.text}")
            return None
    
    def get_input_set_yaml(self, input_set_identifier: str, pipeline_identifier: str,
                          org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> Optional[str]:
        """Get input set YAML string"""
        input_set_data = self.get_input_set_data(input_set_identifier, pipeline_identifier, org_identifier, project_identifier)
        if input_set_data:
            return input_set_data.get('inputSetYaml', '')
        return None
    
    def create_input_set(self, input_set_data: Dict, pipeline_identifier: str,
                        org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Create input set (for inline resources)"""
        endpoint = "/pipeline/api/inputSets"
        params = {
            'pipelineIdentifier': pipeline_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('POST', endpoint, params=params, data=input_set_data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created input set")
            return True
        else:
            print(f"Failed to create input set: {response.status_code} - {response.text}")
            return False
    
    def import_input_set_yaml(self, git_details: Dict, input_set_identifier: str, input_set_name: str,
                             pipeline_identifier: str, input_set_description: Optional[str] = None,
                             org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Import input set from Git location (for GitX resources only)"""
        endpoint = f"/pipeline/api/inputSets/import/{input_set_identifier}"
        params = {
            'accountIdentifier': self.account_id,
            'pipelineIdentifier': pipeline_identifier
        }
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
        
        # Add connector reference if present in git details
        if 'connectorRef' in git_details:
            params['connectorRef'] = git_details['connectorRef']
        
        # Add isHarnessCodeRepo (default to false if not specified)
        params['isHarnessCodeRepo'] = git_details.get('isHarnessCodeRepo', 'false')
        
        # Build JSON body with input set name and description
        data = {
            'inputSetName': input_set_name,
            'inputSetDescription': input_set_description if input_set_description else ''
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported input set from GitX")
            return True
        else:
            print(f"Failed to import input set from GitX: {response.status_code} - {response.text}")
            return False
    
    def list_triggers(self, pipeline_identifier: str, org_identifier: Optional[str] = None,
                     project_identifier: Optional[str] = None) -> List[Dict]:
        """List all triggers for a pipeline"""
        endpoint = "/pipeline/api/triggers"
        params = {
            'pipelineIdentifier': pipeline_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            return self._fetch_paginated('GET', endpoint, params=params)
        except Exception as e:
            print(f"Failed to list triggers: {e}")
            return []
    
    def get_trigger_data(self, trigger_identifier: str, pipeline_identifier: str,
                        org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get trigger data"""
        endpoint = f"/pipeline/api/triggers/{trigger_identifier}"
        params = {
            'pipelineIdentifier': pipeline_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Extract from nested 'trigger' key if present, fallback to 'data' itself
            trigger_data = data.get('data', {}).get('trigger', data.get('data', {}))
            return trigger_data
        else:
            print(f"Failed to get trigger data: {response.status_code} - {response.text}")
            return None
    
    def create_trigger(self, trigger_data: Dict, pipeline_identifier: str,
                      org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Create trigger"""
        endpoint = "/pipeline/api/triggers"
        params = {
            'pipelineIdentifier': pipeline_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Build JSON payload with trigger data
        data = {
            'trigger': trigger_data
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created trigger")
            return True
        else:
            print(f"Failed to create trigger: {response.status_code} - {response.text}")
            return False
    
    def list_services(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all services with pagination support"""
        endpoint = "/ng/api/servicesV2"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            return self._fetch_paginated('GET', endpoint, params=params)
        except Exception as e:
            print(f"Failed to list services: {e}")
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
        """List all environments with pagination support"""
        endpoint = "/ng/api/environmentsV2"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            return self._fetch_paginated('GET', endpoint, params=params)
        except Exception as e:
            print(f"Failed to list environments: {e}")
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
        """List all connectors with pagination support"""
        endpoint = "/ng/api/connectors"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            all_items = self._fetch_paginated('GET', endpoint, params=params)
            # Extract connector data from the "connector" key in each item
            connectors = []
            for item in all_items:
                connector = item.get('connector', item)  # Fallback to item itself if no "connector" key
                connectors.append(connector)
            return connectors
        except Exception as e:
            print(f"Failed to list connectors: {e}")
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
        """List all infrastructures for a specific environment with pagination support"""
        endpoint = "/ng/api/infrastructures"
        params = {
            'environmentIdentifier': environment_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            return self._fetch_paginated('GET', endpoint, params=params)
        except Exception as e:
            print(f"Failed to list infrastructures: {e}")
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
    
    def list_templates(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all templates with pagination support"""
        endpoint = "/template/api/templates/list-metadata"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        params['templateListType'] = 'LastUpdated'
        params['sort'] = 'lastUpdatedAt,DESC'
        params['checkReferenced'] = 'true'
        # routingId is typically the account identifier
        params['routingId'] = self.account_id
        
        try:
            return self._fetch_paginated('POST', endpoint, params=params, data={
                'filterType': 'Template'
            })
        except Exception as e:
            print(f"Failed to list templates: {e}")
            return []
    
    def list_secrets(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all secrets with pagination support using v2 API
        
        Based on Harness API docs: https://apidocs.harness.io/secrets
        Uses POST /ng/api/v2/secrets/list/secrets with pageIndex/pageSize pagination
        """
        endpoint = "/ng/api/v2/secrets/list/secrets"
        params = {
            'routingId': self.account_id,
            'sortOrders': 'lastModifiedAt,DESC'
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        all_items = []
        page_index = 0
        page_size = 100
        
        while True:
            params['pageIndex'] = page_index
            params['pageSize'] = page_size
            
            response = self._make_request('POST', endpoint, params=params, data={
                'filterType': 'Secret'
            })
            
            if response.status_code != 200:
                print(f"Failed to fetch secrets page {page_index}: {response.status_code} - {response.text}")
                break
            
            response_data = response.json()
            
            # Extract content from response - v2 API structure may vary
            content = response_data.get('data', {}).get('content', [])
            if not content and 'content' in response_data:
                content = response_data.get('content', [])
            if not isinstance(content, list):
                content = []
            
            all_items.extend(content)
            
            # Check pagination metadata
            total_pages = None
            try:
                data_obj = response_data.get('data', {})
                if 'totalPages' in data_obj:
                    total_pages = int(data_obj['totalPages'])
                elif 'totalPages' in response_data:
                    total_pages = int(response_data['totalPages'])
            except Exception:
                pass
            
            # If we got fewer items than page_size, we're done
            if len(content) < page_size:
                break
            
            # If we have total_pages info, check if we've reached the last page
            if total_pages is not None and page_index >= total_pages - 1:
                break
            
            # Continue to next page
            page_index += 1
            
            # Safety limit
            if page_index > 10000:
                print(f"Warning: Reached pagination limit at page {page_index}")
                break
        
        return all_items
    
    def get_secret_data(self, secret_identifier: str, org_identifier: Optional[str] = None,
                       project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get secret data by ID and scope using v2 API
        
        Based on Harness API docs: https://apidocs.harness.io/secrets
        Uses GET endpoint: Get the Secret by ID and Scope
        """
        endpoint = f"/ng/api/v2/secrets/{secret_identifier}"
        params = {
            'routingId': self.account_id
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Extract from nested 'secret' key if present, fallback to 'data' itself
            secret_data = data.get('data', {}).get('secret', data.get('data', {}))
            # v2 API might return secret directly in 'data' or 'resource'
            if not secret_data and 'resource' in data.get('data', {}):
                secret_data = data.get('data', {}).get('resource', {})
            if not secret_data and 'secret' in data:
                secret_data = data.get('secret', {})
            return secret_data
        else:
            print(f"Failed to get secret data: {response.status_code} - {response.text}")
            return None
    
    def create_secret(self, secret_data: Dict, org_identifier: Optional[str] = None,
                     project_identifier: Optional[str] = None, dry_run: bool = False) -> bool:
        """Create secret from secret data using v2 API
        
        Based on Harness API docs: https://apidocs.harness.io/secrets
        Uses POST endpoint: Creates a Secret at given Scope
        
        For secrets stored in harnessSecretManager, the value cannot be migrated,
        so a dummy value of "changeme" is used instead.
        """
        # Remove read-only fields
        cleaned_data = clean_for_creation(secret_data)
        
        # Check if secret uses harnessSecretManager
        # secretManagerIdentifier is in the spec dictionary, not at top level
        spec = cleaned_data.get('spec', {})
        secret_manager_identifier = spec.get('secretManagerIdentifier', '')
        
        # harnessSecretManager can exist at different levels:
        # - account.harnessSecretManager (account level)
        # - org.harnessSecretManager (org level)
        # - harnessSecretManager (project level)
        is_harness_secret_manager = (
            secret_manager_identifier == 'harnessSecretManager' or
            secret_manager_identifier == 'account.harnessSecretManager' or
            secret_manager_identifier == 'org.harnessSecretManager'
        )
        
        if is_harness_secret_manager:
            # For harnessSecretManager, we cannot migrate the value
            # Set a dummy value that the user must change
            if 'spec' in cleaned_data:
                cleaned_data['spec']['value'] = 'changeme'
        
        # Prepare the request body - v2 API expects secret object
        request_body = {
            'secret': cleaned_data
        }
        
        if dry_run:
            secret_name = cleaned_data.get('name', cleaned_data.get('identifier', 'Unknown'))
            secret_id = cleaned_data.get('identifier', 'Unknown')
            secret_type = cleaned_data.get('type', 'Unknown')
            print(f"  [DRY RUN] Would create secret: {secret_name} ({secret_id}) type: {secret_type}")
            if is_harness_secret_manager:
                print(f"  [DRY RUN] Note: Secret uses harnessSecretManager ({secret_manager_identifier}), value will be set to 'changeme'")
            return True
        
        endpoint = "/ng/api/v2/secrets"
        params = {
            'routingId': self.account_id
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created secret")
            if is_harness_secret_manager:
                print(f"  Warning: Secret uses harnessSecretManager ({secret_manager_identifier}), value set to 'changeme' - please update manually")
            return True
        else:
            print(f"Failed to create secret: {response.status_code} - {response.text}")
            return False
    
    def get_template_versions(self, template_identifier: str, org_identifier: Optional[str] = None,
                              project_identifier: Optional[str] = None) -> List[str]:
        """Get all versions of a template"""
        endpoint = "/template/api/templates/list-metadata"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        params['templateListType'] = 'All'
        params['size'] = 100
        params['module'] = 'cd'
        params['routingId'] = self.account_id
        
        # Request body with template identifier filter
        request_body = {
            'filterType': 'Template',
            'templateIdentifiers': [template_identifier]
        }
        
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        if response.status_code == 200:
            data = response.json()
            content = data.get('data', {}).get('content', [])
            # Extract versionLabel from each template entry
            version_list = []
            for template_entry in content:
                version_label = template_entry.get('versionLabel', '')
                if version_label:
                    version_list.append(version_label)
            return version_list
        else:
            print(f"Failed to get template versions: {response.status_code} - {response.text}")
            return []
    
    def get_template_data(self, template_identifier: str, version: str,
                         org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get template data for a specific version (for both GitX and Inline detection)"""
        endpoint = f"/template/api/templates/{template_identifier}"
        params = {
            'versionLabel': version
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Extract from nested 'template' key if present, fallback to 'data' itself
            template_data = data.get('data', {}).get('template', data.get('data', {}))
            return template_data
        else:
            print(f"Failed to get template data: {response.status_code} - {response.text}")
            return None
    
    def get_template_yaml(self, template_identifier: str, version: str,
                         org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> Optional[str]:
        """Get template YAML for a specific version"""
        template_data = self.get_template_data(template_identifier, version, org_identifier, project_identifier)
        if template_data:
            # Templates may use 'yaml' or 'templateYaml' field
            return template_data.get('yaml', '') or template_data.get('templateYaml', '')
        return None
    
    def create_template(self, yaml_content: str, identifier: str, name: str, version: str,
                       org_identifier: Optional[str] = None, project_identifier: Optional[str] = None,
                       tags: Optional[Dict[str, str]] = None) -> bool:
        """Create template from YAML content (for inline resources)"""
        endpoint = "/template/api/templates"
        params = {
            'isNewTemplate': 'false',
            'storeType': 'INLINE',
            'comments': ''
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Templates are created by passing YAML directly in the request body
        # The Content-Type should be application/yaml
        headers = self.headers.copy()
        headers['Content-Type'] = 'application/yaml'
        
        url = f"{self.base_url}{endpoint}"
        params['accountIdentifier'] = self.account_id
        
        try:
            response = requests.post(url, headers=headers, params=params, data=yaml_content)
            
            if response.status_code in [200, 201]:
                print(f"Successfully created template version {version}")
                return True
            else:
                print(f"Failed to create template version {version}: {response.status_code} - {response.text}")
                return False
        except requests.exceptions.RequestException as e:
            print(f"Request error: {e}")
            return False
    
    def import_template_yaml(self, git_details: Dict, template_identifier: str, version: str,
                            template_name: str, template_description: Optional[str] = None,
                            org_identifier: Optional[str] = None,
                            project_identifier: Optional[str] = None) -> bool:
        """Import template from Git location (for GitX resources only)"""
        endpoint = f"/template/api/templates/import/{template_identifier}"
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
        
        # Add connector reference if present in git details
        if 'connectorRef' in git_details:
            params['connectorRef'] = git_details['connectorRef']
        
        # Add isHarnessCodeRepo (default to false if not specified)
        params['isHarnessCodeRepo'] = git_details.get('isHarnessCodeRepo', 'false')
        
        # Build JSON body with template description, version, and name
        data = {
            'templateDescription': template_description if template_description else '',
            'templateVersion': version,
            'templateName': template_name
        }
        
        response = self._make_request('POST', endpoint, params=params, data=data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported template version {version} from GitX")
            return True
        else:
            print(f"Failed to import template version {version} from GitX: {response.status_code} - {response.text}")
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
    
    def _get_project_scopes(self) -> List[tuple]:
        """Get only project-level scopes (org_id, project_id) where both are not None"""
        scopes = []
        
        # Get all organizations
        orgs = self.source_client.list_organizations()
        for org in orgs:
            org_item = org.get('organization', org)
            org_id = org_item.get('identifier', '')
            if not org_id:
                continue
            
            # Get all projects for this organization
            projects = self.source_client.list_projects(org_id)
            for project in projects:
                project_item = project.get('project', project)
                project_id = project_item.get('identifier', '')
                if project_id:
                    scopes.append((org_id, project_id))
        
        return scopes
    
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
    
    def migrate_secrets(self) -> Dict[str, Any]:
        """Migrate secrets at all scopes (account, org, project)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Secrets ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing secrets at {scope_label} ---")
            
            secrets = self.source_client.list_secrets(org_id, project_id)
            
            for secret in secrets:
                # Extract secret data from nested structure if present
                secret_item = secret.get('secret', secret) if isinstance(secret, dict) else secret
                identifier = secret_item.get('identifier', '') if isinstance(secret_item, dict) else ''
                name = secret_item.get('name', identifier) if isinstance(secret_item, dict) else identifier
                print(f"\nProcessing secret: {name} ({identifier}) at {scope_label}")
                
                # Get full secret data
                secret_data = self.source_client.get_secret_data(identifier, org_id, project_id)
                
                if not secret_data:
                    print(f"  Failed to get data for secret {name}")
                    results['failed'] += 1
                    continue
                
                # Export secret data to file for backup (without sensitive values)
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                export_file = self.export_dir / f"secret_{identifier}{scope_suffix}.json"
                
                # Create a safe copy for export (remove sensitive values)
                export_data = secret_data.copy()
                if 'spec' in export_data:
                    export_spec = export_data['spec'].copy()
                    if 'value' in export_spec:
                        export_spec['value'] = '***REDACTED***'
                    export_data['spec'] = export_spec
                
                try:
                    import json
                    export_file.write_text(json.dumps(export_data, indent=2))
                    print(f"  Exported secret metadata to {export_file}")
                except Exception as e:
                    print(f"  Warning: Failed to export secret metadata: {e}")
                
                # Create in destination (skip in dry-run mode)
                if self.dry_run:
                    # secretManagerIdentifier is in spec, not at top level
                    spec = secret_data.get('spec', {})
                    secret_manager = spec.get('secretManagerIdentifier', 'Unknown')
                    is_harness = (
                        secret_manager == 'harnessSecretManager' or
                        secret_manager == 'account.harnessSecretManager' or
                        secret_manager == 'org.harnessSecretManager'
                    )
                    if is_harness:
                        print(f"  [DRY RUN] Would create secret with value 'changeme' (harnessSecretManager: {secret_manager})")
                    else:
                        print(f"  [DRY RUN] Would create secret")
                    results['success'] += 1
                else:
                    if self.dest_client.create_secret(
                        secret_data=secret_data, org_identifier=org_id, project_identifier=project_id
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
        """Migrate pipelines at project level only (pipelines only exist at project level)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Pipelines ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_project_scopes()
        for org_id, project_id in scopes:
            scope_label = f"project {project_id} (org {org_id})"
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
                
                # Save exported data (pipelines are always at project level)
                scope_suffix = f"_org_{org_id}_project_{project_id}"
                
                yaml_content = None
                git_details = None
                
                if is_gitx:
                    # GitX: Get git details for import
                    git_details = pipeline_data.get('gitDetails', {})
                    if not git_details:
                        print(f"  Failed to get git details for GitX pipeline {name}")
                        results['failed'] += 1
                        continue
                    # Extract connector reference from pipeline data if present
                    connector_ref = pipeline_data.get('connectorRef')
                    if connector_ref:
                        git_details['connectorRef'] = connector_ref
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
                        # Extract pipeline description from pipeline data
                        pipeline_description = pipeline_data.get('description') or pipeline_data.get('pipelineDescription')
                        if self.dest_client.import_pipeline_yaml(
                            git_details=git_details, pipeline_description=pipeline_description,
                            org_identifier=org_id, project_identifier=project_id
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
    
    def migrate_input_sets(self) -> Dict[str, Any]:
        """Migrate input sets for all pipelines at project level only (pipelines only exist at project level)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Input Sets ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_project_scopes()
        for org_id, project_id in scopes:
            scope_label = f"project {project_id} (org {org_id})"
            print(f"\n--- Processing input sets at {scope_label} ---")
            
            # Get all pipelines for this scope
            pipelines = self.source_client.list_pipelines(org_id, project_id)
            
            for pipeline in pipelines:
                # Extract pipeline data from nested structure if present
                pipeline_item = pipeline.get('pipeline', pipeline)
                pipeline_identifier = pipeline_item.get('identifier', '')
                pipeline_name = pipeline_item.get('name', pipeline_identifier)
                
                # List input sets for this pipeline
                input_sets = self.source_client.list_input_sets(pipeline_identifier, org_id, project_id)
                
                if not input_sets:
                    continue  # No input sets for this pipeline
                
                # Get pipeline data to check if pipeline is GitX (input sets inherit GitX from pipeline)
                pipeline_data = self.source_client.get_pipeline_data(pipeline_identifier, org_id, project_id)
                pipeline_is_gitx = False
                if pipeline_data:
                    pipeline_is_gitx = self.source_client.is_gitx_resource(pipeline_data)
                
                print(f"\nProcessing input sets for pipeline: {pipeline_name} ({pipeline_identifier})")
                print(f"  Pipeline storage type: {'GitX' if pipeline_is_gitx else 'Inline'}")
                
                for input_set in input_sets:
                    # Extract input set data from nested structure if present
                    input_set_item = input_set.get('inputSet', input_set)
                    identifier = input_set_item.get('identifier', '')
                    name = input_set_item.get('name', identifier)
                    print(f"  Processing input set: {name} ({identifier})")
                    
                    # Get full input set data
                    input_set_data = self.source_client.get_input_set_data(
                        identifier, pipeline_identifier, org_id, project_id
                    )
                    
                    if not input_set_data:
                        print(f"    Failed to get data for input set {name}")
                        results['failed'] += 1
                        continue
                    
                    # Input sets inherit GitX storage from their pipeline
                    is_gitx = pipeline_is_gitx
                    storage_type = "GitX" if is_gitx else "Inline"
                    print(f"    Input set storage type: {storage_type}")
                    
                    # Export input set YAML to file for backup (input sets are always at project level)
                    scope_suffix = f"_org_{org_id}_project_{project_id}"
                    
                    yaml_content = None
                    git_details = None
                    
                    if is_gitx:
                        # GitX: Get git details for import
                        git_details = input_set_data.get('gitDetails', {}) or input_set_data.get('entityGitDetails', {})
                        if not git_details:
                            print(f"    Failed to get git details for GitX input set {name}")
                            results['failed'] += 1
                            continue
                        # Extract connector reference from pipeline data if present
                        connector_ref = pipeline_data.get('connectorRef') if pipeline_data else None
                        if connector_ref:
                            git_details['connectorRef'] = connector_ref
                        # Also get YAML for export
                        yaml_content = input_set_data.get('inputSetYaml', '')
                        export_file = self.export_dir / f"inputset_{pipeline_identifier}_{identifier}{scope_suffix}.yaml"
                        if yaml_content:
                            export_file.write_text(yaml_content)
                            print(f"    Exported to {export_file}")
                    else:
                        # Inline: Get YAML content for import
                        yaml_content = input_set_data.get('inputSetYaml', '')
                        if not yaml_content:
                            print(f"    Failed to get YAML for inline input set {name}")
                            results['failed'] += 1
                            continue
                        export_file = self.export_dir / f"inputset_{pipeline_identifier}_{identifier}{scope_suffix}.yaml"
                        export_file.write_text(yaml_content)
                        print(f"    Exported to {export_file}")
                    
                    # Migrate to destination (skip in dry-run mode)
                    if self.dry_run:
                        if is_gitx:
                            print(f"    [DRY RUN] Would import input set (GitX) from git location")
                        else:
                            print(f"    [DRY RUN] Would create input set (Inline) with YAML content")
                        results['success'] += 1
                    else:
                        if is_gitx:
                            # GitX: Use import endpoint with git details
                            # Extract input set name and description from input set data
                            input_set_name = input_set_data.get('name', name)
                            input_set_description = input_set_data.get('description') or input_set_data.get('inputSetDescription')
                            if self.dest_client.import_input_set_yaml(
                                git_details=git_details, input_set_identifier=identifier,
                                input_set_name=input_set_name, pipeline_identifier=pipeline_identifier,
                                input_set_description=input_set_description,
                                org_identifier=org_id, project_identifier=project_id
                            ):
                                results['success'] += 1
                            else:
                                results['failed'] += 1
                        else:
                            # Inline: Use create endpoint with YAML content
                            # Parse YAML string to get input set dict
                            try:
                                input_set_dict = yaml.safe_load(yaml_content)
                                if not input_set_dict or not isinstance(input_set_dict, dict):
                                    print(f"    Failed to parse input set YAML for {name}")
                                    results['failed'] += 1
                                    continue
                            except Exception as e:
                                print(f"    Failed to parse input set YAML for {name}: {e}")
                                results['failed'] += 1
                                continue
                            
                            # Create a safe copy for creation (remove read-only fields)
                            export_data = clean_for_creation(input_set_dict.copy())
                            
                            if self.dest_client.create_input_set(
                                input_set_data=export_data, pipeline_identifier=pipeline_identifier,
                                org_identifier=org_id, project_identifier=project_id
                            ):
                                results['success'] += 1
                            else:
                                results['failed'] += 1
                    
                    time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_triggers(self) -> Dict[str, Any]:
        """Migrate triggers for all pipelines at project level only (pipelines only exist at project level)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Triggers ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_project_scopes()
        for org_id, project_id in scopes:
            scope_label = f"project {project_id} (org {org_id})"
            print(f"\n--- Processing triggers at {scope_label} ---")
            
            # Get all pipelines for this scope
            pipelines = self.source_client.list_pipelines(org_id, project_id)
            
            for pipeline in pipelines:
                # Extract pipeline data from nested structure if present
                pipeline_item = pipeline.get('pipeline', pipeline)
                pipeline_identifier = pipeline_item.get('identifier', '')
                pipeline_name = pipeline_item.get('name', pipeline_identifier)
                
                # List triggers for this pipeline
                triggers = self.source_client.list_triggers(pipeline_identifier, org_id, project_id)
                
                if not triggers:
                    continue  # No triggers for this pipeline
                
                print(f"\nProcessing triggers for pipeline: {pipeline_name} ({pipeline_identifier})")
                
                for trigger in triggers:
                    # Extract trigger data from nested structure if present
                    trigger_item = trigger.get('trigger', trigger)
                    identifier = trigger_item.get('identifier', '')
                    name = trigger_item.get('name', identifier)
                    print(f"  Processing trigger: {name} ({identifier})")
                    
                    # Get full trigger data
                    trigger_data = self.source_client.get_trigger_data(
                        identifier, pipeline_identifier, org_id, project_id
                    )
                    
                    if not trigger_data:
                        print(f"    Failed to get data for trigger {name}")
                        results['failed'] += 1
                        continue
                    
                    # Export trigger data to file for backup (triggers are always at project level)
                    scope_suffix = f"_org_{org_id}_project_{project_id}"
                    export_file = self.export_dir / f"trigger_{pipeline_identifier}_{identifier}{scope_suffix}.json"
                    
                    # Create a safe copy for export (remove read-only fields)
                    export_data = clean_for_creation(trigger_data.copy())
                    export_file.write_text(json.dumps(export_data, indent=2))
                    print(f"    Exported to {export_file}")
                    
                    # Create in destination (skip in dry-run mode)
                    if self.dry_run:
                        print(f"    [DRY RUN] Would create trigger in destination account")
                        results['success'] += 1
                    else:
                        if self.dest_client.create_trigger(
                            trigger_data=export_data, pipeline_identifier=pipeline_identifier,
                            org_identifier=org_id, project_identifier=project_id
                        ):
                            results['success'] += 1
                        else:
                            results['failed'] += 1
                    
                    time.sleep(0.5)  # Rate limiting
        
        return results
    
    def _migrate_template_version(self, template_identifier: str, template_name: str, version: str,
                                 template_data: Dict, org_id: Optional[str], project_id: Optional[str],
                                 scope_suffix: str) -> Dict[str, int]:
        """Migrate a single template version - returns success/failed counts"""
        version_results = {'success': 0, 'failed': 0}
        
        # Detect if template is GitX or Inline
        is_gitx = self.source_client.is_gitx_resource(template_data)
        storage_type = "GitX" if is_gitx else "Inline"
        print(f"    Template storage type: {storage_type}")
        
        yaml_content = None
        git_details = None
        
        if is_gitx:
            # GitX: Get git details for import
            git_details = template_data.get('gitDetails', {}) or template_data.get('entityGitDetails', {})
            if not git_details:
                print(f"    Failed to get git details for GitX template {template_name} version {version}")
                version_results['failed'] += 1
                return version_results
            # Extract connector reference from template data if present
            connector_ref = template_data.get('connectorRef')
            if connector_ref:
                git_details['connectorRef'] = connector_ref
            # Also get YAML for export
            yaml_content = template_data.get('yaml', '') or template_data.get('templateYaml', '')
            export_file = self.export_dir / f"template_{template_identifier}_v{version}{scope_suffix}.yaml"
            if yaml_content:
                export_file.write_text(yaml_content)
                print(f"    Exported YAML to {export_file}")
        else:
            # Inline: Get YAML content for import
            yaml_content = template_data.get('yaml', '') or template_data.get('templateYaml', '')
            if not yaml_content:
                print(f"    Failed to get YAML for inline template {template_name} version {version}")
                version_results['failed'] += 1
                return version_results
            export_file = self.export_dir / f"template_{template_identifier}_v{version}{scope_suffix}.yaml"
            export_file.write_text(yaml_content)
            print(f"    Exported YAML to {export_file}")
        
        # Import to destination (skip in dry-run mode)
        if self.dry_run:
            if is_gitx:
                print(f"    [DRY RUN] Would import template version {version} (GitX) from git location")
            else:
                print(f"    [DRY RUN] Would create template version {version} (Inline) with YAML content")
            version_results['success'] += 1
        else:
            if is_gitx:
                # GitX: Use import endpoint with git details
                # Extract template description from template data
                template_description = template_data.get('description') or template_data.get('templateDescription')
                if self.dest_client.import_template_yaml(
                    git_details=git_details, template_identifier=template_identifier, version=version,
                    template_name=template_name, template_description=template_description,
                    org_identifier=org_id, project_identifier=project_id
                ):
                    version_results['success'] += 1
                else:
                    version_results['failed'] += 1
            else:
                # Inline: Use create endpoint with YAML content
                # Extract tags from YAML document
                tags = None
                if yaml_content:
                    try:
                        parsed_yaml = yaml.safe_load(yaml_content)
                        if parsed_yaml and isinstance(parsed_yaml, dict):
                            # Tags are typically at template.tags or directly at tags
                            tags = parsed_yaml.get('template', {}).get('tags') or parsed_yaml.get('tags')
                    except Exception as e:
                        print(f"    Warning: Failed to parse YAML for tags: {e}")
                
                if self.dest_client.create_template(
                    yaml_content=yaml_content, identifier=template_identifier, name=template_name, version=version,
                    org_identifier=org_id, project_identifier=project_id, tags=tags
                ):
                    version_results['success'] += 1
                else:
                    version_results['failed'] += 1
        
        time.sleep(0.5)  # Rate limiting
        return version_results
    
    def migrate_templates(self, template_types: Optional[List[str]] = None) -> Dict[str, Any]:
        """Migrate templates at all scopes (account, org, project) - migrates all versions of each template
        
        Args:
            template_types: List of template types to migrate. If None, migrates all types in dependency order.
                            Order: SecretManager, DeploymentTemplate/ArtifactSource (early), Step/MonitoredService, StepGroup, Stage, Pipeline, then others.
                            Referenced templates must be migrated first.
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Templates ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        # Template type migration order based on dependencies
        # SecretManager templates are handled separately (migrated early)
        # Deployment Template and Artifact Source templates are handled separately (migrated before services/environments)
        # Dependencies: Pipeline references Stage, Stage references Step/MonitoredService/StepGroup
        # So we must migrate in reverse dependency order: Step/MonitoredService -> StepGroup -> Stage -> Pipeline
        # This method handles: Step/MonitoredService -> StepGroup -> Stage -> Pipeline -> Others
        template_type_order = ['Step', 'MonitoredService', 'StepGroup', 'Stage', 'Pipeline']
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing templates at {scope_label} ---")
            
            templates = self.source_client.list_templates(org_id, project_id)
            
            # Group templates by type
            templates_by_type = {}
            for template in templates:
                # Extract template data from nested structure if present
                template_item = template.get('template', template)
                template_type = template_item.get('templateEntityType', 'Unknown')
                
                # Filter by requested types if specified
                if template_types and template_type not in template_types:
                    continue
                
                if template_type not in templates_by_type:
                    templates_by_type[template_type] = []
                templates_by_type[template_type].append(template_item)
            
            # Migrate templates in dependency order
            # First, migrate types in the defined order
            for template_type in template_type_order:
                if template_type in templates_by_type:
                    print(f"\n--- Migrating {template_type} templates ---")
                    for template_item in templates_by_type[template_type]:
                        identifier = template_item.get('identifier', '')
                        name = template_item.get('name', identifier)
                        print(f"\nProcessing {template_type} template: {name} ({identifier}) at {scope_label}")
                        
                        # Get all versions for this template
                        versions = self.source_client.get_template_versions(identifier, org_id, project_id)
                        
                        if not versions:
                            print(f"  No versions found for template {name}")
                            results['skipped'] += 1
                            continue
                        
                        print(f"  Found {len(versions)} version(s): {', '.join(versions)}")
                        
                        # Migrate each version
                        for version in versions:
                            print(f"\n  Processing version: {version}")
                            
                            # Get template data for this version to detect storage type
                            template_data = self.source_client.get_template_data(
                                identifier, version, org_id, project_id
                            )
                            
                            if not template_data:
                                print(f"    Failed to get data for template {name} version {version}")
                                results['failed'] += 1
                                continue
                            
                            scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                            version_results = self._migrate_template_version(
                                identifier, name, version, template_data, org_id, project_id, scope_suffix
                            )
                            results['success'] += version_results['success']
                            results['failed'] += version_results['failed']
            
            # Then migrate other template types (not in the ordered list)
            other_types = [t for t in templates_by_type.keys() if t not in template_type_order]
            if other_types:
                print(f"\n--- Migrating other template types: {', '.join(other_types)} ---")
                for template_type in other_types:
                    for template_item in templates_by_type[template_type]:
                        identifier = template_item.get('identifier', '')
                        name = template_item.get('name', identifier)
                        print(f"\nProcessing {template_type} template: {name} ({identifier}) at {scope_label}")
                        
                        # Get all versions for this template
                        versions = self.source_client.get_template_versions(identifier, org_id, project_id)
                        
                        if not versions:
                            print(f"  No versions found for template {name}")
                            results['skipped'] += 1
                            continue
                        
                        print(f"  Found {len(versions)} version(s): {', '.join(versions)}")
                        
                        # Migrate each version
                        for version in versions:
                            print(f"\n  Processing version: {version}")
                            
                            # Get template data for this version to detect storage type
                            template_data = self.source_client.get_template_data(
                                identifier, version, org_id, project_id
                            )
                            
                            if not template_data:
                                print(f"    Failed to get data for template {name} version {version}")
                                results['failed'] += 1
                                continue
                            
                            scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                            version_results = self._migrate_template_version(
                                identifier, name, version, template_data, org_id, project_id, scope_suffix
                            )
                            results['success'] += version_results['success']
                            results['failed'] += version_results['failed']
        
        return results
    
    def migrate_secret_manager_templates(self) -> Dict[str, Any]:
        """Migrate SecretManager templates - must be migrated early (right after projects/orgs)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} SecretManager Templates ===")
        return self.migrate_templates(template_types=['SecretManager'])
    
    def migrate_deployment_and_artifact_source_templates(self) -> Dict[str, Any]:
        """Migrate Deployment Template and Artifact Source templates - must be migrated before services and environments"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Deployment Template and Artifact Source Templates ===")
        return self.migrate_templates(template_types=['DeploymentTemplate', 'ArtifactSource'])
    
    def migrate_all(self, resource_types: Optional[List[str]] = None) -> Dict[str, Dict[str, Any]]:
        """Migrate all resources"""
        if resource_types is None:
            resource_types = ['organizations', 'projects', 'connectors', 'secrets', 'environments', 'infrastructures', 'services', 'templates', 'pipelines', 'input-sets', 'triggers']
        
        all_results = {}
        
        # Migrate in dependency order - organizations and projects first
        if 'organizations' in resource_types:
            all_results['organizations'] = self.migrate_organizations()
        
        if 'projects' in resource_types:
            all_results['projects'] = self.migrate_projects()
        
        # SecretManager templates must be migrated early (right after projects/orgs)
        if 'templates' in resource_types:
            all_results['secret_manager_templates'] = self.migrate_secret_manager_templates()
        
        # Deployment Template and Artifact Source templates must be migrated before services and environments
        if 'templates' in resource_types:
            all_results['deployment_artifact_templates'] = self.migrate_deployment_and_artifact_source_templates()
        
        # Then migrate other resources
        if 'connectors' in resource_types:
            all_results['connectors'] = self.migrate_connectors()
        
        if 'secrets' in resource_types:
            all_results['secrets'] = self.migrate_secrets()
        
        if 'environments' in resource_types:
            all_results['environments'] = self.migrate_environments()
        
        if 'infrastructures' in resource_types:
            all_results['infrastructures'] = self.migrate_infrastructures()
        
        if 'services' in resource_types:
            all_results['services'] = self.migrate_services()
        
        # Other templates (Pipeline, Stage, Step, MonitoredService, and others) - migrated before pipelines
        if 'templates' in resource_types:
            all_results['templates'] = self.migrate_templates()
        
        if 'pipelines' in resource_types:
            all_results['pipelines'] = self.migrate_pipelines()
        
        # Input sets and triggers are child entities of pipelines, migrate after pipelines
        # Input sets must be migrated before triggers (triggers may reference input sets)
        if 'input-sets' in resource_types:
            all_results['input_sets'] = self.migrate_input_sets()
        
        if 'triggers' in resource_types:
            all_results['triggers'] = self.migrate_triggers()
        
        return all_results


def main():
    parser = argparse.ArgumentParser(description='Migrate Harness account resources')
    parser.add_argument('--source-api-key', required=True, help='Source account API key (account ID will be extracted from key)')
    parser.add_argument('--dest-api-key', help='Destination account API key (not required for dry-run, account ID will be extracted from key)')
    parser.add_argument('--org-identifier', help='Organization identifier (optional)')
    parser.add_argument('--project-identifier', help='Project identifier (optional)')
    parser.add_argument('--resource-types', nargs='+', 
                       choices=['organizations', 'projects', 'connectors', 'secrets', 'environments', 'infrastructures', 'services', 'pipelines', 'templates', 'input-sets', 'triggers'],
                       default=['organizations', 'projects', 'connectors', 'secrets', 'environments', 'infrastructures', 'services', 'pipelines', 'templates', 'input-sets', 'triggers'],
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
