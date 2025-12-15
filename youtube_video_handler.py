"""
YouTube video download and transcript fetching utilities
"""

import os
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound


class YouTubeVideoError(Exception):
    """Custom exception for YouTube video operations"""
    pass


def extract_video_id(url: str) -> Optional[str]:
    """
    Extract video ID from YouTube URL

    Args:
        url: YouTube video URL (various formats supported)

    Returns:
        Video ID or None if invalid
    """
    # Handle different YouTube URL formats
    if 'youtube.com/watch?v=' in url:
        return url.split('watch?v=')[1].split('&')[0]
    elif 'youtu.be/' in url:
        return url.split('youtu.be/')[1].split('?')[0]
    elif 'youtube.com/embed/' in url:
        return url.split('embed/')[1].split('?')[0]
    else:
        # Assume it's just the video ID
        return url


def get_video_transcript(video_url: str, languages: List[str] = ['en']) -> Optional[Dict]:
    """
    Fetch video transcript/captions

    Args:
        video_url: YouTube video URL
        languages: List of language codes to try (default: ['en'])

    Returns:
        Dictionary with transcript data or None if unavailable
    """
    try:
        video_id = extract_video_id(video_url)
        if not video_id:
            return None

        # Create API instance and fetch transcript
        api = YouTubeTranscriptApi()
        transcript_obj = None

        # Try each language in order
        for lang in languages:
            try:
                transcript_obj = api.fetch(video_id, languages=[lang])
                break
            except (NoTranscriptFound, TranscriptsDisabled):
                continue

        # If no transcript in preferred languages, try English
        if not transcript_obj:
            try:
                transcript_obj = api.fetch(video_id, languages=['en'])
            except:
                pass

        if not transcript_obj:
            return None

        # Combine all text segments
        full_text = ' '.join([snippet.text for snippet in transcript_obj.snippets])

        # Convert snippets to dict format for compatibility
        segments = [
            {
                'text': snippet.text,
                'start': snippet.start,
                'duration': snippet.duration
            }
            for snippet in transcript_obj.snippets
        ]

        return {
            'video_id': transcript_obj.video_id,
            'language': transcript_obj.language_code,
            'is_generated': transcript_obj.is_generated,
            'transcript': full_text,
            'segments': segments,
            'duration_seconds': segments[-1]['start'] + segments[-1]['duration'] if segments else 0
        }

    except TranscriptsDisabled:
        print(f"[WARN] Transcripts disabled for video: {video_url}")
        return None
    except NoTranscriptFound:
        print(f"[WARN] No transcript found for video: {video_url}")
        return None
    except Exception as e:
        print(f"[ERROR] Failed to fetch transcript: {e}")
        return None


def download_video(
    video_url: str,
    output_dir: str,
    max_duration_seconds: int = 600,
    max_filesize_mb: int = 100
) -> Optional[Dict]:
    """
    Download YouTube video to local storage

    Args:
        video_url: YouTube video URL
        output_dir: Directory to save video
        max_duration_seconds: Maximum video duration (default: 10 minutes)
        max_filesize_mb: Maximum file size in MB (default: 100MB)

    Returns:
        Dictionary with download info or None if failed
    """
    try:
        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Configure yt-dlp options
        ydl_opts = {
            'format': 'best[ext=mp4][height<=720]/best[ext=mp4]/best',  # Prefer 720p MP4
            'outtmpl': os.path.join(output_dir, '%(id)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'max_filesize': max_filesize_mb * 1024 * 1024,  # Convert to bytes
            'match_filter': lambda info: f"Video too long (>{max_duration_seconds}s)" if info.get('duration', 0) > max_duration_seconds else None,
            'prefer_free_formats': True,
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }] if 'ffmpeg' in os.environ.get('PATH', '') else [],
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info first
            info = ydl.extract_info(video_url, download=False)

            if not info:
                raise YouTubeVideoError("Failed to extract video info")

            # Check duration
            duration = info.get('duration', 0)
            if duration > max_duration_seconds:
                print(f"[SKIP] Video too long: {duration}s (max: {max_duration_seconds}s)")
                return None

            # Check filesize estimate
            filesize = info.get('filesize', 0) or info.get('filesize_approx', 0)
            if filesize and filesize > max_filesize_mb * 1024 * 1024:
                print(f"[SKIP] Video too large: {filesize / (1024*1024):.1f}MB (max: {max_filesize_mb}MB)")
                return None

            # Download the video
            print(f"[DOWNLOAD] Downloading video: {info.get('title', 'Unknown')}")
            ydl.download([video_url])

            # Get the downloaded file path
            video_id = info.get('id')
            ext = info.get('ext', 'mp4')
            file_path = os.path.join(output_dir, f"{video_id}.{ext}")

            if not os.path.exists(file_path):
                raise YouTubeVideoError(f"Downloaded file not found: {file_path}")

            return {
                'video_id': video_id,
                'title': info.get('title'),
                'duration_seconds': duration,
                'file_path': file_path,
                'file_size_mb': os.path.getsize(file_path) / (1024 * 1024),
                'width': info.get('width'),
                'height': info.get('height'),
                'description': info.get('description'),
                'upload_date': info.get('upload_date'),
                'view_count': info.get('view_count', 0),
                'like_count': info.get('like_count', 0),
            }

    except yt_dlp.utils.DownloadError as e:
        print(f"[ERROR] Download failed: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected error downloading video: {e}")
        return None


