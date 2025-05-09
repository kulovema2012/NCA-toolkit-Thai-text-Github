"""
Storage utility module for handling file storage with MinIO and Google Cloud Storage.
Provides a unified interface for storing and retrieving files with automatic fallback.
"""

import os
import uuid
import logging
import datetime
from typing import Optional, Union, BinaryIO, Tuple
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Storage configuration
DEFAULT_STORAGE = "minio"  # Force MinIO as default
FALLBACK_STORAGE = "none"  # Disable fallback to avoid GCP

# MinIO configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_SECURE = os.getenv("MINIO_SECURE", "true").lower() == "true"
MINIO_BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "")

# Google Cloud Storage configuration (kept for future use)
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
GCP_BUCKET_NAME = os.getenv("GCP_BUCKET_NAME", "")

# Initialize storage clients
minio_client = None
gcs_client = None

def init_minio_client():
    """Initialize MinIO client if credentials are available."""
    global minio_client
    if not all([MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET_NAME]):
        logger.warning("MinIO credentials not fully configured. MinIO storage will not be available.")
        logger.warning(f"Missing credentials: ENDPOINT={not MINIO_ENDPOINT}, ACCESS_KEY={not MINIO_ACCESS_KEY}, SECRET_KEY={not MINIO_SECRET_KEY}, BUCKET={not MINIO_BUCKET_NAME}")
        return False
    
    try:
        from minio import Minio
        # Log the raw endpoint for debugging
        logger.info(f"Initializing MinIO client with raw endpoint: {MINIO_ENDPOINT}")
        
        # Extract the endpoint without protocol
        endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
        
        # Special handling for Railway internal endpoints
        is_railway_internal = "railway.internal" in endpoint
        
        # Remove any port specification if present
        if ":" in endpoint:
            endpoint_parts = endpoint.split(":")
            endpoint = endpoint_parts[0]
            # If it's a Railway internal endpoint, use port 9000
            if is_railway_internal:
                port = 9000
                logger.info(f"Detected Railway internal endpoint, using port {port}")
            else:
                # Use the specified port or default to 443 for secure, 80 for non-secure
                port = int(endpoint_parts[1]) if len(endpoint_parts) > 1 else (443 if MINIO_SECURE else 80)
        else:
            port = 443 if MINIO_SECURE else 80
            
        logger.info(f"Connecting to MinIO at {endpoint}:{port} (secure={MINIO_SECURE})")
        
        # For Railway internal endpoints, we need to ensure we're using the right configuration
        if is_railway_internal:
            logger.info("Using Railway internal MinIO configuration")
            minio_client = Minio(
                endpoint,
                access_key=MINIO_ACCESS_KEY,
                secret_key=MINIO_SECRET_KEY,
                secure=False,  # Railway internal endpoints use HTTP
                port=port
            )
        else:
            minio_client = Minio(
                endpoint,
                access_key=MINIO_ACCESS_KEY,
                secret_key=MINIO_SECRET_KEY,
                secure=MINIO_SECURE,
                port=port
            )
        
        # Check if bucket exists, create if it doesn't
        if not minio_client.bucket_exists(MINIO_BUCKET_NAME):
            minio_client.make_bucket(MINIO_BUCKET_NAME)
            # Set bucket policy to public
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": "*"},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{MINIO_BUCKET_NAME}/*"]
                    }
                ]
            }
            import json
            minio_client.set_bucket_policy(MINIO_BUCKET_NAME, json.dumps(policy))
            
        logger.info(f"MinIO client initialized with bucket: {MINIO_BUCKET_NAME}")
        return True
    except ImportError:
        logger.error("MinIO Python client not installed. Run 'pip install minio'")
        return False
    except Exception as e:
        logger.error(f"Failed to initialize MinIO client: {str(e)}")
        return False

def init_gcs_client():
    """Initialize Google Cloud Storage client if credentials are available."""
    global gcs_client
    if not all([GCP_PROJECT_ID, GCP_BUCKET_NAME]):
        logger.warning("GCP credentials not fully configured. GCS storage will not be available.")
        return False
    
    try:
        from google.cloud import storage
        gcs_client = storage.Client(project=GCP_PROJECT_ID)
        
        # Check if bucket exists
        try:
            gcs_client.get_bucket(GCP_BUCKET_NAME)
            logger.info(f"GCS client initialized with bucket: {GCP_BUCKET_NAME}")
            return True
        except Exception:
            logger.error(f"GCS bucket {GCP_BUCKET_NAME} does not exist or is not accessible")
            return False
    except ImportError:
        logger.error("Google Cloud Storage client not installed. Run 'pip install google-cloud-storage'")
        return False
    except Exception as e:
        logger.error(f"Failed to initialize GCS client: {str(e)}")
        return False

