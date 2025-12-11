"""
Platform API clients and data fetchers for social media platforms
"""

import time
import json
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta
from abc import ABC, abstractmethod

from config import (
    PLATFORM_CONFIGS,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    EXPONENTIAL_BACKOFF,
    DEFAULT_TIME_RANGE_DAYS
)


class PlatformClientError(Exception):
    """Custom exception for platform client errors"""
    pass


class PlatformClient(ABC):
    """Base class for platform API clients with unified interface"""

    def __init__(self, platform_name: str):
        """
        Initialize platform client

        Args:
            platform_name: Name of the platform (youtube, instagram, tiktok, twitch)
        """
        self.platform_name = platform_name
        self.config = PLATFORM_CONFIGS.get(platform_name, {})

    @abstractmethod
    def get_profile_stats(self, profile_url: str) -> Dict:
        """
        Get basic profile statistics

        Args:
            profile_url: URL to the creator's profile

        Returns:
            Dict with profile stats in unified format
        """
        pass

    @abstractmethod
    def get_recent_posts(self, profile_url: str, days: int = DEFAULT_TIME_RANGE_DAYS,
                        max_posts: int = 50) -> List[Dict]:
        """
        Get recent posts from a creator

        Args:
            profile_url: URL to the creator's profile
            days: Number of days to look back
            max_posts: Maximum number of posts to retrieve

        Returns:
            List of post dictionaries in unified format
        """
        pass

    def _retry_with_backoff(self, func: Callable, *args, **kwargs):
        """
        Retry a function with exponential backoff

        Args:
            func: Function to retry
            *args, **kwargs: Arguments to pass to function

        Returns:
            Result from function

        Raises:
            PlatformClientError: If all retries fail
        """
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e

                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_SECONDS
                    if EXPONENTIAL_BACKOFF:
                        delay *= (2 ** attempt)

                    print(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay}s...")
                    time.sleep(delay)

        raise PlatformClientError(f"Failed after {MAX_RETRIES} attempts: {last_error}")


