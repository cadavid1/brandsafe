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
    """Instagram client using Instaloader library"""

    def __init__(self, username: str = None, password: str = None, session_file: str = None):
        super().__init__("instagram")
        self._loader = None
        self._last_request_time = 0
        self._min_request_interval = 2  # Reduce to 2 seconds when logged in
        self.username = username
        self.password = password
        self.session_file = session_file or "./data/.instagram_session"
        self._is_logged_in = False

        # Try importing Instaloader
        try:
            import instaloader
            self.instaloader = instaloader
            self.api_available = True
        except ImportError:
            print("Instaloader not installed. Install with: pip install instaloader")
            self.api_available = False

    def _get_loader(self):
        """Get or create Instaloader instance with optional login"""
        if not self.api_available:
            raise PlatformClientError("Instaloader library not installed")

        if self._loader is None:
            self._loader = self.instaloader.Instaloader(
                quiet=True,
                download_pictures=False,
                download_videos=False,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                compress_json=False,
                max_connection_attempts=1  # Fail fast on connection errors
            )

            # Try to load session or login
            if not self._is_logged_in:
                try:
                    # Try loading saved session first
                    import os
                    if os.path.exists(self.session_file) and self.username:
                        self._loader.load_session_from_file(self.username, self.session_file)
                        print(f"  [INFO] Loaded Instagram session for @{self.username}")
                        self._is_logged_in = True
                    elif self.username and self.password:
                        # Login with credentials
                        print(f"  [INFO] Logging into Instagram as @{self.username}...")
                        self._loader.login(self.username, self.password)
                        self._loader.save_session_to_file(self.session_file)
                        print(f"  [SUCCESS] Instagram login successful")
                        self._is_logged_in = True
                    else:
                        print(f"  [WARNING] No Instagram credentials - using anonymous access (limited)")
                except Exception as e:
                    print(f"  [WARNING] Instagram login failed: {e}")
                    print(f"  [INFO] Continuing with anonymous access (limited)")

        return self._loader

    def _rate_limit(self):
        """Enforce rate limiting to avoid Instagram blocks"""
        current_time = time.time()
        time_since_last_request = current_time - self._last_request_time

        if time_since_last_request < self._min_request_interval:
            sleep_time = self._min_request_interval - time_since_last_request
            print(f"  [RATE LIMIT] Waiting {sleep_time:.1f}s before next request...")
            time.sleep(sleep_time)

        self._last_request_time = time.time()

    def _extract_username(self, profile_url: str) -> str:
        """Extract username from Instagram URL"""
        # Handle different Instagram URL formats
        # https://www.instagram.com/username/
        # https://instagram.com/username
        # instagram.com/username

        url = profile_url.rstrip('/')

        if 'instagram.com/' in url:
            username = url.split('instagram.com/')[-1].split('?')[0].split('/')[0]
            return username
        else:
            # Assume it's just the username
            return url.strip('@')

    def get_profile_stats(self, profile_url: str) -> Dict:
        """
        Get Instagram profile statistics using Instaloader

        Args:
            profile_url: Instagram profile URL or username

        Returns:
            Dict with unified profile stats
        """
        if not self.api_available:
            raise PlatformClientError("Instaloader not available")

        def _fetch_stats():
            self._rate_limit()

            loader = self._get_loader()
            username = self._extract_username(profile_url)

            try:
                # Get profile
                profile = self.instaloader.Profile.from_username(loader.context, username)

                # Check if profile is private
                is_private = profile.is_private

                return {
                    'platform': 'instagram',
                    'platform_user_id': str(profile.userid),
                    'handle': f"@{profile.username}",
                    'name': profile.full_name or profile.username,
                    'description': profile.biography or '',
                    'profile_image_url': profile.profile_pic_url,
                    'verified': profile.is_verified,
                    'followers_count': profile.followers,
                    'following_count': profile.followees,
                    'total_posts': profile.mediacount,
                    'is_private': is_private,
                    'is_business': profile.is_business_account,
                    'created_at': '',  # Not available via Instaloader
                    'raw_data': {
                        'username': profile.username,
                        'full_name': profile.full_name,
                        'biography': profile.biography,
                        'external_url': profile.external_url,
                        'is_private': is_private,
                        'is_verified': profile.is_verified,
                        'is_business_account': profile.is_business_account,
                    }
                }
            except self.instaloader.exceptions.ProfileNotExistsException:
                raise PlatformClientError(f"Instagram profile not found: {username}")
            except self.instaloader.exceptions.ConnectionException as e:
                raise PlatformClientError(f"Instagram connection error: {e}")
            except Exception as e:
                raise PlatformClientError(f"Instagram error: {e}")

        return self._retry_with_backoff(_fetch_stats)

    def get_recent_posts(self, profile_url: str, days: int = DEFAULT_TIME_RANGE_DAYS,
                        max_posts: int = 50) -> List[Dict]:
        """
        Get recent Instagram posts using Instaloader

        Args:
            profile_url: Instagram profile URL or username
            days: Number of days to look back
            max_posts: Maximum number of posts to retrieve

        Returns:
            List of post dictionaries
        """
        if not self.api_available:
            raise PlatformClientError("Instaloader not available")

        def _fetch_posts():
            self._rate_limit()

            loader = self._get_loader()
            username = self._extract_username(profile_url)

            try:
                # Get profile
                profile = self.instaloader.Profile.from_username(loader.context, username)

                # Check if profile is private
                if profile.is_private:
                    print(f"  [WARNING] Profile @{username} is private, cannot fetch posts")
                    return []

                # Calculate date threshold
                date_threshold = datetime.now() - timedelta(days=days)

                posts = []
                post_count = 0
                error_count = 0
                consecutive_errors = 0
                max_consecutive_errors = 5  # Stop after 5 consecutive errors
                max_total_errors = 20  # Allow more total errors if we get some successes

                # Iterate through posts
                for post in profile.get_posts():
                    # Stop if too many consecutive errors (likely being blocked)
                    if consecutive_errors >= max_consecutive_errors:
                        print(f"  [WARNING] Too many consecutive errors ({consecutive_errors}), stopping post fetch")
                        if post_count > 0:
                            print(f"  [INFO] Successfully fetched {post_count} posts before errors")
                        else:
                            print(f"  [ERROR] Unable to fetch any posts - Instagram may be blocking requests")
                            print(f"  [SUGGESTION] Try again later or configure Instagram credentials in settings")
                        break

                    # Stop if too many total errors
                    if error_count >= max_total_errors:
                        print(f"  [WARNING] Too many total errors ({error_count}), stopping post fetch")
                        print(f"  [INFO] Successfully fetched {post_count} posts")
                        break

                    # Stop if we have enough posts
                    if post_count >= max_posts:
                        break

                    # Stop if post is too old
                    if post.date_utc < date_threshold:
                        break

                    # Rate limit between post fetches
                    if post_count > 0 and post_count % 5 == 0:
                        print(f"  [PROGRESS] Fetched {post_count} posts...")
                        time.sleep(2)  # Small delay every 5 posts

                    try:
                        # Determine post type
                        if post.is_video:
                            post_type = 'video'
                        elif post.typename == 'GraphSidecar':
                            post_type = 'carousel'
                        else:
                            post_type = 'image'

                        posts.append({
                            'post_id': post.shortcode,
                            'post_url': f"https://www.instagram.com/p/{post.shortcode}/",
                            'post_date': post.date_utc.isoformat() + 'Z',
                            'post_type': post_type,
                            'caption': post.caption or '',
                            'title': '',  # Instagram doesn't have titles
                            'likes_count': post.likes,
                            'comments_count': post.comments,
                            'views_count': post.video_view_count if post.is_video else 0,
                            'thumbnail_url': post.url,
                            'hashtags': post.caption_hashtags if post.caption else [],
                            'raw_data': {
                                'shortcode': post.shortcode,
                                'typename': post.typename,
                                'is_video': post.is_video,
                                'video_duration': post.video_duration if post.is_video else 0,
                            }
                        })

                        post_count += 1
                        consecutive_errors = 0  # Reset consecutive error count on success

                    except self.instaloader.exceptions.QueryReturnedForbiddenException as e:
                        error_count += 1
                        consecutive_errors += 1
                        print(f"  [WARNING] 403 Forbidden - Instagram blocking request (consecutive: {consecutive_errors}/{max_consecutive_errors}, total: {error_count})")

                        # Exponential backoff on 403s
                        wait_time = min(30, 5 * consecutive_errors)
                        time.sleep(wait_time)
                        continue

                    except self.instaloader.exceptions.ConnectionException as e:
                        error_count += 1
                        consecutive_errors += 1
                        print(f"  [WARNING] Connection error: {str(e)[:100]}")
                        time.sleep(3)
                        continue

                    except Exception as post_error:
                        error_count += 1
                        consecutive_errors += 1
                        error_msg = str(post_error)

                        # Check for rate limiting indicators
                        if "429" in error_msg or "rate limit" in error_msg.lower():
                            print(f"  [WARNING] Rate limited by Instagram - waiting longer...")
                            time.sleep(30)
                        else:
                            print(f"  [WARNING] Error fetching post: {error_msg[:100]}")
                            time.sleep(3)
                        continue

                if post_count > 0:
                    print(f"  [SUCCESS] Fetched {post_count} posts total")
                elif error_count > 0:
                    print(f"  [WARNING] No posts fetched due to {error_count} errors")

                return posts

            except self.instaloader.exceptions.ProfileNotExistsException:
                raise PlatformClientError(f"Instagram profile not found: {username}")
            except self.instaloader.exceptions.LoginRequiredException:
                raise PlatformClientError(f"Instagram requires login to view posts from @{username}")
            except self.instaloader.exceptions.ConnectionException as e:
                # If we get connection errors at the profile level, don't retry
                error_msg = str(e)
                if "403" in error_msg or "Forbidden" in error_msg:
                    print(f"  [ERROR] Instagram blocked the request - please try again later or configure authentication")
                    return []  # Return empty instead of raising to continue with other platforms
                raise PlatformClientError(f"Instagram connection error: {e}")
            except KeyboardInterrupt:
                print(f"  [INTERRUPTED] Stopping Instagram fetch, returning {post_count} posts")
                return posts
            except Exception as e:
                error_msg = str(e)
                if "403" in error_msg or "Forbidden" in error_msg:
                    print(f"  [ERROR] Instagram access denied - please configure Instagram credentials or try again later")
                    return []  # Return empty instead of raising
                raise PlatformClientError(f"Instagram error: {e}")

        # Override retry logic for Instagram - only retry on non-403 errors
        try:
            return _fetch_posts()
        except PlatformClientError as e:
            # Check if it's a 403/blocking error
            error_msg = str(e)
            if "403" in error_msg or "Forbidden" in error_msg or "blocked" in error_msg.lower():
                print(f"  [ERROR] {e}")
                return []  # Return empty list instead of failing
            # For other errors, use standard retry logic
            return self._retry_with_backoff(_fetch_posts)


