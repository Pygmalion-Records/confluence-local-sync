#!/usr/bin/env python3
"""
Confluence Content Sync Tool

This module provides functionality to synchronize content between local filesystem
and Confluence Cloud. It implements a performance-first architecture with proper
error handling and logging.

Performance Characteristics:
- Uses connection pooling for HTTP requests
- Implements caching to minimize API calls
- Batch processing for content updates

Error Handling:
- Graceful degradation on API failures
- Detailed error logging
- Automatic retry mechanism
"""

import os
import json
import time
import logging
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional, Union, Tuple
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from dotenv import load_dotenv
import click
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import timedelta

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class ConfluenceAPIError(Exception):
    """Custom exception for Confluence API errors"""
    def __init__(self, message: str, status_code: Optional[int] = None, response: Optional[str] = None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)

class ConfluenceAPI:
    """
    Confluence API client with proper error handling and performance optimizations.
    
    Performance Characteristics:
    - Connection pooling
    - Automatic retries with exponential backoff
    - Request session reuse
    """
    
    def __init__(self):
        load_dotenv()
        self.base_url = os.getenv('CONFLUENCE_URL')
        self.username = os.getenv('CONFLUENCE_USERNAME')
        self.api_token = os.getenv('CONFLUENCE_API_TOKEN')
        self.space_key = os.getenv('CONFLUENCE_SPACE_KEY')
        self.api_version = os.getenv('CONFLUENCE_API_VERSION', '2')
        
        if not all([self.base_url, self.username, self.api_token, self.space_key]):
            raise ValueError("Missing required environment variables")
        
        self.session = self._create_session()
        self.local = LocalContentManager()  # Initialize LocalContentManager

    def _create_session(self) -> requests.Session:
        """Create an optimized session with retries and connection pooling"""
        session = requests.Session()
        
        # Configure retries
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        # Configure connection pooling
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,
            pool_maxsize=10
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Configure authentication and headers
        session.auth = (self.username, self.api_token)
        session.headers.update({
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
        
        return session

    def get_space_content(self) -> Dict:
        """Get all content from the space"""
        print("DEBUG: Starting get_space_content")  # Temporary print
        
        try:
            # First get the space ID from the key
            url = f"{self.base_url}/wiki/api/v{self.api_version}/spaces"
            params = {'keys': self.space_key}
            
            print(f"DEBUG: Getting space ID for key {self.space_key}")  # Temporary print
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            results = data.get('results', [])
            if not results:
                raise ConfluenceAPIError(f"Space {self.space_key} not found")
            
            space_id = results[0].get('id')
            print(f"DEBUG: Found space ID: {space_id}")  # Temporary print
            
            # Now get the pages using the space ID
            url = f"{self.base_url}/wiki/api/v{self.api_version}/pages"
            params = {
                'space-id': space_id,
                'status': 'current',
                'limit': 100,
                'sort': 'created-date',
                'body-format': 'storage',
                'expand': 'body.storage,space'
            }
            
            print(f"DEBUG: Getting pages with params: {params}")  # Temporary print
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            print(f"DEBUG: Got {len(data.get('results', []))} pages")  # Temporary print
            
            return data
            
        except requests.exceptions.RequestException as e:
            print(f"DEBUG: API request failed: {str(e)}")  # Temporary print
            raise ConfluenceAPIError(f"Failed to get space content: {str(e)}")

    def get_space_id(self) -> str:
        """
        Get the space ID for the configured space key
        
        Returns:
            str: The space ID
        
        Raises:
            ConfluenceAPIError: If the space cannot be found
        """
        spaces_url = f"{self.base_url}/wiki/api/v{self.api_version}/spaces"
        try:
            spaces_response = self.session.get(spaces_url, timeout=(5, 30))
            spaces_response.raise_for_status()
            spaces_data = spaces_response.json()
            
            # Find our space
            space = next(
                (s for s in spaces_data.get('results', []) 
                 if s.get('key') == self.space_key),
                None
            )
            
            if not space:
                raise ConfluenceAPIError(
                    f"Space '{self.space_key}' not found",
                    status_code=404
                )
                
            space_id = space.get('id')
            if not space_id:
                raise ConfluenceAPIError(
                    f"Could not get ID for space '{self.space_key}'",
                    status_code=404
                )
                
            return space_id
            
        except requests.exceptions.RequestException as e:
            raise ConfluenceAPIError(
                f"Failed to get space ID: {str(e)}",
                status_code=getattr(e.response, 'status_code', None),
                response=getattr(e.response, 'text', None)
            )

    def get_page_by_id(self, page_id: str) -> Dict:
        """Get a page by its ID"""
        print(f"DEBUG: Getting page by ID: {page_id}")  # Debug print
        
        url = f"{self.base_url}/wiki/api/v{self.api_version}/pages/{page_id}"
        params = {
            'body-format': 'storage',
            'expand': 'body.storage,space,version'  # Add body.storage to expansion
        }
        
        print(f"DEBUG: Request URL: {url}")  # Debug print
        print(f"DEBUG: Request params: {params}")  # Debug print
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            print(f"DEBUG: Response data keys: {list(data.keys())}")  # Debug print
            if 'body' in data:
                print(f"DEBUG: Body keys: {list(data['body'].keys())}")  # Debug print
                if 'storage' in data['body']:
                    print(f"DEBUG: Storage value length: {len(data['body']['storage'].get('value', ''))}")  # Debug print
            
            return data
            
        except requests.exceptions.RequestException as e:
            print(f"DEBUG: API request failed: {str(e)}")  # Debug print
            raise ConfluenceAPIError(f"Failed to get page {page_id}: {str(e)}")

    def update_page(self, page_id: str, content: Dict) -> Dict:
        """
        Update an existing page with proper error handling, version conflict resolution,
        and ADF format support

        Args:
            page_id: The ID of the page to update
            content: The page content and metadata in ADF format

        Returns:
            Dict: The updated page data

        Raises:
            ConfluenceAPIError: If the update fails
        """
        url = f"{self.base_url}/wiki/api/v{self.api_version}/pages/{page_id}"

        # Get current page to get the version number
        try:
            current_page = self.get_page_by_id(page_id)
            current_version = current_page.get('version', {}).get('number', 1)
            logger.info(f"Current version of page {page_id} is {current_version}")
        except ConfluenceAPIError as e:
            logger.error(f"Failed to get current page version: {e.message}")
            raise

        # The content is already in ADF format, just need to structure it correctly
        update_data = {
            "id": page_id,
            "status": "current",
            "title": content.get('title', ''),
            "body": {
                "representation": "storage",
                "value": content.get('body', {}).get('storage', {}).get('value', '')
            },
            "version": {
                "number": current_version + 1,
                "message": f"Updated via sync tool at {datetime.now().isoformat()}"
            }
        }

        # Handle space moves in two steps:
        # 1. First convert to draft if needed
        # 2. Then move to new space
        current_space_id = current_page.get('spaceId')
        new_space_id = self.get_space_id()
        is_space_move = current_space_id != new_space_id

        if is_space_move:
            # Step 1: Convert to draft if not already
            if current_page.get('status') != 'draft':
                draft_data = update_data.copy()
                draft_data['status'] = 'draft'
                draft_data['version']['number'] = 1

                try:
                    logger.info(f"Converting page {page_id} to draft status")
                    response = self.session.put(url, json=draft_data, timeout=(5, 30))
                    response.raise_for_status()

                    # Wait and verify the page is actually in draft status
                    max_draft_checks = 3
                    draft_check_count = 0
                    while draft_check_count < max_draft_checks:
                        time.sleep(1)  # Wait a second before checking
                        current_page = self.get_page_by_id(page_id)
                        if current_page.get('status') == 'draft':
                            logger.info(f"Successfully converted page {page_id} to draft")
                            break
                        draft_check_count += 1
                        if draft_check_count == max_draft_checks:
                            raise ConfluenceAPIError(
                                f"Failed to convert page {page_id} to draft status after {max_draft_checks} attempts",
                                status_code=400
                            )
                except requests.exceptions.RequestException as e:
                    raise ConfluenceAPIError(f"Failed to convert page {page_id} to draft", e)

            # Step 2: Move to new space
            update_data['spaceId'] = new_space_id

        try:
            response = self.session.put(url, json=update_data, timeout=(5, 30))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if isinstance(e, requests.exceptions.HTTPError):
                try:
                    error_data = e.response.json()
                    error_message = error_data.get('errors', [{}])[0].get('title', str(e))
                    logger.error(f"Error updating page {page_id} (status: {e.response.status_code})")
                    logger.error(f"Error response: {json.dumps(error_data)}")
                    raise ConfluenceAPIError(
                        f"Failed to update page {page_id} (HTTP {e.response.status_code}): {json.dumps(error_data)}",
                        status_code=e.response.status_code
                    )
                except (json.JSONDecodeError, KeyError, AttributeError):
                    pass
            raise ConfluenceAPIError(f"Failed to update page {page_id}", e)

    def create_page(self, content: Dict) -> Dict:
        """
        Create a new page with proper error handling
        
        Args:
            content: The page content and metadata
            
        Returns:
            Dict: The created page data
            
        Raises:
            ConfluenceAPIError: If the creation fails
        """
        url = f"{self.base_url}/wiki/api/v{self.api_version}/pages"
        
        # Ensure we're using the correct space ID
        space_id = self.get_space_id()
        
        # Format the request body according to Confluence API v2 specs
        create_data = {
            "spaceId": space_id,
            "status": "current",
            "title": content.get('title', ''),
            "body": {
                "representation": "storage",
                "value": content.get('body', {}).get('storage', {}).get('value', '')
            }
        }
        
        try:
            logger.debug(f"Creating new page with data: {json.dumps(create_data)}")
            response = self.session.post(url, json=create_data, timeout=(5, 30))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if e.response and e.response.status_code == 400:
                error_details = e.response.text
                logger.error(f"Failed to create page. API Response: {error_details}")
                try:
                    error_json = e.response.json()
                    logger.error(f"Detailed error: {json.dumps(error_json, indent=2)}")
                except:
                    pass
            raise ConfluenceAPIError(
                "Failed to create page: {str(e)}",
                status_code=getattr(e.response, 'status_code', None),
                response=getattr(e.response, 'text', None)
            )

    def get_attachments(self, page_id: str, *, media_type: str = None, filename: str = None, 
                       status: List[str] = None, limit: int = 50) -> List[Dict]:
        """
        Get list of attachments for a page with filtering support
        
        Args:
            page_id: The ID of the page
            media_type: Filter by media type
            filename: Filter by filename
            status: Filter by status (current, archived, trashed)
            limit: Maximum number of results (max 250)
            
        Returns:
            List[Dict]: List of attachment metadata
            
        Raises:
            ConfluenceAPIError: If the request fails
        """
        url = f"{self.base_url}/wiki/api/v{self.api_version}/pages/{page_id}/attachments"
        params = {'limit': min(limit, 250)}
        
        if media_type:
            params['mediaType'] = media_type
        if filename:
            params['filename'] = filename
        if status:
            params['status'] = status
            
        all_results = []
        
        try:
            while url and len(all_results) < limit:
                logger.debug(f"Getting attachments from {url}")
                response = self.session.get(url, params=params, timeout=(5, 30))
                response.raise_for_status()
                
                data = response.json()
                results = data.get('results', [])
                all_results.extend(results)
                
                # Get next page URL from Link header
                url = None
                link_header = response.headers.get('Link')
                if link_header:
                    matches = re.findall(r'<([^>]+)>;\s*rel="([^"]+)"', link_header)
                    for url_match, rel in matches:
                        if rel == 'next':
                            url = url_match
                            params = {}  # Parameters are included in the URL
                            break
                            
            return all_results[:limit]
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to get attachments for page {page_id}"
            if hasattr(e, 'response') and e.response is not None:
                error_msg += f": {e.response.status_code} - {e.response.text}"
            else:
                error_msg += f": {str(e)}"
            logger.error(error_msg)
            raise ConfluenceAPIError(error_msg)

    def get_attachment_metadata(self, attachment_id: str) -> Dict:
        """
        Get full metadata for an attachment including versions, labels, and properties
        
        Args:
            attachment_id: The ID of the attachment
            
        Returns:
            Dict: Full attachment metadata
            
        Raises:
            ConfluenceAPIError: If any request fails
        """
        try:
            # Get basic attachment info
            url = f"{self.base_url}/wiki/api/v{self.api_version}/attachments/{attachment_id}"
            response = self.session.get(url, timeout=(5, 30))
            response.raise_for_status()
            metadata = response.json()
            
            # Get versions
            url = f"{self.base_url}/wiki/api/v{self.api_version}/attachments/{attachment_id}/versions"
            response = self.session.get(url, timeout=(5, 30))
            if response.ok:
                metadata['versions'] = response.json().get('results', [])
            
            # Get labels
            url = f"{self.base_url}/wiki/api/v{self.api_version}/attachments/{attachment_id}/labels"
            response = self.session.get(url, timeout=(5, 30))
            if response.ok:
                metadata['labels'] = response.json().get('results', [])
            
            # Get properties
            url = f"{self.base_url}/wiki/api/v{self.api_version}/attachments/{attachment_id}/properties"
            response = self.session.get(url, timeout=(5, 30))
            if response.ok:
                metadata['properties'] = response.json().get('results', [])
            
            return metadata
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Failed to get metadata for attachment {attachment_id}"
            if hasattr(e, 'response') and e.response is not None:
                error_msg += f": {e.response.status_code} - {e.response.text}"
            else:
                error_msg += f": {str(e)}"
            logger.error(error_msg)
            raise ConfluenceAPIError(error_msg)

    def _save_attachment_metadata(self, page_id: str, attachment: Dict):
        """Save attachment metadata to local cache"""
        try:
            # Get full metadata including versions, labels, etc.
            metadata = self.get_attachment_metadata(attachment['id'])
            
            # Create metadata directory
            metadata_dir = self.local.attachments_dir / str(page_id) / '.metadata'
            metadata_dir.mkdir(parents=True, exist_ok=True)
            
            # Save metadata JSON
            metadata_file = metadata_dir / f"{attachment['title']}.json"
            with metadata_file.open('w') as f:
                json.dump(metadata, f, indent=2)
                
        except Exception as e:
            logger.warning(f"Failed to save metadata for attachment {attachment.get('title', 'Unknown')}: {str(e)}")

    def download_attachment(self, page_id: str, attachment: Dict) -> bytes:
        """
        Download an attachment's content with retry logic
        
        Args:
            page_id: The ID of the page
            attachment: The attachment metadata
            
        Returns:
            bytes: The attachment content
            
        Raises:
            ConfluenceAPIError: If the download fails after retries
        """
        max_retries = 3
        retry_delay = 1  # seconds
        
        # Get the download URL from the attachment metadata
        download_url = attachment.get('_links', {}).get('download')
        if not download_url:
            error_msg = f"No download URL found for attachment {attachment.get('title', 'Unknown')}"
            logger.error(error_msg)
            raise ConfluenceAPIError(error_msg)

        # Try different URL patterns based on Confluence API v2 specification
        url_patterns = []
        
        # If it's a relative URL
        if download_url.startswith('/'):
            # Strip any leading /wiki or /rest to normalize the path
            clean_path = re.sub(r'^/(wiki|rest)/', '/', download_url)
            
            # Try different URL combinations according to the API spec
            url_patterns = [
                f"{self.base_url}{clean_path}",  # Direct to API
                f"{self.base_url}/wiki{clean_path}",  # Through wiki path
                f"{self.base_url}/rest{clean_path}",  # Through REST path
                f"{self.base_url}/download{clean_path}"  # Direct download path
            ]
            
            # If it's a download URL, also try the special download endpoints
            if 'download' in clean_path:
                url_patterns.extend([
                    f"{self.base_url}/attachments/{page_id}/download",
                    f"{self.base_url}/wiki/attachments/{page_id}/download"
                ])
        else:
            # If it's already a full URL, use it as is
            url_patterns = [download_url]

        last_error = None
        for url in url_patterns:
            for attempt in range(max_retries):
                try:
                    logger.debug(f"Downloading attachment from {url} (attempt {attempt + 1}/{max_retries})")
                    response = self.session.get(
                        url,
                        timeout=(5, 30),
                        headers={'Accept': '*/*'}  # Accept any content type
                    )
                    
                    # Check for specific error cases
                    if response.status_code == 404:
                        logger.warning(f"Attachment not found at {url}")
                        break  # Try next URL format
                    
                    response.raise_for_status()
                    content_length = len(response.content)
                    logger.debug(f"Successfully downloaded {content_length} bytes")
                    return response.content
                    
                except requests.exceptions.RequestException as e:
                    last_error = e
                    error_msg = f"Failed to download attachment {attachment.get('title', 'Unknown')}"
                    if hasattr(e, 'response') and e.response is not None:
                        error_msg += f": {e.response.status_code}"
                        if e.response.status_code == 404:
                            break  # Try next URL format
                    else:
                        error_msg += f": {str(e)}"
                    
                    logger.warning(f"{error_msg} - Attempt {attempt + 1}/{max_retries}")
                    
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))  # Exponential backoff
                        
        # If we get here, all attempts failed
        error_msg = f"Failed to download attachment {attachment.get('title', 'Unknown')} after trying multiple URLs"
        if last_error and hasattr(last_error, 'response') and last_error.response is not None:
            error_msg += f": {last_error.response.status_code} - {last_error.response.text}"
        else:
            error_msg += f": {str(last_error) if last_error else 'Unknown error'}"
        logger.error(error_msg)
        raise ConfluenceAPIError(error_msg)

    def upload_attachment(self, page_id: str, file_path: Path) -> Dict:
        """Upload an attachment to a page"""
        url = f"{self.base_url}/wiki/api/v{self.api_version}/attachments"
        files = {
            'file': (file_path.name, file_path.open('rb'), 'application/octet-stream')
        }
        data = {'id': page_id}
        try:
            response = self.session.post(url, files=files, data=data, timeout=(5, 30))
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise ConfluenceAPIError(f"Failed to upload attachment to page {page_id}: {str(e)}")

    def delete_page(self, page_id: str) -> None:
        """
        Delete a page from Confluence
        
        Args:
            page_id: The ID of the page to delete
            
        Raises:
            ConfluenceAPIError: If the deletion fails
        """
        url = f"{self.base_url}/wiki/api/v{self.api_version}/pages/{page_id}"
        
        try:
            logger.debug(f"Deleting page {page_id}")
            response = self.session.delete(url, timeout=(5, 30))
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            if e.response and e.response.status_code == 404:
                # Page already deleted, that's fine
                return
            raise ConfluenceAPIError(
                f"Failed to delete page {page_id}: {str(e)}",
                status_code=getattr(e.response, 'status_code', None),
                response=getattr(e.response, 'text', None)
            )

    def _download_attachment(self, page_id: str, attachment: Dict):
        """
        Download an attachment and save it locally with metadata
        
        Args:
            page_id: The ID of the page
            attachment: The attachment metadata
        """
        filename = attachment.get('title', '')
        if not filename:
            logger.warning(f"Skipping attachment with no filename for page {page_id}")
            return
            
        # Skip attachments that consistently fail to download
        if self._should_skip_attachment(filename):
            logger.info(f"Skipping previously failed attachment: {filename}")
            return
            
        try:
            # Get the attachment content
            content = self.download_attachment(page_id, attachment)
            
            # Create the attachments directory for this page
            page_attachments_dir = self.local.attachments_dir / str(page_id)
            page_attachments_dir.mkdir(parents=True, exist_ok=True)
            
            # Save the attachment with proper error handling
            file_path = page_attachments_dir / filename
            try:
                with file_path.open('wb') as f:
                    f.write(content)
                logger.info(f"Successfully downloaded attachment {filename} ({len(content)} bytes)")
                self._clear_failed_attachment(filename)
                
                # Save metadata after successful download
                self._save_attachment_metadata(page_id, attachment)
                
            except OSError as e:
                logger.error(f"Failed to write attachment {filename} to disk: {str(e)}")
                return
                
        except ConfluenceAPIError as e:
            logger.error(f"Failed to download attachment {filename}: {e.message}")
            self._mark_failed_attachment(filename)
        except Exception as e:
            logger.error(f"Unexpected error downloading attachment {filename}: {str(e)}")
            self._mark_failed_attachment(filename)

    def _should_skip_attachment(self, filename: str) -> bool:
        """Check if an attachment should be skipped based on previous failures"""
        failed_attachments_file = self.local.cache_dir / '.failed_attachments'
        if not failed_attachments_file.exists():
            return False
            
        try:
            with failed_attachments_file.open('r') as f:
                failed_attachments = json.load(f)
                
            # Check if the attachment has failed multiple times recently
            if filename in failed_attachments:
                failures = failed_attachments[filename]
                if len(failures) >= 3:  # Skip after 3 failures
                    last_failure = datetime.fromisoformat(failures[-1])
                    if datetime.now() - last_failure < timedelta(hours=24):
                        return True
            return False
        except (json.JSONDecodeError, OSError):
            return False

    def _mark_failed_attachment(self, filename: str):
        """Mark an attachment as failed"""
        failed_attachments_file = self.local.cache_dir / '.failed_attachments'
        try:
            failed_attachments = {}
            if failed_attachments_file.exists():
                with failed_attachments_file.open('r') as f:
                    failed_attachments = json.load(f)
                    
            # Add new failure timestamp
            if filename not in failed_attachments:
                failed_attachments[filename] = []
            failed_attachments[filename].append(datetime.now().isoformat())
            
            # Keep only recent failures
            failed_attachments[filename] = [
                ts for ts in failed_attachments[filename]
                if datetime.now() - datetime.fromisoformat(ts) < timedelta(hours=24)
            ]
            
            with failed_attachments_file.open('w') as f:
                json.dump(failed_attachments, f)
                
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to update failed attachments list: {str(e)}")

    def _clear_failed_attachment(self, filename: str):
        """Remove an attachment from the failed list"""
        failed_attachments_file = self.local.cache_dir / '.failed_attachments'
        if not failed_attachments_file.exists():
            return
            
        try:
            with failed_attachments_file.open('r') as f:
                failed_attachments = json.load(f)
                
            if filename in failed_attachments:
                del failed_attachments[filename]
                
            with failed_attachments_file.open('w') as f:
                json.dump(failed_attachments, f)
                
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to clear failed attachment: {str(e)}")

    def _clean_adf_content(self, content: Dict) -> Dict:
        """
        Clean and normalize ADF content from various possible formats
        """
        if not content:
            return {}

        # Handle nested value structure
        if isinstance(content.get('value'), dict):
            value = content['value']
            if value.get('representation') == 'atlas_doc_format':
                return {'value': value.get('value', {})}
            return {'value': value}

        # Handle JSON string value
        if isinstance(content.get('value'), str):
            try:
                return {'value': json.loads(content['value'])}
            except json.JSONDecodeError:
                return {}

        return content

    def get_page_body(self, page_id: str) -> Dict:
        """
        Get the body content of a page in storage format
        
        Args:
            page_id: ID of the page to get body content for
        
        Returns:
            Dict: Body content in storage format with representation and value fields
        
        Raises:
            ConfluenceAPIError: If the API request fails or page is not in the correct space
        """
        print(f"DEBUG: Getting body for page {page_id}")  # Temporary print for debugging
        
        url = f"{self.base_url}/wiki/api/v{self.api_version}/pages/{page_id}"
        params = {
            'body-format': 'storage',
            'expand': 'body.storage,space'  # Add space to expansion
        }
        
        print(f"DEBUG: Request URL: {url}")  # Temporary print for debugging
        print(f"DEBUG: Request params: {params}")  # Temporary print for debugging
        
        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            print(f"DEBUG: Response status: {response.status_code}")  # Temporary print
            print(f"DEBUG: Response data keys: {list(data.keys())}")  # Temporary print
            
            # Verify page is in the correct space
            space = data.get('space', {})
            if space.get('key') != self.space_key:
                raise ConfluenceAPIError(f"Page {page_id} is not in space {self.space_key}")
            
            # Extract and return the body content
            body = data.get('body', {})
            print(f"DEBUG: Body keys: {list(body.keys())}")  # Temporary print
            
            storage = body.get('storage', {})
            print(f"DEBUG: Storage keys: {list(storage.keys())}")  # Temporary print
            
            value = storage.get('value', '')
            print(f"DEBUG: Body content length: {len(value)}")  # Temporary print
            
            if not value:
                print(f"DEBUG: No body content found for page {page_id}")  # Temporary print
            
            return {
                'representation': 'storage',
                'value': value
            }
            
        except requests.exceptions.RequestException as e:
            print(f"DEBUG: API request failed: {str(e)}")  # Temporary print
            raise ConfluenceAPIError(f"Failed to get page body: {str(e)}")