# Initialize clients based on configuration
if DEFAULT_STORAGE == "minio" or FALLBACK_STORAGE == "minio":
    minio_available = init_minio_client()
else:
    minio_available = False

if DEFAULT_STORAGE == "gcp" or FALLBACK_STORAGE == "gcp":
    gcs_available = init_gcs_client()
else:
    gcs_available = False

def upload_file(
    file_data: Union[bytes, BinaryIO, str],
    object_name: Optional[str] = None,
    content_type: str = "application/octet-stream",
    folder: str = "",
    make_public: bool = True
) -> Tuple[bool, str, str]:
    """
    Upload a file to the configured storage service.
    
    Args:
        file_data: File data as bytes, file-like object, or path to file
        object_name: Name to give the object in storage (if None, generates a UUID)
        content_type: MIME type of the file
        folder: Optional folder path within the bucket
        make_public: Whether to make the file publicly accessible
        
    Returns:
        Tuple of (success, url, storage_used)
    """
    if object_name is None:
        object_name = str(uuid.uuid4())
    
    if folder:
        if not folder.endswith('/'):
            folder += '/'
        object_name = f"{folder}{object_name}"
    
    # Determine which storage to use
    storage_used = None
    success = False
    url = ""
    
    # Try primary storage
    if DEFAULT_STORAGE == "minio" and minio_available:
        success, url = _upload_to_minio(file_data, object_name, content_type)
        storage_used = "minio"
    elif DEFAULT_STORAGE == "gcp" and gcs_available:
        success, url = _upload_to_gcs(file_data, object_name, content_type, make_public)
        storage_used = "gcp"
    
    # If primary storage failed and fallback is configured, try fallback
    if not success and FALLBACK_STORAGE != "none":
        if FALLBACK_STORAGE == "minio" and minio_available:
            success, url = _upload_to_minio(file_data, object_name, content_type)
            storage_used = "minio"
        elif FALLBACK_STORAGE == "gcp" and gcs_available:
            success, url = _upload_to_gcs(file_data, object_name, content_type, make_public)
            storage_used = "gcp"
    
    if not success:
        logger.error("Failed to upload file to any configured storage service")
    
    return success, url, storage_used

def _upload_to_minio(
    file_data: Union[bytes, BinaryIO, str],
    object_name: str,
    content_type: str
) -> Tuple[bool, str]:
    """Upload a file to MinIO storage."""
    try:
        # Log MinIO client state with more details
        logger.info(f"MinIO upload attempt - Details:")
        logger.info(f"  - Endpoint: {MINIO_ENDPOINT}")
        logger.info(f"  - Bucket: {MINIO_BUCKET_NAME}")
        logger.info(f"  - Secure: {MINIO_SECURE}")
        logger.info(f"  - Object name: {object_name}")
        logger.info(f"  - Content type: {content_type}")
        
        # Ensure MinIO client is initialized
        if minio_client is None:
            logger.error("MinIO client is not initialized - check credentials and endpoint")
            return False, ""
            
        # Convert file_data to appropriate format
        if isinstance(file_data, str) and os.path.isfile(file_data):
            # It's a file path
            logger.debug(f"Uploading file from path: {file_data}")
            minio_client.fput_object(
                MINIO_BUCKET_NAME, 
                object_name, 
                file_data,
                content_type=content_type
            )
        elif isinstance(file_data, bytes):
            # It's bytes data
            logger.debug(f"Uploading {len(file_data)} bytes of data")
            minio_client.put_object(
                MINIO_BUCKET_NAME,
                object_name,
                BytesIO(file_data),
                length=len(file_data),
                content_type=content_type
            )
        else:
            # Assume it's a file-like object
            logger.debug("Uploading from file-like object")
            file_size = file_data.seek(0, 2)
            file_data.seek(0)
            minio_client.put_object(
                MINIO_BUCKET_NAME,
                object_name,
                file_data,
                length=file_size,
                content_type=content_type
            )
        
        # Generate public URL
        # Extract the domain from the endpoint
        endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
        protocol = "https" if MINIO_SECURE else "http"
        
        # For Railway internal endpoints, use the public URL format
        if "railway.internal" in endpoint:
            # Use the Railway public URL without port specification for public access
            url = f"https://bucket-production-dce5.up.railway.app/{MINIO_BUCKET_NAME}/{object_name}"
            
            # For internal operations, continue using the internal endpoint
            logger.debug(f"Using Railway internal endpoint for MinIO: {MINIO_ENDPOINT}")
        else:
            url = f"{protocol}://{endpoint}/{MINIO_BUCKET_NAME}/{object_name}"
        
        logger.info(f"Successfully uploaded to MinIO: {object_name}")
        return True, url
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        logger.error(f"MinIO upload failed with error: {str(e)}")
        logger.error(f"Error details: {error_trace}")
        
        # Check for specific error types
        if "ConnectionError" in str(e) or "Connection refused" in str(e):
            logger.error("Connection error - Check if MinIO service is running and accessible")
        elif "AccessDenied" in str(e) or "InvalidAccessKeyId" in str(e):
            logger.error("Authentication error - Check your MinIO credentials")
        elif "NoSuchBucket" in str(e):
            logger.error(f"Bucket '{MINIO_BUCKET_NAME}' does not exist - Check bucket name or try to create it")
        
        return False, ""