class TikTokClient(PlatformClient):
    """TikTok client using TikTokApi library with Playwright"""

    def __init__(self):
        super().__init__("tiktok")
        self._api = None

        # Try importing TikTokApi
        try:
            from TikTokApi import TikTokApi
            self.TikTokApi = TikTokApi
            self.api_available = True
        except ImportError:
            print("TikTokApi not installed. Install with: pip install TikTokApi playwright && python -m playwright install")
            self.api_available = False

    def _get_api(self):
        """Get or create TikTokApi instance"""
        if not self.api_available:
            raise PlatformClientError("TikTokApi library not installed")

        if self._api is None:
            self._api = self.TikTokApi()
        return self._api

    def _extract_username(self, profile_url: str) -> str:
        """Extract username from TikTok URL"""
        # Handle different TikTok URL formats
        # https://www.tiktok.com/@username
        # https://tiktok.com/@username
        # tiktok.com/@username
        # @username

        url = profile_url.rstrip('/')

        if 'tiktok.com/@' in url:
            username = url.split('/@')[-1].split('?')[0].split('/')[0]
            return username
        elif url.startswith('@'):
            return url[1:]  # Remove @ symbol
        else:
            # Assume it's just the username
            return url.strip('@')

    async def _fetch_user_async(self, username: str):
        """Async method to fetch TikTok user data"""
        api = self._get_api()

        async with api:
            user = api.user(username)
            user_data = await user.info()

            # Get user stats
            stats = user_data.get('stats', {})
            user_info = user_data.get('user', {})

            return {
                'platform': 'tiktok',
                'platform_user_id': user_info.get('id', ''),
                'handle': f"@{username}",
                'name': user_info.get('nickname', username),
                'description': user_info.get('signature', ''),
                'profile_image_url': user_info.get('avatarLarger', ''),
                'verified': user_info.get('verified', False),
                'followers_count': stats.get('followerCount', 0),
                'following_count': stats.get('followingCount', 0),
                'total_posts': stats.get('videoCount', 0),
                'total_views': stats.get('heartCount', 0),  # Total likes on TikTok
                'created_at': '',  # Not easily available
                'raw_data': user_data
            }

    async def _fetch_videos_async(self, username: str, days: int, max_posts: int):
        """Async method to fetch TikTok videos"""
        api = self._get_api()

        async with api:
            user = api.user(username)

            # Calculate date threshold
            date_threshold = datetime.now() - timedelta(days=days)

            videos = []
            video_count = 0

            async for video in user.videos(count=max_posts):
                if video_count >= max_posts:
                    break

                # Get video creation time
                create_time = video.get('createTime', 0)
                if create_time > 0:
                    video_date = datetime.fromtimestamp(create_time)
                    if video_date < date_threshold:
                        break
                else:
                    video_date = datetime.now()

                # Get video stats
                stats = video.get('stats', {})
                video_id = video.get('id', '')

                videos.append({
                    'post_id': video_id,
                    'post_url': f"https://www.tiktok.com/@{username}/video/{video_id}",
                    'post_date': video_date.isoformat() + 'Z',
                    'post_type': 'video',
                    'caption': video.get('desc', ''),
                    'title': '',  # TikTok doesn't have separate titles
                    'likes_count': stats.get('diggCount', 0),
                    'comments_count': stats.get('commentCount', 0),
                    'shares_count': stats.get('shareCount', 0),
                    'views_count': stats.get('playCount', 0),
                    'duration': video.get('video', {}).get('duration', 0),
                    'thumbnail_url': video.get('video', {}).get('cover', ''),
                    'hashtags': [tag.get('name', '') for tag in video.get('challenges', [])],
                    'raw_data': video
                })

                video_count += 1

            return videos

    def get_profile_stats(self, profile_url: str) -> Dict:
        """
        Get TikTok profile statistics using TikTokApi

        Args:
            profile_url: TikTok profile URL or username

        Returns:
            Dict with unified profile stats
        """
        if not self.api_available:
            raise PlatformClientError("TikTokApi not available")

        def _fetch_stats():
            import asyncio

            username = self._extract_username(profile_url)

            try:
                # Run async function
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self._fetch_user_async(username))
                loop.close()
                return result

            except Exception as e:
                raise PlatformClientError(f"TikTok error fetching profile: {e}")

        return self._retry_with_backoff(_fetch_stats)

    def get_recent_posts(self, profile_url: str, days: int = DEFAULT_TIME_RANGE_DAYS,
                        max_posts: int = 50) -> List[Dict]:
        """
        Get recent TikTok videos using TikTokApi

        Args:
            profile_url: TikTok profile URL or username
            days: Number of days to look back
            max_posts: Maximum number of videos to retrieve

        Returns:
            List of video dictionaries
        """
        if not self.api_available:
            raise PlatformClientError("TikTokApi not available")

        def _fetch_videos():
            import asyncio

            username = self._extract_username(profile_url)

            try:
                # Run async function
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                result = loop.run_until_complete(self._fetch_videos_async(username, days, max_posts))
                loop.close()
                return result

            except Exception as e:
                raise PlatformClientError(f"TikTok error fetching videos: {e}")

        return self._retry_with_backoff(_fetch_videos)