class LocalContentManager:
    def __init__(self):
        self.content_dir = Path(os.getenv('LOCAL_CONTENT_DIR', './content'))
        self.attachments_dir = Path(os.getenv('LOCAL_ATTACHMENTS_DIR', './attachments'))
        self.cache_dir = Path(os.getenv('LOCAL_CACHE_DIR', './cache'))
        
        # Create directories if they don't exist
        for directory in [self.content_dir, self.attachments_dir, self.cache_dir]:
            directory.mkdir(parents=True, exist_ok=True)
            
        # Load or create the ID to filename mapping
        self.id_map_file = self.cache_dir / 'id_mapping.json'
        self.id_to_filename = self._load_id_mapping()

    def _load_id_mapping(self) -> Dict[str, str]:
        """Load the ID to filename mapping from cache"""
        try:
            if self.id_map_file.exists():
                with self.id_map_file.open('r') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load ID mapping: {e}")
        return {}

    def _save_id_mapping(self):
        """Save the ID to filename mapping to cache"""
        try:
            with self.id_map_file.open('w') as f:
                json.dump(self.id_to_filename, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save ID mapping: {e}")

    def _sanitize_filename(self, title: str) -> str:
        """
        Convert a title to a safe filename
        
        Args:
            title: The title to convert
            
        Returns:
            str: A filename-safe version of the title
        """
        # Remove or replace unsafe characters
        safe_name = "".join(c.lower() if c.isalnum() else '-' for c in title)
        # Remove consecutive dashes and trim
        safe_name = '-'.join(filter(None, safe_name.split('-')))
        return safe_name[:100]  # Limit length to 100 chars

    def get_local_content(self) -> Dict[str, Dict]:
        """Get all local content with their metadata"""
        content = {}
        for file_path in self.content_dir.glob('*.json'):
            try:
                with file_path.open('r') as f:
                    file_content = json.load(f)
                    content[file_path.stem] = {
                        'content': file_content,
                        'hash': self._get_file_hash(file_path)
                    }
            except Exception as e:
                logger.error(f"Failed to read content file {file_path}: {e}")
        return content

    def save_content(self, page_id: str, content: Dict):
        """Save content to local file"""
        logger.debug(f"Saving content for page {page_id}")  
        logger.debug(f"Content keys: {list(content.keys())}")  
        
        # Ensure content directory exists
        os.makedirs(self.content_dir, exist_ok=True)
        
        # Get the title for the filename
        title = content.get('title', 'untitled').lower().replace(' ', '_')
        filename = f"{title}.json"
        filepath = os.path.join(self.content_dir, filename)
        
        logger.debug(f"Saving to file: {filepath}")  
        
        # Extract body content
        body = content.get('body', {})
        if isinstance(body, dict) and 'storage' in body:
            body_content = {
                'representation': 'storage',
                'value': body['storage'].get('value', '')
            }
        else:
            body_content = {}
            logger.debug(f"No storage content found in body: {body}")  
        
        # Prepare content for saving
        save_content = {
            'id': content.get('id'),
            'title': content.get('title'),
            'type': content.get('type'),
            'status': content.get('status'),
            'body': body_content,
            'version': content.get('version'),
            'createdAt': content.get('createdAt'),
            'authorId': content.get('authorId'),
            'lastOwnerId': content.get('lastOwnerId'),
            'position': content.get('position')
        }
        
        logger.debug(f"Final body content: {body_content}")  
        
        # Save mapping content first
        mapping_filepath = os.path.join(self.content_dir, f"{title}_mapping.json")
        logger.debug(f"Saving mapping to file: {mapping_filepath}")  
        with open(mapping_filepath, 'w', encoding='utf-8') as f:
            json.dump(save_content, f, indent=2, ensure_ascii=False)
        
        # Save the main content
        logger.debug(f"Saving main content to file: {filepath}")  
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(save_content, f, indent=2, ensure_ascii=False)

    def get_page_id_from_filename(self, filename: str) -> Optional[str]:
        """Get the page ID associated with a filename"""
        # Remove .json extension if present
        filename = filename.replace('.json', '')
        
        # Look up the ID in our mapping
        for page_id, mapped_filename in self.id_to_filename.items():
            if mapped_filename == filename:
                return page_id
        return None

    def _get_file_hash(self, file_path: Path) -> str:
        """Calculate MD5 hash of a file"""
        try:
            with file_path.open('rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception as e:
            logger.error(f"Failed to calculate hash for {file_path}: {e}")
            return ""

    def delete_local_content(self, filename: str) -> None:
        """
        Delete local content file and update mappings
        
        Args:
            filename: The filename to delete (without .json extension)
        """
        file_path = self.content_dir / f"{filename}.json"
        if file_path.exists():
            try:
                file_path.unlink()
                # Remove from ID mapping if present
                page_id = self.get_page_id_from_filename(filename)
                if page_id and page_id in self.id_to_filename:
                    del self.id_to_filename[page_id]
                    self._save_id_mapping()
            except Exception as e:
                logger.error(f"Failed to delete local file {filename}: {e}")

class ContentSyncer:
    def __init__(self):
        self.confluence = ConfluenceAPI()
        self.local = LocalContentManager()
        self.cache_file = self.local.cache_dir / 'sync_cache.json'
        self.deleted_pages_file = self.local.cache_dir / 'deleted_pages.json'

    def _load_cache(self) -> Dict:
        """Load the sync cache"""
        if self.cache_file.exists():
            with self.cache_file.open('r') as f:
                return json.load(f)
        return {}

    def _save_cache(self, cache: Dict):
        """Save the sync cache"""
        with self.cache_file.open('w') as f:
            json.dump(cache, f, indent=2)

    def _load_deleted_pages(self) -> set:
        """Load the set of deleted page IDs"""
        try:
            if self.deleted_pages_file.exists():
                with self.deleted_pages_file.open('r') as f:
                    return set(json.load(f))
        except Exception as e:
            logger.warning(f"Failed to load deleted pages: {e}")
        return set()

    def _save_deleted_pages(self, deleted_pages: set):
        """Save the set of deleted page IDs"""
        try:
            with self.deleted_pages_file.open('w') as f:
                json.dump(list(deleted_pages), f)
        except Exception as e:
            logger.error(f"Failed to save deleted pages: {e}")

    def pull_from_confluence(self):
        """Pull content from Confluence to local"""
        logger.info("Pulling content from Confluence...")
        try:
            logger.debug("Fetching space content...")
            space_content = self.confluence.get_space_content()
        except ConfluenceAPIError as e:
            logger.error(f"Failed to pull content: {e.message}")
            return

        deleted_pages = self._load_deleted_pages()
        
        logger.debug(f"Processing {len(space_content.get('results', []))} pages...")
        for page in space_content.get('results', []):
            page_id = page['id']
            
            # Skip pages that were deleted locally
            if page_id in deleted_pages:
                logger.debug(f"Skipping deleted page {page_id}")
                continue
                
            try:
                logger.debug(f"Processing page: {page.get('title', 'Untitled')} (ID: {page_id})")
                full_page = self.confluence.get_page_by_id(page_id)
                self.local.save_content(page_id, full_page)
                
                # Download attachments with proper error handling
                try:
                    logger.debug(f"Getting attachments for page {page_id}...")
                    attachments = self.confluence.get_attachments(page_id)
                    if attachments:
                        logger.info(f"Downloading {len(attachments)} attachments for page {page_id}")
                        for attachment in attachments:
                            self.confluence._download_attachment(page_id, attachment)
                except ConfluenceAPIError as e:
                    logger.error(f"Failed to get attachments for page {page_id}: {e.message}")
                    continue
                    
            except ConfluenceAPIError as e:
                logger.error(f"Failed to get page {page_id}: {e.message}")
                continue

        logger.info("Pull completed successfully")

    def push_to_confluence(self):
        """Push local content to Confluence"""
        logger.info("Pushing content to Confluence...")
        local_content = self.local.get_local_content()
        cache = self._load_cache()
        deleted_pages = self._load_deleted_pages()

        # Check for deleted files
        cached_files = set(cache.keys())
        current_files = set(local_content.keys())
        deleted_files = cached_files - current_files

        # Handle deleted files
        for filename in deleted_files:
            page_id = self.local.get_page_id_from_filename(filename)
            if page_id:
                try:
                    logger.info(f"Deleting page '{filename}' from Confluence")
                    self.confluence.delete_page(page_id)
                    deleted_pages.add(page_id)
                    if page_id in self.local.id_to_filename:
                        del self.local.id_to_filename[page_id]
                except ConfluenceAPIError as e:
                    logger.error(f"Failed to delete page: {e.message}")
                    continue

        # Handle existing and new content
        for filename, content in local_content.items():
            current_hash = content['hash']
            cached_hash = cache.get(filename)

            if current_hash != cached_hash:
                # Get the page ID from the filename or content
                page_id = (
                    content['content'].get('id') or 
                    self.local.get_page_id_from_filename(filename)
                )
                
                try:
                    if page_id:
                        if page_id in deleted_pages:
                            # Page was previously deleted, create a new one
                            logger.info(f"Re-creating previously deleted page '{content['content'].get('title', 'Untitled')}'")
                            result = self.confluence.create_page(content['content'])
                            if result and result.get('id'):
                                content['content']['id'] = result['id']
                                self.local.save_content(result['id'], content['content'])
                                deleted_pages.remove(page_id)
                        else:
                            # Update existing page
                            logger.info(f"Updating existing page '{content['content'].get('title', 'Untitled')}'")
                            self.confluence.update_page(page_id, content['content'])
                    else:
                        # Create new page
                        logger.info(f"Creating new page '{content['content'].get('title', 'Untitled')}'")
                        result = self.confluence.create_page(content['content'])
                        if result and result.get('id'):
                            content['content']['id'] = result['id']
                            self.local.save_content(result['id'], content['content'])
                
                except ConfluenceAPIError as e:
                    if e.status_code == 404 and page_id:
                        # Page was deleted in Confluence, create it again
                        try:
                            logger.info(f"Page '{content['content'].get('title', 'Untitled')}' not found in Confluence, creating new page")
                            result = self.confluence.create_page(content['content'])
                            if result and result.get('id'):
                                content['content']['id'] = result['id']
                                self.local.save_content(result['id'], content['content'])
                                if page_id in deleted_pages:
                                    deleted_pages.remove(page_id)
                        except ConfluenceAPIError as create_error:
                            logger.error(f"Failed to create page: {create_error.message}")
                            continue
                    else:
                        logger.error(f"Failed to {'update' if page_id else 'create'} page: {e.message}")
                        continue
                
                # Update cache with the new hash
                cache[filename] = current_hash

        # Save updated cache and deleted pages
        self._save_cache(cache)
        self._save_deleted_pages(deleted_pages)
        logger.info("Push completed successfully")

    def _download_attachment(self, page_id: str, attachment: Dict):
        """
        Download an attachment and save it locally
        
        Args:
            page_id: The ID of the page
            attachment: The attachment metadata
        """
        filename = attachment.get('title', '')
        if not filename:
            logger.warning(f"Skipping attachment with no filename for page {page_id}")
            return
            
        # Skip attachments that consistently fail to download
        if self.confluence._should_skip_attachment(filename):
            logger.info(f"Skipping previously failed attachment: {filename}")
            return
            
        try:
            # Get the attachment content
            content = self.confluence.download_attachment(page_id, attachment)
            
            # Create the attachments directory for this page
            page_attachments_dir = self.local.attachments_dir / str(page_id)
            page_attachments_dir.mkdir(parents=True, exist_ok=True)
            
            # Save the attachment with proper error handling
            file_path = page_attachments_dir / filename
            try:
                with file_path.open('wb') as f:
                    f.write(content)
                logger.info(f"Successfully downloaded attachment {filename} ({len(content)} bytes)")
                self.confluence._clear_failed_attachment(filename)  # Clear from failed list if successful
            except OSError as e:
                logger.error(f"Failed to write attachment {filename} to disk: {str(e)}")
                return
                
        except ConfluenceAPIError as e:
            logger.error(f"Failed to download attachment {filename}: {e.message}")
            self.confluence._mark_failed_attachment(filename)  # Mark as failed for future reference
        except Exception as e:
            logger.error(f"Unexpected error downloading attachment {filename}: {str(e)}")
            self.confluence._mark_failed_attachment(filename)

class ContentChangeHandler(FileSystemEventHandler):
    def __init__(self, syncer: ContentSyncer):
        self.syncer = syncer

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith('.json'):
            logger.info(f"Change detected in {event.src_path}")
            self.syncer.push_to_confluence()

@click.group()
def cli():
    """Confluence Content Sync Tool"""
    pass

@cli.command()
def pull():
    """Pull content from Confluence to local"""
    syncer = ContentSyncer()
    syncer.pull_from_confluence()

@cli.command()
def push():
    """Push local content to Confluence"""
    syncer = ContentSyncer()
    syncer.push_to_confluence()

@cli.command()
def watch():
    """Watch for local changes and sync automatically"""
    syncer = ContentSyncer()
    event_handler = ContentChangeHandler(syncer)
    observer = Observer()
    
    observer.schedule(event_handler, str(syncer.local.content_dir), recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == '__main__':
    # Configure logging before anything else
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        force=True  # Force reconfiguration
    )
    
    # Ensure requests logging is also at debug level
    logging.getLogger('urllib3').setLevel(logging.DEBUG)
    
    cli()