def _upload_to_gcs(
    file_data: Union[bytes, BinaryIO, str],
    object_name: str,
    content_type: str,
    make_public: bool
) -> Tuple[bool, str]:
    """Upload a file to Google Cloud Storage."""
    try:
        bucket = gcs_client.bucket(GCP_BUCKET_NAME)
        blob = bucket.blob(object_name)
        
        # Set content type
        blob.content_type = content_type
        
        # Upload the file
        if isinstance(file_data, str) and os.path.isfile(file_data):
            # It's a file path
            blob.upload_from_filename(file_data)
        elif isinstance(file_data, bytes):
            # It's bytes data
            blob.upload_from_string(file_data)
        else:
            # Assume it's a file-like object
            blob.upload_from_file(file_data)
        
        # Make public if requested
        if make_public:
            blob.make_public()
            url = blob.public_url
        else:
            url = blob.generate_signed_url(
                version="v4",
                expiration=datetime.timedelta(days=7),
                method="GET"
            )
        
        logger.info(f"Successfully uploaded to GCS: {object_name}")
        return True, url
    except Exception as e:
        logger.error(f"GCS upload failed: {str(e)}")
        return False, ""

def delete_file(object_name: str, storage: Optional[str] = None) -> bool:
    """
    Delete a file from storage.
    
    Args:
        object_name: Name of the object to delete
        storage: Which storage to use ('minio', 'gcp', or None for default)
        
    Returns:
        True if deletion was successful, False otherwise
    """
    if storage is None:
        storage = DEFAULT_STORAGE
    
    try:
        if storage == "minio" and minio_available:
            minio_client.remove_object(MINIO_BUCKET_NAME, object_name)
            logger.info(f"Successfully deleted from MinIO: {object_name}")
            return True
        elif storage == "gcp" and gcs_available:
            bucket = gcs_client.bucket(GCP_BUCKET_NAME)
            blob = bucket.blob(object_name)
            blob.delete()
            logger.info(f"Successfully deleted from GCS: {object_name}")
            return True
        else:
            logger.error(f"Cannot delete file: storage '{storage}' not available")
            return False
    except Exception as e:
        logger.error(f"Failed to delete file {object_name}: {str(e)}")
        return False

def get_file_url(object_name: str, storage: Optional[str] = None, make_public: bool = True) -> str:
    """
    Get the URL for a file in storage.
    
    Args:
        object_name: Name of the object
        storage: Which storage to use ('minio', 'gcp', or None for default)
        make_public: Whether to return a public URL (GCS only)
        
    Returns:
        URL to the file or empty string if not found
    """
    if storage is None:
        storage = DEFAULT_STORAGE
    
    try:
        if storage == "minio" and minio_available:
            # Extract the domain from the endpoint
            endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
            protocol = "https" if MINIO_SECURE else "http"
            
            # For Railway internal endpoints, use the public URL format
            if "railway.internal" in endpoint:
                return f"https://bucket-production-dce5.up.railway.app/{MINIO_BUCKET_NAME}/{object_name}"
            else:
                return f"{protocol}://{endpoint}/{MINIO_BUCKET_NAME}/{object_name}"
        
        elif storage == "gcp" and gcs_available:
            bucket = gcs_client.bucket(GCP_BUCKET_NAME)
            blob = bucket.blob(object_name)
            
            if make_public:
                # Ensure the blob is public
                blob.make_public()
                return blob.public_url
            else:
                # Generate a signed URL
                return blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(days=7),
                    method="GET"
                )
        else:
            logger.error(f"Cannot get file URL: storage '{storage}' not available")
            return ""
    except Exception as e:
        logger.error(f"Failed to get URL for file {object_name}: {str(e)}")
        return ""
