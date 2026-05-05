import io
import json
import logging
import mimetypes
import os
import re
from datetime import datetime
from typing import Dict, List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseUpload

logger = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


class GoogleDriveService:
    """Google Drive helper used by the LDA app.

    This uses a Google service account so the backend can create folders and
    upload worker photos into the shared job folder structure.

    Supported environment variables:
      - GOOGLE_SERVICE_ACCOUNT_JSON: full JSON service account key as one env var
      - GOOGLE_SERVICE_ACCOUNT_FILE: path to the JSON key file
      - GOOGLE_APPLICATION_CREDENTIALS: path to the JSON key file
    """

    def __init__(self):
        self.service = None

    def _load_credentials(self):
        raw_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
        service_account_file = (
            os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
            or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        )

        if raw_json:
            try:
                info = json.loads(raw_json)
            except json.JSONDecodeError:
                # Some hosting dashboards store new lines escaped inside env vars.
                info = json.loads(raw_json.replace("\\n", "\n"))
            return service_account.Credentials.from_service_account_info(
                info,
                scopes=DRIVE_SCOPES,
            )

        if service_account_file:
            return service_account.Credentials.from_service_account_file(
                service_account_file,
                scopes=DRIVE_SCOPES,
            )

        raise ValueError(
            "Google Drive service account credentials are missing. Set "
            "GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE."
        )

    def get_service(self):
        if self.service is None:
            credentials = self._load_credentials()
            self.service = build("drive", "v3", credentials=credentials, cache_discovery=False)
            logger.info("Google Drive service initialised")
        return self.service

    @staticmethod
    def extract_folder_id(value: Optional[str]) -> Optional[str]:
        """Accept a raw folder ID or a Google Drive folder URL and return the ID."""
        if not value:
            return None

        value = str(value).strip()
        if not value:
            return None

        # Already looks like a Drive ID.
        if re.match(r"^[A-Za-z0-9_-]{20,}$", value):
            return value

        patterns = [
            r"/folders/([A-Za-z0-9_-]+)",
            r"[?&]id=([A-Za-z0-9_-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, value)
            if match:
                return match.group(1)
        return None

    @staticmethod
    def safe_filename(filename: str) -> str:
        filename = os.path.basename(filename or "photo.jpg")
        filename = re.sub(r"[^A-Za-z0-9._ -]", "_", filename)
        filename = re.sub(r"\s+", " ", filename).strip()
        return filename or "photo.jpg"

    def find_child_folder(self, parent_id: str, folder_name: str) -> Optional[Dict]:
        service = self.get_service()
        escaped_name = folder_name.replace("'", "\\'")
        query = (
            f"'{parent_id}' in parents and "
            "mimeType='application/vnd.google-apps.folder' and "
            f"name='{escaped_name}' and trashed=false"
        )
        result = service.files().list(
            q=query,
            spaces="drive",
            fields="files(id,name,webViewLink)",
            pageSize=10,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        files = result.get("files", [])
        return files[0] if files else None

    def create_child_folder(self, parent_id: str, folder_name: str) -> Dict:
        service = self.get_service()
        metadata = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent_id],
        }
        return service.files().create(
            body=metadata,
            fields="id,name,webViewLink",
            supportsAllDrives=True,
        ).execute()

    def get_or_create_child_folder(self, parent_id: str, folder_name: str) -> Dict:
        existing = self.find_child_folder(parent_id, folder_name)
        if existing:
            return existing
        return self.create_child_folder(parent_id, folder_name)

    def get_or_create_nested_folder(self, parent_id: str, folder_names: List[str]) -> Dict:
        current_parent = parent_id
        current_folder = None
        for folder_name in folder_names:
            current_folder = self.get_or_create_child_folder(current_parent, folder_name)
            current_parent = current_folder["id"]
        return current_folder

    def get_post_works_images_folder(self, job_folder_id: str) -> Dict:
        return self.get_or_create_nested_folder(
            job_folder_id,
            [
                "007: Site Deliverables",
                "04: Site Images Pre & Post",
                "02: Post Works Images",
            ],
        )

    def upload_file_to_folder(
        self,
        *,
        folder_id: str,
        file_content: bytes,
        filename: str,
        content_type: Optional[str] = None,
        description: str = "",
    ) -> Dict:
        service = self.get_service()
        clean_filename = self.safe_filename(filename)
        content_type = content_type or mimetypes.guess_type(clean_filename)[0] or "application/octet-stream"

        metadata = {
            "name": clean_filename,
            "parents": [folder_id],
            "description": description,
        }
        media = MediaIoBaseUpload(
            io.BytesIO(file_content),
            mimetype=content_type,
            resumable=True,
        )

        uploaded = service.files().create(
            body=metadata,
            media_body=media,
            fields="id,name,webViewLink,webContentLink,mimeType,createdTime",
            supportsAllDrives=True,
        ).execute()

        return {
            "file_id": uploaded.get("id"),
            "filename": uploaded.get("name"),
            "mime_type": uploaded.get("mimeType"),
            "share_url": uploaded.get("webViewLink"),
            "direct_url": uploaded.get("webContentLink", ""),
            "created_time": uploaded.get("createdTime"),
        }

    def upload_post_work_image(
        self,
        *,
        job_folder_id: str,
        file_content: bytes,
        filename: str,
        content_type: Optional[str] = None,
        worker_name: str = "",
        job_name: str = "",
    ) -> Dict:
        target_folder = self.get_post_works_images_folder(job_folder_id)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        clean_filename = self.safe_filename(filename)
        drive_filename = f"POST_{timestamp}_{clean_filename}"

        description_bits = ["LDA worker post works image"]
        if job_name:
            description_bits.append(f"Job: {job_name}")
        if worker_name:
            description_bits.append(f"Uploaded by: {worker_name}")

        uploaded = self.upload_file_to_folder(
            folder_id=target_folder["id"],
            file_content=file_content,
            filename=drive_filename,
            content_type=content_type,
            description=" | ".join(description_bits),
        )
        uploaded["folder_id"] = target_folder["id"]
        uploaded["folder_name"] = target_folder.get("name")
        uploaded["folder_link"] = target_folder.get("webViewLink")
        return uploaded


def get_google_drive_service() -> Optional[GoogleDriveService]:
    try:
        return GoogleDriveService()
    except Exception as exc:
        logger.error("Google Drive service unavailable: %s", exc)
        return None