def get_video_content(
    video_url: str,
    mode: str = "transcript",
    download_dir: Optional[str] = None,
    max_duration_seconds: int = 600,
    max_filesize_mb: int = 100
) -> Tuple[Optional[str], Optional[Dict]]:
    """
    Get video content - either transcript or full video download

    Args:
        video_url: YouTube video URL
        mode: "transcript" for text only, "full" for video download, "auto" to try transcript first
        download_dir: Directory for video downloads (required if mode is "full" or "auto")
        max_duration_seconds: Max video duration
        max_filesize_mb: Max file size

    Returns:
        Tuple of (file_path or None, metadata dict)
    """
    metadata = {
        'video_url': video_url,
        'video_id': extract_video_id(video_url),
        'mode': mode,
        'transcript_available': False,
        'video_downloaded': False,
    }

    if mode == "transcript":
        # Transcript-only mode
        transcript_data = get_video_transcript(video_url)
        if transcript_data:
            metadata.update({
                'transcript_available': True,
                'transcript': transcript_data['transcript'],
                'language': transcript_data['language'],
                'is_generated': transcript_data['is_generated'],
                'duration_seconds': transcript_data['duration_seconds']
            })
            return None, metadata
        else:
            print(f"[WARN] No transcript available for: {video_url}")
            return None, metadata

    elif mode == "full":
        # Full video download mode
        if not download_dir:
            raise ValueError("download_dir required for full video mode")

        download_info = download_video(video_url, download_dir, max_duration_seconds, max_filesize_mb)
        if download_info:
            metadata.update({
                'video_downloaded': True,
                'file_path': download_info['file_path'],
                'duration_seconds': download_info['duration_seconds'],
                'file_size_mb': download_info['file_size_mb'],
                'title': download_info['title'],
            })
            return download_info['file_path'], metadata
        else:
            print(f"[WARN] Failed to download video: {video_url}")
            return None, metadata

    elif mode == "auto":
        # Auto mode: Try transcript first, fallback to download
        if not download_dir:
            raise ValueError("download_dir required for auto mode")

        # Try transcript first (faster, cheaper)
        transcript_data = get_video_transcript(video_url)
        # Check if transcript is substantial enough (at least 100 characters)
        # Short transcripts (< 100 chars) are often YouTube Shorts with minimal captions
        if transcript_data and len(transcript_data['transcript']) >= 100:
            metadata.update({
                'transcript_available': True,
                'transcript': transcript_data['transcript'],
                'language': transcript_data['language'],
                'is_generated': transcript_data['is_generated'],
                'duration_seconds': transcript_data['duration_seconds'],
                'analysis_method': 'transcript'
            })
            return None, metadata
        elif transcript_data and len(transcript_data['transcript']) < 100:
            print(f"[INFO] Transcript too short ({len(transcript_data['transcript'])} chars), attempting video download...")
        else:
            print(f"[INFO] No transcript available, attempting video download...")

        # Fallback to full video download
        download_info = download_video(video_url, download_dir, max_duration_seconds, max_filesize_mb)
        if download_info:
            metadata.update({
                'video_downloaded': True,
                'file_path': download_info['file_path'],
                'duration_seconds': download_info['duration_seconds'],
                'file_size_mb': download_info['file_size_mb'],
                'title': download_info['title'],
                'analysis_method': 'full_video'
            })
            return download_info['file_path'], metadata
        else:
            print(f"[ERROR] Both transcript and download failed for: {video_url}")
            return None, metadata

    else:
        raise ValueError(f"Invalid mode: {mode}. Must be 'transcript', 'full', or 'auto'")


def cleanup_video_file(file_path: str) -> bool:
    """
    Delete downloaded video file

    Args:
        file_path: Path to video file

    Returns:
        True if deleted successfully
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            return True
        return False
    except Exception as e:
        print(f"[ERROR] Failed to delete video file: {e}")
        return False