class YouTubeClient(PlatformClient):
    """YouTube Data API v3 client"""

    def __init__(self, api_keys: List[str] = None):
        """
        Initialize YouTube client

        Args:
            api_keys: List of YouTube API keys for rotation
        """
        super().__init__("youtube")
        self.api_keys = api_keys or []
        self.current_key_index = 0
        self.quota_used = {key: 0 for key in self.api_keys}

        # Try importing YouTube API
        try:
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
            self.build = build
            self.HttpError = HttpError
            self.api_available = True
        except ImportError:
            print("YouTube API library not installed. Install with: pip install google-api-python-client")
            self.api_available = False

    def _get_youtube_service(self):
        """Get YouTube API service with current key"""
        if not self.api_available:
            raise PlatformClientError("YouTube API library not installed")

        if not self.api_keys:
            raise PlatformClientError("No YouTube API keys configured")

        current_key = self.api_keys[self.current_key_index]
        return self.build('youtube', 'v3', developerKey=current_key)

    def _rotate_api_key(self):
        """Rotate to next available API key"""
        if len(self.api_keys) <= 1:
            raise PlatformClientError("No additional API keys available for rotation")

        self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
        print(f"Rotated to API key {self.current_key_index + 1}")

    def _extract_channel_id(self, url: str) -> str:
        """
        Extract channel ID from YouTube URL

        Args:
            url: YouTube channel URL

        Returns:
            Channel ID or handle
        """
        # Handle different YouTube URL formats
        # https://www.youtube.com/channel/UCxxxxx
        # https://www.youtube.com/c/channelname
        # https://www.youtube.com/@handle
        # https://youtube.com/user/username

        url = url.rstrip('/')

        if '/channel/' in url:
            return url.split('/channel/')[-1].split('?')[0]
        elif '/@' in url:
            return url.split('/@')[-1].split('?')[0]
        elif '/c/' in url:
            return url.split('/c/')[-1].split('?')[0]
        elif '/user/' in url:
            return url.split('/user/')[-1].split('?')[0]
        else:
            # Assume it's just the handle/ID
            return url.split('/')[-1].split('?')[0]

    def _search_channel_by_handle(self, handle: str) -> Optional[str]:
        """Search for channel ID by handle or username"""
        try:
            youtube = self._get_youtube_service()

            # Try search API
            request = youtube.search().list(
                part='snippet',
                q=handle,
                type='channel',
                maxResults=1
            )
            response = request.execute()

            if response.get('items'):
                return response['items'][0]['snippet']['channelId']

            return None
        except Exception as e:
            print(f"Error searching for channel: {e}")
            return None

    def get_profile_stats(self, profile_url: str) -> Dict:
        """
        Get YouTube channel statistics

        Args:
            profile_url: YouTube channel URL

        Returns:
            Dict with unified profile stats
        """
        if not self.api_available:
            raise PlatformClientError("YouTube API not available")

        def _fetch_stats():
            youtube = self._get_youtube_service()
            channel_id = self._extract_channel_id(profile_url)

            # If it's a handle, search for the channel ID
            if channel_id.startswith('@') or not channel_id.startswith('UC'):
                channel_id = self._search_channel_by_handle(channel_id)
                if not channel_id:
                    raise PlatformClientError(f"Could not find channel for: {profile_url}")

            # Get channel statistics
            request = youtube.channels().list(
                part='snippet,statistics,contentDetails',
                id=channel_id
            )
            response = request.execute()

            if not response.get('items'):
                raise PlatformClientError(f"Channel not found: {channel_id}")

            channel = response['items'][0]
            snippet = channel['snippet']
            stats = channel['statistics']

            # Track quota usage
            self.quota_used[self.api_keys[self.current_key_index]] += 1

            return {
                'platform': 'youtube',
                'platform_user_id': channel_id,
                'handle': snippet.get('customUrl', ''),
                'name': snippet['title'],
                'description': snippet.get('description', ''),
                'profile_image_url': snippet['thumbnails']['high']['url'],
                'verified': False,  # YouTube API doesn't expose verification status easily
                'followers_count': int(stats.get('subscriberCount', 0)),
                'total_posts': int(stats.get('videoCount', 0)),
                'total_views': int(stats.get('viewCount', 0)),
                'created_at': snippet.get('publishedAt', ''),
                'raw_data': channel
            }

        return self._retry_with_backoff(_fetch_stats)

    def get_recent_posts(self, profile_url: str, days: int = DEFAULT_TIME_RANGE_DAYS,
                        max_posts: int = 50) -> List[Dict]:
        """
        Get recent videos from a YouTube channel

        Args:
            profile_url: YouTube channel URL
            days: Number of days to look back
            max_posts: Maximum number of videos to retrieve

        Returns:
            List of video dictionaries
        """
        if not self.api_available:
            raise PlatformClientError("YouTube API not available")

        def _fetch_videos():
            youtube = self._get_youtube_service()
            channel_id = self._extract_channel_id(profile_url)

            # If it's a handle, search for the channel ID
            if channel_id.startswith('@') or not channel_id.startswith('UC'):
                channel_id = self._search_channel_by_handle(channel_id)
                if not channel_id:
                    raise PlatformClientError(f"Could not find channel for: {profile_url}")

            # Calculate date threshold
            date_threshold = (datetime.now() - timedelta(days=days)).isoformat() + 'Z'

            # Get uploads playlist ID
            channel_request = youtube.channels().list(
                part='contentDetails',
                id=channel_id
            )
            channel_response = channel_request.execute()

            if not channel_response.get('items'):
                raise PlatformClientError(f"Channel not found: {channel_id}")

            uploads_playlist = channel_response['items'][0]['contentDetails']['relatedPlaylists']['uploads']

            # Get videos from uploads playlist
            videos = []
            next_page_token = None

            while len(videos) < max_posts:
                playlist_request = youtube.playlistItems().list(
                    part='snippet,contentDetails',
                    playlistId=uploads_playlist,
                    maxResults=min(50, max_posts - len(videos)),
                    pageToken=next_page_token
                )
                playlist_response = playlist_request.execute()

                self.quota_used[self.api_keys[self.current_key_index]] += 1

                # Filter videos by date and collect video IDs
                video_ids = []
                for item in playlist_response.get('items', []):
                    published_at = item['snippet']['publishedAt']
                    if published_at >= date_threshold:
                        video_ids.append(item['contentDetails']['videoId'])

                # Get detailed statistics for these videos
                if video_ids:
                    video_request = youtube.videos().list(
                        part='snippet,statistics,contentDetails',
                        id=','.join(video_ids)
                    )
                    video_response = video_request.execute()

                    self.quota_used[self.api_keys[self.current_key_index]] += 1

                    for video in video_response.get('items', []):
                        snippet = video['snippet']
                        stats = video['statistics']
                        content = video['contentDetails']

                        videos.append({
                            'post_id': video['id'],
                            'post_url': f"https://www.youtube.com/watch?v={video['id']}",
                            'post_date': snippet['publishedAt'],
                            'post_type': 'video',
                            'caption': snippet.get('description', ''),
                            'title': snippet['title'],
                            'likes_count': int(stats.get('likeCount', 0)),
                            'comments_count': int(stats.get('commentCount', 0)),
                            'views_count': int(stats.get('viewCount', 0)),
                            'duration': content.get('duration', ''),
                            'thumbnail_url': snippet['thumbnails']['high']['url'],
                            'raw_data': video
                        })

                # Check if there are more pages
                next_page_token = playlist_response.get('nextPageToken')
                if not next_page_token or len(videos) >= max_posts:
                    break

            return videos[:max_posts]

        return self._retry_with_backoff(_fetch_videos)

    def get_quota_usage(self) -> Dict:
        """Get current quota usage per API key"""
        return self.quota_used.copy()


