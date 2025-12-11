"""
Video processing and validation utilities
"""

import os
import cv2
from pathlib import Path
from typing import Dict, Optional, Tuple
from config import (
    MAX_VIDEO_SIZE_MB,
    MAX_VIDEO_DURATION_SECONDS,
    SUPPORTED_VIDEO_FORMATS,
    VIDEO_STORAGE_PATH
)


class VideoValidationError(Exception):
    """Custom exception for video validation errors"""
    pass


def ensure_video_directory(user_id: Optional[int] = None):
    """Create video storage directory if it doesn't exist

    Args:
        user_id: Optional user ID for user-specific directory. If None, creates base directory.
    """
    if user_id:
        # Create user-specific directory
        user_dir = Path(VIDEO_STORAGE_PATH) / f"user_{user_id}"
        user_dir.mkdir(parents=True, exist_ok=True)
    else:
        # Create base directory
        Path(VIDEO_STORAGE_PATH).mkdir(parents=True, exist_ok=True)


def validate_video_format(filename: str) -> Tuple[bool, str]:
    """
    Validate video file format

    Args:
        filename: Name of the video file

    Returns:
        Tuple of (is_valid, message)
    """
    file_ext = Path(filename).suffix.lower()

    if file_ext not in SUPPORTED_VIDEO_FORMATS:
        return False, f"Unsupported format '{file_ext}'. Supported: {', '.join(SUPPORTED_VIDEO_FORMATS)}"

    return True, "Format valid"


def validate_video_size(file_size_bytes: int) -> Tuple[bool, str]:
    """
    Validate video file size

    Args:
        file_size_bytes: Size of file in bytes

    Returns:
        Tuple of (is_valid, message)
    """
    file_size_mb = file_size_bytes / (1024 * 1024)

    if file_size_mb > MAX_VIDEO_SIZE_MB:
        return False, f"File too large ({file_size_mb:.1f}MB). Maximum: {MAX_VIDEO_SIZE_MB}MB"

    return True, f"Size OK ({file_size_mb:.1f}MB)"


def extract_video_metadata(file_path: str) -> Dict:
    """
    Extract metadata from video file using OpenCV

    Args:
        file_path: Path to video file

    Returns:
        Dictionary with video metadata
    """
    try:
        cap = cv2.VideoCapture(file_path)

        if not cap.isOpened():
            raise VideoValidationError("Could not open video file")

        # Extract metadata
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        duration_seconds = frame_count / fps if fps > 0 else 0

        cap.release()

        return {
            "duration_seconds": duration_seconds,
            "fps": fps,
            "frame_count": frame_count,
            "width": width,
            "height": height,
            "resolution": f"{width}x{height}"
        }

    except Exception as e:
        raise VideoValidationError(f"Failed to extract metadata: {str(e)}")


def validate_video_duration(duration_seconds: float) -> Tuple[bool, str]:
    """
    Validate video duration

    Args:
        duration_seconds: Duration in seconds

    Returns:
        Tuple of (is_valid, message)
    """
    if duration_seconds > MAX_VIDEO_DURATION_SECONDS:
        max_minutes = MAX_VIDEO_DURATION_SECONDS / 60
        actual_minutes = duration_seconds / 60
        return False, f"Video too long ({actual_minutes:.1f} min). Maximum: {max_minutes:.0f} min"

    if duration_seconds < 1:
        return False, "Video too short (< 1 second)"

    return True, f"Duration OK ({duration_seconds:.1f}s)"


def save_uploaded_video(uploaded_file, user_id: int, custom_name: Optional[str] = None) -> str:
    """
    Save uploaded video file to user-specific storage

    Args:
        uploaded_file: Streamlit UploadedFile object
        user_id: User ID for user-specific directory
        custom_name: Optional custom filename (without extension)

    Returns:
        Path to saved file
    """
    ensure_video_directory(user_id)

    # Get user-specific directory
    user_dir = Path(VIDEO_STORAGE_PATH) / f"user_{user_id}"

    # Generate filename
    if custom_name:
        ext = Path(uploaded_file.name).suffix
        filename = f"{custom_name}{ext}"
    else:
        filename = uploaded_file.name

    # Ensure unique filename within user's directory
    file_path = user_dir / filename
    counter = 1
    while file_path.exists():
        stem = Path(filename).stem
        ext = Path(filename).suffix
        filename = f"{stem}_{counter}{ext}"
        file_path = user_dir / filename
        counter += 1

    # Save file
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return str(file_path)


def validate_and_process_video(uploaded_file, user_id: int) -> Dict:
    """
    Complete video validation and processing pipeline

    Args:
        uploaded_file: Streamlit UploadedFile object
        user_id: User ID for user-specific directory

    Returns:
        Dictionary with validation results and metadata

    Raises:
        VideoValidationError: If validation fails
    """
    result = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "metadata": {},
        "file_path": None
    }

    # Validate format
    is_valid, message = validate_video_format(uploaded_file.name)
    if not is_valid:
        result["valid"] = False
        result["errors"].append(message)
        return result

    # Validate size
    file_size = uploaded_file.size
    is_valid, message = validate_video_size(file_size)
    if not is_valid:
        result["valid"] = False
        result["errors"].append(message)
        return result

    # Save file temporarily to extract metadata
    try:
        file_path = save_uploaded_video(uploaded_file, user_id)
        result["file_path"] = file_path

        # Extract metadata
        metadata = extract_video_metadata(file_path)
        result["metadata"] = metadata

        # Add file size to metadata
        result["metadata"]["file_size_mb"] = file_size / (1024 * 1024)

        # Validate duration
        is_valid, message = validate_video_duration(metadata["duration_seconds"])
        if not is_valid:
            result["valid"] = False
            result["errors"].append(message)
            # Clean up file if validation failed
            if os.path.exists(file_path):
                os.remove(file_path)
            return result

    except VideoValidationError as e:
        result["valid"] = False
        result["errors"].append(str(e))
        # Clean up file if it exists
        if result["file_path"] and os.path.exists(result["file_path"]):
            os.remove(result["file_path"])
        return result

    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Unexpected error: {str(e)}")
        # Clean up file if it exists
        if result["file_path"] and os.path.exists(result["file_path"]):
            os.remove(result["file_path"])
        return result

    return result


def delete_video_file(file_path: str) -> bool:
    """
    Delete a video file from storage

    Args:
        file_path: Path to video file

    Returns:
        True if deleted successfully, False otherwise
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
    except Exception:
        return False


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable string

    Args:
        seconds: Duration in seconds

    Returns:
        Formatted string (e.g., "2m 30s")
    """
    if seconds < 60:
        return f"{seconds:.0f}s"

    minutes = int(seconds // 60)
    remaining_seconds = int(seconds % 60)

    if remaining_seconds == 0:
        return f"{minutes}m"

    return f"{minutes}m {remaining_seconds}s"


def get_video_file_size(file_path: str) -> float:
    """
    Get video file size in MB

    Args:
        file_path: Path to video file

    Returns:
        File size in MB
    """
    if os.path.exists(file_path):
        size_bytes = os.path.getsize(file_path)
        return size_bytes / (1024 * 1024)
    return 0.0
