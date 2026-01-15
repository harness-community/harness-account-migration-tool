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
import re
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


def is_resource_already_exists_error(status_code: int, response_text: str) -> bool:
    """Check if an API error response indicates a resource already exists"""
    # Check status codes that typically indicate resource already exists
    # Include 500 for MongoDB duplicate key errors (e.g., user journeys)
    if status_code not in [400, 409, 500]:
        return False
    
    response_lower = response_text.lower()
    
    # Specific error codes that indicate duplicate/existing resource
    specific_error_codes = ['DUPLICATE_FIELD', 'DUPLICATE_FILE_IMPORT', 'INVALID_REQUEST']
    
    # Error messages that definitively indicate resource already exists
    # These must contain words like "already" or "duplicate" to avoid false positives
    definitive_error_messages = [
        'already exists',
        'already present', 
        'already been imported',
        'duplicate',
        'already been created',
        'resource already',
        'cannot be used',  # For connectors
        'must be unique',  # For policies/policy sets
        'already exists or',  # For pipelines
        'e11000 duplicate key',  # MongoDB duplicate key errors
        'dup key',  # MongoDB duplicate key errors
        'identifier must be unique',  # For policies/policy sets
        'already exists or is soft deleted',  # For triggers
        'already exists or has been deleted',  # For pipelines
        'already exists in this scope',  # For secrets
        'already exists.',  # For IP allowlists
    ]
    
    # Check for specific error codes (these are definitive)
    for error_code in specific_error_codes:
        if error_code.lower() in response_lower:
            # For INVALID_REQUEST, also check if it contains "already exists" to avoid false positives
            if error_code == 'INVALID_REQUEST':
                if any(msg in response_lower for msg in ['already exists', 'already been imported', 'already present']):
                    return True
            else:
                return True
    
    # Check for definitive error messages (these are definitive)
    for error_msg in definitive_error_messages:
        if error_msg in response_lower:
            return True
    
    return False


def format_resource_already_exists_message(resource_type: str, identifier: str, response_text: str, scope_info: str) -> str:
    """Format a user-friendly message when a resource already exists"""
    return f"Resource '{resource_type}' with identifier '{identifier}' already exists at {scope_info}. Skipping migration."


