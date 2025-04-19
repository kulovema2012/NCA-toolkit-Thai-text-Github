from flask import Blueprint, request, jsonify
import os
import logging
import json
import tempfile
import uuid
import subprocess
import re
from werkzeug.utils import secure_filename
from pythainlp.tokenize import word_tokenize

from services.gcp_toolkit import upload_to_gcs_with_path
from services.file_management import download_file

# Set up logging
logger = logging.getLogger(__name__)

# Create blueprint
add_title_to_video_bp = Blueprint('add_title_to_video', __name__, url_prefix='/api/v1/video')

@add_title_to_video_bp.route('/add-title', methods=['POST'])
def add_title_to_video():
    """
    Add a title to a video with proper handling of Thai text.
    
    Request JSON:
    {
        "video_url": "URL of the video to add title to",
        "title": "Title text to add",
        "font_name": "Font name (default: 'Sarabun' for Thai, 'Arial' for others)",
        "font_size": 50,
        "font_color": "black",
        "border_color": "#ffc8dd",
        "border_width": 2,
        "padding_top": 200,
        "padding_color": "white",
        "id": "Optional job ID"
    }
    
    Returns:
        JSON with URL to the processed video
    """
    try:
        data = request.get_json()
        
        # Extract parameters
        video_url = data.get('video_url')
        title = data.get('title')
        font_name = data.get('font_name')
        font_size = data.get('font_size', 50)
        font_color = data.get('font_color', 'black')
        border_color = data.get('border_color', '#ffc8dd')
        border_width = data.get('border_width', 2)
        padding_top = data.get('padding_top', 200)
        padding_color = data.get('padding_color', 'white')
        job_id = data.get('id', f"title_{uuid.uuid4()}")
        
        # Validate required parameters
        if not video_url:
            return jsonify({"error": "Missing required parameter: video_url"}), 400
        if not title:
            return jsonify({"error": "Missing required parameter: title"}), 400
            
        # Auto-detect Thai text and set default font
        is_thai = bool(re.search(r'[\u0E00-\u0E7F]', title))
        if not font_name:
            font_name = "Sarabun" if is_thai else "Arial"
            
        # Process the title with proper Thai text handling
        title_lines = smart_split_thai_text(title)
        
        # Process the video
        result = process_add_title(
            video_url=video_url,
            title_lines=title_lines,
            font_name=font_name,
            font_size=font_size,
            font_color=font_color,
            border_color=border_color,
            border_width=border_width,
            padding_top=padding_top,
            padding_color=padding_color,
            job_id=job_id
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Error in add_title_to_video: {str(e)}")
        return jsonify({"error": str(e)}), 500

def smart_split_thai_text(text, max_chars_per_line=25):
    """
    Intelligently split Thai text into lines using pythainlp for proper word tokenization.
    
    Args:
        text: The text to split
        max_chars_per_line: Maximum characters per line
        
    Returns:
        List of lines
    """
    # If text already has newlines, respect them
    if '\n' in text:
        return text.split('\n')
        
    # If text is short enough, return as is
    if len(text) <= max_chars_per_line:
        return [text]
    
    # Check if text is primarily Thai
    is_thai = bool(re.search(r'[\u0E00-\u0E7F]', text))
    
    if is_thai:
        # Use pythainlp to tokenize Thai text into words
        words = word_tokenize(text, engine="newmm")
    else:
        # For non-Thai text, split by spaces
        words = text.split()
    
    lines = []
    current_line = ""
    
    for word in words:
        # Check if adding this word would exceed the max line length
        if len(current_line) + len(word) <= max_chars_per_line:
            current_line += word
        else:
            # Line would be too long, start a new line
            if current_line:
                lines.append(current_line)
            current_line = word
    
    # Add the last line if it's not empty
    if current_line:
        lines.append(current_line)
    
    return lines

def process_add_title(video_url, title_lines, font_name, font_size, font_color, 
                     border_color, border_width, padding_top, padding_color, job_id):
    """
    Process the video to add a title with padding.
    
    Args:
        video_url: URL of the video
        title_lines: List of title lines
        font_name: Font name
        font_size: Font size
        font_color: Font color
        border_color: Border color
        border_width: Border width
        padding_top: Top padding in pixels
        padding_color: Padding color
        job_id: Job ID
        
    Returns:
        Dictionary with result information
    """
    try:
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        
        # Download the video
        input_video = os.path.join(temp_dir, f"input_{job_id}.mp4")
        download_file(video_url, input_video)
        
        # Get video dimensions
        ffprobe_cmd = [
            "ffprobe", 
            "-v", "error", 
            "-select_streams", "v:0", 
            "-show_entries", "stream=width,height", 
            "-of", "json", 
            input_video
        ]
        
        ffprobe_result = subprocess.run(ffprobe_cmd, capture_output=True, text=True)
        video_info = json.loads(ffprobe_result.stdout)
        
        width = video_info["streams"][0]["width"]
        height = video_info["streams"][0]["height"]
        
        # Calculate line height and positions
        line_height = min(font_size * 1.3, padding_top / (len(title_lines) + 1))
        y_start = max(10, (padding_top - len(title_lines) * line_height) / 2)
        
        # Create drawtext filters for each line
        drawtext_filters = []
        for i, line in enumerate(title_lines):
            # Escape single quotes for FFmpeg
            escaped_line = line.replace("'", "'\\''")
            
            filter_text = (
                f"drawtext=text='{escaped_line}':"
                f"fontfile=/usr/share/fonts/truetype/thai-tlwg/{font_name}.ttf:"
                f"fontsize={font_size}:"
                f"fontcolor={font_color}:"
                f"bordercolor={border_color}:"
                f"borderw={border_width}:"
                f"x=(w-text_w)/2:"
                f"y={int(y_start + i * line_height)}"
            )
            drawtext_filters.append(filter_text)
        
        # Create the full filter string
        filter_string = f"scale={width}:{height},pad={width}:{height+padding_top}:0:{padding_top}:color={padding_color}"
        for filter_text in drawtext_filters:
            filter_string += f",{filter_text}"
        
        # Output video path
        output_video = os.path.join(temp_dir, f"output_{job_id}.mp4")
        
        # Run FFmpeg command
        ffmpeg_cmd = [
            "ffmpeg",
            "-i", input_video,
            "-vf", filter_string,
            "-c:v", "libx264",
            "-c:a", "aac",
            "-y",
            output_video
        ]
        
        subprocess.run(ffmpeg_cmd, check=True)
        
        # Upload to GCS
        destination_path = f"titled_videos/{os.path.basename(output_video)}"
        video_url = upload_to_gcs_with_path(output_video, destination_path=destination_path)
        
        # Clean up
        try:
            os.remove(input_video)
            os.remove(output_video)
            os.rmdir(temp_dir)
        except:
            logger.warning(f"Could not clean up all temporary files for job {job_id}")
        
        return {
            "id": job_id,
            "status": "success",
            "video_url": video_url
        }
        
    except Exception as e:
        logger.error(f"Error processing video title: {str(e)}")
        return {
            "id": job_id,
            "status": "error",
            "error": str(e)
        }