class TwitchClient(PlatformClient):
    """Twitch Helix API client"""

    def __init__(self, client_id: str = "", client_secret: str = ""):
        super().__init__("twitch")
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
        self.token_expires_at = 0

        # Try importing requests
        try:
            import requests
            self.requests = requests
            self.api_available = True
        except ImportError:
            print("Requests library not installed. Install with: pip install requests")
            self.api_available = False

    def _get_access_token(self):
        """Get OAuth2 access token for Twitch API"""
        if not self.api_available:
            raise PlatformClientError("Requests library not installed")

        if not self.client_id or not self.client_secret:
            raise PlatformClientError("Twitch client_id and client_secret required")

        # Check if token is still valid
        current_time = time.time()
        if self.access_token and current_time < self.token_expires_at:
            return self.access_token

        # Request new token
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'grant_type': 'client_credentials'
        }

        try:
            response = self.requests.post(url, params=params)
            response.raise_for_status()
            data = response.json()

            self.access_token = data['access_token']
            # Set expiration time (with 60 second buffer)
            self.token_expires_at = current_time + data['expires_in'] - 60

            return self.access_token

        except Exception as e:
            raise PlatformClientError(f"Failed to get Twitch access token: {e}")

    def _make_api_request(self, endpoint: str, params: dict = None):
        """Make authenticated request to Twitch Helix API"""
        if not self.api_available:
            raise PlatformClientError("Requests library not installed")

        token = self._get_access_token()
        url = f"https://api.twitch.tv/helix/{endpoint}"

        headers = {
            'Client-ID': self.client_id,
            'Authorization': f'Bearer {token}'
        }

        try:
            response = self.requests.get(url, headers=headers, params=params or {})
            response.raise_for_status()
            return response.json()
        except self.requests.exceptions.HTTPError as e:
            raise PlatformClientError(f"Twitch API error: {e}")
        except Exception as e:
            raise PlatformClientError(f"Twitch request failed: {e}")

    def _extract_username(self, profile_url: str) -> str:
        """Extract username from Twitch URL"""
        # Handle different Twitch URL formats
        # https://www.twitch.tv/username
        # https://twitch.tv/username
        # twitch.tv/username

        url = profile_url.rstrip('/')

        if 'twitch.tv/' in url:
            username = url.split('twitch.tv/')[-1].split('?')[0].split('/')[0]
            return username
        else:
            # Assume it's just the username
            return url

    def get_profile_stats(self, profile_url: str) -> Dict:
        """
        Get Twitch channel statistics using Helix API

        Args:
            profile_url: Twitch channel URL or username

        Returns:
            Dict with unified profile stats
        """
        if not self.api_available:
            raise PlatformClientError("Requests library not available")

        def _fetch_stats():
            username = self._extract_username(profile_url)

            # Get user info
            user_data = self._make_api_request('users', {'login': username})

            if not user_data.get('data'):
                raise PlatformClientError(f"Twitch user not found: {username}")

            user = user_data['data'][0]
            user_id = user['id']

            # Get follower count
            follower_data = self._make_api_request('channels/followers', {'broadcaster_id': user_id})
            follower_count = follower_data.get('total', 0)

            # Get channel info for additional details
            channel_data = self._make_api_request('channels', {'broadcaster_id': user_id})
            channel = channel_data['data'][0] if channel_data.get('data') else {}

            return {
                'platform': 'twitch',
                'platform_user_id': user_id,
                'handle': user['login'],
                'name': user['display_name'],
                'description': user['description'],
                'profile_image_url': user['profile_image_url'],
                'verified': user['broadcaster_type'] in ['partner', 'affiliate'],
                'followers_count': follower_count,
                'following_count': 0,  # Not available in Helix API
                'total_posts': 0,  # Videos/VODs fetched separately
                'total_views': user.get('view_count', 0),
                'created_at': user['created_at'],
                'raw_data': {
                    'user': user,
                    'channel': channel,
                    'broadcaster_type': user['broadcaster_type'],
                }
            }

        return self._retry_with_backoff(_fetch_stats)

    def get_recent_posts(self, profile_url: str, days: int = DEFAULT_TIME_RANGE_DAYS,
                        max_posts: int = 50) -> List[Dict]:
        """
        Get recent Twitch streams/VODs using Helix API

        Args:
            profile_url: Twitch channel URL or username
            days: Number of days to look back
            max_posts: Maximum number of VODs to retrieve

        Returns:
            List of VOD dictionaries
        """
        if not self.api_available:
            raise PlatformClientError("Requests library not available")

        def _fetch_vods():
            username = self._extract_username(profile_url)

            # Get user ID first
            user_data = self._make_api_request('users', {'login': username})

            if not user_data.get('data'):
                raise PlatformClientError(f"Twitch user not found: {username}")

            user_id = user_data['data'][0]['id']

            # Calculate date threshold
            date_threshold = datetime.now() - timedelta(days=days)

            # Get VODs
            vods = []
            params = {
                'user_id': user_id,
                'type': 'archive',  # Get archived broadcasts
                'first': min(100, max_posts)  # Max 100 per request
            }

            vod_data = self._make_api_request('videos', params)

            for video in vod_data.get('data', []):
                # Check date
                created_at = datetime.fromisoformat(video['created_at'].replace('Z', '+00:00'))
                if created_at.replace(tzinfo=None) < date_threshold:
                    break

                # Parse duration (format: 1h23m45s)
                duration_str = video.get('duration', '0s')
                duration_seconds = self._parse_duration(duration_str)

                vods.append({
                    'post_id': video['id'],
                    'post_url': video['url'],
                    'post_date': video['created_at'],
                    'post_type': 'stream' if video['type'] == 'archive' else 'clip',
                    'caption': video['description'],
                    'title': video['title'],
                    'likes_count': 0,  # Not available in Helix API
                    'comments_count': 0,  # Not available
                    'views_count': video['view_count'],
                    'duration': duration_seconds,
                    'thumbnail_url': video['thumbnail_url'].replace('%{width}', '640').replace('%{height}', '360'),
                    'raw_data': video
                })

                if len(vods) >= max_posts:
                    break

            return vods

        return self._retry_with_backoff(_fetch_vods)

    def _parse_duration(self, duration_str: str) -> int:
        """Parse Twitch duration string (e.g., '1h23m45s') to seconds"""
        import re

        hours = 0
        minutes = 0
        seconds = 0

        hour_match = re.search(r'(\d+)h', duration_str)
        if hour_match:
            hours = int(hour_match.group(1))

        minute_match = re.search(r'(\d+)m', duration_str)
        if minute_match:
            minutes = int(minute_match.group(1))

        second_match = re.search(r'(\d+)s', duration_str)
        if second_match:
            seconds = int(second_match.group(1))

        return hours * 3600 + minutes * 60 + seconds


