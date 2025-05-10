from flask import Blueprint, request, jsonify
import os
import logging
import json
import tempfile
import uuid
import subprocess
import re
import glob
from werkzeug.utils import secure_filename
from pythainlp.tokenize import word_tokenize

from services.gcp_toolkit import upload_to_gcs_with_path
from services.file_management import download_file
from services.v1.ffmpeg.ffmpeg_compose import find_thai_font

# Set up logging with more detailed format
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
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
        "text_align": "center",              # Optional: text alignment (left, center, right)
        "max_lines": 3,                      # Optional: maximum number of lines to display
        "padding_multiplier": 0.5,           # Optional: padding multiplier for breathing area (0.5 = 50% of font size)
        "id": "Optional job ID",
        "metadata": {
            "thumbnail": true,
            "filesize": true,
            "duration": true,
            "bitrate": true,
            "encoder": true
        }
    }
    
    Returns:
        JSON with URL to the processed video and optional metadata
    """
    try:
        logger.info("[DEBUG] Starting add_title_to_video endpoint processing")
        
        data = request.get_json()
        logger.info(f"[DEBUG] Received request data: {json.dumps(data, ensure_ascii=False)}")
        
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
        text_align = data.get('text_align', 'center')  # Default to center alignment
        max_lines = data.get('max_lines', 3)  # Default to 3 lines maximum
        padding_multiplier = data.get('padding_multiplier', 0.5)  # Default to 50% of font size
        job_id = data.get('id', f"title_{uuid.uuid4()}")
        metadata_request = data.get('metadata', {})
        
        logger.info(f"[DEBUG] Processing parameters - Font: {font_name}, Align: {text_align}, Max Lines: {max_lines}")
        logger.info(f"[DEBUG] Title text: {title}")
        logger.info(f"[DEBUG] Padding multiplier: {padding_multiplier}")
        
        # Validate required parameters
        if not video_url:
            logger.warning("[DEBUG] Missing required parameter: video_url")
            return jsonify({"error": "Missing required parameter: video_url"}), 400
        if not title:
            logger.warning("[DEBUG] Missing required parameter: title")
            return jsonify({"error": "Missing required parameter: title"}), 400
            
        # Auto-detect Thai text and set default font
        is_thai = bool(re.search(r'[\u0E00-\u0E7F]', title))
        if not font_name:
            font_name = "Sarabun" if is_thai else "Arial"
        
        # Clean title text by removing colons and semicolons
        title = clean_title_text(title)
        logger.info(f"[DEBUG] Cleaned title: {title}")
            
        # Process the title with adaptive Thai text handling
        title_lines = adaptive_split_thai_text(title, max_lines)
        logger.info(f"[DEBUG] Split title into {len(title_lines)} lines: {title_lines}")
        
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
            text_align=text_align,
            padding_multiplier=padding_multiplier,
            job_id=job_id,
            metadata_request=metadata_request
        )
        
        logger.info(f"[DEBUG] Video processing completed, result URL: {result.get('video_url', 'No URL')}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"[DEBUG] Error in add_title_to_video: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

def clean_title_text(text):
    """
    Clean title text by removing colons and semicolons.
    
    Args:
        text: The title text to clean
        
    Returns:
        Cleaned text without colons or semicolons
    """
    # Remove colons and semicolons
    cleaned_text = text.replace(':', '').replace(';', '')
    
    # If the text contains Thai characters, we need to handle it differently
    if re.search(r'[\u0E00-\u0E7F]', text):
        # For Thai text with colons or semicolons, we want to split at those points
        # but not include the punctuation
        if ':' in text:
            parts = text.split(':', 1)
            if len(parts) == 2:
                title_part = parts[0].strip()
                subtitle_part = parts[1].strip()
                # Join with a space instead of the colon
                cleaned_text = f"{title_part} {subtitle_part}"
        
        # Same for semicolons
        if ';' in cleaned_text:
            parts = cleaned_text.split(';', 1)
            if len(parts) == 2:
                title_part = parts[0].strip()
                subtitle_part = parts[1].strip()
                # Join with a space instead of the semicolon
                cleaned_text = f"{title_part} {subtitle_part}"
    
    return cleaned_text

def smart_split_thai_text(text, max_chars_per_line=30):
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
    
    # Special handling for titles with colon format "Title: Subtitle"
    if ':' in text:
        parts = text.split(':', 1)  # Split only on the first colon
        if len(parts) == 2:
            title_part = parts[0].strip()
            subtitle_part = parts[1].strip()
            
            # If both parts are reasonably sized, return them as separate lines
            if len(title_part) <= max_chars_per_line and len(subtitle_part) <= max_chars_per_line:
                return [title_part, subtitle_part]
            
            # If title part is short but subtitle is long, keep title as is and split subtitle
            if len(title_part) <= max_chars_per_line:
                subtitle_lines = smart_split_thai_text(subtitle_part, max_chars_per_line)
                return [title_part] + subtitle_lines
    
    # Check if text is primarily Thai
    is_thai = bool(re.search(r'[\u0E00-\u0E7F]', text))
    
    if is_thai:
        # Use pythainlp to tokenize Thai text into words
        words = word_tokenize(text, engine="newmm")
        
        # Special handling to preserve punctuation with the preceding word
        processed_words = []
        current_word = ""
        
        for word in words:
            if word in [',', '.', ':', ';', '?', '!', ')', ']', '}', '"', "'"]:
                # Attach punctuation to the previous word
                if current_word:
                    current_word += word
                else:
                    processed_words.append(word)
            else:
                if current_word:
                    processed_words.append(current_word)
                current_word = word
                
        if current_word:
            processed_words.append(current_word)
            
        words = processed_words
    else:
        # For non-Thai text, split by spaces
        words = text.split()
    
    lines = []
    current_line = ""
    
    for word in words:
        # Check if adding this word would exceed the max line length
        test_line = current_line + ("" if not current_line else (" " if not is_thai else "")) + word
        
        if len(test_line) <= max_chars_per_line:
            # Add the word to the current line (with space for non-Thai text only)
            if current_line:
                if is_thai:
                    # For Thai text, don't add spaces between words
                    current_line += word
                else:
                    # For non-Thai text, add spaces between words
                    current_line += " " + word
            else:
                current_line = word
        else:
            # Line would be too long, start a new line
            if current_line:
                lines.append(current_line)
            current_line = word
    
    # Add the last line if it's not empty
    if current_line:
        lines.append(current_line)
    
    return lines

def adaptive_split_thai_text(text, max_lines):
    """
    Adaptively split Thai text to fit within a specified number of lines.
    Adjusts the characters per line based on the maximum number of lines allowed.
    
    Args:
        text: The text to split
        max_lines: Maximum number of lines to use
        
    Returns:
        List of lines that fit within the max_lines constraint
    """
    # If text is empty or max_lines is 0, return empty list
    if not text or max_lines <= 0:
        return []
    
    # Start with a reasonable character limit
    chars_per_line = 30
    
    # Get initial split
    lines = smart_split_thai_text(text, max_chars_per_line=chars_per_line)
    
    # If it already fits, we're done
    if len(lines) <= max_lines:
        logger.info(f"[DEBUG] Text fits in {len(lines)} lines with {chars_per_line} chars per line")
        return lines
    
    # Binary search to find the optimal characters per line
    min_chars = 10  # Minimum reasonable characters per line
    max_chars = 100  # Maximum reasonable characters per line
    
    while min_chars <= max_chars:
        mid_chars = (min_chars + max_chars) // 2
        lines = smart_split_thai_text(text, max_chars_per_line=mid_chars)
        
        if len(lines) <= max_lines:
            # This works, but try to find a smaller chars_per_line that still works
            max_chars = mid_chars - 1
            chars_per_line = mid_chars  # Save this working value
        else:
            # Too many lines, need more chars per line
            min_chars = mid_chars + 1
    
    # Use the last working value
    lines = smart_split_thai_text(text, max_chars_per_line=chars_per_line)
    
    # If we still have too many lines (shouldn't happen due to binary search), force truncate
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    
    logger.info(f"[DEBUG] Adaptive split: {len(lines)} lines with {chars_per_line} chars per line")
    return lines

def process_add_title(video_url, title_lines, font_name, font_size, font_color, 
                     border_color, border_width, padding_top, padding_color, job_id, 
                     text_align='center', padding_multiplier=0.5, metadata_request=None):
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
        text_align: Text alignment (left, center, right)
        padding_multiplier: Multiplier for padding space (breathing area) above and below text
        metadata_request: Dictionary specifying which metadata to include
        
    Returns:
        Dictionary with result information
    """
    try:
        logger.info(f"[DEBUG] Starting video processing with job_id: {job_id}")
        logger.info(f"[DEBUG] Video URL: {video_url}")
        logger.info(f"[DEBUG] Title lines: {title_lines}")
        logger.info(f"[DEBUG] Font settings: size={font_size}, color={font_color}, name={font_name}")
        logger.info(f"[DEBUG] Text alignment: {text_align}")
        logger.info(f"[DEBUG] Padding multiplier: {padding_multiplier}")
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        logger.info(f"[DEBUG] Created temp directory: {temp_dir}")
        
        # Download the video
        input_video = os.path.join(temp_dir, f"input_{job_id}.mp4")
        download_file(video_url, input_video)
        logger.info(f"[DEBUG] Downloaded video to: {input_video}")
        
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
        
        original_width = video_info["streams"][0]["width"]
        original_height = video_info["streams"][0]["height"]
        logger.info(f"[DEBUG] Original video dimensions: {original_width}x{original_height}")
        
        # We want to maintain the final dimensions at original size (e.g., 1080x1920)
        # So we need to scale the video down to make room for the padding
        target_width = original_width
        target_height = original_height
        
        # Calculate the new video height to make room for padding
        video_height = target_height - padding_top
        
        # Calculate line height and positions for perfect vertical centering
        total_lines = len(title_lines)
        
        # Adjust line spacing to 30% of font size for better readability (like in image tool)
        line_spacing = int(font_size * 0.3)
        logger.info(f"[DEBUG] Using line spacing: {line_spacing}px (30% of font size)")
        
        # Calculate the total height of all text lines including spacing
        total_text_height = (total_lines * font_size) + ((total_lines - 1) * line_spacing)
        
        # Add extra padding above and below text using the padding_multiplier parameter
        extra_padding = int(font_size * padding_multiplier)
        logger.info(f"[DEBUG] Extra padding: {extra_padding}px ({padding_multiplier} * font size)")
        
        # Calculate minimum required padding
        min_required_padding = total_text_height + (extra_padding * 2)
        logger.info(f"[DEBUG] Calculated min required padding: {min_required_padding}px")
        
        # If requested padding is less than required, increase it
        if padding_top < min_required_padding:
            padding_top = min_required_padding
            logger.info(f"[DEBUG] Increased padding to {padding_top}px to fit text properly")
            
            # Recalculate video height with new padding
            video_height = target_height - padding_top
            if video_height <= 0:
                # If padding would take up entire video, reduce padding to half the video height
                padding_top = original_height // 2
                video_height = original_height - padding_top
                logger.warning(f"[DEBUG] Padding was too large, reduced to {padding_top}px")
        
        # Calculate starting Y position to center text vertically in the padding area with extra space
        y_start = extra_padding
        logger.info(f"[DEBUG] Text starting Y position: {y_start}")
        
        # Find Thai font using the existing function
        thai_font_path = find_thai_font()
        if not thai_font_path:
            logger.warning(f"[DEBUG] No Thai font found, using default font specification: {font_name}")
            font_path = f"/usr/share/fonts/truetype/thai-tlwg/{font_name}.ttf"
        else:
            logger.info(f"[DEBUG] Using Thai font: {thai_font_path}")
            font_path = thai_font_path
        
        # Create drawtext filters for each line with improved spacing
        drawtext_filters = []
        
        # Set margins for text alignment
        left_margin = 30  # Left margin for left-aligned text
        right_margin = 30  # Right margin for right-aligned text
        
        for i, line in enumerate(title_lines):
            # Escape single quotes for FFmpeg
            escaped_line = line.replace("'", "'\\''")
            
            # Calculate exact Y position for this line with improved spacing
            y_pos = y_start + (i * (font_size + line_spacing))
            
            # For Thai text, use a slightly larger font size and bold font if available
            is_thai = bool(re.search(r'[\u0E00-\u0E7F]', escaped_line))
            
            # Try to use a bold font for better visibility
            if is_thai and "Bold" not in font_path and os.path.exists(font_path.replace(".ttf", "-Bold.ttf")):
                current_font_path = font_path.replace(".ttf", "-Bold.ttf")
            elif is_thai and "Bold" not in font_path and os.path.exists(font_path.replace("Regular", "Bold")):
                current_font_path = font_path.replace("Regular", "Bold")
            else:
                current_font_path = font_path
            
            # Add a shadow for better visibility for Thai text
            if is_thai:
                shadow_option = ":shadowcolor=black:shadowx=1:shadowy=1"
            else:
                shadow_option = ""
            
            # Set x position based on text alignment
            if text_align == 'center':
                x_position = "(w-text_w)/2"
            elif text_align == 'left':
                x_position = str(left_margin)
            elif text_align == 'right':
                x_position = f"w-text_w-{right_margin}"
            else:
                logger.warning(f"[DEBUG] Unknown text alignment: {text_align}. Defaulting to center.")
                x_position = "(w-text_w)/2"
                
            logger.info(f"[DEBUG] Line {i+1} alignment: {text_align}, x position: {x_position}")
            
            filter_text = (
                f"drawtext=text='{escaped_line}':"
                f"fontfile={current_font_path}:"
                f"fontsize={font_size}:"
                f"fontcolor={font_color}:"
                f"bordercolor={border_color}:"
                f"borderw={border_width}{shadow_option}:"
                # Position text based on alignment
                f"x={x_position}:"
                # Position text precisely
                f"y={int(y_pos)}"
            )
            drawtext_filters.append(filter_text)
            logger.info(f"[DEBUG] Created filter for line {i+1}: '{escaped_line}' at y={int(y_pos)}")
        
        # Create the full filter string - Scale video first, then add padding
        # This keeps the final dimensions at the original size
        filter_string = f"scale={target_width}:{video_height},pad={target_width}:{target_height}:0:{padding_top}:color={padding_color}"
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
        
        logger.info(f"[DEBUG] Running FFmpeg command with filter: {filter_string}")
        subprocess.run(ffmpeg_cmd, check=True)
        logger.info(f"[DEBUG] FFmpeg command completed successfully")
        
        # Upload to GCS
        destination_path = f"titled_videos/{os.path.basename(output_video)}"
        video_url = upload_to_gcs_with_path(output_video, destination_path=destination_path)
        logger.info(f"[DEBUG] Uploaded video to GCS: {video_url}")
        
        # Prepare result
        result = {
            "id": job_id,
            "status": "success",
            "video_url": video_url
        }
        
        # Add metadata if requested
        if metadata_request:
            metadata = {}
            
            # Generate thumbnail if requested
            if metadata_request.get('thumbnail'):
                thumbnail_path = os.path.join(temp_dir, f"thumbnail_{job_id}.jpg")
                thumbnail_cmd = [
                    "ffmpeg",
                    "-i", output_video,
                    "-ss", "00:00:01",
                    "-vframes", "1",
                    "-y",
                    thumbnail_path
                ]
                subprocess.run(thumbnail_cmd, check=True)
                
                # Upload thumbnail
                thumbnail_dest = f"thumbnails/{os.path.basename(thumbnail_path)}"
                thumbnail_url = upload_to_gcs_with_path(thumbnail_path, destination_path=thumbnail_dest)
                metadata["thumbnail_url"] = thumbnail_url
                logger.info(f"[DEBUG] Generated and uploaded thumbnail: {thumbnail_url}")
            
            # Get file size if requested
            if metadata_request.get('filesize'):
                metadata["filesize"] = os.path.getsize(output_video)
                logger.info(f"[DEBUG] File size: {metadata['filesize']} bytes")
            
            # Get duration, bitrate, and encoder info if requested
            if metadata_request.get('duration') or metadata_request.get('bitrate') or metadata_request.get('encoder'):
                media_info_cmd = [
                    "ffprobe",
                    "-v", "error",
                    "-show_entries", "format=duration,bit_rate:stream=codec_name",
                    "-of", "json",
                    output_video
                ]
                media_info_result = subprocess.run(media_info_cmd, capture_output=True, text=True)
                media_info = json.loads(media_info_result.stdout)
                
                if metadata_request.get('duration') and 'duration' in media_info.get('format', {}):
                    metadata["duration"] = float(media_info['format']['duration'])
                
                if metadata_request.get('bitrate') and 'bit_rate' in media_info.get('format', {}):
                    metadata["bitrate"] = int(media_info['format']['bit_rate'])
                
                if metadata_request.get('encoder') and 'streams' in media_info and len(media_info['streams']) > 0:
                    metadata["encoder"] = media_info['streams'][0].get('codec_name', 'unknown')
                
                logger.info(f"[DEBUG] Media info metadata: {metadata}")
            
            # Add metadata to result
            result["metadata"] = metadata
        
        # Clean up
        try:
            os.remove(input_video)
            os.remove(output_video)
            if metadata_request and metadata_request.get('thumbnail'):
                os.remove(thumbnail_path)
            os.rmdir(temp_dir)
            logger.info(f"[DEBUG] Cleaned up temporary files and directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"[DEBUG] Could not clean up all temporary files for job {job_id}: {e}")
        
        logger.info(f"[DEBUG] Video processing completed successfully")
        return result
        
    except Exception as e:
        logger.error(f"[DEBUG] Error processing video title: {str(e)}", exc_info=True)
        return {
            "id": job_id,
            "status": "error",
            "error": str(e)
        }