class InstagramClient(PlatformClient):
    """Instagram client (primarily web scraping, Graph API optional)"""

    def __init__(self):
        super().__init__("instagram")

    def get_profile_stats(self, profile_url: str) -> Dict:
        """
        Get Instagram profile statistics

        Note: This is a placeholder. Actual implementation will use web scraping
        or Instagram Graph API (requires business account)
        """
        raise NotImplementedError("Instagram scraping to be implemented in web_scraper.py")

    def get_recent_posts(self, profile_url: str, days: int = DEFAULT_TIME_RANGE_DAYS,
                        max_posts: int = 50) -> List[Dict]:
        """Get recent Instagram posts"""
        raise NotImplementedError("Instagram scraping to be implemented in web_scraper.py")


class TikTokClient(PlatformClient):
    """TikTok client (primarily web scraping)"""

    def __init__(self):
        super().__init__("tiktok")

    def get_profile_stats(self, profile_url: str) -> Dict:
        """Get TikTok profile statistics"""
        raise NotImplementedError("TikTok scraping to be implemented in web_scraper.py")

    def get_recent_posts(self, profile_url: str, days: int = DEFAULT_TIME_RANGE_DAYS,
                        max_posts: int = 50) -> List[Dict]:
        """Get recent TikTok posts"""
        raise NotImplementedError("TikTok scraping to be implemented in web_scraper.py")


class TwitchClient(PlatformClient):
    """Twitch API client"""

    def __init__(self, client_id: str = "", client_secret: str = ""):
        super().__init__("twitch")
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None

    def get_profile_stats(self, profile_url: str) -> Dict:
        """Get Twitch channel statistics"""
        raise NotImplementedError("Twitch API integration to be implemented")

    def get_recent_posts(self, profile_url: str, days: int = DEFAULT_TIME_RANGE_DAYS,
                        max_posts: int = 50) -> List[Dict]:
        """Get recent Twitch streams/VODs"""
        raise NotImplementedError("Twitch API integration to be implemented")


# Factory function to get appropriate client
def get_platform_client(platform: str, **kwargs) -> PlatformClient:
    """
    Get platform client instance

    Args:
        platform: Platform name (youtube, instagram, tiktok, twitch)
        **kwargs: Platform-specific configuration

    Returns:
        PlatformClient instance
    """
    platform = platform.lower()

    if platform == 'youtube':
        api_keys = kwargs.get('api_keys', [])
        return YouTubeClient(api_keys=api_keys)
    elif platform == 'instagram':
        return InstagramClient()
    elif platform == 'tiktok':
        return TikTokClient()
    elif platform == 'twitch':
        client_id = kwargs.get('client_id', '')
        client_secret = kwargs.get('client_secret', '')
        return TwitchClient(client_id=client_id, client_secret=client_secret)
    else:
        raise ValueError(f"Unsupported platform: {platform}")
