import os
import requests
import hashlib
import mimetypes
import json
import tempfile
import logging
from typing import Optional, Dict, Any, List, BinaryIO, Tuple
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('ZoteroClient')

class ZoteroClient:
    """A comprehensive client for interacting with the Zotero API, with focus on file uploads."""
    
    def __init__(self, api_key: str, library_type: str = 'user', library_id: str = None):
        """
        Initialize the Zotero client.
        
        Args:
            api_key: Your Zotero API key
            library_type: Type of library ('user' or 'group')
            library_id: ID of the library (userID for user libraries)
        """
        self.api_key = api_key
        self.library_type = library_type
        self.library_id = library_id
        self.base_url = 'https://api.zotero.org'
        self.headers = {
            'Zotero-API-Version': '3',
            'Authorization': f'Bearer {api_key}'
        }

    def get_template(self, item_type: str, **params) -> Dict[str, Any]:
        """
        Get an empty template for creating a new item.
        
        Args:
            item_type: Type of item (e.g., 'attachment', 'document', 'journalArticle')
            **params: Additional parameters for the template (e.g., linkMode for attachments)
            
        Returns:
            Dict containing the editable JSON template
        """
        logger.debug(f"Getting template for type: {item_type}")
        logger.debug(f"Template params: {params}")
        
        endpoint = f"{self.base_url}/items/new"
        query_params = {'itemType': item_type, **params}
        
        response = requests.get(endpoint, headers=self.headers, params=query_params)
        response.raise_for_status()
        
        # Extract the editable JSON from the data property
        template = response.json()
        if isinstance(template, dict) and 'data' in template:
            template = template['data']
        
        logger.debug(f"Got template: {template}")
        return template

    def get_item(self, item_key: str) -> Dict[str, Any]:
        """
        Retrieve an item from Zotero.
        
        Args:
            item_key: Key of the item to retrieve
            
        Returns:
            Dict containing the item details (editable JSON data)
        """
        logger.debug(f"Getting item with key: {item_key}")
        
        endpoint = f'{self.base_url}/{self.library_type}s/{self.library_id}/items/{item_key}'
        response = requests.get(endpoint, headers=self.headers)
        response.raise_for_status()
        
        # Extract the editable JSON from the data property
        result = response.json()
        if isinstance(result, dict) and 'data' in result:
            result = result['data']
            
        logger.debug(f"Got item: {result}")
        return result

    def create_item(self, item_type: str, metadata: Dict[str, Any]) -> Dict[Any, Any]:
        """
        Create a new item in Zotero by first getting an empty template and then submitting it.
        
        Args:
            item_type: Type of item (e.g., 'document', 'journalArticle')
            metadata: Dict containing item metadata
            
        Returns:
            Dict containing the created item details (editable JSON data)
        """
        logger.debug(f"Creating item of type: {item_type}")
        logger.debug(f"Metadata: {metadata}")
        
        try:
            # Get empty template from API
            endpoint = f"{self.base_url}/items/new"
            params = {'itemType': item_type}
            
            response = requests.get(endpoint, headers=self.headers, params=params)
            response.raise_for_status()
            
            # Get the template data
            template = response.json()
            logger.debug(f"Got empty template: {template}")
            
            # Update template with metadata
            template.update(metadata)
            
            # Submit the modified template in an array
            create_endpoint = f'{self.base_url}/{self.library_type}s/{self.library_id}/items'
            data = [template]  # Submit as array
            logger.debug(f"Submitting data: {json.dumps(data, indent=2)}")
            
            create_response = requests.post(
                create_endpoint,
                headers={**self.headers, 'Content-Type': 'application/json'},
                json=data  # Submit as array
            )
            
            if create_response.status_code != 200:
                logger.error(f"Error creating item. Status: {create_response.status_code}")
                logger.error(f"Response: {create_response.text}")
                
            create_response.raise_for_status()
            
            # Extract the successful item data
            result = create_response.json()
            logger.debug(f"Create response: {json.dumps(result, indent=2)}")
            
            if isinstance(result, dict) and 'successful' in result:
                # Get the first successful item's key and data
                success_key = next(iter(result['successful']))
                item_data = result['successful'][success_key]['data']
                logger.debug(f"Created item: {json.dumps(item_data, indent=2)}")
                return item_data
            else:
                logger.error(f"Unexpected response format: {result}")
                raise ValueError("Invalid response format from Zotero API")
            
        except Exception as e:
            logger.error(f"Failed to create item: {str(e)}")
            raise

    def create_attachment(self, parent_key: str, link_mode: str, metadata: Dict[str, Any]) -> Dict[Any, Any]:
        """
        Create an attachment item by first getting an empty template and then submitting it.
        
        Args:
            parent_key: Key of the parent item
            link_mode: One of 'imported_file', 'imported_url', 'linked_file', 'linked_url'
            metadata: Dict containing attachment metadata
            
        Returns:
            Dict containing the created attachment details (editable JSON data)
        """
        logger.debug(f"Creating attachment for parent: {parent_key}")
        logger.debug(f"Link mode: {link_mode}")
        logger.debug(f"Metadata: {metadata}")
        
        try:
            # Get empty template from API
            endpoint = f"{self.base_url}/items/new"
            params = {
                'itemType': 'attachment',
                'linkMode': link_mode
            }
            
            response = requests.get(endpoint, headers=self.headers, params=params)
            response.raise_for_status()
            
            # Get the template data
            template = response.json()
            logger.debug(f"Got empty template: {template}")
            
            # Update template with required fields and metadata
            template['parentItem'] = parent_key
            template.update(metadata)
            
            # Submit the modified template in an array
            create_endpoint = f'{self.base_url}/{self.library_type}s/{self.library_id}/items'
            data = [template]  # Submit as array
            logger.debug(f"Submitting data: {json.dumps(data, indent=2)}")
            
            create_response = requests.post(
                create_endpoint,
                headers={**self.headers, 'Content-Type': 'application/json'},
                json=data  # Submit as array
            )
            
            if create_response.status_code != 200:
                logger.error(f"Error creating attachment. Status: {create_response.status_code}")
                logger.error(f"Response: {create_response.text}")
                
            create_response.raise_for_status()
            
            # Extract the successful item data
            result = create_response.json()
            logger.debug(f"Create response: {json.dumps(result, indent=2)}")
            
            if isinstance(result, dict) and 'successful' in result:
                # Get the first successful item's key and data
                success_key = next(iter(result['successful']))
                item_data = result['successful'][success_key]['data']
                logger.debug(f"Created attachment: {json.dumps(item_data, indent=2)}")
                return item_data
            else:
                logger.error(f"Unexpected response format: {result}")
                raise ValueError("Invalid response format from Zotero API")
            
        except Exception as e:
            logger.error(f"Failed to create attachment: {str(e)}")
            raise

    def get_file_metadata(self, file_path: str) -> Dict[str, Any]:
        """
        Get metadata for a file including size, MD5 hash, and MIME type.
        
        Args:
            file_path: Path to the file
            
        Returns:
            Dict containing file metadata
        """
        logger.debug(f"Getting file metadata for: {file_path}")
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")
            
        with open(file_path, 'rb') as f:
            content = f.read()
            
        metadata = {
            'filename': os.path.basename(file_path),
            'filesize': len(content),
            'md5': hashlib.md5(content).hexdigest(),
            'mtime': int(os.path.getmtime(file_path) * 1000),  # Convert to milliseconds
            'content_type': mimetypes.guess_type(file_path)[0] or 'application/octet-stream'
        }
        
        logger.debug(f"File metadata: {metadata}")
        return metadata

    def get_upload_authorization(self, item_key: str, file_metadata: Dict[str, Any]) -> Dict[Any, Any]:
        """
        Get authorization for file upload.
        
        Args:
            item_key: Key of the item to attach the file to
            file_metadata: Dict containing file metadata
            
        Returns:
            Dict containing upload authorization details or {'exists': 1} if file already exists
        """
        logger.debug("Getting upload authorization")
        logger.debug(f"Item key: {item_key}")
        logger.debug(f"File metadata: {file_metadata}")
        
        # First, get the current item to check its version
        item = self.get_item(item_key)
        version = item.get('version')
        
        endpoint = f'{self.base_url}/{self.library_type}s/{self.library_id}/items/{item_key}/file'
        headers = {
            **self.headers,
            'Content-Type': 'application/x-www-form-urlencoded',
            #'If-Match': file_metadata['md5']  # Use current version for If-Match
            'If-None-Match': '*'  # Use current version for If-Match
        }
        
        # Build form data string with proper URL encoding
        from urllib.parse import urlencode
        form_data = {
            'md5': file_metadata['md5'],
            'filename': file_metadata['filename'],
            'filesize': str(file_metadata['filesize']),
            'mtime': str(file_metadata['mtime'])
        }
        
        logger.debug(f"Request headers: {headers}")
        logger.debug(f"Request form data: {form_data}")
        
        try:
            #response = requests.post(endpoint, headers=headers, data=form_data)
            response = requests.post(endpoint, headers=headers, data=form_data)
            response.raise_for_status()
            
            result = response.json()
            logger.debug(f"Got upload authorization: {result}")
            
            if result.get('exists') == 1:
                logger.info("File already exists on server")
                
            return result
            
        except requests.exceptions.HTTPError as e:
            logger.debug(e)
            if e.response.status_code == 412:  # Precondition Failed
                # Try again with If-None-Match for new files
                headers['If-None-Match'] = '*'
                del headers['If-Match']
                
                response = requests.post(endpoint, headers=headers, data=form_data)  # Use same form data format
                response.raise_for_status()
                
                result = response.json()
                logger.debug(f"Got upload authorization (retry): {result}")
                return result
            raise

    def upload_to_s3(self, auth_data: Dict[str, Any], file_path: str) -> None:
        """
        Upload file to S3 using the authorization data.
        
        Args:
            auth_data: Authorization data from get_upload_authorization
            file_path: Path to the file to upload
        """
        logger.debug(f"Uploading to S3: {file_path}")
        logger.debug(f"Auth data: {auth_data}")
        
        with open(file_path, 'rb') as f:
            response = requests.post(
                auth_data['url'],
                data=auth_data['params'],
                files={'file': (os.path.basename(file_path), f, mimetypes.guess_type(file_path)[0])},
                headers={'Content-Type': 'multipart/form-data'}
            )
        response.raise_for_status()
        logger.debug("S3 upload successful")

    def register_upload(self, item_key: str, upload_key: str) -> Dict[Any, Any]:
        """
        Register the upload with Zotero.
        
        Args:
            item_key: Key of the item to attach the file to
            upload_key: Upload key from the authorization response
            
        Returns:
            Dict containing the registration response (editable JSON data)
        """
        logger.debug(f"Registering upload for item: {item_key}")
        logger.debug(f"Upload key: {upload_key}")
        
        endpoint = f'{self.base_url}/{self.library_type}s/{self.library_id}/items/{item_key}/file'
        response = requests.post(
            endpoint,
            headers={**self.headers, 'If-None-Match': '*'},
            params={'upload': upload_key}
        )
        response.raise_for_status()
        
        # Extract the editable JSON from the data property
        result = response.json()
        if isinstance(result, dict) and 'data' in result:
            result = result['data']
            
        logger.debug(f"Upload registered: {result}")
        return result

    def upload_file(self, file_path: str, collection: Optional[str] = None, parent_key: Optional[str] = None, title: Optional[str] = None) -> Dict[Any, Any]:
        """
        Upload a file to Zotero following the recommended API procedure:
        1. Create attachment item
        2. Get upload authorization
        3. Upload file to S3
        4. Register upload
        
        Args:
            file_path: Path to the file to upload
            parent_key: Optional key of parent item to attach to
            title: Optional title for the new item (defaults to filename)
            
        Returns:
            Dict containing the upload response (editable JSON data)
        """
        logger.debug(f"Starting file upload: {file_path}")
        logger.debug(f"Parent key: {parent_key}")
        logger.debug(f"Title: {title}")
        
        # Get file metadata
        file_metadata = self.get_file_metadata(file_path)
        
        # Create parent item if none provided
        if not parent_key:
            parent = self.create_item('document', {
                'title': title or os.path.splitext(file_metadata['filename'])[0],
                'creators': [],
                'collections': [collection]
            })
            parent_key = parent['key']
        
        # Create attachment item
        attachment = self.create_attachment(
            parent_key,
            'imported_file',
            {
                'title': title or file_metadata['filename'],
                'contentType': file_metadata['content_type'],
                'filename': file_metadata['filename'],
                'md5': ''
            }
        )
        
        # Get upload authorization
        auth = self.get_upload_authorization(attachment['key'], file_metadata)
        
        # If file doesn't already exist, upload it
        if not auth.get('exists'):
            # Upload to S3
            self.upload_to_s3(auth, file_path)
            
            # Register upload
            return self.register_upload(attachment['key'], auth['uploadKey'])
        else:
            logger.info("File already exists, no need to upload")
            return attachment

    def upload_pdf(self, pdf_path: str, collection: Optional[str] = None, parent_key: Optional[str] = None, title: Optional[str] = None) -> Dict[Any, Any]:
        """
        Convenience method specifically for uploading PDF files.
        
        Args:
            pdf_path: Path to the PDF file
            parent_key: Optional key of parent item to attach to
            title: Optional title for the new item
            
        Returns:
            Dict containing the upload response (editable JSON data)
        """
        logger.debug(f"Starting PDF upload: {pdf_path}")
        logger.debug(f"Parent key: {parent_key}")
        logger.debug(f"Title: {title}")
        
        if not pdf_path.lower().endswith('.pdf'):
            raise ValueError("File must be a PDF")
        
        return self.upload_file(pdf_path, collection, parent_key, title)

    def get_collections(self) -> List[Dict[str, Any]]:
        """
        Retrieve all collections from the Zotero library.
        
        Returns:
            List of dictionaries containing collection details
        """
        logger.debug("Retrieving all collections")
        
        endpoint = f'{self.base_url}/{self.library_type}s/{self.library_id}/collections'
        response = requests.get(endpoint, headers=self.headers)
        response.raise_for_status()
        
        collections = response.json()
        logger.debug(f"Retrieved {len(collections)} collections")
        return collections

def test_upload():
    api_key = os.getenv('ZOTERO_API_KEY')
    library_id = os.getenv('ZOTERO_LIBRARY_ID')
    library_type = 'user'

    zot = ZoteroClient(api_key=api_key, library_type=library_type, library_id=library_id)


    pdf_path = "/mnt/books/Books/GPT/2311.02883.pdf"
    collection = 'VK44MNQB'
    
    try:
        logger.info("Starting test PDF upload")
        response = zot.upload_pdf(pdf_path,collection )
        logger.info("Upload successful")
        logger.debug(f"Response: {json.dumps(response, indent=2)}")
    except Exception as e:
        logger.error(f"Upload failed: {str(e)}", exc_info=True)

        
def test_get_collection():
    
    api_key = os.getenv('ZOTERO_API_KEY')
    library_id = os.getenv('ZOTERO_LIBRARY_ID')
    library_type = 'user'
    
    zot = ZoteroClient(api_key=api_key, library_type=library_type, library_id=library_id)
    
    collections = zot.get_collections()
    for collection in collections:
        logger.debug(collection)

if __name__ == "__main__":
    #test_get_collection()
    
    test_upload()