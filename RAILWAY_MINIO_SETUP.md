# Railway Deployment with MinIO Storage Integration

This guide will walk you through setting up a CI/CD pipeline that deploys your application to Railway and configures MinIO for object storage, replacing Google Cloud Storage.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Setting Up MinIO on Railway](#setting-up-minio-on-railway)
3. [Configuring Your Application for MinIO](#configuring-your-application-for-minio)
4. [Setting Up GitHub Secrets](#setting-up-github-secrets)
5. [Creating the GitHub Actions Workflow](#creating-the-github-actions-workflow)
6. [Testing the Integration](#testing-the-integration)
7. [Troubleshooting](#troubleshooting)

## Prerequisites

- A GitHub repository containing your application code
- A Railway account (https://railway.app)
- Basic understanding of CI/CD concepts

## Setting Up MinIO on Railway

Railway provides MinIO as a built-in service that you can easily add to your project. You have two options:

### Option 1: Same-Project MinIO Setup (Recommended)

1. Log in to your Railway dashboard at https://railway.app
2. Select your project or create a new one
3. Click "New" and select "Database"
4. Choose "MinIO" from the list of available services
5. Configure the service settings (or keep the defaults)
6. Click "Add" to create the MinIO service

Once created, Railway will provide you with the following environment variables:
- `MINIO_ENDPOINT` (typically `http://bucket.railway.internal:9000`)
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_BUCKET_NAME`

### Option 2: Cross-Project MinIO Setup

If you want to keep your MinIO service in a separate project:

1. Create or use an existing MinIO service in a different Railway project
2. Get the public URL of your MinIO service (looks like `https://bucket-production-xxxx.up.railway.app`)
3. Copy the access key and secret key from the MinIO service
4. In your main project, set the following environment variables:
   - `MINIO_ENDPOINT` = the public URL of your MinIO service
   - `MINIO_ACCESS_KEY` = the access key from the MinIO service
   - `MINIO_SECRET_KEY` = the secret key from the MinIO service
   - `MINIO_BUCKET_NAME` = your bucket name
   - `MINIO_SECURE` = `true` (since you're using HTTPS)

## Configuring Your Application for MinIO

### 1. Create a Storage Utility Module

Create a file named `storage_utils.py` in your project with the following content:

```python
"""
Storage utility module for handling file storage with MinIO.
Provides a unified interface for storing and retrieving files.
"""

import os
import uuid
import logging
from typing import Optional, Union, BinaryIO, Tuple
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Storage configuration
DEFAULT_STORAGE = os.getenv("DEFAULT_STORAGE", "minio")

# MinIO configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "")
MINIO_SECURE = os.getenv("MINIO_SECURE", "true").lower() == "true"
MINIO_BUCKET_NAME = os.getenv("MINIO_BUCKET_NAME", "")

# Initialize storage client
minio_client = None

def init_minio_client():
    """Initialize MinIO client if credentials are available."""
    global minio_client
    if not all([MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY, MINIO_BUCKET_NAME]):
        logger.warning("MinIO credentials not fully configured. MinIO storage will not be available.")
        return False
    
    try:
        from minio import Minio
        # Extract the endpoint without protocol
        endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
        # Remove any port specification if present
        if ":" in endpoint:
            endpoint_parts = endpoint.split(":")
            endpoint = endpoint_parts[0]
            # If it's a Railway internal endpoint, use port 9000
            if "railway.internal" in endpoint:
                port = 9000
            else:
                # Use the specified port or default to 443 for secure, 80 for non-secure
                port = int(endpoint_parts[1]) if len(endpoint_parts) > 1 else (443 if MINIO_SECURE else 80)
        else:
            port = 443 if MINIO_SECURE else 80
            
        logger.debug(f"Connecting to MinIO at {endpoint}:{port} (secure={MINIO_SECURE})")
        
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

# Initialize client based on configuration
if DEFAULT_STORAGE == "minio":
    minio_available = init_minio_client()
else:
    minio_available = False

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
    
    # Try MinIO storage
    if minio_available:
        success, url = _upload_to_minio(file_data, object_name, content_type)
        storage_used = "minio"
    
    if not success:
        logger.error("Failed to upload file to MinIO storage")
    
    return success, url, storage_used

def _upload_to_minio(
    file_data: Union[bytes, BinaryIO, str],
    object_name: str,
    content_type: str
) -> Tuple[bool, str]:
    """Upload a file to MinIO storage."""
    try:
        # Log MinIO client state
        logger.debug(f"MinIO client: endpoint={MINIO_ENDPOINT}, bucket={MINIO_BUCKET_NAME}, secure={MINIO_SECURE}")
        
        # Ensure MinIO client is initialized
        if minio_client is None:
            logger.error("MinIO client is not initialized")
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
        logger.error(f"MinIO upload failed: {str(e)}")
        return False, ""

def get_file_url(object_name: str, make_public: bool = True) -> str:
    """
    Get the URL for a file in storage.
    
    Args:
        object_name: Name of the object
        make_public: Whether to return a public URL
        
    Returns:
        URL to the file or empty string if not found
    """
    if minio_available:
        # Extract the domain from the endpoint
        endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
        protocol = "https" if MINIO_SECURE else "http"
        
        # For Railway internal endpoints, use the public URL format
        if "railway.internal" in endpoint:
            url = f"https://bucket-production-dce5.up.railway.app/{MINIO_BUCKET_NAME}/{object_name}"
        else:
            url = f"{protocol}://{endpoint}/{MINIO_BUCKET_NAME}/{object_name}"
        
        return url
    
    return ""
```

### 2. Update Your Requirements File

Make sure your `requirements.txt` file includes the MinIO client:

```
minio>=7.0.0
python-dotenv>=0.19.0
```

### 3. Create a Railway Configuration File

Create a `railway.json` file in your project root:

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "./Dockerfile"
  },
  "deploy": {
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10,
    "startCommand": "python run_gunicorn.sh"
  }
}
```

## Setting Up GitHub Secrets

To securely store your Railway and MinIO credentials, add them as GitHub secrets:

1. Go to your GitHub repository
2. Click on "Settings" > "Secrets and variables" > "Actions"
3. Click "New repository secret"
4. Add the following secrets:
   - `RAILWAY_TOKEN`: Your Railway API token (get this from Railway dashboard > Account Settings > Tokens)
   - `RAILWAY_PROJECT_ID`: Your Railway project ID (found in the URL of your project page)
   - `MINIO_ENDPOINT`: The MinIO endpoint (from Railway)
   - `MINIO_ACCESS_KEY`: Your MinIO access key
   - `MINIO_SECRET_KEY`: Your MinIO secret key
   - `MINIO_BUCKET_NAME`: Your MinIO bucket name

## Creating the GitHub Actions Workflow

### Option 1: Using GitHub Actions with Railway CLI

Create a file at `.github/workflows/railway-deploy.yml`:

```yaml
name: Deploy to Railway

on:
  push:
    branches:
      - main
  workflow_dispatch:

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v3
      
      - name: Install Railway CLI
        run: npm install -g @railway/cli
      
      - name: Deploy to Railway
        run: railway up
        env:
          RAILWAY_TOKEN: ${{ secrets.RAILWAY_TOKEN }}
```

### Option 2: Using Railway's Direct GitHub Integration (Recommended)

This is the simpler and more reliable approach:

1. Go to your Railway dashboard
2. Select your project
3. Click on "Settings" > "GitHub"
4. Connect your GitHub repository
5. Select the branch to deploy from (usually `main`)
6. Enable "Auto Deploy" to automatically deploy when you push to the selected branch

## Testing the Integration

1. Push your changes to GitHub:
   ```bash
   git add .
   git commit -m "Integrate MinIO storage and Railway deployment"
   git push origin main
   ```

2. Check the deployment status:
   - If using GitHub Actions: Go to your repository > "Actions" tab
   - If using Railway's direct integration: Go to your Railway dashboard > Project > Deployments

3. Test file uploads:
   - Upload a file through your application
   - Verify that the file is stored in MinIO
   - Check that the URL is accessible

## Troubleshooting

### MinIO Connection Issues

If you're having trouble connecting to MinIO:

1. Verify your environment variables are correctly set in Railway
2. Check that the MinIO service is running in Railway
3. Ensure your application has the correct permissions to access the bucket
4. Check the logs for any connection errors

#### Cross-Project MinIO Troubleshooting

If you're using MinIO from a different project:

1. Make sure the `MINIO_ENDPOINT` is the full public URL (e.g., `https://bucket-production-xxxx.up.railway.app`)
2. Ensure `MINIO_SECURE` is set to `true` since you're using HTTPS
3. Verify that the access key and secret key are correct
4. Check that the bucket name exists in the MinIO service
5. Look for CORS (Cross-Origin Resource Sharing) errors in the logs, which might require additional configuration

### Deployment Failures

If your deployment fails:

1. Check the GitHub Actions logs for errors
2. Verify that your `RAILWAY_TOKEN` is valid and has not expired
3. Ensure your `railway.json` file is correctly formatted
4. Check that your Dockerfile is valid and builds successfully

### File Upload Failures

If files fail to upload:

1. Check the application logs for errors
2. Verify that the MinIO bucket exists and is accessible
3. Ensure the application has the correct permissions to write to the bucket
4. Test with a small file to rule out size-related issues

## Additional Resources

- [Railway Documentation](https://docs.railway.app/)
- [MinIO Python Client Documentation](https://min.io/docs/minio/linux/developers/python/API.html)
- [GitHub Actions Documentation](https://docs.github.com/en/actions)