def get_scope_info(org_identifier: Optional[str], project_identifier: Optional[str]) -> str:
    """Helper to get a consistent scope info string"""
    if not org_identifier:
        return "account level"
    elif not project_identifier:
        return f"org {org_identifier} level"
    else:
        return f"project {project_identifier} (org {org_identifier}) level"


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
                # If data is a string, send it as raw data; otherwise send as JSON
                if isinstance(data, str):
                    response = requests.put(url, headers=request_headers, params=params, data=data)
                else:
                    response = requests.put(url, headers=request_headers, params=params, json=data)
            elif method.upper() == 'PATCH':
                # If data is a string, send it as raw data; otherwise send as JSON
                if isinstance(data, str):
                    response = requests.patch(url, headers=request_headers, params=params, data=data)
                else:
                    response = requests.patch(url, headers=request_headers, params=params, json=data)
            elif method.upper() == 'PUT':
                # If data is a string, send it as raw data; otherwise send as JSON
                if isinstance(data, str):
                    response = requests.put(url, headers=request_headers, params=params, data=data)
                else:
                    response = requests.put(url, headers=request_headers, params=params, json=data)
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
                        pagination_in_body: bool = False, headers: Optional[Dict] = None,
                        use_offset: bool = False) -> List[Dict]:
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
            content_path: JSON path to the content array (default: 'data.content'). Use empty string '' for direct array responses
            total_pages_path: JSON path to total pages count (default: 'data.totalPages'). Use empty string '' if not available
            total_elements_path: JSON path to total elements count (default: 'data.totalElements')
            pagination_in_body: If True, pagination params go in request body; if False, in query params (default: False)
            headers: Optional custom headers to include in requests
            use_offset: If True, pagination value is calculated as offset = page * page_size; if False, uses page number directly (default: False)
        
        Returns:
            List of all items across all pages
        """
        all_items = []
        page = 0
        
        if params is None:
            params = {}
        
        while True:
            # Set pagination parameters in the appropriate location
            if use_offset:
                # For offset-based pagination: offset = page * page_size
                pagination_value = page * page_size
            else:
                # For page-based pagination: page number
                pagination_value = page
            
            if pagination_in_body and isinstance(data, dict):
                # For POST requests where pagination goes in body
                request_data = data.copy()
                request_data[page_param_name] = pagination_value
                request_data[size_param_name] = page_size
                request_params = params.copy()
            else:
                # For GET requests or POST requests where pagination goes in query params
                request_params = params.copy()
                request_params[page_param_name] = pagination_value
                request_params[size_param_name] = page_size
                request_data = data
            
            response = self._make_request(method, endpoint, params=request_params, data=request_data, headers=headers)
            
            if response.status_code != 200:
                print(f"Failed to fetch page {page}: {response.status_code} - {response.text}")
                break
            
            response_data = response.json()
            
            # Extract content using the content_path
            if not content_path or content_path == '':
                # Direct array response (no nesting)
                content = response_data if isinstance(response_data, list) else []
            else:
                content = response_data
                for key in content_path.split('.'):
                    if key:  # Skip empty strings from split
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
            if is_resource_already_exists_error(response.status_code, response.text):
                identifier = cleaned_data.get('identifier', 'unknown')
                scope_info = get_scope_info(None, None)
                print(f"  {format_resource_already_exists_message('organization', identifier, response.text, scope_info)}")
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
            if is_resource_already_exists_error(response.status_code, response.text):
                identifier = cleaned_data.get('identifier', 'unknown')
                scope_info = get_scope_info(org_identifier, None)
                print(f"  {format_resource_already_exists_message('project', identifier, response.text, scope_info)}")
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
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('pipeline', identifier, response.text, scope_info)}")
            else:
                print(f"Failed to create pipeline: {response.status_code} - {response.text}")
            return False
    
    def import_pipeline_yaml(self, git_details: Dict, pipeline_identifier: str, pipeline_description: Optional[str] = None,
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
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('pipeline', pipeline_identifier, response.text, scope_info)}")
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
        
        # Extract identifier from input_set_data
        # The data may be:
        # 1. A parsed YAML dict with nested structure: {'inputSet': {'identifier': '...', ...}}
        # 2. A flat dict with 'identifier' at top level
        # 3. A dict containing 'inputSetYaml' string that needs parsing
        identifier = input_set_data.get('identifier', 'unknown')
        if identifier == 'unknown':
            # Check for nested inputSet structure (parsed YAML)
            if 'inputSet' in input_set_data and isinstance(input_set_data.get('inputSet'), dict):
                identifier = input_set_data.get('inputSet', {}).get('identifier', 'unknown')
            # Check for inputSetYaml string that needs parsing
            elif 'inputSetYaml' in input_set_data:
                try:
                    import yaml
                    parsed_yaml = yaml.safe_load(input_set_data['inputSetYaml'])
                    if parsed_yaml and isinstance(parsed_yaml, dict):
                        identifier = parsed_yaml.get('inputSet', {}).get('identifier', 'unknown')
                except:
                    pass
        
        response = self._make_request('POST', endpoint, params=params, data=input_set_data)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created input set")
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('input set', identifier, response.text, scope_info)}")
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
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('input set', input_set_identifier, response.text, scope_info)}")
            else:
                print(f"Failed to import input set from GitX: {response.status_code} - {response.text}")
            return False
    
    def list_triggers(self, pipeline_identifier: str, org_identifier: Optional[str] = None,
                     project_identifier: Optional[str] = None) -> List[Dict]:
        """List all triggers for a pipeline"""
        endpoint = "/pipeline/api/triggers"
        params = {
            'routingId': self.account_id,
            'accountIdentifier': self.account_id,
            'targetIdentifier': pipeline_identifier  # targetIdentifier is the pipeline identifier
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
        endpoint = f"/pipeline/api/triggers/{trigger_identifier}/details"
        params = {
            'routingId': self.account_id,
            'accountIdentifier': self.account_id,
            'targetIdentifier': pipeline_identifier  # targetIdentifier is the pipeline identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Trigger data is directly in 'data' key (not nested under 'trigger')
            trigger_data = data.get('data', {})
            return trigger_data
        else:
            print(f"Failed to get trigger data: {response.status_code} - {response.text}")
            return None
    
    def create_trigger(self, trigger_yaml: str, pipeline_identifier: str,
                      org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Create trigger from YAML content (triggers are always inline, not stored in GitX)"""
        endpoint = "/pipeline/api/triggers"
        params = {
            'routingId': self.account_id,
            'targetIdentifier': pipeline_identifier,  # targetIdentifier is the pipeline identifier
            'ignoreError': 'false',
            'storeType': 'INLINE'  # Triggers are always inline
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Send raw YAML content with Content-Type: application/yaml
        headers = {
            'Content-Type': 'application/yaml'
        }
        
        response = self._make_request('POST', endpoint, params=params, data=trigger_yaml, headers=headers)
        
        # Extract identifier from YAML for error messages
        identifier = 'unknown'
        try:
            import yaml
            parsed_yaml = yaml.safe_load(trigger_yaml)
            if parsed_yaml and isinstance(parsed_yaml, dict):
                identifier = parsed_yaml.get('trigger', {}).get('identifier', 'unknown')
        except:
            pass
        
        if response.status_code in [200, 201]:
            print(f"Successfully created trigger")
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('trigger', identifier, response.text, scope_info)}")
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
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('service', identifier, response.text, scope_info)}")
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
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('service', service_identifier, response.text, scope_info)}")
            else:
                print(f"Failed to import service from GitX: {response.status_code} - {response.text}")
            return False
    
    def list_overrides(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all overrides with pagination support
        
        Uses POST /ng/api/serviceOverrides/v2/list endpoint with null body
        Response structure: data.content array with override objects directly (not nested)
        """
        endpoint = "/ng/api/serviceOverrides/v2/list"
        params = {
            'routingId': self.account_id
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        all_items = []
        page = 0
        page_size = 100
        
        while True:
            params['page'] = page
            params['size'] = page_size
            
            # POST request with null body
            response = self._make_request('POST', endpoint, params=params, data=None)
            
            if response.status_code != 200:
                print(f"Failed to fetch overrides page {page}: {response.status_code} - {response.text}")
                break
            
            response_data = response.json()
            
            # Extract content from response - overrides are in data.content
            content = response_data.get('data', {}).get('content', [])
            if not isinstance(content, list):
                content = []
            
            all_items.extend(content)
            
            # Check pagination metadata
            total_pages = response_data.get('data', {}).get('totalPages')
            if total_pages is not None:
                if page >= total_pages - 1:
                    break
            elif len(content) < page_size:
                # If we got fewer items than page_size, we're done
                break
            
            # Continue to next page
            page += 1
            
            # Safety limit
            if page > 10000:
                print(f"Warning: Reached pagination limit at page {page}")
                break
        
        return all_items
    
    def get_override_data(self, override_identifier: str, org_identifier: Optional[str] = None,
                         project_identifier: Optional[str] = None, 
                         repo_name: Optional[str] = None, load_from_fallback_branch: bool = False) -> Optional[Dict]:
        """Get override data using GET endpoint
        
        Uses GET /ng/api/serviceOverrides/{identifier}
        For GitX overrides, requires repoName and loadFromFallbackBranch parameters
        """
        endpoint = f"/ng/api/serviceOverrides/{override_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # For GitX overrides, add repoName and loadFromFallbackBranch
        if repo_name:
            params['repoName'] = repo_name
            params['loadFromFallbackBranch'] = 'true' if load_from_fallback_branch else 'false'
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Override data is in data.data (not nested under 'override' key)
            override_data = data.get('data', {})
            return override_data
        else:
            print(f"Failed to get override data: {response.status_code} - {response.text}")
            return None
    
    def get_override_yaml(self, override_identifier: str, org_identifier: Optional[str] = None,
                          project_identifier: Optional[str] = None) -> Optional[str]:
        """Get override YAML"""
        override_data = self.get_override_data(override_identifier, org_identifier, project_identifier)
        if override_data:
            return override_data.get('yaml', '')
        return None
    
    def create_override(self, override_data: Dict, org_identifier: Optional[str] = None,
                       project_identifier: Optional[str] = None) -> bool:
        """Create/upsert override from override data (for inline resources)
        
        Uses POST /ng/api/serviceOverrides/upsert endpoint
        Requires: type, environmentRef, infraIdentifier (if applicable), identifier, spec, yaml
        """
        endpoint = "/ng/api/serviceOverrides/upsert"
        params = {
            'routingId': self.account_id
        }
        
        # Build request body from override data
        # Required fields: type, environmentRef, identifier, spec, yaml
        # Optional: infraIdentifier, serviceRef
        request_body = {
            'type': override_data.get('type'),
            'environmentRef': override_data.get('environmentRef'),
            'identifier': override_data.get('identifier'),
            'spec': override_data.get('spec', {}),
            'yaml': override_data.get('yaml', '')
        }
        
        # Add optional fields if present
        if 'infraIdentifier' in override_data:
            request_body['infraIdentifier'] = override_data['infraIdentifier']
        if 'serviceRef' in override_data:
            request_body['serviceRef'] = override_data['serviceRef']
        
        # Add scope identifiers
        if org_identifier:
            request_body['orgIdentifier'] = org_identifier
        if project_identifier:
            request_body['projectIdentifier'] = project_identifier
        
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        identifier = override_data.get('identifier', 'unknown')
        
        if response.status_code in [200, 201]:
            print(f"Successfully created/upserted override")
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('override', identifier, response.text, scope_info)}")
            else:
                print(f"Failed to create override: {response.status_code} - {response.text}")
            return False
    
    def import_override_yaml(self, override_data: Dict, git_details: Dict,
                            org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Import override from Git location (for GitX resources only)
        
        Uses POST /ng/api/serviceOverrides/import endpoint
        Query parameters: accountIdentifier, connectorRef, isHarnessCodeRepo, repoName, branch, filePath
        JSON body: type, environmentRef, serviceRef (if applicable), infraIdentifier (if applicable), orgIdentifier, projectIdentifier
        """
        endpoint = "/ng/api/serviceOverrides/import"
        params = {}
        
        # Add connector reference (required for GitX import)
        connector_ref = git_details.get('connectorRef')
        if not connector_ref:
            print(f"Failed to import override: connectorRef is required for GitX imports")
            return False
        params['connectorRef'] = connector_ref
        
        # Add isHarnessCodeRepo (defaults to false if not specified)
        params['isHarnessCodeRepo'] = git_details.get('isHarnessCodeRepo', 'false')
        
        # Add git details fields to query parameters
        if 'repoName' in git_details:
            params['repoName'] = git_details['repoName']
        if 'branch' in git_details:
            params['branch'] = git_details['branch']
        if 'filePath' in git_details:
            params['filePath'] = git_details['filePath']
        
        # Build request body with override metadata (not spec or yaml)
        request_body = {
            'type': override_data.get('type'),
            'environmentRef': override_data.get('environmentRef')
        }
        
        # Add optional fields if present
        if 'infraIdentifier' in override_data:
            request_body['infraIdentifier'] = override_data['infraIdentifier']
        if 'serviceRef' in override_data:
            request_body['serviceRef'] = override_data['serviceRef']
        
        # Add scope identifiers
        if org_identifier:
            request_body['orgIdentifier'] = org_identifier
        if project_identifier:
            request_body['projectIdentifier'] = project_identifier
        
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        identifier = override_data.get('identifier', 'unknown')
        
        if response.status_code in [200, 201]:
            print(f"Successfully imported override from GitX")
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('override', identifier, response.text, scope_info)}")
            else:
                print(f"Failed to import override from GitX: {response.status_code} - {response.text}")
            return False
    
    def list_webhooks(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all webhooks with pagination support
        
        Uses POST /v1/webhooks/list (account level)
        or POST /v1/orgs/{org}/webhooks/list (org level)
        or POST /v1/orgs/{org}/projects/{project}/webhooks/list (project level)
        Request body: empty JSON object {}
        Response: Direct array (not nested)
        """
        # Build endpoint based on scope
        if project_identifier and org_identifier:
            endpoint = f"/v1/orgs/{org_identifier}/projects/{project_identifier}/webhooks/list"
        elif org_identifier:
            endpoint = f"/v1/orgs/{org_identifier}/webhooks/list"
        else:
            endpoint = "/v1/webhooks/list"
        
        params = {}
        
        # Add harness-account header
        headers = {
            'harness-account': self.account_id
        }
        
        try:
            # Use _fetch_paginated helper
            # POST method, pagination in query params (limit/page), content is direct array (empty content_path)
            # Request body is empty JSON object
            return self._fetch_paginated(
                method='POST',
                endpoint=endpoint,
                params=params,
                data={},
                page_size=100,
                page_param_name='page',
                size_param_name='limit',  # Webhook API uses 'limit' not 'size'
                content_path='',  # Direct array response (not nested)
                total_pages_path='',  # No total pages in response
                pagination_in_body=False,  # Pagination in query params
                headers=headers
            )
        except Exception as e:
            print(f"Failed to list webhooks: {e}")
            return []
    
    def get_webhook_data(self, webhook_identifier: str, org_identifier: Optional[str] = None,
                         project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get webhook data using GET endpoint
        
        Uses GET /v1/webhooks/{identifier} (account level)
        or GET /v1/orgs/{org}/webhooks/{identifier} (org level)
        or GET /v1/orgs/{org}/projects/{project}/webhooks/{identifier} (project level)
        Webhooks are always inline (not stored in GitX)
        Response is a direct object (not nested under data)
        """
        # Build endpoint based on scope
        if project_identifier and org_identifier:
            endpoint = f"/v1/orgs/{org_identifier}/projects/{project_identifier}/webhooks/{webhook_identifier}"
        elif org_identifier:
            endpoint = f"/v1/orgs/{org_identifier}/webhooks/{webhook_identifier}"
        else:
            endpoint = f"/v1/webhooks/{webhook_identifier}"
        
        params = {}
        
        # Add harness-account header
        headers = {
            'harness-account': self.account_id
        }
        
        response = self._make_request('GET', endpoint, params=params, headers=headers)
        
        if response.status_code == 200:
            # Response is a direct object (not nested under data)
            webhook_data = response.json()
            return webhook_data
        else:
            print(f"Failed to get webhook data: {response.status_code} - {response.text}")
            return None
    
    def create_webhook(self, webhook_data: Dict, org_identifier: Optional[str] = None,
                      project_identifier: Optional[str] = None) -> bool:
        """Create/upsert webhook from webhook data (for inline resources)
        
        Uses POST /v1/webhooks (account level)
        or POST /v1/orgs/{org}/webhooks (org level)
        or POST /v1/orgs/{org}/projects/{project}/webhooks (project level)
        Requires: webhook_identifier, webhook_name, spec (with webhook_type, connector_ref, etc.)
        """
        # Build endpoint based on scope
        if project_identifier and org_identifier:
            endpoint = f"/v1/orgs/{org_identifier}/projects/{project_identifier}/webhooks"
        elif org_identifier:
            endpoint = f"/v1/orgs/{org_identifier}/webhooks"
        else:
            endpoint = "/v1/webhooks"
        
        params = {}
        
        # Build request body from webhook data
        # Use webhook_identifier and webhook_name (not identifier and name)
        request_body = {
            'webhook_identifier': webhook_data.get('webhook_identifier') or webhook_data.get('identifier'),
            'webhook_name': webhook_data.get('webhook_name') or webhook_data.get('name'),
            'spec': webhook_data.get('spec', {})
        }
        
        # Add optional fields if present
        if 'is_enabled' in webhook_data:
            request_body['is_enabled'] = webhook_data.get('is_enabled')
        
        # Add harness-account header
        headers = {
            'harness-account': self.account_id
        }
        
        response = self._make_request('POST', endpoint, params=params, data=request_body, headers=headers)
        
        identifier = webhook_data.get('webhook_identifier') or webhook_data.get('identifier', 'unknown')
        
        if response.status_code in [200, 201]:
            print(f"Successfully created webhook")
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('webhook', identifier, response.text, scope_info)}")
            else:
                print(f"Failed to create webhook: {response.status_code} - {response.text}")
            return False
    
    def list_policies(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all policies with pagination support
        
        Uses GET /pm/api/v1/policies with per_page and page query parameters
        Response: Direct array (not nested)
        """
        endpoint = "/pm/api/v1/policies"
        params = {
            'excludeRegoFromResponse': 'true',  # Exclude rego from list response for performance
            'includePolicySetCount': 'true'
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            # Use _fetch_paginated helper with GET method
            # Pagination uses per_page and page (not size and page)
            return self._fetch_paginated(
                method='GET',
                endpoint=endpoint,
                params=params,
                page_size=100,
                page_param_name='page',
                size_param_name='per_page',  # Policy API uses 'per_page' not 'size'
                content_path='',  # Direct array response (not nested)
                total_pages_path='',  # No total pages in response
                pagination_in_body=False
            )
        except Exception as e:
            print(f"Failed to list policies: {e}")
            return []
    
    def get_policy_data(self, policy_identifier: str, org_identifier: Optional[str] = None,
                       project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get policy data using GET endpoint
        
        Uses GET /pm/api/v1/policies/{identifier}
        Response is a direct object (not nested under data)
        """
        endpoint = f"/pm/api/v1/policies/{policy_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            # Response is a direct object (not nested under data)
            policy_data = response.json()
            return policy_data
        else:
            print(f"Failed to get policy data: {response.status_code} - {response.text}")
            return None
    
    def create_policy(self, policy_data: Dict, org_identifier: Optional[str] = None,
                     project_identifier: Optional[str] = None) -> bool:
        """Create/upsert policy from policy data (for inline resources)
        
        Uses POST /pm/api/v1/policies endpoint
        Requires: identifier, name, rego (not yaml)
        """
        endpoint = "/pm/api/v1/policies"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Build request body from policy data
        # Use rego field (not yaml)
        request_body = {
            'identifier': policy_data.get('identifier'),
            'name': policy_data.get('name'),
            'rego': policy_data.get('rego', '')
        }
        
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        identifier = policy_data.get('identifier', 'unknown')
        
        if response.status_code in [200, 201]:
            print(f"Successfully created policy")
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('policy', identifier, response.text, scope_info)}")
            else:
                print(f"Failed to create policy: {response.status_code} - {response.text}")
            return False
    
    def list_policy_sets(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all policy sets with pagination support
        
        Uses GET /pm/api/v1/policysets with per_page and page query parameters
        Response: Direct array (not nested)
        """
        endpoint = "/pm/api/v1/policysets"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            # Use _fetch_paginated helper with GET method
            # Pagination uses per_page and page (not size and page)
            return self._fetch_paginated(
                method='GET',
                endpoint=endpoint,
                params=params,
                page_size=100,
                page_param_name='page',
                size_param_name='per_page',  # Policy set API uses 'per_page' not 'size'
                content_path='',  # Direct array response (not nested)
                total_pages_path='',  # No total pages in response
                pagination_in_body=False
            )
        except Exception as e:
            print(f"Failed to list policy sets: {e}")
            return []
    
    def get_policy_set_data(self, policy_set_identifier: str, org_identifier: Optional[str] = None,
                           project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get policy set data using GET endpoint
        
        Uses GET /pm/api/v1/policysets/{identifier}
        Response is a direct object (not nested under data)
        """
        endpoint = f"/pm/api/v1/policysets/{policy_set_identifier}"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            # Response is a direct object (not nested under data)
            policy_set_data = response.json()
            return policy_set_data
        else:
            print(f"Failed to get policy set data: {response.status_code} - {response.text}")
            return None
    
    def create_policy_set(self, policy_set_data: Dict, org_identifier: Optional[str] = None,
                         project_identifier: Optional[str] = None) -> bool:
        """Create/upsert policy set from policy set data
        
        Uses POST /pm/api/v1/policysets endpoint
        Requires: identifier, name, type, action, description, enabled, policies (array of policy references)
        """
        identifier = policy_set_data.get('identifier')
        if not identifier:
            print("Policy set identifier is required")
            return False
        
        endpoint = "/pm/api/v1/policysets"
        params = {}
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Transform policies array: extract only identifier and severity, and scope identifiers properly
        policies_list = policy_set_data.get('policies', [])
        transformed_policies = []
        for policy in policies_list:
            # Policy can be a dict with full policy data or just identifier/severity
            policy_identifier = policy.get('identifier', '')
            severity = policy.get('severity', '')
            
            if not policy_identifier:
                continue
            
            # Check if identifier is already scoped (starts with "account." or "org.")
            if policy_identifier.startswith('account.') or policy_identifier.startswith('org.'):
                # Already scoped, use as-is
                scoped_identifier = policy_identifier
            else:
                # Scope the policy identifier based on where the policy is located
                # Check if policy has account_id, org_id, project_id to determine scope
                policy_org_id = policy.get('org_id', '')
                policy_project_id = policy.get('project_id', '')
                
                # If policy has no org_id and no project_id, it's account level
                if not policy_org_id and not policy_project_id:
                    scoped_identifier = f"account.{policy_identifier}"
                # If policy has org_id but no project_id, it's org level
                elif policy_org_id and not policy_project_id:
                    scoped_identifier = f"org.{policy_identifier}"
                # Otherwise, it's project level (just use the identifier as-is)
                else:
                    scoped_identifier = policy_identifier
            
            transformed_policies.append({
                'identifier': scoped_identifier,
                'severity': severity
            })
        
        # Build request body from policy set data
        # Do not include 'id' field - it's not in the API
        request_body = {
            'identifier': identifier,
            'name': policy_set_data.get('name', identifier),
            'type': policy_set_data.get('type', ''),
            'action': policy_set_data.get('action', ''),
            'description': policy_set_data.get('description', ''),
            'enabled': policy_set_data.get('enabled', False)
        }
        
        # Include policies if present
        if transformed_policies:
            request_body['policies'] = transformed_policies
        
        # Use POST method (not PATCH)
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created policy set")
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('policy set', identifier, response.text, scope_info)}")
            else:
                print(f"Failed to create policy set: {response.status_code} - {response.text}")
            return False
    
    def list_roles(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all roles with pagination support
        
        Uses GET /authz/api/roles endpoint
        Response: Nested under data.content, each item has 'role' key
        Pagination uses pageIndex and pageSize (not page and size)
        """
        endpoint = "/authz/api/roles"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            # Use _fetch_paginated helper with GET method
            # Pagination uses pageIndex and pageSize
            # Response is nested: data.content array, each item has 'role' key
            items = self._fetch_paginated(
                'GET', endpoint, params=params,
                page_param_name='pageIndex',
                size_param_name='pageSize',
                content_path='data.content'
            )
            
            # Extract role data from each item (each has a 'role' key)
            all_roles = []
            for item in items:
                role_data = item.get('role', item)
                all_roles.append(role_data)
            
            return all_roles
        except Exception as e:
            print(f"Failed to list roles: {e}")
            return []
    
    def get_role_data(self, role_identifier: str, org_identifier: Optional[str] = None,
                     project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get role data - try GET endpoint, fallback to list if needed
        
        Uses GET /authz/api/roles/{identifier} if available
        Otherwise, we can get role data from list response
        Response structure may vary
        """
        endpoint = f"/authz/api/roles/{role_identifier}"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Response may be nested under data.role
            role_data = data.get('data', {}).get('role', data.get('data', data))
            return role_data
        else:
            # If GET fails, return None (caller can use list data)
            print(f"Failed to get role data: {response.status_code} - {response.text}")
            return None
    
    def create_role(self, role_data: Dict, org_identifier: Optional[str] = None,
                   project_identifier: Optional[str] = None) -> bool:
        """Create and update role from role data
        
        Harness requires a two-step process:
        1. Create role with POST /authz/api/roles (without permissions)
        2. Update role with PUT /authz/api/roles/{identifier} (with permissions)
        """
        identifier = role_data.get('identifier')
        if not identifier:
            print("Role identifier is required")
            return False
        
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Step 1: Create role with POST (without permissions)
        create_endpoint = "/authz/api/roles"
        create_body = {
            'identifier': identifier,
            'name': role_data.get('name', identifier)
        }
        
        # Add optional fields for creation (but not permissions)
        if 'description' in role_data:
            create_body['description'] = role_data.get('description')
        if 'tags' in role_data:
            create_body['tags'] = role_data.get('tags')
        
        create_response = self._make_request('POST', create_endpoint, params=params, data=create_body)
        
        if create_response.status_code not in [200, 201]:
            if is_resource_already_exists_error(create_response.status_code, create_response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('role', identifier, create_response.text, scope_info)}")
            else:
                print(f"Failed to create role: {create_response.status_code} - {create_response.text}")
            return False
        
        # Step 2: Update role with PUT to add permissions and allowedScopeLevels
        update_endpoint = f"/authz/api/roles/{identifier}"
        update_body = {
            'identifier': identifier,
            'name': role_data.get('name', identifier),
            'permissions': role_data.get('permissions', []),
            'allowedScopeLevels': role_data.get('allowedScopeLevels', [])
        }
        
        # Add optional fields
        if 'description' in role_data:
            update_body['description'] = role_data.get('description')
        if 'tags' in role_data:
            update_body['tags'] = role_data.get('tags')
        
        update_response = self._make_request('PUT', update_endpoint, params=params, data=update_body)
        
        if update_response.status_code in [200, 201]:
            print(f"Successfully created and updated role")
            return True
        else:
            print(f"Failed to update role with permissions: {update_response.status_code} - {update_response.text}")
            return False
    
    def list_resource_groups(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all resource groups with pagination support
        
        Uses GET /resourcegroup/api/v2/resourcegroup endpoint
        Response: Nested under data.content, each item has 'resourceGroup' key
        Pagination uses pageIndex and pageSize (not page and size)
        """
        endpoint = "/resourcegroup/api/v2/resourcegroup"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            # Use _fetch_paginated helper with GET method
            # Pagination uses pageIndex and pageSize
            # Response is nested: data.content array, each item has 'resourceGroup' key
            items = self._fetch_paginated(
                'GET', endpoint, params=params,
                page_param_name='pageIndex',
                size_param_name='pageSize',
                content_path='data.content'
            )
            
            # Extract resource group data from each item (each has a 'resourceGroup' key)
            all_resource_groups = []
            for item in items:
                resource_group_data = item.get('resourceGroup', item)
                all_resource_groups.append(resource_group_data)
            
            return all_resource_groups
        except Exception as e:
            print(f"Failed to list resource groups: {e}")
            return []
    
    def get_resource_group_data(self, resource_group_identifier: str, org_identifier: Optional[str] = None,
                               project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get resource group data using GET endpoint
        
        Uses GET /resourcegroup/api/v2/resourcegroup/{identifier}
        Response is nested under data.resourceGroup
        """
        endpoint = f"/resourcegroup/api/v2/resourcegroup/{resource_group_identifier}"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Response is nested under data.resourceGroup
            resource_group_data = data.get('data', {}).get('resourceGroup', data.get('data', {}))
            return resource_group_data
        else:
            print(f"Failed to get resource group data: {response.status_code} - {response.text}")
            return None
    
    def create_resource_group(self, resource_group_data: Dict, org_identifier: Optional[str] = None,
                             project_identifier: Optional[str] = None) -> bool:
        """Create/upsert resource group from resource group data
        
        Uses PUT /resourcegroup/api/v2/resourcegroup/{identifier} endpoint
        Request body must have nested 'resourceGroup' structure
        """
        identifier = resource_group_data.get('identifier')
        if not identifier:
            print("Resource group identifier is required")
            return False
        
        endpoint = f"/resourcegroup/api/v2/resourcegroup/{identifier}"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Build request body with nested resourceGroup structure
        # Include all fields from resource_group_data
        request_body = {
            'resourceGroup': resource_group_data
        }
        
        # Use PUT method
        response = self._make_request('PUT', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created resource group")
            return True
        else:
            print(f"Failed to create resource group: {response.status_code} - {response.text}")
            return False
    
    def list_settings(self, category: Optional[str] = None, org_identifier: Optional[str] = None,
                     project_identifier: Optional[str] = None) -> List[Dict]:
        """List all settings with optional category filter
        
        Uses GET /ng/api/settings endpoint
        Response: Array of settings, each with 'setting' key containing setting data
        """
        endpoint = "/ng/api/settings"
        params = {}
        if category:
            params['category'] = category
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Response is an array of settings, each with 'setting' key
            settings_list = data.get('data', [])
            # Extract setting data from each item
            settings = []
            for item in settings_list:
                setting_data = item.get('setting', item)
                settings.append(setting_data)
            return settings
        else:
            print(f"Failed to list settings: {response.status_code} - {response.text}")
            return []
    
    def update_settings(self, settings_updates: List[Dict], org_identifier: Optional[str] = None,
                       project_identifier: Optional[str] = None) -> bool:
        """Update settings
        
        Uses PUT /ng/api/settings endpoint
        Request body: Array of setting updates with allowOverrides, updateType, identifier, value
        """
        endpoint = "/ng/api/settings"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Build request body as array of setting updates
        request_body = settings_updates
        
        # Use PUT method
        response = self._make_request('PUT', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            print(f"Successfully updated settings")
            return True
        else:
            print(f"Failed to update settings: {response.status_code} - {response.text}")
            return False
    
    def list_ip_allowlists(self) -> List[Dict]:
        """List all IP allowlists
        
        Uses GET /v1/ip-allowlist endpoint
        Response: Direct array, each item has 'ip_allowlist_config' key
        IP allowlists are account-level only (no org/project scoping)
        """
        endpoint = "/v1/ip-allowlist"
        headers = {
            'harness-account': self.account_id  # harness-account header is required
        }
        
        response = self._make_request('GET', endpoint, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            # Response is a direct array, each item has 'ip_allowlist_config' key
            allowlists = []
            for item in data:
                allowlist_data = item.get('ip_allowlist_config', item)
                allowlists.append(allowlist_data)
            return allowlists
        else:
            print(f"Failed to list IP allowlists: {response.status_code} - {response.text}")
            return []
    
    def create_ip_allowlist(self, ip_allowlist_data: Dict) -> bool:
        """Create IP allowlist from IP allowlist data
        
        Uses POST /v1/ip-allowlist endpoint
        Request body must have nested 'ip_allowlist_config' structure
        IP allowlists are account-level only (no org/project scoping)
        """
        endpoint = "/v1/ip-allowlist"
        headers = {
            'harness-account': self.account_id  # harness-account header is required
        }
        
        # Extract identifier from ip_allowlist_data
        identifier = ip_allowlist_data.get('identifier', 'unknown')
        
        # Build request body with nested ip_allowlist_config structure
        request_body = {
            'ip_allowlist_config': ip_allowlist_data
        }
        
        # Use POST method
        response = self._make_request('POST', endpoint, headers=headers, data=request_body)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created IP allowlist")
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(None, None)  # IP allowlists are account-level only
                print(f"  {format_resource_already_exists_message('IP allowlist', identifier, response.text, scope_info)}")
            else:
                print(f"Failed to create IP allowlist: {response.status_code} - {response.text}")
            return False
    
    def list_users(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all users with pagination support
        
        Uses POST /ng/api/user/aggregate endpoint
        Response: Nested under data.content, each item has 'user' key and 'roleAssignmentMetadata' array
        Pagination uses pageIndex and pageSize (not page and size)
        """
        endpoint = "/ng/api/user/aggregate"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            # Use _fetch_paginated helper with POST method
            # Pagination uses pageIndex and pageSize (in query params, not body)
            # Response is nested: data.content array, each item has 'user' key
            items = self._fetch_paginated(
                'POST', endpoint, params=params, data={},
                page_param_name='pageIndex',
                size_param_name='pageSize',
                content_path='data.content',
                pagination_in_body=False
            )
            
            # Extract user data from each item (each has a 'user' key)
            all_users = []
            for item in items:
                user_data = item.get('user', item)
                # Also include roleAssignmentMetadata for migration
                role_assignments = item.get('roleAssignmentMetadata', [])
                # Combine user data with role assignments
                user_with_roles = user_data.copy()
                user_with_roles['roleAssignmentMetadata'] = role_assignments
                all_users.append(user_with_roles)
            
            return all_users
        except Exception as e:
            print(f"Failed to list users: {e}")
            return []
    
    def create_user(self, user_data: Dict, org_identifier: Optional[str] = None,
                   project_identifier: Optional[str] = None) -> bool:
        """Create/invite user from user data
        
        Uses POST /ng/api/user/users endpoint
        Request body: JSON with emails (array), userGroups (array), roleBindings (array)
        """
        endpoint = "/ng/api/user/users"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Extract email from user data
        email = user_data.get('email', '')
        if not email:
            print("User email is required")
            return False
        
        # Build request body
        # Extract role bindings from roleAssignmentMetadata
        role_bindings = []
        role_assignment_metadata = user_data.get('roleAssignmentMetadata', [])
        for role_assignment in role_assignment_metadata:
            role_binding = {
                'resourceGroupIdentifier': role_assignment.get('resourceGroupIdentifier', ''),
                'roleIdentifier': role_assignment.get('roleIdentifier', ''),
                'roleName': role_assignment.get('roleName', ''),
                'resourceGroupName': role_assignment.get('resourceGroupName', ''),
                'managedRole': role_assignment.get('managedRole', False)
            }
            role_bindings.append(role_binding)
        
        request_body = {
            'emails': [email],
            'userGroups': [],  # User groups are not migrated, so leave empty
            'roleBindings': role_bindings
        }
        
        # Use POST method
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            # Check response for success
            response_data = response.json()
            add_user_response_map = response_data.get('data', {}).get('addUserResponseMap', {})
            user_status = add_user_response_map.get(email, '')
            if user_status in ['USER_INVITED_SUCCESSFULLY', 'USER_ADDED_SUCCESSFULLY']:
                print(f"Successfully created user")
                return True
            elif user_status == 'USER_ALREADY_ADDED':
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  User '{email}' is already a member at {scope_info}. Skipping migration.")
                return False
            elif user_status == 'USER_ALREADY_INVITED':
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  User '{email}' has already been invited at {scope_info}. Skipping migration.")
                return False
            else:
                print(f"User creation returned unexpected status: {user_status}")
                return False
        else:
            print(f"Failed to create user: {response.status_code} - {response.text}")
            return False
    
    def list_service_accounts(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all service accounts with pagination support
        
        Uses GET /ng/api/serviceaccount/aggregate endpoint
        Response: Nested under data.content, each item has 'serviceAccount' key and 'roleAssignmentsMetadataDTO' array
        Pagination uses pageIndex and pageSize (not page and size)
        """
        endpoint = "/ng/api/serviceaccount/aggregate"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            # Use _fetch_paginated helper with GET method
            # Pagination uses pageIndex and pageSize
            # Response is nested: data.content array, each item has 'serviceAccount' key
            items = self._fetch_paginated(
                'GET', endpoint, params=params,
                page_param_name='pageIndex',
                size_param_name='pageSize',
                content_path='data.content'
            )
            
            # Extract service account data from each item (each has a 'serviceAccount' key)
            all_service_accounts = []
            for item in items:
                service_account_data = item.get('serviceAccount', item)
                # Also include roleAssignmentsMetadataDTO for migration (note: it's roleAssignmentsMetadataDTO, not roleAssignmentMetadata)
                # This field is always present in the item, regardless of API key count
                role_assignments = item.get('roleAssignmentsMetadataDTO', [])
                if role_assignments is None:
                    role_assignments = []
                # Combine service account data with role assignments
                service_account_with_roles = service_account_data.copy()
                service_account_with_roles['roleAssignmentMetadata'] = role_assignments  # Normalize to roleAssignmentMetadata for consistency
                all_service_accounts.append(service_account_with_roles)
            
            return all_service_accounts
        except Exception as e:
            print(f"Failed to list service accounts: {e}")
            return []
    
    def get_service_account_data(self, service_account_identifier: str, org_identifier: Optional[str] = None,
                                 project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get service account data using GET endpoint
        
        Uses GET /ng/api/serviceaccount/{identifier}
        Response is nested under data.serviceAccount
        """
        endpoint = f"/ng/api/serviceaccount/{service_account_identifier}"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Response is nested under data.serviceAccount
            service_account_data = data.get('data', {}).get('serviceAccount', data.get('data', {}))
            return service_account_data
        else:
            print(f"Failed to get service account data: {response.status_code} - {response.text}")
            return None
    
    def create_service_account(self, service_account_data: Dict, org_identifier: Optional[str] = None,
                               project_identifier: Optional[str] = None) -> bool:
        """Create service account from service account data
        
        Uses POST /ng/api/serviceaccount endpoint
        Request body: JSON with identifier, name, description, tags, accountIdentifier, email, roleBindings (array)
        """
        endpoint = "/ng/api/serviceaccount"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Build request body from service account data
        identifier = service_account_data.get('identifier')
        if not identifier:
            print("Service account identifier is required")
            return False
        
        # Create service account WITHOUT role bindings (they will be added separately)
        request_body = {
            'identifier': identifier,
            'name': service_account_data.get('name', identifier),
            'description': service_account_data.get('description', ''),
            'tags': service_account_data.get('tags', {}),
            'accountIdentifier': self.account_id,  # Use accountIdentifier (not accountId)
            'email': service_account_data.get('email', '')
        }
        
        # Add orgIdentifier and projectIdentifier if present
        if org_identifier:
            request_body['orgIdentifier'] = org_identifier
        if project_identifier:
            request_body['projectIdentifier'] = project_identifier
        
        # Use POST method
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created service account")
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('service account', identifier, response.text, scope_info)}")
            else:
                print(f"Failed to create service account: {response.status_code} - {response.text}")
            return False
    
    def add_role_bindings_to_service_account(self, service_account_identifier: str, role_bindings: List[Dict],
                                            org_identifier: Optional[str] = None,
                                            project_identifier: Optional[str] = None) -> bool:
        """Add role bindings to an existing service account
        
        Uses POST /authz/api/roleassignments/multi endpoint
        Request body: JSON with roleAssignments array
        Each role assignment has resourceGroupIdentifier, roleIdentifier, and principal (with identifier, type, scopeLevel)
        """
        endpoint = "/authz/api/roleassignments/multi"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Determine scope level
        if project_identifier:
            scope_level = 'project'
        elif org_identifier:
            scope_level = 'organization'
        else:
            scope_level = 'account'
        
        # Build roleAssignments array from role_bindings
        role_assignments = []
        for role_binding in role_bindings:
            role_assignment = {
                'resourceGroupIdentifier': role_binding.get('resourceGroupIdentifier', ''),
                'roleIdentifier': role_binding.get('roleIdentifier', ''),
                'principal': {
                    'identifier': service_account_identifier,
                    'type': 'SERVICE_ACCOUNT',
                    'scopeLevel': scope_level
                }
            }
            role_assignments.append(role_assignment)
        
        # Build request body
        request_body = {
            'roleAssignments': role_assignments
        }
        
        # Use POST method
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            print(f"Successfully added {len(role_assignments)} role binding(s) to service account")
            return True
        else:
            print(f"Failed to add role bindings to service account: {response.status_code} - {response.text}")
            return False
    
    def list_api_keys_for_service_account(self, service_account_identifier: str, org_identifier: Optional[str] = None,
                                         project_identifier: Optional[str] = None) -> List[Dict]:
        """List API keys for a service account
        
        Uses GET /ng/api/apikey/aggregate endpoint
        Query parameters: apiKeyType=SERVICE_ACCOUNT, parentIdentifier={service_account_identifier}
        """
        endpoint = "/ng/api/apikey/aggregate"
        params = {
            'routingId': self.account_id,  # routingId is required
            'apiKeyType': 'SERVICE_ACCOUNT',
            'parentIdentifier': service_account_identifier
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            response = self._make_request('GET', endpoint, params=params)
            
            if response.status_code != 200:
                print(f"Failed to list API keys for service account: {response.status_code} - {response.text}")
                return []
            
            data = response.json()
            # Extract from nested structure: data.content
            content = data.get('data', {}).get('content', [])
            
            # Extract API key data from each item
            api_keys = []
            for item in content:
                # API key data might be nested under 'apiKey' key or directly in item
                api_key_data = item.get('apiKey', item)
                api_keys.append(api_key_data)
            
            return api_keys
        except Exception as e:
            print(f"Failed to list API keys for service account: {e}")
            return []
    
    def create_api_key_for_service_account(self, api_key_data: Dict, org_identifier: Optional[str] = None,
                                          project_identifier: Optional[str] = None) -> bool:
        """Create API key for a service account
        
        Uses POST /ng/api/apikey endpoint
        Request body: JSON with identifier, name, description, tags, accountIdentifier, apiKeyType: "SERVICE_ACCOUNT", orgIdentifier, projectIdentifier, parentIdentifier
        """
        endpoint = "/ng/api/apikey"
        params = {
            'routingId': self.account_id  # routingId is required
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Build request body from API key data
        identifier = api_key_data.get('identifier')
        if not identifier:
            print("API key identifier is required")
            return False
        
        request_body = {
            'identifier': identifier,
            'name': api_key_data.get('name', identifier),
            'description': api_key_data.get('description', ''),
            'tags': api_key_data.get('tags', {}),
            'accountIdentifier': self.account_id,
            'apiKeyType': 'SERVICE_ACCOUNT',
            'parentIdentifier': api_key_data.get('parentIdentifier', '')
        }
        
        # Add orgIdentifier and projectIdentifier if present
        if org_identifier:
            request_body['orgIdentifier'] = org_identifier
        if project_identifier:
            request_body['projectIdentifier'] = project_identifier
        
        # Use POST method
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            print(f"Successfully created API key")
            return True
        else:
            print(f"Failed to create API key: {response.status_code} - {response.text}")
            return False
    
    # User Journeys (SRM)
    def list_user_journeys(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all user journeys with pagination support"""
        endpoint = "/cv/api/user-journey"
        params = {
            'routingId': self.account_id,
            'accountId': self.account_id,  # Required by user journey API
            'offset': 0,
            'pageSize': 100
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            # Remove offset and pageSize from params - _fetch_paginated will handle them
            params.pop('offset', None)
            params.pop('pageSize', None)
            
            # Use _fetch_paginated helper
            # Pagination uses offset and pageSize (offset-based, not page-based)
            # Response is nested: data.content array
            return self._fetch_paginated(
                'GET', endpoint, params=params,
                page_param_name='offset',
                size_param_name='pageSize',
                content_path='data.content',
                page_size=100,
                use_offset=True
            )
        except Exception as e:
            print(f"Failed to list user journeys: {e}")
            return []
    
    def create_user_journey(self, identifier: str, name: str, org_identifier: Optional[str] = None,
                           project_identifier: Optional[str] = None) -> bool:
        """Create user journey"""
        endpoint = "/cv/api/user-journey/create"
        params = {
            'routingId': self.account_id,
            'accountId': self.account_id  # Required by user journey API
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        request_body = {
            'identifier': identifier,
            'name': name
        }
        
        response = self._make_request('POST', endpoint, params=params, data=request_body)
        
        if response.status_code in [200, 201]:
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                # Build scope info string
                if not org_identifier:
                    scope_info = "account level"
                elif not project_identifier:
                    scope_info = f"org {org_identifier} level"
                else:
                    scope_info = f"project {project_identifier} (org {org_identifier}) level"
                print(f"  {format_resource_already_exists_message('user journey', identifier, response.text, scope_info)}")
            else:
                print(f"Failed to create user journey: {response.status_code} - {response.text}")
            return False
    
    # Monitored Services (SRM)
    def list_monitored_services(self, org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> List[Dict]:
        """List all monitored services with pagination support"""
        endpoint = "/cv/api/monitored-service"
        params = {
            'routingId': self.account_id,
            'accountId': self.account_id,  # Required by monitored service API
            'offset': 0,
            'pageSize': 10,
            'filter': '',
            'servicesAtRiskFilter': 'false'
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        try:
            # Remove offset and pageSize from params - _fetch_paginated will handle them
            # Note: monitored services uses pageSize=10 by default, but we'll use 100 for efficiency
            params.pop('offset', None)
            page_size = params.pop('pageSize', 100)
            
            # Use _fetch_paginated helper
            # Pagination uses offset and pageSize (offset-based, not page-based)
            # Response is nested: data.content array
            return self._fetch_paginated(
                'GET', endpoint, params=params,
                page_param_name='offset',
                size_param_name='pageSize',
                content_path='data.content',
                page_size=page_size,
                use_offset=True
            )
        except Exception as e:
            print(f"Failed to list monitored services: {e}")
            return []
    
    def get_monitored_service_data(self, identifier: str, org_identifier: Optional[str] = None,
                                  project_identifier: Optional[str] = None) -> Optional[Dict]:
        """Get monitored service data"""
        endpoint = f"/cv/api/monitored-service/{identifier}"
        params = {
            'routingId': self.account_id,
            'accountId': self.account_id  # Required by monitored service API
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        response = self._make_request('GET', endpoint, params=params)
        
        if response.status_code == 200:
            data = response.json()
            # Extract from nested structure if present
            monitored_service_data = data.get('data', {}).get('monitoredService', data.get('data', {}))
            return monitored_service_data
        else:
            print(f"Failed to get monitored service data: {response.status_code} - {response.text}")
            return None
    
    def create_monitored_service(self, monitored_service_data: Dict, org_identifier: Optional[str] = None,
                                project_identifier: Optional[str] = None) -> bool:
        """Create monitored service"""
        endpoint = "/cv/api/monitored-service"
        params = {
            'routingId': self.account_id,
            'accountId': self.account_id  # Required by monitored service API
        }
        
        # Clean data for creation
        cleaned_data = remove_none_values(clean_for_creation(monitored_service_data))
        
        response = self._make_request('POST', endpoint, params=params, data=cleaned_data)
        
        if response.status_code in [200, 201]:
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                identifier = cleaned_data.get('identifier', 'unknown')
                # Build scope info string
                if not org_identifier:
                    scope_info = "account level"
                elif not project_identifier:
                    scope_info = f"org {org_identifier} level"
                else:
                    scope_info = f"project {project_identifier} (org {org_identifier}) level"
                print(f"  {format_resource_already_exists_message('monitored service', identifier, response.text, scope_info)}")
            else:
                print(f"Failed to create monitored service: {response.status_code} - {response.text}")
            return False
    
    def update_monitored_service(self, identifier: str, monitored_service_data: Dict,
                                org_identifier: Optional[str] = None, project_identifier: Optional[str] = None) -> bool:
        """Update monitored service (used to add health sources)"""
        endpoint = f"/cv/api/monitored-service/{identifier}"
        params = {
            'routingId': self.account_id,
            'accountId': self.account_id  # Required by monitored service API
        }
        if org_identifier:
            params['orgIdentifier'] = org_identifier
        if project_identifier:
            params['projectIdentifier'] = project_identifier
        
        # Clean data for update
        cleaned_data = remove_none_values(clean_for_creation(monitored_service_data))
        
        response = self._make_request('PUT', endpoint, params=params, data=cleaned_data)
        
        if response.status_code in [200, 201]:
            return True
        else:
            print(f"Failed to update monitored service: {response.status_code} - {response.text}")
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
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('environment', identifier, response.text, scope_info)}")
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
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('environment', environment_identifier, response.text, scope_info)}")
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
                # Extract identifier from YAML for error messages
                identifier = 'unknown'
                try:
                    import yaml
                    parsed_yaml = yaml.safe_load(yaml_content)
                    if parsed_yaml and isinstance(parsed_yaml, dict):
                        identifier = parsed_yaml.get('connector', {}).get('identifier', 'unknown')
                except:
                    pass
                
                if is_resource_already_exists_error(response.status_code, response.text):
                    scope_info = get_scope_info(org_identifier, project_identifier)
                    print(f"  {format_resource_already_exists_message('connector', identifier, response.text, scope_info)}")
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
    
    def create_infrastructure(self, yaml_content: str, infrastructure_identifier: str, environment_identifier: str,
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
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('infrastructure', infrastructure_identifier, response.text, scope_info)}")
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
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('infrastructure', infrastructure_identifier, response.text, scope_info)}")
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
        
        # Use _fetch_paginated helper with POST method
        # Pagination uses pageIndex and pageSize (in query params, not body)
        # Response is nested: data.content array
        return self._fetch_paginated(
            'POST', endpoint, params=params,
            data={'filterType': 'Secret'},
            page_param_name='pageIndex',
            size_param_name='pageSize',
            content_path='data.content',
            pagination_in_body=False
        )
    
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
        
        identifier = cleaned_data.get('identifier', 'unknown')
        
        if response.status_code in [200, 201]:
            print(f"Successfully created secret")
            if is_harness_secret_manager:
                print(f"  Warning: Secret uses harnessSecretManager ({secret_manager_identifier}), value set to 'changeme' - please update manually")
            return True
        else:
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message('secret', identifier, response.text, scope_info)}")
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
                if is_resource_already_exists_error(response.status_code, response.text):
                    scope_info = get_scope_info(org_identifier, project_identifier)
                    print(f"  {format_resource_already_exists_message(f'template version {version}', identifier, response.text, scope_info)}")
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
            if is_resource_already_exists_error(response.status_code, response.text):
                scope_info = get_scope_info(org_identifier, project_identifier)
                print(f"  {format_resource_already_exists_message(f'template version {version}', template_identifier, response.text, scope_info)}")
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
            
            # Skip default organization
            if self._is_default_organization(identifier):
                print(f"\nSkipping default organization: {name} ({identifier})")
                results['skipped'] += 1
                continue
            
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
            
            # Skip default project
            if self._is_default_project(identifier):
                print(f"\nSkipping default project: {name} ({identifier})" + (f" in org {org_id}" if org_id else ""))
                results['skipped'] += 1
                continue
            
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
    
    def _is_default_organization(self, org_identifier: str) -> bool:
        """Check if an organization is a default resource that should be skipped"""
        return org_identifier == 'default'
    
    def _is_default_project(self, project_identifier: str) -> bool:
        """Check if a project is a default resource that should be skipped"""
        return project_identifier == 'default_project'
    
    def _get_scope_info(self, org_identifier: Optional[str], project_identifier: Optional[str]) -> str:
        """Get scope information string for error messages"""
        if not org_identifier:
            return "account level"
        elif not project_identifier:
            return f"org {org_identifier} level"
        else:
            return f"project {project_identifier} (org {org_identifier}) level"
    
    def _is_default_connector(self, connector_identifier: str, org_id: Optional[str], project_id: Optional[str]) -> bool:
        """Check if a connector is a default resource that should be skipped"""
        # Skip harnessImage connector at account level
        if not org_id and not project_id and connector_identifier == 'harnessImage':
            return True
        # Skip harnessSecretManager connector at all scopes
        if connector_identifier == 'harnessSecretManager':
            return True
        return False
    
    def _is_custom_secret_manager_connector(self, connector_data: Dict) -> bool:
        """Check if a connector is a custom secret manager connector (only 'customsecretmanager' type)"""
        connector_type = connector_data.get('type', '').lower()
        return connector_type == 'customsecretmanager'
    
    def _is_secret_manager_connector(self, connector_data: Dict) -> bool:
        """Check if a connector is a secret manager connector (excluding custom secret manager)"""
        # Secret manager connectors typically have a 'type' field that indicates secret manager types
        # Common secret manager connector types: Vault, AwsSecretManager, AzureKeyVault, GcpKms, etc.
        # Excludes 'customsecretmanager' which is handled separately
        connector_type = connector_data.get('type', '').lower()
        secret_manager_types = [
            'vault', 'awssecretmanager', 'azurekeyvault', 'gcpkms', 
            'awssecretsmanager', 'azuresecretmanager'
        ]
        return connector_type in secret_manager_types
    
    def _is_builtin_example_policy(self, policy_identifier: str) -> bool:
        """Check if a policy is a built-in example policy that should be skipped
        
        Built-in example policies have IDs matching the pattern: builtin-example-policy-[0-9]+
        """
        if not policy_identifier:
            return False
        # Match pattern: builtin-example-policy followed by one or more digits
        pattern = r'^builtin-example-policy-\d+$'
        return bool(re.match(pattern, policy_identifier))
    
    def _is_builtin_resource_group(self, identifier: str) -> bool:
        """Check if a resource group identifier is built-in (starts with underscore)
        
        Built-in resource groups have IDs that start with "_" and should be skipped during migration.
        """
        if not identifier:
            return False
        return identifier.startswith('_')
    
    def _is_builtin_role(self, identifier: str) -> bool:
        """Check if a role identifier is built-in (starts with underscore)
        
        Built-in roles have IDs that start with "_" and should be skipped during migration.
        """
        if not identifier:
            return False
        return identifier.startswith('_')
    
    def migrate_custom_secret_manager_connectors(self) -> Dict[str, Any]:
        """Migrate custom secret manager connectors at all scopes (account, org, project)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Custom Secret Manager Connectors ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing custom secret manager connectors at {scope_label} ---")
            
            connectors = self.source_client.list_connectors(org_id, project_id)
            
            for connector in connectors:
                connector_data = connector.get('connector', connector)
                
                # Only process custom secret manager connectors
                if not self._is_custom_secret_manager_connector(connector_data):
                    continue
                
                identifier = connector_data.get('identifier', '')
                
                # Skip default connectors
                if self._is_default_connector(identifier, org_id, project_id):
                    results['skipped'] += 1
                    continue
                
                name = connector_data.get('name', identifier)
                print(f"\nProcessing custom secret manager connector: {name} ({identifier}) at {scope_label}")
                
                yaml_content = self.source_client.get_connector_yaml(
                    identifier, org_id, project_id
                )
                
                if not yaml_content:
                    print(f"  Failed to get YAML for connector {name}")
                    results['failed'] += 1
                    continue
                
                # Save exported YAML with scope in filename
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                export_file = self.export_dir / f"connector_secret_manager_{identifier}{scope_suffix}.yaml"
                export_file.write_text(yaml_content)
                print(f"  Exported YAML to {export_file}")
                
                # Create connector in destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create custom secret manager connector to destination account")
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
    
    def migrate_secret_manager_connectors(self) -> Dict[str, Any]:
        """Migrate secret manager connectors at all scopes (account, org, project) - excludes custom secret manager"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Secret Manager Connectors ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing secret manager connectors at {scope_label} ---")
            
            connectors = self.source_client.list_connectors(org_id, project_id)
            
            for connector in connectors:
                connector_data = connector.get('connector', connector)
                
                # Only process secret manager connectors (excluding custom secret manager)
                if not self._is_secret_manager_connector(connector_data):
                    continue
                
                identifier = connector_data.get('identifier', '')
                
                # Skip default connectors
                if self._is_default_connector(identifier, org_id, project_id):
                    results['skipped'] += 1
                    continue
                
                name = connector_data.get('name', identifier)
                print(f"\nProcessing secret manager connector: {name} ({identifier}) at {scope_label}")
                
                yaml_content = self.source_client.get_connector_yaml(
                    identifier, org_id, project_id
                )
                
                if not yaml_content:
                    print(f"  Failed to get YAML for connector {name}")
                    results['failed'] += 1
                    continue
                
                # Save exported YAML with scope in filename
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                export_file = self.export_dir / f"connector_secret_manager_{identifier}{scope_suffix}.yaml"
                export_file.write_text(yaml_content)
                print(f"  Exported YAML to {export_file}")
                
                # Create connector in destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create secret manager connector to destination account")
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
    
    def migrate_connectors(self) -> Dict[str, Any]:
        """Migrate connectors at all scopes (account, org, project), excluding custom secret manager connectors and secret manager connectors"""
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
                
                # Skip custom secret manager connectors and secret manager connectors (they are migrated separately)
                if self._is_custom_secret_manager_connector(connector_data):
                    results['skipped'] += 1
                    continue
                if self._is_secret_manager_connector(connector_data):
                    results['skipped'] += 1
                    continue
                
                identifier = connector_data.get('identifier', '')
                
                # Skip default connectors
                if self._is_default_connector(identifier, org_id, project_id):
                    results['skipped'] += 1
                    continue
                
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
    
    def _is_harness_secret_manager_secret(self, secret_data: Dict) -> bool:
        """Check if a secret is stored in harnessSecretManager"""
        spec = secret_data.get('spec', {})
        secret_manager = spec.get('secretManagerIdentifier', '')
        return (
            secret_manager == 'harnessSecretManager' or
            secret_manager == 'account.harnessSecretManager' or
            secret_manager == 'org.harnessSecretManager'
        )
    
    def migrate_harness_secret_manager_secrets(self) -> Dict[str, Any]:
        """Migrate secrets stored in harnessSecretManager at all scopes (account, org, project)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Secrets (harnessSecretManager) ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing harnessSecretManager secrets at {scope_label} ---")
            
            secrets = self.source_client.list_secrets(org_id, project_id)
            
            for secret in secrets:
                # Extract secret data from nested structure if present
                secret_item = secret.get('secret', secret) if isinstance(secret, dict) else secret
                identifier = secret_item.get('identifier', '') if isinstance(secret_item, dict) else ''
                name = secret_item.get('name', identifier) if isinstance(secret_item, dict) else identifier
                
                # Get full secret data to check secret manager
                secret_data = self.source_client.get_secret_data(identifier, org_id, project_id)
                
                if not secret_data:
                    continue
                
                # Only process secrets stored in harnessSecretManager
                if not self._is_harness_secret_manager_secret(secret_data):
                    continue
                
                print(f"\nProcessing harnessSecretManager secret: {name} ({identifier}) at {scope_label}")
                
                # Export secret data to file for backup (without sensitive values)
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                export_file = self.export_dir / f"secret_harness_{identifier}{scope_suffix}.json"
                
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
                    spec = secret_data.get('spec', {})
                    secret_manager = spec.get('secretManagerIdentifier', 'Unknown')
                    print(f"  [DRY RUN] Would create secret with value 'changeme' (harnessSecretManager: {secret_manager})")
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
    
    def migrate_secrets(self) -> Dict[str, Any]:
        """Migrate secrets at all scopes (account, org, project), excluding harnessSecretManager secrets"""
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
                
                # Get full secret data to check secret manager
                secret_data = self.source_client.get_secret_data(identifier, org_id, project_id)
                
                if not secret_data:
                    print(f"  Failed to get data for secret {name}")
                    results['failed'] += 1
                    continue
                
                # Skip secrets stored in harnessSecretManager (they are migrated separately)
                if self._is_harness_secret_manager_secret(secret_data):
                    results['skipped'] += 1
                    continue
                
                print(f"\nProcessing secret: {name} ({identifier}) at {scope_label}")
                
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
                                yaml_content=yaml_content, infrastructure_identifier=identifier, environment_identifier=env_identifier,
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
    
    def migrate_overrides(self) -> Dict[str, Any]:
        """Migrate overrides at all scopes (account, org, project)
        
        Overrides are always inline (not stored in GitX).
        Uses /ng/api/serviceOverrides/v2/list for listing and /ng/api/serviceOverrides/upsert for creation.
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Overrides ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing overrides at {scope_label} ---")
            
            overrides = self.source_client.list_overrides(org_id, project_id)
            
            for override in overrides:
                # Overrides in list response are directly in the items (not nested under "override" key)
                identifier = override.get('identifier', '')
                override_type = override.get('type', 'Unknown')
                environment_ref = override.get('environmentRef', '')
                
                # Build a display name from available fields
                name = f"{override_type}"
                if environment_ref:
                    name += f" for {environment_ref}"
                if identifier:
                    name += f" ({identifier})"
                
                print(f"\nProcessing override: {name} at {scope_label}")
                
                # Get full override data to detect storage type
                # First try without repoName (works for inline overrides)
                # For GitX overrides, the GET might still return entityGitInfo even without repoName
                override_data = self.source_client.get_override_data(
                    identifier, org_id, project_id
                )
                
                # If GET succeeded and we got entityGitInfo, it's GitX - re-fetch with repoName for complete data
                if override_data and override_data.get('entityGitInfo'):
                    entity_git_info = override_data.get('entityGitInfo', {})
                    repo_name = entity_git_info.get('repoName')
                    if repo_name:
                        # Re-fetch with repoName to get complete GitX data
                        override_data = self.source_client.get_override_data(
                            identifier, org_id, project_id,
                            repo_name=repo_name,
                            load_from_fallback_branch=True
                        )
                
                # If GET failed, try using data from list (might be incomplete for GitX)
                if not override_data:
                    override_data = override
                
                if not override_data:
                    print(f"  Failed to get data for override {identifier}")
                    results['failed'] += 1
                    continue
                
                # Detect if override is GitX or Inline
                is_gitx = self.source_client.is_gitx_resource(override_data)
                storage_type = "GitX" if is_gitx else "Inline"
                print(f"  Override storage type: {storage_type}")
                
                # Save exported data
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                yaml_content = None
                git_details = None
                
                if is_gitx:
                    # GitX: Get git details from entityGitInfo
                    entity_git_info = override_data.get('entityGitInfo', {})
                    if not entity_git_info:
                        print(f"  Failed to get entityGitInfo for GitX override {identifier}")
                        results['failed'] += 1
                        continue
                    
                    # Extract git details from entityGitInfo
                    git_details = {
                        'repoName': entity_git_info.get('repoName'),
                        'branch': entity_git_info.get('branch'),
                        'filePath': entity_git_info.get('filePath')
                    }
                    
                    # Get connector reference
                    connector_ref = override_data.get('connectorRef')
                    if connector_ref:
                        git_details['connectorRef'] = connector_ref
                    
                    # Also get YAML for export
                    yaml_content = override_data.get('yaml', '')
                    export_file = self.export_dir / f"override_{identifier}{scope_suffix}.yaml"
                    if yaml_content:
                        export_file.write_text(yaml_content)
                        print(f"  Exported YAML to {export_file}")
                else:
                    # Inline: Get YAML content
                    yaml_content = override_data.get('yaml', '')
                    if not yaml_content:
                        print(f"  Failed to get YAML for inline override {identifier}")
                        results['failed'] += 1
                        continue
                    export_file = self.export_dir / f"override_{identifier}{scope_suffix}.yaml"
                    export_file.write_text(yaml_content)
                    print(f"  Exported YAML to {export_file}")
                
                # Import to destination (skip in dry-run mode)
                if self.dry_run:
                    if is_gitx:
                        print(f"  [DRY RUN] Would import override (GitX) from git location")
                    else:
                        print(f"  [DRY RUN] Would create override (Inline) with YAML content")
                    results['success'] += 1
                else:
                    if is_gitx:
                        # GitX: Use import endpoint with git details and override data
                        if self.dest_client.import_override_yaml(
                            override_data=override_data,
                            git_details=git_details,
                            org_identifier=org_id, project_identifier=project_id
                        ):
                            results['success'] += 1
                        else:
                            results['failed'] += 1
                    else:
                        # Inline: Use create endpoint with override data
                        if self.dest_client.create_override(
                            override_data=override_data,
                            org_identifier=org_id,
                            project_identifier=project_id
                        ):
                            results['success'] += 1
                        else:
                            results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_user_journeys(self) -> Dict[str, Any]:
        """Migrate user journeys at project level (required before SLOs)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} User Journeys ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        # User journeys are project-level only
        scopes = self._get_project_scopes()
        for org_id, project_id in scopes:
            scope_label = f"project {project_id} (org {org_id})"
            print(f"\n--- Processing user journeys at {scope_label} ---")
            
            user_journeys = self.source_client.list_user_journeys(org_id, project_id)
            
            if not user_journeys:
                print(f"  No user journeys found at {scope_label}")
                continue
            
            print(f"  Found {len(user_journeys)} user journey(s) at {scope_label}")
            
            for user_journey in user_journeys:
                # Extract user journey data (may be nested or direct)
                uj_data = user_journey.get('userJourney', user_journey) if isinstance(user_journey, dict) and 'userJourney' in user_journey else user_journey
                identifier = uj_data.get('identifier', '')
                name = uj_data.get('name', identifier)
                
                if not identifier:
                    print(f"  Skipping user journey without identifier")
                    results['skipped'] += 1
                    continue
                
                print(f"\nProcessing user journey: {name} ({identifier}) at {scope_label}")
                
                # User journeys are always inline
                print(f"  User journey storage type: Inline")
                
                # Save exported data (as JSON)
                scope_suffix = f"_org_{org_id}_project_{project_id}"
                export_file = self.export_dir / f"user_journey_{identifier}{scope_suffix}.json"
                try:
                    export_file.write_text(json.dumps(uj_data, indent=2))
                    print(f"  Exported JSON to {export_file}")
                except Exception as e:
                    print(f"  Failed to export user journey data: {e}")
                
                # Migrate to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create user journey (Inline) with JSON data")
                    results['success'] += 1
                else:
                    if self.dest_client.create_user_journey(
                        identifier=identifier,
                        name=name,
                        org_identifier=org_id,
                        project_identifier=project_id
                    ):
                        print(f"  Successfully created user journey")
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_monitored_services(self) -> Dict[str, Any]:
        """Migrate monitored services at project level (requires services and environments)"""
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Monitored Services ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        # Monitored services are project-level only
        scopes = self._get_project_scopes()
        for org_id, project_id in scopes:
            scope_label = f"project {project_id} (org {org_id})"
            print(f"\n--- Processing monitored services at {scope_label} ---")
            
            monitored_services = self.source_client.list_monitored_services(org_id, project_id)
            
            if not monitored_services:
                print(f"  No monitored services found at {scope_label}")
                continue
            
            print(f"  Found {len(monitored_services)} monitored service(s) at {scope_label}")
            
            for monitored_service in monitored_services:
                # Extract monitored service data (may be nested or direct)
                ms_data = monitored_service.get('monitoredService', monitored_service) if isinstance(monitored_service, dict) and 'monitoredService' in monitored_service else monitored_service
                identifier = ms_data.get('identifier', '')
                name = ms_data.get('name', identifier)
                
                if not identifier:
                    print(f"  Skipping monitored service without identifier")
                    results['skipped'] += 1
                    continue
                
                print(f"\nProcessing monitored service: {name} ({identifier}) at {scope_label}")
                
                # Get full monitored service data (includes health sources)
                full_ms_data = self.source_client.get_monitored_service_data(identifier, org_id, project_id)
                if not full_ms_data:
                    print(f"  Failed to get data for monitored service {identifier}")
                    results['failed'] += 1
                    continue
                
                # Monitored services are always inline
                print(f"  Monitored service storage type: Inline")
                
                # Save exported data (as JSON)
                scope_suffix = f"_org_{org_id}_project_{project_id}"
                export_file = self.export_dir / f"monitored_service_{identifier}{scope_suffix}.json"
                try:
                    export_file.write_text(json.dumps(full_ms_data, indent=2))
                    print(f"  Exported JSON to {export_file}")
                except Exception as e:
                    print(f"  Failed to export monitored service data: {e}")
                
                # Check for health sources
                sources = full_ms_data.get('sources', {})
                health_sources = sources.get('healthSources', []) if sources else []
                if health_sources:
                    print(f"  Found {len(health_sources)} health source(s) in monitored service")
                
                # Migrate to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create monitored service (Inline) with JSON data")
                    if health_sources:
                        print(f"  [DRY RUN] Would add {len(health_sources)} health source(s) to monitored service")
                    results['success'] += 1
                else:
                    # Step 1: Create monitored service (without health sources initially, or with them if included)
                    # The create API may accept health sources in the initial request
                    if self.dest_client.create_monitored_service(
                        monitored_service_data=full_ms_data,
                        org_identifier=org_id,
                        project_identifier=project_id
                    ):
                        print(f"  Successfully created monitored service")
                        # Step 2: If health sources exist and weren't included in create, update to add them
                        # Actually, based on HAR file, health sources are added via PUT update
                        # But let's try creating with them first, and if that doesn't work, we'll update
                        # For now, we'll create without health sources, then update with them
                        if health_sources:
                            # Re-create the monitored service data with health sources for update
                            # The update should include all health sources
                            if self.dest_client.update_monitored_service(
                                identifier=identifier,
                                monitored_service_data=full_ms_data,
                                org_identifier=org_id,
                                project_identifier=project_id
                            ):
                                print(f"  Successfully added {len(health_sources)} health source(s) to monitored service")
                            else:
                                print(f"  Warning: Monitored service created but failed to add health sources")
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_webhooks(self) -> Dict[str, Any]:
        """Migrate webhooks at all scopes (account, org, project)
        
        Webhooks are always inline (not stored in GitX).
        Uses /v1/webhooks for listing and creation.
        Webhooks use JSON structure with webhook_identifier, webhook_name, and spec (not YAML).
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Webhooks ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        # Webhooks are account-level only (no org/project scope based on examples)
        # But we'll still iterate through scopes in case they support it
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing webhooks at {scope_label} ---")
            
            webhooks = self.source_client.list_webhooks(org_id, project_id)
            
            for webhook in webhooks:
                # Webhook data is directly in the list response (not nested)
                # Use webhook_identifier and webhook_name (not identifier and name)
                identifier = webhook.get('webhook_identifier', '')
                name = webhook.get('webhook_name', identifier)
                
                print(f"\nProcessing webhook: {name} ({identifier}) at {scope_label}")
                
                # Get full webhook data
                webhook_data = self.source_client.get_webhook_data(
                    identifier, org_id, project_id
                )
                
                # If GET failed, try using data from list
                if not webhook_data:
                    webhook_data = webhook
                
                if not webhook_data:
                    print(f"  Failed to get data for webhook {identifier}")
                    results['failed'] += 1
                    continue
                
                # Webhooks are always inline
                print(f"  Webhook storage type: Inline")
                
                # Save exported data (as JSON, not YAML)
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                # Export webhook data as JSON
                export_file = self.export_dir / f"webhook_{identifier}{scope_suffix}.json"
                try:
                    export_file.write_text(json.dumps(webhook_data, indent=2))
                    print(f"  Exported JSON to {export_file}")
                except Exception as e:
                    print(f"  Failed to export webhook data: {e}")
                
                # Migrate to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create webhook (Inline) with JSON data")
                    results['success'] += 1
                else:
                    # Use create endpoint with webhook data
                    if self.dest_client.create_webhook(
                        webhook_data=webhook_data,
                        org_identifier=org_id,
                        project_identifier=project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_policies(self) -> Dict[str, Any]:
        """Migrate policies at all scopes (account, org, project)
        
        Policies use /pm/api/v1/policies endpoints.
        Policies stored in GitX are created as inline on the target account (GitX import not supported).
        Policies use 'rego' field instead of 'yaml'.
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Policies ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing policies at {scope_label} ---")
            
            policies = self.source_client.list_policies(org_id, project_id)
            
            # Count built-in policies to summarize at end
            builtin_count = 0
            
            for policy in policies:
                # Policy data is directly in the list response (not nested)
                identifier = policy.get('identifier', '')
                name = policy.get('name', identifier)
                
                # Skip built-in example policies (count but don't print each one)
                if self._is_builtin_example_policy(identifier):
                    builtin_count += 1
                    results['skipped'] += 1
                    continue
                
                print(f"\nProcessing policy: {name} ({identifier}) at {scope_label}")
                
                # Get full policy data (with rego content)
                policy_data = self.source_client.get_policy_data(
                    identifier, org_id, project_id
                )
                
                # If GET failed, try using data from list (but it won't have rego)
                if not policy_data:
                    policy_data = policy
                
                if not policy_data:
                    print(f"  Failed to get data for policy {identifier}")
                    results['failed'] += 1
                    continue
                
                # Policies stored in GitX are created as inline on target (GitX import not supported)
                # Check if it was GitX in source for informational purposes
                is_gitx_source = self.source_client.is_gitx_resource(policy_data)
                if is_gitx_source:
                    print(f"  Policy was stored in GitX in source - will create as inline on target")
                else:
                    print(f"  Policy storage type: Inline")
                
                # Save exported data
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                # Get rego content (not yaml)
                rego_content = policy_data.get('rego', '')
                if not rego_content:
                    print(f"  Warning: Policy {identifier} has no rego content")
                    # Still try to migrate it, might be empty policy
                
                # Export policy rego content
                export_file = self.export_dir / f"policy_{identifier}{scope_suffix}.rego"
                try:
                    export_file.write_text(rego_content)
                    print(f"  Exported rego to {export_file}")
                except Exception as e:
                    print(f"  Failed to export policy rego: {e}")
                
                # Migrate to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create policy (Inline) with rego content")
                    results['success'] += 1
                else:
                    # Always use create endpoint (GitX import not supported)
                    # Create as inline even if it was GitX in source
                    if self.dest_client.create_policy(
                        policy_data=policy_data,
                        org_identifier=org_id,
                        project_identifier=project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
            
            # Print summary of skipped built-in policies for this scope
            if builtin_count > 0:
                print(f"  Skipped {builtin_count} built-in example policy(ies) at {scope_label}")
        
        return results
    
    def migrate_policy_sets(self) -> Dict[str, Any]:
        """Migrate policy sets at all scopes (account, org, project)
        
        Policy sets use /pm/api/v1/policysets endpoints.
        Policy sets reference policies, so policies must be migrated first.
        Policy sets are always inline (not stored in GitX).
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Policy Sets ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing policy sets at {scope_label} ---")
            
            policy_sets = self.source_client.list_policy_sets(org_id, project_id)
            
            for policy_set in policy_sets:
                # Policy set data is directly in the list response (not nested)
                identifier = policy_set.get('identifier', '')
                name = policy_set.get('name', identifier)
                
                print(f"\nProcessing policy set: {name} ({identifier}) at {scope_label}")
                
                # Get full policy set data
                policy_set_data = self.source_client.get_policy_set_data(
                    identifier, org_id, project_id
                )
                
                # If GET failed, try using data from list
                if not policy_set_data:
                    policy_set_data = policy_set
                
                if not policy_set_data:
                    print(f"  Failed to get data for policy set {identifier}")
                    results['failed'] += 1
                    continue
                
                # Policy sets are always inline
                print(f"  Policy set storage type: Inline")
                
                # Save exported data (as JSON, not YAML)
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                # Export policy set data as JSON
                export_file = self.export_dir / f"policy_set_{identifier}{scope_suffix}.json"
                try:
                    export_file.write_text(json.dumps(policy_set_data, indent=2))
                    print(f"  Exported JSON to {export_file}")
                except Exception as e:
                    print(f"  Failed to export policy set data: {e}")
                
                # Migrate to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create policy set (Inline) with JSON data")
                    results['success'] += 1
                else:
                    # Use create endpoint with policy set data
                    if self.dest_client.create_policy_set(
                        policy_set_data=policy_set_data,
                        org_identifier=org_id,
                        project_identifier=project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_roles(self) -> Dict[str, Any]:
        """Migrate roles at all scopes (account, org, project)
        
        Roles use /authz/api/roles endpoints.
        Roles are always inline (not stored in GitX).
        Roles should be migrated after organizations and projects are created.
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Roles ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing roles at {scope_label} ---")
            
            roles = self.source_client.list_roles(org_id, project_id)
            
            # Count built-in roles silently
            builtin_count = 0
            
            for role in roles:
                # Role data is already extracted from 'role' key in list_roles
                # But handle both cases (nested or direct) - list_roles already extracts it
                # So role should already be the role data object
                role_data = role.get('role', role) if isinstance(role, dict) and 'role' in role else role
                identifier = role_data.get('identifier', '')
                name = role_data.get('name', identifier)
                
                # Skip built-in roles (IDs starting with "_")
                if self._is_builtin_role(identifier):
                    builtin_count += 1
                    results['skipped'] += 1
                    continue
                
                print(f"\nProcessing role: {name} ({identifier}) at {scope_label}")
                
                # Get full role data
                full_role_data = self.source_client.get_role_data(
                    identifier, org_id, project_id
                )
                
                # If GET failed, use data from list (already extracted)
                if not full_role_data:
                    full_role_data = role_data
                
                if not full_role_data:
                    print(f"  Failed to get data for role {identifier}")
                    results['failed'] += 1
                    continue
                
                # Roles are always inline
                print(f"  Role storage type: Inline")
                
                # Save exported data (as JSON, not YAML)
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                # Export role data as JSON
                export_file = self.export_dir / f"role_{identifier}{scope_suffix}.json"
                try:
                    export_file.write_text(json.dumps(full_role_data, indent=2))
                    print(f"  Exported JSON to {export_file}")
                except Exception as e:
                    print(f"  Failed to export role data: {e}")
                
                # Migrate to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create role (Inline) with JSON data")
                    results['success'] += 1
                else:
                    # Use create endpoint with role data
                    if self.dest_client.create_role(
                        role_data=full_role_data,
                        org_identifier=org_id,
                        project_identifier=project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
            
            # Print summary of skipped built-in roles for this scope
            if builtin_count > 0:
                print(f"  Skipped {builtin_count} built-in role(s) at {scope_label}")
        
        return results
    
    def migrate_resource_groups(self) -> Dict[str, Any]:
        """Migrate resource groups at all scopes (account, org, project)
        
        Resource groups use /resourcegroup/api/v2/resourcegroup endpoints.
        Resource groups are always inline (not stored in GitX).
        Resource groups should be migrated after organizations and projects are created.
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Resource Groups ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing resource groups at {scope_label} ---")
            
            resource_groups = self.source_client.list_resource_groups(org_id, project_id)
            
            for resource_group in resource_groups:
                # Resource group data is already extracted from 'resourceGroup' key in list_resource_groups
                # But handle both cases (nested or direct)
                resource_group_data = resource_group.get('resourceGroup', resource_group) if isinstance(resource_group, dict) and 'resourceGroup' in resource_group else resource_group
                identifier = resource_group_data.get('identifier', '')
                name = resource_group_data.get('name', identifier)
                
                # Skip built-in resource groups (IDs starting with "_")
                if self._is_builtin_resource_group(identifier):
                    print(f"\nSkipping built-in resource group: {name} ({identifier})")
                    results['skipped'] += 1
                    continue
                
                print(f"\nProcessing resource group: {name} ({identifier}) at {scope_label}")
                
                # Get full resource group data
                full_resource_group_data = self.source_client.get_resource_group_data(
                    identifier, org_id, project_id
                )
                
                # If GET failed, use data from list (already extracted)
                if not full_resource_group_data:
                    full_resource_group_data = resource_group_data
                
                if not full_resource_group_data:
                    print(f"  Failed to get data for resource group {identifier}")
                    results['failed'] += 1
                    continue
                
                # Resource groups are always inline
                print(f"  Resource group storage type: Inline")
                
                # Save exported data (as JSON, not YAML)
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                # Export resource group data as JSON
                export_file = self.export_dir / f"resource_group_{identifier}{scope_suffix}.json"
                try:
                    export_file.write_text(json.dumps(full_resource_group_data, indent=2))
                    print(f"  Exported JSON to {export_file}")
                except Exception as e:
                    print(f"  Failed to export resource group data: {e}")
                
                # Migrate to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create resource group (Inline) with JSON data")
                    results['success'] += 1
                else:
                    # Use create endpoint with resource group data
                    if self.dest_client.create_resource_group(
                        resource_group_data=full_resource_group_data,
                        org_identifier=org_id,
                        project_identifier=project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_settings(self) -> Dict[str, Any]:
        """Migrate settings at all scopes (account, org, project)
        
        Settings use /ng/api/settings endpoints.
        Settings are always inline (not stored in GitX).
        Only settings that have been overridden (settingSource != "DEFAULT") should be migrated.
        Settings are organized by category and must be fetched per category.
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Settings ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        # Available settings categories (from Harness API)
        # Not all categories may be available depending on which Harness modules are enabled
        settings_categories = [
            'CORE',
            'CONNECTORS',
            'CD',
            'CI',
            'GIT_EXPERIENCE',
            'PMS',
            'NOTIFICATIONS',
            'DBOPS',
            'EULA',
            'MODULES_VISIBILITY'
        ]
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing settings at {scope_label} ---")
            
            # Process each category
            for category in settings_categories:
                try:
                    # Get settings for this category
                    settings = self.source_client.list_settings(category, org_id, project_id)
                    
                    # If no settings returned, category might not be available - skip gracefully
                    if not settings:
                        continue
                    
                    # Filter to only settings that have been overridden (not DEFAULT)
                    overridden_settings = []
                    for setting in settings:
                        setting_source = setting.get('settingSource', '')
                        # Only migrate settings that are not DEFAULT (i.e., have been overridden)
                        if setting_source and setting_source != 'DEFAULT':
                            overridden_settings.append(setting)
                    
                    if not overridden_settings:
                        continue
                    
                    print(f"\n  Found {len(overridden_settings)} overridden settings in category: {category}")
                    
                    # Build settings updates array
                    settings_updates = []
                    for setting in overridden_settings:
                        identifier = setting.get('identifier', '')
                        value = setting.get('value')
                        allow_overrides = setting.get('allowOverrides', True)
                        
                        if not identifier:
                            continue
                        
                        settings_updates.append({
                            'identifier': identifier,
                            'value': value,
                            'allowOverrides': allow_overrides,
                            'updateType': 'UPDATE'
                        })
                    
                    if not settings_updates:
                        continue
                    
                    # Save exported data (as JSON, not YAML)
                    scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                    
                    # Export settings data as JSON
                    export_file = self.export_dir / f"settings_{category}{scope_suffix}.json"
                    try:
                        export_file.write_text(json.dumps(settings_updates, indent=2))
                        print(f"  Exported JSON to {export_file}")
                    except Exception as e:
                        print(f"  Failed to export settings data: {e}")
                    
                    # Migrate to destination (skip in dry-run mode)
                    if self.dry_run:
                        print(f"  [DRY RUN] Would update {len(settings_updates)} settings in category {category}")
                        results['success'] += len(settings_updates)
                    else:
                        # Use update endpoint with settings updates
                        if self.dest_client.update_settings(
                            settings_updates=settings_updates,
                            org_identifier=org_id,
                            project_identifier=project_id
                        ):
                            results['success'] += len(settings_updates)
                        else:
                            results['failed'] += len(settings_updates)
                    
                    time.sleep(0.5)  # Rate limiting
                    
                except Exception as e:
                    # Gracefully handle errors (e.g., category not available)
                    print(f"  Skipping category {category} due to error: {e}")
                    continue
        
        return results
    
    def migrate_ip_allowlists(self) -> Dict[str, Any]:
        """Migrate IP allowlists at account level
        
        IP allowlists use /v1/ip-allowlist endpoints.
        IP allowlists are always inline (not stored in GitX).
        IP allowlists are account-level only (no org/project scoping).
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} IP Allowlists ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        print(f"\n--- Processing IP allowlists at account level ---")
        
        ip_allowlists = self.source_client.list_ip_allowlists()
        
        if not ip_allowlists:
            print(f"  No IP allowlists found")
            return results
        
        print(f"  Found {len(ip_allowlists)} IP allowlists")
        
        for ip_allowlist in ip_allowlists:
            # IP allowlist data is already extracted from 'ip_allowlist_config' key in list_ip_allowlists
            # But handle both cases (nested or direct)
            allowlist_data = ip_allowlist.get('ip_allowlist_config', ip_allowlist) if isinstance(ip_allowlist, dict) and 'ip_allowlist_config' in ip_allowlist else ip_allowlist
            identifier = allowlist_data.get('identifier', '')
            name = allowlist_data.get('name', identifier)
            
            print(f"\nProcessing IP allowlist: {name} ({identifier})")
            
            if not allowlist_data:
                print(f"  Failed to get data for IP allowlist {identifier}")
                results['failed'] += 1
                continue
            
            # IP allowlists are always inline
            print(f"  IP allowlist storage type: Inline")
            
            # Save exported data (as JSON, not YAML)
            export_file = self.export_dir / f"ip_allowlist_{identifier}_account.json"
            try:
                export_file.write_text(json.dumps(allowlist_data, indent=2))
                print(f"  Exported JSON to {export_file}")
            except Exception as e:
                print(f"  Failed to export IP allowlist data: {e}")
            
            # Migrate to destination (skip in dry-run mode)
            if self.dry_run:
                print(f"  [DRY RUN] Would create IP allowlist (Inline) with JSON data")
                results['success'] += 1
            else:
                # Use create endpoint with IP allowlist data
                if self.dest_client.create_ip_allowlist(
                    ip_allowlist_data=allowlist_data
                ):
                    results['success'] += 1
                else:
                    results['failed'] += 1
            
            time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_users(self) -> Dict[str, Any]:
        """Migrate users at all scopes (account, org, project)
        
        Users use /ng/api/user endpoints.
        Users are always inline (not stored in GitX).
        Users should be migrated after roles and resource groups (users reference them via role bindings).
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Users ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing users at {scope_label} ---")
            
            users = self.source_client.list_users(org_id, project_id)
            
            if not users:
                print(f"  No users found at {scope_label}")
                continue
            
            print(f"  Found {len(users)} users at {scope_label}")
            
            for user in users:
                # User data is already extracted from 'user' key in list_users
                # But handle both cases (nested or direct)
                user_data = user.get('user', user) if isinstance(user, dict) and 'user' in user else user
                email = user_data.get('email', '')
                name = user_data.get('name', email)
                
                if not email:
                    print(f"  Skipping user without email")
                    results['skipped'] += 1
                    continue
                
                print(f"\nProcessing user: {name} ({email}) at {scope_label}")
                
                # Include role assignments in user data for migration
                if 'roleAssignmentMetadata' not in user_data:
                    user_data['roleAssignmentMetadata'] = user.get('roleAssignmentMetadata', [])
                
                # Users are always inline
                print(f"  User storage type: Inline")
                
                # Save exported data (as JSON, not YAML)
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                # Export user data as JSON (sanitize email for filename)
                export_file = self.export_dir / f"user_{email.replace('@', '_at_')}{scope_suffix}.json"
                try:
                    export_file.write_text(json.dumps(user_data, indent=2))
                    print(f"  Exported JSON to {export_file}")
                except Exception as e:
                    print(f"  Failed to export user data: {e}")
                
                # Migrate to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create user (Inline) with JSON data")
                    results['success'] += 1
                else:
                    # Use create endpoint with user data
                    if self.dest_client.create_user(
                        user_data=user_data,
                        org_identifier=org_id,
                        project_identifier=project_id
                    ):
                        results['success'] += 1
                    else:
                        results['failed'] += 1
                
                time.sleep(0.5)  # Rate limiting
        
        return results
    
    def migrate_service_accounts(self) -> Dict[str, Any]:
        """Migrate service accounts at all scopes (account, org, project)
        
        Service accounts use /ng/api/serviceaccount endpoints.
        Service accounts are always inline (not stored in GitX).
        Service accounts should be migrated after roles and resource groups (service accounts reference them via role bindings).
        """
        action = "Listing" if self.dry_run else "Migrating"
        print(f"\n=== {action} Service Accounts ===")
        results = {'success': 0, 'failed': 0, 'skipped': 0}
        
        scopes = self._get_all_scopes()
        for org_id, project_id in scopes:
            scope_label = "account level" if not org_id else (f"org {org_id}" if not project_id else f"project {project_id} (org {org_id})")
            print(f"\n--- Processing service accounts at {scope_label} ---")
            
            service_accounts = self.source_client.list_service_accounts(org_id, project_id)
            
            if not service_accounts:
                print(f"  No service accounts found at {scope_label}")
                continue
            
            print(f"  Found {len(service_accounts)} service accounts at {scope_label}")
            
            for service_account in service_accounts:
                # The list_service_accounts method already extracts serviceAccount data and adds roleAssignmentMetadata
                # So service_account here is the combined object with both serviceAccount fields and roleAssignmentMetadata
                # We should use it directly, not extract serviceAccount again
                identifier = service_account.get('identifier', '')
                name = service_account.get('name', identifier)
                
                if not identifier:
                    print(f"  Skipping service account without identifier")
                    results['skipped'] += 1
                    continue
                
                print(f"\nProcessing service account: {name} ({identifier}) at {scope_label}")
                
                # Service account data is already complete from list response with roleAssignmentMetadata
                # The list_service_accounts method already normalizes roleAssignmentsMetadataDTO to roleAssignmentMetadata
                full_service_account_data = service_account.copy()
                
                # Ensure roleAssignmentMetadata is set (it should already be set by list_service_accounts)
                if 'roleAssignmentMetadata' not in full_service_account_data:
                    # Fallback: try the original field name
                    role_assignments = service_account.get('roleAssignmentsMetadataDTO', [])
                    full_service_account_data['roleAssignmentMetadata'] = role_assignments
                
                # Debug: Print role assignments found
                role_count = len(full_service_account_data.get('roleAssignmentMetadata', []))
                if role_count > 0:
                    print(f"  Found {role_count} role assignment(s) in service account data")
                else:
                    print(f"  Warning: No role assignments found in service account data")
                
                if not full_service_account_data:
                    print(f"  Failed to get data for service account {identifier}")
                    results['failed'] += 1
                    continue
                
                # Service accounts are always inline
                print(f"  Service account storage type: Inline")
                
                # Save exported data (as JSON, not YAML)
                scope_suffix = f"_account" if not org_id else (f"_org_{org_id}" if not project_id else f"_org_{org_id}_project_{project_id}")
                
                # Export service account data as JSON
                export_file = self.export_dir / f"service_account_{identifier}{scope_suffix}.json"
                try:
                    export_file.write_text(json.dumps(full_service_account_data, indent=2))
                    print(f"  Exported JSON to {export_file}")
                except Exception as e:
                    print(f"  Failed to export service account data: {e}")
                
                # Migrate to destination (skip in dry-run mode)
                if self.dry_run:
                    print(f"  [DRY RUN] Would create service account (Inline) with JSON data")
                    role_count = len(full_service_account_data.get('roleAssignmentMetadata', []))
                    if role_count > 0:
                        print(f"  [DRY RUN] Would add {role_count} role binding(s) to service account")
                    results['success'] += 1
                else:
                    # Step 1: Create service account (without role bindings)
                    if not self.dest_client.create_service_account(
                        service_account_data=full_service_account_data,
                        org_identifier=org_id,
                        project_identifier=project_id
                    ):
                        results['failed'] += 1
                        continue
                    
                    # Step 2: Add role bindings (if any)
                    role_assignment_metadata = full_service_account_data.get('roleAssignmentMetadata', [])
                    if role_assignment_metadata:
                        # Extract role bindings from roleAssignmentMetadata
                        role_bindings = []
                        for role_assignment in role_assignment_metadata:
                            role_binding = {
                                'resourceGroupIdentifier': role_assignment.get('resourceGroupIdentifier', ''),
                                'roleIdentifier': role_assignment.get('roleIdentifier', ''),
                                'roleName': role_assignment.get('roleName', ''),
                                'resourceGroupName': role_assignment.get('resourceGroupName', ''),
                                'managedRole': role_assignment.get('managedRole', False)
                            }
                            # Only add non-empty role bindings
                            if role_binding.get('roleIdentifier') and role_binding.get('resourceGroupIdentifier'):
                                role_bindings.append(role_binding)
                        
                        if role_bindings:
                            print(f"  Adding {len(role_bindings)} role binding(s) to service account")
                            if not self.dest_client.add_role_bindings_to_service_account(
                                service_account_identifier=identifier,
                                role_bindings=role_bindings,
                                org_identifier=org_id,
                                project_identifier=project_id
                            ):
                                print(f"  Warning: Failed to add role bindings, but service account was created")
                                # Don't fail the migration, just warn
                        
                        time.sleep(0.5)  # Rate limiting between role binding calls
                    
                    # Step 3: Migrate API keys (if any)
                    api_keys = self.source_client.list_api_keys_for_service_account(
                        service_account_identifier=identifier,
                        org_identifier=org_id,
                        project_identifier=project_id
                    )
                    
                    if api_keys:
                        print(f"  Found {len(api_keys)} API key(s) for service account")
                        for api_key in api_keys:
                            api_key_identifier = api_key.get('identifier', '')
                            api_key_name = api_key.get('name', api_key_identifier)
                            
                            print(f"    Processing API key: {api_key_name} ({api_key_identifier})")
                            
                            # Ensure parentIdentifier is set
                            api_key['parentIdentifier'] = identifier
                            
                            if self.dry_run:
                                print(f"    [DRY RUN] Would create API key for service account")
                            else:
                                if not self.dest_client.create_api_key_for_service_account(
                                    api_key_data=api_key,
                                    org_identifier=org_id,
                                    project_identifier=project_id
                                ):
                                    print(f"    Warning: Failed to create API key {api_key_identifier}")
                                time.sleep(0.5)  # Rate limiting between API key calls
                    else:
                        print(f"  No API keys found for service account")
                    
                    results['success'] += 1
                
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
                            git_details=git_details, pipeline_identifier=identifier, pipeline_description=pipeline_description,
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
                    # Trigger data is directly in the list response (not nested under 'trigger' key)
                    identifier = trigger.get('identifier', '')
                    name = trigger.get('name', identifier)
                    print(f"  Processing trigger: {name} ({identifier})")
                    
                    # Get full trigger data
                    trigger_data = self.source_client.get_trigger_data(
                        identifier, pipeline_identifier, org_id, project_id
                    )
                    
                    if not trigger_data:
                        print(f"    Failed to get data for trigger {name}")
                        results['failed'] += 1
                        continue
                    
                    # Extract YAML content from trigger data
                    trigger_yaml = trigger_data.get('yaml', '')
                    if not trigger_yaml:
                        print(f"    Failed to get YAML for trigger {name}")
                        results['failed'] += 1
                        continue
                    
                    # Triggers are always inline (not stored in GitX, even for GitX pipelines)
                    print(f"    Trigger storage type: Inline")
                    
                    # Export trigger YAML to file for backup (triggers are always at project level)
                    scope_suffix = f"_org_{org_id}_project_{project_id}"
                    export_file = self.export_dir / f"trigger_{pipeline_identifier}_{identifier}{scope_suffix}.yaml"
                    export_file.write_text(trigger_yaml)
                    print(f"    Exported to {export_file}")
                    
                    # Create in destination (skip in dry-run mode)
                    if self.dry_run:
                        print(f"    [DRY RUN] Would create trigger in destination account")
                        results['success'] += 1
                    else:
                        if self.dest_client.create_trigger(
                            trigger_yaml=trigger_yaml, pipeline_identifier=pipeline_identifier,
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
            resource_types = ['organizations', 'projects', 'connectors', 'secrets', 'environments', 'infrastructures', 'services', 'overrides', 'templates', 'pipelines', 'input-sets', 'triggers']
        
        all_results = {}
        
        # Migrate in dependency order - organizations and projects first
        if 'organizations' in resource_types:
            all_results['organizations'] = self.migrate_organizations()
        
        if 'projects' in resource_types:
            all_results['projects'] = self.migrate_projects()
        
        # SecretManager templates must be migrated early (right after projects/orgs)
        if 'templates' in resource_types:
            all_results['secret_manager_templates'] = self.migrate_secret_manager_templates()
        
        # Custom secret manager connectors must be migrated right after secret manager templates
        if 'connectors' in resource_types:
            all_results['custom_secret_manager_connectors'] = self.migrate_custom_secret_manager_connectors()
        
        # Secrets stored in harnessSecretManager must be migrated before connectors
        if 'secrets' in resource_types:
            all_results['harness_secret_manager_secrets'] = self.migrate_harness_secret_manager_secrets()
        
        # Secret manager connectors must be migrated after harnessSecretManager secrets, before remaining secrets
        if 'connectors' in resource_types:
            all_results['secret_manager_connectors'] = self.migrate_secret_manager_connectors()
        
        # Then migrate other secrets (excluding harnessSecretManager secrets) - before regular connectors
        if 'secrets' in resource_types:
            all_results['secrets'] = self.migrate_secrets()
        
        # Then migrate other connectors (excluding custom secret manager connectors and secret manager connectors)
        if 'connectors' in resource_types:
            all_results['connectors'] = self.migrate_connectors()
        
        # Deployment Template and Artifact Source templates must be migrated before services and environments
        if 'templates' in resource_types:
            all_results['deployment_artifact_templates'] = self.migrate_deployment_and_artifact_source_templates()
        
        if 'environments' in resource_types:
            all_results['environments'] = self.migrate_environments()
        
        if 'infrastructures' in resource_types:
            all_results['infrastructures'] = self.migrate_infrastructures()
        
        if 'services' in resource_types:
            all_results['services'] = self.migrate_services()
        
        # Overrides must be migrated after environments, infrastructures, and services
        if 'overrides' in resource_types:
            all_results['overrides'] = self.migrate_overrides()
        
        # Monitored services must be migrated after services and environments
        if 'monitored-services' in resource_types:
            all_results['monitored_services'] = self.migrate_monitored_services()
        
        # User journeys
        if 'user-journeys' in resource_types:
            all_results['user_journeys'] = self.migrate_user_journeys()
        
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
        
        # Webhooks are migrated after triggers (webhooks might be used by triggers)
        if 'webhooks' in resource_types:
            all_results['webhooks'] = self.migrate_webhooks()
        
        # Policies are migrated before policy sets (policy sets reference policies)
        if 'policies' in resource_types:
            all_results['policies'] = self.migrate_policies()
        
        # Policy sets are migrated after policies (they reference policies)
        if 'policy-sets' in resource_types:
            all_results['policy_sets'] = self.migrate_policy_sets()
        
        # Roles are migrated after organizations and projects (they can reference them)
        if 'roles' in resource_types:
            all_results['roles'] = self.migrate_roles()
        
        # Resource groups are migrated after organizations and projects (they can reference them)
        if 'resource-groups' in resource_types:
            all_results['resource_groups'] = self.migrate_resource_groups()
        
        # Settings are migrated after organizations and projects (they can reference them)
        if 'settings' in resource_types:
            all_results['settings'] = self.migrate_settings()
        
        # IP allowlists are account-level only, migrated after organizations and projects
        if 'ip-allowlists' in resource_types:
            all_results['ip_allowlists'] = self.migrate_ip_allowlists()
        
        # Users are migrated after roles and resource groups (users reference them via role bindings)
        if 'users' in resource_types:
            all_results['users'] = self.migrate_users()
        
        # Service accounts are migrated after roles and resource groups (service accounts reference them via role bindings)
        if 'service-accounts' in resource_types:
            all_results['service_accounts'] = self.migrate_service_accounts()
        
        return all_results


def main():
    parser = argparse.ArgumentParser(description='Migrate Harness account resources')
    parser.add_argument('--source-api-key', required=True, help='Source account API key (account ID will be extracted from key)')
    parser.add_argument('--dest-api-key', help='Destination account API key (not required for dry-run, account ID will be extracted from key)')
    parser.add_argument('--org-identifier', help='Organization identifier (optional)')
    parser.add_argument('--project-identifier', help='Project identifier (optional)')
    parser.add_argument('--resource-types', nargs='+', 
                       choices=['organizations', 'projects', 'connectors', 'secrets', 'environments', 'infrastructures', 'services', 'overrides', 'monitored-services', 'user-journeys', 'pipelines', 'templates', 'input-sets', 'triggers', 'webhooks', 'policies', 'policy-sets', 'roles', 'resource-groups', 'settings', 'ip-allowlists', 'users', 'service-accounts'],
                       default=['organizations', 'projects', 'connectors', 'secrets', 'environments', 'infrastructures', 'services', 'overrides', 'monitored-services', 'user-journeys', 'pipelines', 'templates', 'input-sets', 'triggers', 'webhooks', 'policies', 'policy-sets', 'roles', 'resource-groups', 'settings', 'ip-allowlists', 'users', 'service-accounts'],
                       help='Resource types to migrate')
    parser.add_argument('--exclude-resource-types', nargs='+',
                       choices=['organizations', 'projects', 'connectors', 'secrets', 'environments', 'infrastructures', 'services', 'overrides', 'monitored-services', 'user-journeys', 'pipelines', 'templates', 'input-sets', 'triggers', 'webhooks', 'policies', 'policy-sets', 'roles', 'resource-groups', 'settings', 'ip-allowlists', 'users', 'service-accounts'],
                       default=[],
                       help='Resource types to exclude from migration (takes precedence over --resource-types)')
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
    
    # Apply exclusions: remove excluded resource types from the list
    # Exclusions take precedence over inclusions
    excluded_types = set(args.exclude_resource_types) if args.exclude_resource_types else set()
    final_resource_types = [rt for rt in args.resource_types if rt not in excluded_types]
    
    # Warn if any excluded types were in the include list
    excluded_but_included = excluded_types.intersection(set(args.resource_types))
    if excluded_but_included:
        print(f"Warning: The following resource types were excluded even though they were in --resource-types: {', '.join(sorted(excluded_but_included))}")
    
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
    print(f"Resource Types: {', '.join(final_resource_types)}")
    if excluded_types:
        print(f"Excluded Resource Types: {', '.join(sorted(excluded_types))}")
    if args.dry_run:
        print("\n[DRY RUN MODE] Resources will be listed and exported but NOT migrated")
    
    results = migrator.migrate_all(final_resource_types)
    
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
