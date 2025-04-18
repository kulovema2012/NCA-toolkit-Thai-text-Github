from flask import Blueprint, jsonify
import os
import logging
import json
from datetime import datetime
import sys

# Import GCP toolkit to test connectivity
from services.gcp_toolkit import gcs_client, GCP_BUCKET_NAME

# Set up logging
logger = logging.getLogger(__name__)

# Create blueprint
health_bp = Blueprint('health', __name__)

@health_bp.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint to verify API is running and dependencies are working.
    """
    try:
        # Basic health information
        health_info = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "version": "1.0.0",
            "python_version": sys.version,
            "dependencies": {}
        }
        
        # Check API_KEY
        api_key = os.environ.get('API_KEY')
        health_info["dependencies"]["api_key"] = {
            "configured": api_key is not None,
            "status": "available" if api_key else "missing"
        }
        
        # Check GCP Storage
        gcp_status = "unavailable"
        gcp_error = None
        
        try:
            if gcs_client and GCP_BUCKET_NAME:
                # Try to list a single file to verify connectivity
                bucket = gcs_client.bucket(GCP_BUCKET_NAME)
                blobs = list(bucket.list_blobs(max_results=1))
                gcp_status = "connected"
            else:
                gcp_status = "client_not_initialized"
        except Exception as e:
            gcp_error = str(e)
            logger.error(f"GCP health check error: {e}")
        
        health_info["dependencies"]["gcp_storage"] = {
            "status": gcp_status,
            "bucket": GCP_BUCKET_NAME,
            "error": gcp_error
        }
        
        # Check OpenAI API
        openai_key = os.environ.get('OPENAI_API_KEY')
        health_info["dependencies"]["openai"] = {
            "configured": openai_key is not None,
            "status": "available" if openai_key else "missing"
        }
        
        # Check Replicate API
        replicate_token = os.environ.get('REPLICATE_API_TOKEN')
        health_info["dependencies"]["replicate"] = {
            "configured": replicate_token is not None,
            "status": "available" if replicate_token else "missing"
        }
        
        # Overall status
        if (gcp_status != "connected" or 
            not api_key or 
            not openai_key or 
            not replicate_token):
            health_info["status"] = "degraded"
        
        return jsonify(health_info), 200
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 500