# Factory function to get appropriate client
def get_platform_client(platform: str, **kwargs) -> PlatformClient:
    """
    Get platform client instance

    Args:
        platform: Platform name (youtube, instagram, tiktok, twitch)
        **kwargs: Platform-specific configuration
            - api_keys: List of YouTube API keys (YouTube only)
            - instagram_username: Instagram username for login (Instagram only)
            - instagram_password: Instagram password for login (Instagram only)
            - instagram_session_file: Path to session file (Instagram only)
            - client_id: Twitch client ID (Twitch only)
            - client_secret: Twitch client secret (Twitch only)

    Returns:
        PlatformClient instance
    """
    platform = platform.lower()

    if platform == 'youtube':
        api_keys = kwargs.get('api_keys', [])
        return YouTubeClient(api_keys=api_keys)
    elif platform == 'instagram':
        username = kwargs.get('instagram_username', kwargs.get('username'))
        password = kwargs.get('instagram_password', kwargs.get('password'))
        session_file = kwargs.get('instagram_session_file', kwargs.get('session_file'))
        return InstagramClient(username=username, password=password, session_file=session_file)
    elif platform == 'tiktok':
        return TikTokClient()
    elif platform == 'twitch':
        client_id = kwargs.get('client_id', kwargs.get('twitch_client_id', ''))
        client_secret = kwargs.get('client_secret', kwargs.get('twitch_client_secret', ''))
        return TwitchClient(client_id=client_id, client_secret=client_secret)
    else:
        raise ValueError(f"Unsupported platform: {platform}")
