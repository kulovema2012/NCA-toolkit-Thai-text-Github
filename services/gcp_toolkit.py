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

def initialize_gcp_client():
    GCP_SA_CREDENTIALS = os.getenv('GCP_SA_CREDENTIALS')

    if not GCP_SA_CREDENTIALS:
        logger.warning("GCP credentials not found. Skipping GCS client initialization.")
        return None  # Skip client initialization if credentials are missing

    # Define the required scopes for Google Cloud Storage
    GCS_SCOPES = ['https://www.googleapis.com/auth/devstorage.full_control']

    try:
        # First try parsing as JSON directly
        try:
            credentials_info = json.loads(GCP_SA_CREDENTIALS)
        except json.JSONDecodeError as json_err:
            # If that fails, try fixing common issues with the JSON string
            logger.warning(f"Initial JSON parsing failed: {json_err}. Attempting to fix JSON format...")
            
            # Try to clean up the JSON string - handle potential escaping issues
            # This handles cases where the JSON might have been double-escaped or has extra quotes
            cleaned_json = GCP_SA_CREDENTIALS.strip()
            
            # If it starts with a quote and ends with a quote, try removing them
            if (cleaned_json.startswith('"') and cleaned_json.endswith('"')) or \
               (cleaned_json.startswith("'") and cleaned_json.endswith("'")):
                cleaned_json = cleaned_json[1:-1]
            
            # Replace escaped quotes with actual quotes
            cleaned_json = cleaned_json.replace('\\"', '"')
            
            # Log the first few characters for debugging (avoid logging the entire credential)
            safe_prefix = cleaned_json[:20] + "..." if len(cleaned_json) > 20 else cleaned_json
            logger.info(f"Attempting to parse cleaned JSON: {safe_prefix}")
            
            try:
                credentials_info = json.loads(cleaned_json)
            except json.JSONDecodeError:
                # If still failing, try one more approach - sometimes the JSON is stringified multiple times
                logger.warning("Second attempt failed. Trying alternative approach...")
                try:
                    # Try to handle double-stringified JSON
                    if cleaned_json.startswith('\\"{') or cleaned_json.startswith('"{'):
                        import re
                        # Use regex to extract the actual JSON object
                        match = re.search(r'({.*})', cleaned_json)
                        if match:
                            credentials_info = json.loads(match.group(1))
                        else:
                            raise ValueError("Could not extract valid JSON from credential string")
                    else:
                        raise ValueError("JSON format could not be automatically fixed")
                except Exception as e:
                    logger.error(f"All JSON parsing attempts failed: {e}")
                    logger.error("Please check the format of your GCP_SA_CREDENTIALS environment variable")
                    logger.error("It should be a valid JSON service account key without extra quotes or escaping")
                    return None
        
        # Create credentials from the parsed info
        gcs_credentials = service_account.Credentials.from_service_account_info(
            credentials_info,
            scopes=GCS_SCOPES
        )
        return storage.Client(credentials=gcs_credentials)
    except Exception as e:
        logger.error(f"Failed to initialize GCS client: {e}")
        # Log more details about the credential format to help debugging
        if GCP_SA_CREDENTIALS:
            credential_type = type(GCP_SA_CREDENTIALS).__name__
            credential_length = len(GCP_SA_CREDENTIALS)
            credential_start = GCP_SA_CREDENTIALS[:10].replace('\n', '').replace('\r', '') + "..."
            logger.error(f"Credential info - Type: {credential_type}, Length: {credential_length}, Start: {credential_start}")
        return None

# Initialize the GCS client
gcs_client = initialize_gcp_client()

def upload_to_gcs(file_path, bucket_name=GCP_BUCKET_NAME):
    if not gcs_client:
        raise ValueError("GCS client is not initialized. Skipping file upload.")

    try:
        logger.info(f"Uploading file to Google Cloud Storage: {file_path}")
        bucket = gcs_client.bucket(bucket_name)
        blob = bucket.blob(os.path.basename(file_path))
        blob.upload_from_filename(file_path)
        logger.info(f"File uploaded successfully to GCS: {blob.public_url}")
        return blob.public_url
    except Exception as e:
        logger.error(f"Error uploading file to GCS: {e}")
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
