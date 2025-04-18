import os
import json
import logging
from google.oauth2 import service_account
from google.cloud import storage

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# GCS environment variables
GCP_BUCKET_NAME = os.getenv('GCP_BUCKET_NAME')
STORAGE_PATH = "/tmp/"
gcs_client = None

def validate_gcp_environment():
    """Validate GCP environment variables at startup and log helpful messages."""
    issues = []
    
    # Check GCP_BUCKET_NAME
    if not GCP_BUCKET_NAME:
        issues.append("GCP_BUCKET_NAME environment variable is not set")
        logger.warning("GCP_BUCKET_NAME environment variable is not set")
    
    # Check GCP_SA_CREDENTIALS
    creds = os.getenv('GCP_SA_CREDENTIALS')
    if not creds:
        issues.append("GCP_SA_CREDENTIALS environment variable is not set")
        logger.warning("GCP_SA_CREDENTIALS environment variable is not set")
    elif len(creds) < 100:  # A valid service account JSON should be larger than this
        issues.append("GCP_SA_CREDENTIALS appears to be too short to be valid")
        logger.warning("GCP_SA_CREDENTIALS appears to be too short to be valid")
    
    if issues:
        logger.warning("GCP environment validation found issues: %s", issues)
        return False
    
    logger.info("GCP environment validation passed")
    return True

def initialize_gcp_client():
    """Initialize Google Cloud Storage client with service account credentials."""
    GCP_SA_CREDENTIALS = os.getenv('GCP_SA_CREDENTIALS')

    if not GCP_SA_CREDENTIALS:
        logger.warning("GCP credentials not found. Skipping GCS client initialization.")
        return None  # Skip client initialization if credentials are missing

    # Define the required scopes for Google Cloud Storage
    GCS_SCOPES = ['https://www.googleapis.com/auth/devstorage.full_control']

    try:
        # First, try to load the credentials directly as a JSON object
        try:
            # Check if the credentials are already a valid JSON string
            credentials_info = json.loads(GCP_SA_CREDENTIALS)
            logger.info("Successfully parsed GCP credentials as JSON")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse GCP credentials as JSON: {e}")
            
            # Try to write credentials to a temporary file and load from there
            # This approach handles many formatting issues
            import tempfile
            
            with tempfile.NamedTemporaryFile(mode='w+', delete=False) as temp:
                temp_path = temp.name
                temp.write(GCP_SA_CREDENTIALS)
                temp.flush()
            
            try:
                logger.info(f"Attempting to load credentials from temp file: {temp_path}")
                gcs_credentials = service_account.Credentials.from_service_account_file(
                    temp_path,
                    scopes=GCS_SCOPES
                )
                # If we get here, we successfully loaded credentials from file
                os.unlink(temp_path)  # Clean up temp file
                return storage.Client(credentials=gcs_credentials)
            except Exception as file_error:
                logger.error(f"Failed to load credentials from temp file: {file_error}")
                os.unlink(temp_path)  # Clean up temp file
                
                # Last resort: try to fix common JSON formatting issues
                logger.warning("Attempting to fix JSON format...")
                cleaned_json = GCP_SA_CREDENTIALS.strip()
                
                # If it starts with a quote and ends with a quote, try removing them
                if (cleaned_json.startswith('"') and cleaned_json.endswith('"')) or \
                   (cleaned_json.startswith("'") and cleaned_json.endswith("'")):
                    cleaned_json = cleaned_json[1:-1]
                
                # Replace escaped quotes with actual quotes
                cleaned_json = cleaned_json.replace('\\"', '"')
                
                try:
                    credentials_info = json.loads(cleaned_json)
                    logger.info("Successfully parsed cleaned GCP credentials")
                except Exception:
                    logger.error("All attempts to parse GCP credentials failed")
                    logger.error("Please check your GCP_SA_CREDENTIALS environment variable")
                    return None
        
        # Create credentials from the parsed info
        gcs_credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=GCS_SCOPES
        )
        client = storage.Client(credentials=gcs_credentials)
        
        # Verify we can access the bucket
        if GCP_BUCKET_NAME:
            try:
                bucket = client.bucket(GCP_BUCKET_NAME)
                # Try a simple operation to verify access
                bucket.exists()
                logger.info(f"Successfully verified access to bucket: {GCP_BUCKET_NAME}")
            except Exception as bucket_error:
                logger.error(f"Failed to access bucket {GCP_BUCKET_NAME}: {bucket_error}")
                # Continue anyway, as the bucket might be created later
        
        return client
    except Exception as e:
        logger.error(f"Failed to initialize GCS client: {e}")
        # Log more details about the credential format to help debugging
        if GCP_SA_CREDENTIALS:
            credential_type = type(GCP_SA_CREDENTIALS).__name__
            credential_length = len(GCP_SA_CREDENTIALS)
            credential_start = GCP_SA_CREDENTIALS[:10].replace('\n', '').replace('\r', '') + "..."
            logger.error(f"Credential info - Type: {credential_type}, Length: {credential_length}, Start: {credential_start}")
        return None

# Validate environment at module load time
validate_gcp_environment()

# Initialize the GCS client
gcs_client = initialize_gcp_client()

def upload_to_gcs(file_path, bucket_name=GCP_BUCKET_NAME):
    """
    Upload a file to Google Cloud Storage.
    
    Args:
        file_path: Local path to the file to upload
        bucket_name: GCS bucket name
        
    Returns:
        Public URL to the uploaded file
    """
    if not gcs_client:
        error_msg = "GCS client is not initialized. Skipping file upload."
        logger.error(error_msg)
        raise ValueError(error_msg)

    if not bucket_name:
        error_msg = "Bucket name is not provided. Skipping file upload."
        logger.error(error_msg)
        raise ValueError(error_msg)

    try:
        logger.info(f"Uploading file to Google Cloud Storage: {file_path}")
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(os.path.basename(file_path))
        blob.upload_from_filename(file_path)
        logger.info(f"File uploaded successfully to GCS: {blob.public_url}")
        return blob.public_url
    except Exception as e:
        logger.error(f"Failed to upload file to GCS: {e}")
        raise

def upload_to_gcs_with_path(file_path, bucket_name=GCP_BUCKET_NAME, destination_path=None):
    """
    Upload a file to Google Cloud Storage with a custom destination path.
    
    Args:
        file_path: Local path to the file to upload
        bucket_name: GCS bucket name
        destination_path: Custom path in the bucket (e.g., 'thumbnails/image.jpg')
        
    Returns:
        Public URL to the uploaded file
    """
    if not gcs_client:
        raise ValueError("GCS client is not initialized. Skipping file upload.")

    try:
        logger.info(f"Uploading file to Google Cloud Storage with custom path: {file_path} -> {destination_path}")
        bucket = gcs_client.bucket(bucket_name)
        
        # Use destination_path if provided, otherwise use the basename
        blob_path = destination_path if destination_path else os.path.basename(file_path)
        blob = bucket.blob(blob_path)
        
        blob.upload_from_filename(file_path)
        logger.info(f"File uploaded successfully to GCS: {blob.public_url}")
        return blob.public_url
    except Exception as e:
        logger.error(f"Error uploading file to GCS with custom path: {e}")
        raise
