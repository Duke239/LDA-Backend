import os
import io
import logging
import tempfile
from typing import List, Dict, Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload
from google.auth.credentials import Credentials
from google.oauth2 import service_account
from datetime import datetime

logger = logging.getLogger(__name__)

class GoogleDriveService:
    """Google Drive service for uploading photos with API key authentication"""
    
    def __init__(self):
        self.api_key = os.getenv("GOOGLE_DRIVE_API_KEY")
        self.service = None
        
        if not self.api_key:
            logger.error("Google Drive API key not found in environment variables")
            raise ValueError("GOOGLE_DRIVE_API_KEY environment variable is required")
    
    def get_service(self):
        """Get or initialize Google Drive service"""
        if not self.service:
            try:
                # Use API key authentication for public file uploads
                self.service = build('drive', 'v3', developerKey=self.api_key)
                logger.info("Google Drive service initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Google Drive service: {e}")
                raise
        
        return self.service
    
    async def upload_photo(
        self, 
        file_content: bytes, 
        filename: str, 
        quote_id: str,
        content_type: str = "image/jpeg"
    ) -> Dict[str, str]:
        """
        Upload a photo to Google Drive and return file info
        
        Args:
            file_content: Binary content of the file
            filename: Original filename
            quote_id: Quote ID for organization
            content_type: MIME type of the file
        
        Returns:
            Dict containing file_id, filename, and share_url
        """
        try:
            service = self.get_service()
            
            # Create unique filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            drive_filename = f"{quote_id}_{timestamp}_{filename}"
            
            # File metadata
            file_metadata = {
                'name': drive_filename,
                'description': f'Photo for quote {quote_id} - LDA Group',
            }
            
            # Create media upload from bytes
            media = MediaIoBaseUpload(
                io.BytesIO(file_content),
                mimetype=content_type,
                resumable=True
            )
            
            # Upload file
            result = service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id,name,webViewLink'
            ).execute()
            
            file_id = result.get('id')
            
            # Make file publicly viewable
            permission = {
                'role': 'reader',
                'type': 'anyone'
            }
            
            service.permissions().create(
                fileId=file_id,
                body=permission
            ).execute()
            
            # Get file info with shareable link
            file_info = service.files().get(
                fileId=file_id,
                fields='id,name,webViewLink,webContentLink'
            ).execute()
            
            logger.info(f"Successfully uploaded {filename} for quote {quote_id}")
            
            return {
                'file_id': file_info['id'],
                'filename': file_info['name'],
                'original_filename': filename,
                'share_url': file_info['webViewLink'],
                'direct_url': file_info.get('webContentLink', ''),
                'upload_time': datetime.utcnow().isoformat()
            }
            
        except HttpError as error:
            logger.error(f"Google Drive API error during upload: {error}")
            raise Exception(f"Failed to upload to Google Drive: {error}")
        except Exception as error:
            logger.error(f"Unexpected error during upload: {error}")
            raise Exception(f"Upload failed: {str(error)}")
    
    async def upload_multiple_photos(
        self, 
        files: List[Dict], 
        quote_id: str
    ) -> List[Dict]:
        """
        Upload multiple photos for a quote
        
        Args:
            files: List of dicts with 'content', 'filename', 'content_type'
            quote_id: Quote ID for organization
        
        Returns:
            List of upload results
        """
        results = []
        
        for file_data in files:
            try:
                result = await self.upload_photo(
                    file_content=file_data['content'],
                    filename=file_data['filename'],
                    quote_id=quote_id,
                    content_type=file_data.get('content_type', 'image/jpeg')
                )
                results.append(result)
            except Exception as error:
                logger.error(f"Failed to upload {file_data['filename']}: {error}")
                results.append({
                    'filename': file_data['filename'],
                    'error': str(error),
                    'success': False
                })
        
        return results
    
    async def get_quote_photos(self, quote_id: str) -> List[Dict]:
        """
        Get all photos for a specific quote
        
        Args:
            quote_id: Quote ID to search for
            
        Returns:
            List of photo information
        """
        try:
            service = self.get_service()
            
            # Search for files with quote_id in name
            query = f"name contains '{quote_id}_'"
            
            results = service.files().list(
                q=query,
                fields='files(id,name,webViewLink,webContentLink,createdTime)',
                pageSize=50
            ).execute()
            
            files = results.get('files', [])
            
            photos = []
            for file in files:
                photos.append({
                    'file_id': file['id'],
                    'filename': file['name'],
                    'share_url': file['webViewLink'],
                    'direct_url': file.get('webContentLink', ''),
                    'created_time': file['createdTime']
                })
            
            return photos
            
        except HttpError as error:
            logger.error(f"Google Drive API error retrieving photos: {error}")
            return []
        except Exception as error:
            logger.error(f"Unexpected error retrieving photos: {error}")
            return []
    
    def validate_photo_file(self, content: bytes, filename: str) -> bool:
        """
        Validate that the uploaded file is a valid JPEG image
        
        Args:
            content: File content bytes
            filename: Original filename
            
        Returns:
            True if valid, False otherwise
        """
        # Check file extension
        if not filename.lower().endswith(('.jpg', '.jpeg')):
            return False
        
        # Check file size (max 10MB)
        if len(content) > 10 * 1024 * 1024:
            return False
        
        # Check JPEG magic number
        if len(content) < 10:
            return False
        
        # JPEG files start with FFD8
        if content[:2] != b'\xff\xd8':
            return False
        
        return True

# Global service instance - lazy initialization
google_drive_service = None

def get_google_drive_service():
    """Get or create Google Drive service instance"""
    global google_drive_service
    if google_drive_service is None:
        google_drive_service = GoogleDriveService()
    return google_drive_service