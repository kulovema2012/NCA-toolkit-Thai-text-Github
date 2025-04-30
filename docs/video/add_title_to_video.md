# Add Title to Video

This endpoint adds a title to a video with proper handling of Thai text, including adaptive text splitting, adjustable padding, and text alignment options.

## Endpoint

```
POST /api/v1/video/add-title
```

## Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `video_url` | string | Yes | - | URL of the video to add title to |
| `title` | string | Yes | - | Title text to add to the video |
| `font_name` | string | No | "Sarabun" for Thai, "Arial" for others | Font name to use for the title |
| `font_size` | integer | No | 50 | Font size for the title text |
| `font_color` | string | No | "black" | Color of the title text (e.g., "white", "#FFFFFF") |
| `border_color` | string | No | "#ffc8dd" | Color of the text border |
| `border_width` | integer | No | 2 | Width of the text border (in pixels) |
| `padding_top` | integer | No | 200 | Top padding in pixels |
| `padding_color` | string | No | "white" | Background color for the padding area |
| `text_align` | string | No | "center" | Text alignment: "left", "center", or "right" |
| `max_lines` | integer | No | 3 | Maximum number of lines to display for the title |
| `padding_multiplier` | float | No | 0.5 | Multiplier for breathing area above/below text (e.g., 1.0 for 100% of font size) |
| `id` | string | No | auto-generated | Optional job ID |
| `metadata` | object | No | {} | Optional metadata to include in response |

### Metadata Options

The `metadata` object can include the following boolean fields:

| Field | Description |
|-------|-------------|
| `thumbnail` | Generate and return a thumbnail URL |
| `filesize` | Include the file size in bytes |
| `duration` | Include the video duration in seconds |
| `bitrate` | Include the video bitrate |
| `encoder` | Include the video encoder information |

## Example Request

```json
{
  "video_url": "https://example.com/video.mp4",
  "title": "สวัสดีชาวโลก - Hello World",
  "font_size": 60,
  "font_color": "white",
  "border_color": "#000000",
  "border_width": 3,
  "padding_top": 250,
  "padding_color": "#1a1a1a",
  "text_align": "center",
  "max_lines": 2,
  "padding_multiplier": 0.8,
  "metadata": {
    "thumbnail": true,
    "duration": true
  }
}
```

## Response

```json
{
  "id": "title_f8a7b6c5",
  "status": "success",
  "video_url": "https://storage.googleapis.com/bucket-name/titled_videos/output_title_f8a7b6c5.mp4",
  "metadata": {
    "thumbnail_url": "https://storage.googleapis.com/bucket-name/thumbnails/thumbnail_f8a7b6c5.jpg",
    "duration": 15.4
  }
}
```

## Features

### Adaptive Text Splitting

The tool automatically adjusts the characters per line based on the `max_lines` parameter to ensure that all text fits within the specified number of lines without truncation. It uses a binary search algorithm to find the optimal character limit.

### Thai Text Support

- Automatically detects Thai text and selects appropriate fonts
- Uses pythainlp for proper word tokenization
- Adds shadows to Thai text for better visibility
- Attempts to use bold font variants for Thai text when available

### Adjustable Padding Space

The `padding_multiplier` parameter controls the amount of "breathing space" above and below the text. The default value is 0.5 (50% of the font size), but you can increase it for more space or decrease it for less.

### Text Alignment Options

Text can be aligned left, center, or right using the `text_align` parameter:
- `"center"`: Centers text horizontally (default)
- `"left"`: Aligns text to the left with a margin
- `"right"`: Aligns text to the right with a margin

### Automatic Padding Adjustment

If the specified `padding_top` is not sufficient to fit the text with proper spacing, the tool automatically increases the padding to ensure all text is visible.

## Error Handling

If an error occurs, the response will include an error message:

```json
{
  "id": "title_f8a7b6c5",
  "status": "error",
  "error": "Error message details"
}
```

## Implementation Details

- Uses FFmpeg for video processing
- Supports Thai fonts with proper rendering
- Preserves audio quality in the output video
- Uploads processed videos to Google Cloud Storage
- Generates thumbnails on request
