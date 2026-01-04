"""
Creator analysis orchestration engine
Coordinates multi-platform data fetching, analysis, and report generation
"""

import json
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta

from storage import get_db
from platform_clients import get_platform_client, PlatformClientError
from gemini_client import GeminiClient, GeminiAPIError
from youtube_video_handler import get_video_content, cleanup_video_file, YouTubeVideoError
from deep_research_client import DeepResearchClient, DeepResearchError
from config import (
    ANALYSIS_TIERS,
    DEFAULT_TIME_RANGE_DAYS,
    CREATOR_ANALYSIS_SYSTEM_PROMPT,
    DEFAULT_MODEL,
    VIDEO_DOWNLOAD_PATH
)


def _debug_log_demographics(message: str, enabled: bool = None):
    """
    Print debug message for demographics tracking

    Args:
        message: Debug message to print
        enabled: Override for debug state (if None, checks database)
    """
    if enabled is None:
        try:
            db = get_db()
            # Try to get user_id from session state if available
            try:
                import streamlit as st
                if hasattr(st, 'session_state') and 'user_id' in st.session_state:
                    user_id = st.session_state.user_id
                else:
                    user_id = 1
            except:
                user_id = 1

            enabled = db.get_setting(user_id, "demographics_debug", "false") == "true"
        except:
            return

    if enabled:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [DEMOGRAPHICS] {message}")


def _debug_log_alignment(message: str, enabled: bool = None):
    """
    Print debug message for natural alignment scoring

    Args:
        message: Debug message to print
        enabled: Override for debug state (if None, checks database)
    """
    if enabled is None:
        try:
            db = get_db()
            # Try to get user_id from session state if available
            try:
                import streamlit as st
                if hasattr(st, 'session_state') and 'user_id' in st.session_state:
                    user_id = st.session_state.user_id
                else:
                    user_id = 1
            except:
                user_id = 1

            enabled = db.get_setting(user_id, "alignment_debug", "false") == "true"
        except:
            return

    if enabled:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [ALIGNMENT] {message}")


class CreatorAnalysisError(Exception):
    """Custom exception for creator analysis errors"""
    pass


class CreatorAnalyzer:
    """
    Orchestrates multi-step creator analysis:
    1. Fetch data from all platforms
    2. Analyze content themes/sentiment
    3. Calculate brand fit scores
    4. Generate report sections
    """

    def __init__(self, gemini_api_key: str, youtube_api_keys: List[str] = None):
        """
        Initialize creator analyzer

        Args:
            gemini_api_key: Gemini API key for content analysis and Deep Research
            youtube_api_keys: List of YouTube API keys for rotation
        """
        self.gemini_client = GeminiClient(gemini_api_key)
        self.deep_research_client = DeepResearchClient(gemini_api_key)
        self.youtube_api_keys = youtube_api_keys or []
        self.db = get_db()
        self._last_token_usage = None
        self._demographics_debug = False  # Will be set based on user settings
        self._deep_research_cost = 0.0

    def analyze_creator(
        self,
        creator_id: int,
        brief_id: int,
        time_range_days: int = DEFAULT_TIME_RANGE_DAYS,
        analysis_depth: str = "standard",
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict:
        """
        Complete creator analysis pipeline

        Args:
            creator_id: Creator ID to analyze
            brief_id: Brief ID for context
            time_range_days: Days to look back for posts
            analysis_depth: "quick", "standard", or "deep"
            progress_callback: Optional callback(message, progress_0_to_1)

        Returns:
            Analysis results dictionary
        """
        try:
            # Convert IDs to native Python int to avoid numpy type issues with SQLite
            creator_id = int(creator_id)
            brief_id = int(brief_id)

            print(f"\n{'='*60}")
            print(f"[ANALYSIS START] Creator ID: {creator_id}, Brief ID: {brief_id}")
            print(f"{'='*60}")

            # Step 1: Get creator and brief info (need this first to get user_id)
            if progress_callback:
                progress_callback("Loading creator information", 0.0)

            print(f"\n[STEP 1/5] Loading creator information...")
            creator = self.db.get_creator(creator_id)
            if not creator:
                raise CreatorAnalysisError(f"Creator not found: {creator_id}")
            print(f"[SUCCESS] Found creator: {creator['name']}")

            # Set user_id for settings lookups
            self.user_id = creator['user_id']

            # Get analysis tier config
            tier_config = ANALYSIS_TIERS.get(analysis_depth, ANALYSIS_TIERS["standard"]).copy()

            # Override max_posts with custom setting if available
            custom_max_posts_key = f"tier_{analysis_depth}_max_posts"
            custom_max_posts = self.db.get_setting(self.user_id, custom_max_posts_key, "")
            if custom_max_posts:
                tier_config['max_posts'] = int(custom_max_posts)

            print(f"[CONFIG] Analysis depth: {analysis_depth}")
            print(f"[CONFIG] Max posts per platform: {tier_config['max_posts']}")
            print(f"[CONFIG] Analyze videos: {tier_config['analyze_videos']}")

            # Fetch brief
            print(f"[STEP 1/5] Loading brief information...")
            brief = self.db.get_brief(brief_id)

            if not brief:
                raise CreatorAnalysisError(f"Brief not found: {brief_id}")
            print(f"[SUCCESS] Found brief: {brief['name']}")

            # Step 2: Get all social accounts for this creator
            if progress_callback:
                progress_callback("Fetching social accounts", 0.1)

            print(f"\n[STEP 2/5] Fetching social accounts...")
            accounts_df = self.db.get_social_accounts(creator_id)
            if accounts_df.empty:
                raise CreatorAnalysisError(f"No social accounts found for creator {creator['name']}")
            print(f"[SUCCESS] Found {len(accounts_df)} social account(s)")
            for _, acc in accounts_df.iterrows():
                print(f"  - {acc['platform']}: {acc['profile_url']}")

            # Step 3: Fetch platform data
            print(f"\n[STEP 3/5] Fetching platform data...")
            all_posts = []
            platform_stats = {}
            total_accounts = len(accounts_df)

            for idx, account in accounts_df.iterrows():
                account_progress = 0.1 + (idx / total_accounts) * 0.4
                platform = account['platform']
                profile_url = account['profile_url']
                account_id = account['id']

                if progress_callback:
                    progress_callback(f"Fetching {platform} data", account_progress)

                print(f"\n[PLATFORM] Processing {platform.upper()}...")
                print(f"  URL: {profile_url}")

                try:
                    # Get platform client with appropriate credentials
                    if platform == 'youtube':
                        print(f"  [INFO] Using YouTube API (keys available: {len(self.youtube_api_keys)})")
                        client = get_platform_client(platform, api_keys=self.youtube_api_keys)
                    elif platform == 'instagram':
                        # Get Instagram credentials from database
                        instagram_username = self.db.get_setting(creator['user_id'], "instagram_username", "")
                        instagram_password = self.db.get_setting(creator['user_id'], "instagram_password", "")

                        if instagram_username:
                            print(f"  [INFO] Using Instagram authenticated access (@{instagram_username})")
                        else:
                            print(f"  [INFO] Using Instagram anonymous access (limited)")

                        client = get_platform_client(
                            platform,
                            instagram_username=instagram_username,
                            instagram_password=instagram_password
                        )
                    else:
                        print(f"  [INFO] Using web scraping for {platform}")
                        client = get_platform_client(platform)

                    # Fetch profile stats
                    print(f"  [API CALL] Fetching profile stats...")
                    stats = client.get_profile_stats(profile_url)
                    platform_stats[platform] = stats
                    print(f"  [SUCCESS] Followers: {stats.get('followers_count', 'N/A')}, Posts: {stats.get('total_posts', 'N/A')}")

                    # Save analytics to database
                    analytics_data = {
                        'followers_count': stats.get('followers_count', 0),
                        'following_count': stats.get('following_count', 0),
                        'total_posts': stats.get('total_posts', 0),
                        'engagement_rate': 0.0,  # Will calculate from posts
                        'data_source': 'api',
                        'raw_data': stats
                    }
                    self.db.save_platform_analytics(account_id, analytics_data)
                    self.db.update_social_account_fetch_time(account_id)

                    # Fetch recent posts if needed
                    if tier_config['max_posts'] > 0:
                        content_type = "videos" if platform == "youtube" else "posts"
                        print(f"  [API CALL] Fetching up to {tier_config['max_posts']} recent {content_type}...")
                        posts = client.get_recent_posts(
                            profile_url,
                            days=time_range_days,
                            max_posts=tier_config['max_posts']
                        )
                        print(f"  [SUCCESS] Fetched {len(posts)} {content_type} (metadata only)")
                        if tier_config['analyze_videos'] and platform == "youtube":
                            print(f"  [NOTE] Full video content analysis not yet implemented - analyzing metadata only")

                        # Add platform and account_id to each post
                        for post in posts:
                            post['platform'] = platform
                            post['social_account_id'] = account_id
                            all_posts.append(post)

                        # Save posts to database
                        for post in posts:
                            self.db.save_post_analysis(account_id, post)

                        # Calculate engagement rate from posts
                        if posts and stats.get('followers_count', 0) > 0:
                            total_engagement = 0
                            valid_posts = 0
                            for post in posts:
                                likes = post.get('likes', 0) or post.get('likes_count', 0) or 0
                                comments = post.get('comments', 0) or post.get('comments_count', 0) or 0
                                if likes > 0 or comments > 0:
                                    total_engagement += likes + comments
                                    valid_posts += 1

                            if valid_posts > 0:
                                avg_engagement_per_post = total_engagement / valid_posts
                                engagement_rate = (avg_engagement_per_post / stats['followers_count']) * 100

                                # Update the analytics with calculated engagement rate
                                self.db.update_analytics_engagement_rate(account_id, engagement_rate)
                                print(f"  [INFO] Calculated engagement rate: {engagement_rate:.2f}%")

                    # Check for cached demographics (used in reports)
                    if tier_config.get('deep_research', False):
                        demographics = self.db.get_demographics_data(account_id)
                        if demographics:
                            platform_stats[platform]['demographics'] = demographics
                            print(f"  [INFO] Using cached demographics data")
                        else:
                            print(f"  [INFO] No cached demographics - will fetch after report is saved")

                except PlatformClientError as e:
                    print(f"  [ERROR] Failed to fetch {platform} data: {e}")
                    # Continue with other platforms
                except NotImplementedError:
                    print(f"  [WARNING] {platform} client not yet implemented, skipping")

            print(f"\n[SUMMARY] Total posts collected: {len(all_posts)}")

            # Step 4: Analyze content with Gemini
            if progress_callback:
                progress_callback("Analyzing content themes", 0.5)

            print(f"\n[STEP 4/6] Analyzing content with Gemini AI...")
            content_analysis = {}
            if tier_config['max_posts'] > 0 and all_posts:
                print(f"  [API CALL] Sending {len(all_posts)} posts to Gemini for analysis...")
                content_analysis = self._analyze_content_batch(all_posts, brief['brand_context'])
                print(f"  [SUCCESS] Content analysis complete")
                print(f"    - Brand Safety Score: {content_analysis.get('brand_safety_score', 'N/A')}")
                print(f"    - Content Themes: {', '.join(content_analysis.get('content_themes', []))[:100]}")
            else:
                print(f"  [SKIP] No posts to analyze (quick scan mode)")

            # Step 5: Analyze videos (if enabled)
            video_analysis = {}
            if tier_config.get('analyze_videos', False):
                if progress_callback:
                    progress_callback("Analyzing videos", 0.6)

                print(f"\n[STEP 5/6] Analyzing YouTube videos...")
                video_analysis = self._analyze_youtube_videos(
                    all_posts,
                    tier_config,
                    brief['brand_context']
                )
                if video_analysis.get('videos_analyzed', 0) > 0:
                    print(f"  [SUCCESS] Analyzed {video_analysis['videos_analyzed']} videos")
                    print(f"    - Video analysis cost: ${video_analysis.get('video_cost', 0.0):.4f}")
                else:
                    print(f"  [SKIP] No videos analyzed")
            else:
                print(f"\n[STEP 5/6] Video analysis disabled for this tier")

            # Step 6: Calculate overall metrics
            if progress_callback:
                progress_callback("Calculating brand fit score", 0.7)

            print(f"\n[STEP 6/6] Calculating overall metrics...")
            overall_metrics = self._calculate_overall_metrics(
                platform_stats,
                content_analysis,
                brief['brand_context'],
                video_analysis
            )
            print(f"  [SUCCESS] Brand Fit Score: {overall_metrics.get('brand_fit_score', 'N/A')}/5.0")

            # Step 6: Generate summary and recommendations
            if progress_callback:
                progress_callback("Generating recommendations", 0.9)

            print(f"\n[GENERATING] Creating summary and recommendations...")
            summary = self._generate_summary(
                creator['name'],
                platform_stats,
                content_analysis,
                overall_metrics,
                brief['brand_context']
            )
            print(f"  [SUCCESS] Summary generated ({len(summary)} characters)")

            # Step 7: Save report
            report_data = {
                'overall_score': overall_metrics.get('brand_fit_score', 5.0),
                'natural_alignment_score': overall_metrics.get('natural_alignment_score', 3.0),
                'summary': summary,
                'strengths': overall_metrics.get('strengths', []),
                'concerns': overall_metrics.get('concerns', []),
                'recommendations': overall_metrics.get('recommendations', []),
                'analysis_cost': overall_metrics.get('analysis_cost', 0.0),
                'model_used': DEFAULT_MODEL,
                'video_insights': video_analysis.get('video_insights', [])
            }

            print(f"\n[SAVING] Saving report to database...")
            report_id = self.db.save_creator_report(brief_id, creator_id, report_data)
            print(f"  [SUCCESS] Report saved with ID: {report_id}")

            if progress_callback:
                progress_callback("Analysis complete", 1.0)

            print(f"\n{'='*60}")
            print(f"[ANALYSIS COMPLETE] Creator: {creator['name']}")
            print(f"  Overall Score: {overall_metrics.get('brand_fit_score', 'N/A')}/5.0")
            print(f"  Analysis Cost: ${overall_metrics.get('analysis_cost', 0.0):.4f}")
            print(f"{'='*60}\n")

            # Fetch demographics if Deep Research tier (after report is saved)
            if tier_config.get('deep_research', False):
                print(f"\n[DEMOGRAPHICS] Deep Research tier detected - fetching demographics...")
                print(f"[INFO] This may take 5-30 minutes. Report is already saved and available.")
                print(f"[INFO] Demographics will be added when fetch completes.\n")

                try:
                    demo_results = self.fetch_demographics_for_creator(
                        creator_id=creator_id,
                        analysis_depth=analysis_depth
                    )

                    # Count successes
                    success_count = sum(1 for v in demo_results.values() if v)
                    total_count = len(demo_results)

                    if success_count > 0:
                        print(f"\n[DEMOGRAPHICS] Successfully fetched for {success_count}/{total_count} platforms")
                        print(f"[INFO] Demographics cached for 90 days")
                    else:
                        print(f"\n[DEMOGRAPHICS] Failed to fetch demographics for any platform")
                        print(f"[INFO] Check logs above for errors")

                except Exception as e:
                    print(f"\n[DEMOGRAPHICS] Error during fetch: {type(e).__name__}: {e}")
                    print(f"[INFO] Report is still valid, demographics can be fetched later via Settings")

            return {
                'success': True,
                'report_id': report_id,
                'platform_stats': platform_stats,
                'content_analysis': content_analysis,
                'overall_metrics': overall_metrics,
                'total_posts_analyzed': len(all_posts)
            }

        except CreatorAnalysisError:
            # Re-raise CreatorAnalysisError as-is
            raise
        except Exception as e:
            print(f"\n{'='*60}")
            print(f"[ERROR] Analysis failed with exception:")
            print(f"  Type: {type(e).__name__}")
            print(f"  Message: {str(e)}")
            print(f"{'='*60}\n")
            raise CreatorAnalysisError(f"Analysis failed: {str(e)}")

    def _analyze_content_batch(self, posts: List[Dict], brand_context: str) -> Dict:
        """
        Analyze a batch of posts using Gemini

        Args:
            posts: List of post dictionaries
            brand_context: Brand context for analysis

        Returns:
            Content analysis results
        """
        # Get custom post limit from settings (default: 20)
        posts_limit = int(self.db.get_setting(self.user_id, "posts_for_gemini_analysis", "20"))

        # Prepare content summary for Gemini
        content_summary = []
        for post in posts[:posts_limit]:  # Use configurable limit
            platform = post.get('platform', '')
            caption = post.get('caption', post.get('title', ''))
            likes = post.get('likes_count', 0)
            views = post.get('views_count', 0)

            content_summary.append({
                'platform': platform,
                'caption': caption[:500] if caption else "",  # Limit caption length
                'engagement': {'likes': likes, 'views': views}
            })

        prompt = f"""
Brand Context: {brand_context}

Analyze the following social media content from a creator:

{json.dumps(content_summary, indent=2)}

Provide your analysis in the specified JSON format.
"""

        try:
            from gemini_client import call_gemini_text

            # Use the Gemini API key from initialization
            if not self.gemini_client.api_key:
                return {
                    'content_themes': [],
                    'brand_safety_score': 3.0,
                    'sentiment': 'neutral',
                    'key_observations': ['Analysis skipped: No API key configured']
                }

            # Get custom prompt from settings (default: CREATOR_ANALYSIS_SYSTEM_PROMPT)
            custom_prompt = self.db.get_setting(self.user_id, "custom_analysis_prompt", "")
            analysis_prompt = custom_prompt if custom_prompt else CREATOR_ANALYSIS_SYSTEM_PROMPT

            result = call_gemini_text(
                api_key=self.gemini_client.api_key,
                model_name=DEFAULT_MODEL,
                prompt=prompt,
                system_instruction=analysis_prompt,
                response_mime_type="application/json"
            )

            if result and 'error' not in result:
                # Store token usage for cost calculation
                if '_usage' in result:
                    self._last_token_usage = result['_usage']
                    print(f"  [TOKENS] Input: {result['_usage']['prompt_tokens']}, Output: {result['_usage']['candidates_tokens']}, Total: {result['_usage']['total_tokens']}")

                # Log raw Gemini response for alignment debugging
                _debug_log_alignment(f"=== Raw Gemini Response Analysis ===")
                _debug_log_alignment(f"Brand context: {brand_context[:100]}...")
                _debug_log_alignment(f"Number of posts analyzed: {len(content_summary)}")

                # Log all scores returned
                _debug_log_alignment(f"Brand Safety Score: {result.get('brand_safety_score', 'MISSING')}")
                _debug_log_alignment(f"Authenticity Score: {result.get('authenticity_score', 'MISSING')}")
                _debug_log_alignment(f"Natural Alignment Score: {result.get('natural_alignment_score', 'MISSING')}")

                # Log brand mentions data
                brand_mentions = result.get('brand_mentions', {})
                if brand_mentions:
                    _debug_log_alignment(f"Brand Mentions Data:")
                    _debug_log_alignment(f"  - Direct mentions: {brand_mentions.get('direct_brand_mentions', 0)}")
                    _debug_log_alignment(f"  - Competitor mentions: {brand_mentions.get('competitor_mentions', 0)}")
                    _debug_log_alignment(f"  - Category discussions: {brand_mentions.get('category_discussions', 0)}")
                    _debug_log_alignment(f"  - Examples: {brand_mentions.get('mention_examples', [])}")
                else:
                    _debug_log_alignment(f"⚠️ WARNING: No brand_mentions object in response")

                # Warn if natural_alignment_score is missing
                if 'natural_alignment_score' not in result:
                    _debug_log_alignment(f"❌ CRITICAL: natural_alignment_score missing from Gemini response")
                    _debug_log_alignment(f"Full response keys: {list(result.keys())}")

                # Validate all scores are present and in valid ranges
                required_scores = ['brand_safety_score', 'authenticity_score', 'natural_alignment_score']
                for score_key in required_scores:
                    if score_key not in result:
                        print(f"  [WARNING] Missing {score_key} in Gemini response")
                        _debug_log_alignment(f"❌ Missing required score: {score_key}")
                    else:
                        score_value = result[score_key]
                        if not isinstance(score_value, (int, float)):
                            print(f"  [ERROR] {score_key} has invalid type: {type(score_value)}")
                            _debug_log_alignment(f"❌ {score_key} invalid type: {type(score_value)}")
                        elif score_value < 1 or score_value > 5:
                            print(f"  [ERROR] {score_key} out of range: {score_value} (must be 1-5)")
                            _debug_log_alignment(f"❌ {score_key} out of range: {score_value}")

                # Validate brand_mentions structure
                if 'brand_mentions' in result:
                    bm = result['brand_mentions']
                    if not isinstance(bm, dict):
                        print(f"  [ERROR] brand_mentions is not a dictionary: {type(bm)}")
                        _debug_log_alignment(f"❌ brand_mentions invalid type: {type(bm)}")
                    else:
                        expected_keys = ['direct_brand_mentions', 'competitor_mentions', 'category_discussions', 'mention_examples']
                        for key in expected_keys:
                            if key not in bm:
                                _debug_log_alignment(f"⚠️ Missing brand_mentions.{key}")

                return result
            else:
                return {
                    'content_themes': [],
                    'brand_safety_score': 3.0,
                    'sentiment': 'neutral',
                    'key_observations': [f"Analysis error: {result.get('error', 'Unknown')}"]
                }

        except Exception as e:
            print(f"Content analysis error: {e}")
            return {
                'content_themes': [],
                'brand_safety_score': 3.0,
                'sentiment': 'neutral',
                'key_observations': [f"Analysis failed: {str(e)}"]
            }

    def _analyze_youtube_videos(
        self,
        posts: List[Dict],
        tier_config: Dict,
        brand_context: str
    ) -> Dict:
        """
        Analyze YouTube videos using Gemini

        Args:
            posts: List of posts (filtered for YouTube videos)
            tier_config: Analysis tier configuration
            brand_context: Brand context

        Returns:
            Video analysis results with cost tracking
        """
        from pathlib import Path

        video_mode = tier_config.get('video_analysis_mode', 'transcript')
        max_videos = tier_config.get('max_videos_to_analyze', 5)
        max_duration = tier_config.get('max_video_duration_seconds', 600)
        max_filesize = tier_config.get('max_video_filesize_mb', 100)

        # Filter for YouTube videos
        youtube_videos = [p for p in posts if p.get('platform') == 'youtube' and p.get('post_url')]

        if not youtube_videos:
            print(f"  [INFO] No YouTube videos found in posts")
            return {'videos_analyzed': 0, 'video_cost': 0.0, 'video_insights': []}

        # Limit to top N videos (sorted by views)
        youtube_videos = sorted(
            youtube_videos,
            key=lambda x: x.get('views_count', 0),
            reverse=True
        )[:max_videos]

        print(f"  [INFO] Found {len(youtube_videos)} YouTube videos to analyze")
        print(f"  [CONFIG] Mode: {video_mode}, Max videos: {max_videos}")

        video_insights = []
        total_video_cost = 0.0
        analyzed_count = 0
        downloaded_files = []

        for idx, video in enumerate(youtube_videos, 1):
            video_url = video.get('post_url')
            video_title = video.get('title', 'Unknown')

            print(f"\n  [VIDEO {idx}/{len(youtube_videos)}] {video_title}")
            print(f"    URL: {video_url}")

            try:
                # Get video content (transcript or full video)
                download_dir = str(Path(VIDEO_DOWNLOAD_PATH) / f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
                file_path, metadata = get_video_content(
                    video_url,
                    mode=video_mode,
                    download_dir=download_dir if video_mode in ['full', 'auto'] else None,
                    max_duration_seconds=max_duration,
                    max_filesize_mb=max_filesize
                )

                if file_path:
                    downloaded_files.append(file_path)

                # Check if we got usable content
                has_transcript = metadata.get('transcript_available', False)
                has_video = metadata.get('video_downloaded', False)

                if not has_transcript and not has_video:
                    print(f"    [SKIP] No content available for analysis")
                    continue

                # Analyze the content
                if has_transcript:
                    # Analyze transcript with text-only Gemini
                    print(f"    [ANALYZING] Using transcript ({len(metadata['transcript'])} chars)")
                    analysis = self._analyze_video_transcript(
                        metadata['transcript'],
                        video_title,
                        brand_context
                    )
                elif has_video:
                    # Analyze full video with Gemini multimodal
                    print(f"    [ANALYZING] Using full video ({metadata['file_size_mb']:.1f}MB)")
                    analysis = self._analyze_video_file(
                        file_path,
                        video_title,
                        brand_context
                    )
                else:
                    continue

                if analysis:
                    video_insights.append({
                        'title': video_title,
                        'url': video_url,
                        'analysis_method': metadata.get('analysis_method', video_mode),
                        **analysis
                    })
                    analyzed_count += 1

                    # Track cost (rough estimate)
                    if has_transcript:
                        # Text-only analysis is cheap
                        total_video_cost += 0.01
                    elif has_video:
                        # Video analysis is more expensive
                        duration = metadata.get('duration_seconds', 300)
                        total_video_cost += (duration / 60) * 0.15  # Rough estimate

                    print(f"    [SUCCESS] Analysis complete")

            except YouTubeVideoError as e:
                print(f"    [ERROR] Video handling failed: {e}")
                continue
            except Exception as e:
                print(f"    [ERROR] Analysis failed: {e}")
                continue

        # Cleanup downloaded files
        for file_path in downloaded_files:
            cleanup_video_file(file_path)

        print(f"\n  [SUMMARY] Analyzed {analyzed_count}/{len(youtube_videos)} videos")
        print(f"  [COST] Video analysis: ${total_video_cost:.4f}")

        return {
            'videos_analyzed': analyzed_count,
            'video_cost': total_video_cost,
            'video_insights': video_insights
        }

    def _analyze_video_transcript(self, transcript: str, title: str, brand_context: str) -> Optional[Dict]:
        """Analyze video transcript for brand safety"""
        prompt = f"""Analyze this YouTube video transcript for brand partnership potential.

Brand Context: {brand_context}

Video Title: {title}

Transcript:
{transcript[:5000]}  # Limit to 5000 chars to save tokens

Rate on 1-5 scale:
- Brand Safety (1=risky, 5=safe)
- Content Relevance to brand
- Production Quality (inferred from transcript quality)

Return JSON with: brand_safety_score, relevance_score, key_topics, concerns"""

        try:
            result = self.gemini_client.analyze_content(prompt, response_type="json")
            return result
        except Exception as e:
            print(f"      [ERROR] Transcript analysis failed: {e}")
            return None

    def _analyze_video_file(self, file_path: str, title: str, brand_context: str) -> Optional[Dict]:
        """Analyze full video file with Gemini multimodal"""
        prompt = f"""Analyze this YouTube video for brand partnership potential.

Brand Context: {brand_context}

Video Title: {title}

Watch the video and rate on 1-5 scale:
- Brand Safety (1=risky, 5=safe)
- Production Quality
- Content Relevance to brand
- Visual Professionalism

Return JSON with: brand_safety_score, relevance_score, production_quality, key_visuals, concerns"""

        system_instruction = """You are a brand partnership analyst evaluating video content.
Provide objective analysis of brand safety, production quality, and content relevance.
Focus on visual elements, tone, and overall presentation quality."""

        try:
            result = self.gemini_client.analyze_video_with_retry(
                video_path=file_path,
                prompt=prompt,
                system_instruction=system_instruction,
                model_name=DEFAULT_MODEL
            )
            return result
        except Exception as e:
            print(f"      [ERROR] Video file analysis failed: {e}")
            return None

    def _get_demographics_data(
        self,
        creator_name: str,
        social_account_id: int,
        platform: str,
        profile_url: str,
        tier_config: Dict
    ) -> Optional[Dict]:
        """
        Get demographics data for a creator's social account

        Checks cache first, then uses Deep Research if needed

        Args:
            creator_name: Creator's name
            social_account_id: Social account ID
            platform: Platform name
            profile_url: Profile URL
            tier_config: Analysis tier configuration

        Returns:
            Demographics dictionary or None
        """
        _debug_log_demographics(f"=== Starting demographics fetch for {creator_name} ({platform}) ===")
        _debug_log_demographics(f"Social account ID: {social_account_id}")
        _debug_log_demographics(f"Profile URL: {profile_url}")
        _debug_log_demographics(f"Tier config: {tier_config.get('name', 'Unknown')}")

        # Check if Deep Research is enabled for this tier
        if not tier_config.get('deep_research', False):
            _debug_log_demographics("❌ Deep Research not enabled for this tier")
            print(f"  [SKIP] Deep Research not enabled for this tier")
            return None

        _debug_log_demographics("✓ Deep Research is enabled")

        # Check if demographics query is requested
        deep_research_queries = tier_config.get('deep_research_queries', [])
        _debug_log_demographics(f"Deep research queries: {deep_research_queries}")

        if 'demographics' not in deep_research_queries:
            _debug_log_demographics("❌ 'demographics' not in deep_research_queries list")
            print(f"  [SKIP] Demographics research not requested")
            return None

        _debug_log_demographics("✓ Demographics query is requested")

        # First, check if we have cached demographics
        print(f"  [DEMOGRAPHICS] Checking cache for {platform} account...")
        _debug_log_demographics(f"Checking DB for cached demographics (account_id={social_account_id})...")

        try:
            demographics = self.db.get_demographics_data(social_account_id)
            _debug_log_demographics(f"DB query result: {'Found data' if demographics else 'No data found'}")

            if demographics:
                _debug_log_demographics(f"Cached data keys: {list(demographics.keys())}")
                # Check if data is still fresh (within cache period)
                cache_days = tier_config.get('deep_research_cache_days', 90)
                snapshot_date_str = demographics.get('snapshot_date')
                _debug_log_demographics(f"Snapshot date: {snapshot_date_str}, Cache limit: {cache_days} days")

                if snapshot_date_str:
                    try:
                        snapshot_date = datetime.fromisoformat(snapshot_date_str)
                        age_days = (datetime.now() - snapshot_date).days

                        if age_days < cache_days:
                            _debug_log_demographics(f"✓ Cache is fresh ({age_days} days old, limit: {cache_days})")
                            print(f"  [CACHE HIT] Using cached demographics ({age_days} days old)")
                            return demographics
                        else:
                            _debug_log_demographics(f"❌ Cache expired ({age_days} days old, limit: {cache_days})")
                            print(f"  [CACHE EXPIRED] Demographics data is {age_days} days old (limit: {cache_days})")
                    except Exception as e:
                        _debug_log_demographics(f"❌ Error parsing snapshot date: {e}")
                else:
                    _debug_log_demographics("⚠️ No snapshot_date in cached data, treating as expired")
            else:
                _debug_log_demographics("No cached demographics found in database")
        except Exception as e:
            _debug_log_demographics(f"❌ ERROR checking cache: {e}")
            print(f"  [ERROR] Failed to check demographics cache: {e}")

        # No cache or expired, use Deep Research
        print(f"  [DEEP RESEARCH] Fetching demographics for {creator_name} on {platform}...")
        _debug_log_demographics(f"Initiating Deep Research API call...")

        try:
            # Generate query hash for deduplication
            query_text = f"demographics_{creator_name}_{platform}_{profile_url}"
            query_hash = DeepResearchClient.generate_query_hash(query_text)
            _debug_log_demographics(f"Query hash: {query_hash}")

            # Check if we have this exact query cached
            _debug_log_demographics("Checking Deep Research query cache...")
            cached_query = self.db.get_cached_deep_research(query_hash)

            if cached_query:
                _debug_log_demographics(f"✓ Found cached Deep Research query")
                print(f"  [CACHE HIT] Found cached Deep Research query")
                demographics_result = cached_query['result_data']
                self._deep_research_cost += cached_query['cost']
                _debug_log_demographics(f"Result keys: {list(demographics_result.keys()) if isinstance(demographics_result, dict) else 'Not a dict'}")
            else:
                _debug_log_demographics("No cached query found, calling Deep Research API...")
                # Perform Deep Research
                try:
                    result = self.deep_research_client.research_creator_demographics(
                        creator_name=creator_name,
                        platform=platform,
                        profile_url=profile_url,
                        timeout=1800,  # 30 minutes max
                        db_manager=self.db  # Pass DB manager for connection refresh
                    )
                    _debug_log_demographics(f"Deep Research API returned status: {result.get('status', 'unknown')}")

                    if result['status'] != 'completed':
                        _debug_log_demographics(f"❌ Deep Research failed with status: {result['status']}")
                        _debug_log_demographics(f"Result data: {result}")
                        print(f"  [ERROR] Deep Research failed with status: {result['status']}")
                        return None

                    demographics_result = result['result']
                    _debug_log_demographics(f"✓ Deep Research completed successfully")
                    _debug_log_demographics(f"Result keys: {list(demographics_result.keys()) if isinstance(demographics_result, dict) else 'Not a dict'}")

                    # Calculate cost
                    cost = DeepResearchClient.calculate_cost(
                        result['input_tokens'],
                        result['output_tokens']
                    )
                    self._deep_research_cost += cost
                    _debug_log_demographics(f"Cost: ${cost:.4f}, Tokens: {result['input_tokens']} in / {result['output_tokens']} out")

                    print(f"  [SUCCESS] Demographics research completed (cost: ${cost:.4f})")

                    # Save to database cache
                    cache_expiration = datetime.now() + timedelta(days=tier_config.get('deep_research_cache_days', 90))

                    query_data = {
                        'query_hash': query_hash,
                        'query_text': query_text,
                        'query_type': 'demographics',
                        'creator_id': None,  # Will be set by caller if available
                        'social_account_id': social_account_id,
                        'interaction_id': result.get('interaction_id', ''),
                        'status': 'completed',
                        'result_data': demographics_result,
                        'citations': demographics_result.get('sources', []),
                        'cost': cost,
                        'input_tokens': result['input_tokens'],
                        'output_tokens': result['output_tokens'],
                        'expires_at': cache_expiration.isoformat()
                    }

                    _debug_log_demographics("Saving Deep Research query to cache...")
                    self.db.save_deep_research_query(query_data)
                    _debug_log_demographics("✓ Query cache saved")
                except Exception as api_error:
                    _debug_log_demographics(f"❌ Deep Research API call failed: {type(api_error).__name__}: {api_error}")
                    raise

            # Save demographics to platform_analytics
            _debug_log_demographics("Preparing demographics data for saving...")
            demographics_data = {
                'gender': demographics_result.get('gender', {}),
                'age_brackets': demographics_result.get('age_brackets', {}),
                'geography': demographics_result.get('geography', []),
                'languages': demographics_result.get('languages', []),
                'interests': demographics_result.get('interests', []),
                'data_source': 'deep_research',
                'data_confidence': demographics_result.get('data_confidence', 'medium'),
                'collected_at': datetime.now().isoformat(),
                'expires_at': (datetime.now() + timedelta(days=tier_config.get('deep_research_cache_days', 90))).isoformat()
            }
            _debug_log_demographics(f"Demographics data structure: {json.dumps({k: (len(v) if isinstance(v, (list, dict)) else v) for k, v in demographics_data.items()}, indent=2)}")

            _debug_log_demographics(f"Saving demographics to platform_analytics for account_id={social_account_id}...")
            try:
                self.db.save_demographics_data(social_account_id, demographics_data)
                _debug_log_demographics("✓ Demographics saved to database")

                # Verify save worked
                verification = self.db.get_demographics_data(social_account_id)
                if verification:
                    _debug_log_demographics(f"✓ VERIFICATION: Successfully retrieved saved demographics")
                    _debug_log_demographics(f"Verification keys: {list(verification.keys())}")
                else:
                    _debug_log_demographics(f"❌ VERIFICATION FAILED: Could not retrieve saved demographics!")
            except Exception as save_error:
                _debug_log_demographics(f"❌ ERROR saving demographics: {type(save_error).__name__}: {save_error}")
                raise

            _debug_log_demographics(f"=== Demographics fetch completed successfully ===")
            return demographics_data

        except DeepResearchError as e:
            _debug_log_demographics(f"❌ DeepResearchError: {e}")
            print(f"  [ERROR] Deep Research failed: {e}")
            return None
        except Exception as e:
            _debug_log_demographics(f"❌ Unexpected error: {type(e).__name__}: {e}")
            _debug_log_demographics(f"Traceback: {e.__traceback__}")
            print(f"  [ERROR] Demographics fetch failed: {e}")
            return None

    def fetch_demographics_for_creator(self, creator_id: int, analysis_depth: str = "deep_research") -> Dict[str, bool]:
        """
        Fetch demographics data for all platforms of a creator (separate from main analysis)

        This is designed to run separately/asynchronously to avoid blocking the main analysis.
        Returns a dict mapping platform names to success status.

        Args:
            creator_id: Creator ID
            analysis_depth: Analysis tier (must have deep_research enabled)

        Returns:
            Dict with platform names as keys and success boolean as values
        """
        results = {}

        # Get tier config
        tier_config = ANALYSIS_TIERS.get(analysis_depth)
        if not tier_config or not tier_config.get('deep_research', False):
            print(f"[DEMOGRAPHICS] Tier '{analysis_depth}' does not support demographics")
            return results

        # Get creator info
        creator = self.db.get_creator(creator_id)
        if not creator:
            print(f"[DEMOGRAPHICS] Creator {creator_id} not found")
            return results

        print(f"\n[DEMOGRAPHICS FETCH] Starting for {creator['name']}")
        print("=" * 60)

        # Get social accounts
        accounts = self.db.get_social_accounts(creator_id)

        for _, account in accounts.iterrows():
            platform = account['platform']
            account_id = account['id']
            profile_url = account['profile_url']

            print(f"\n[PLATFORM] {platform.upper()}")

            try:
                demographics = self._get_demographics_data(
                    creator_name=creator['name'],
                    social_account_id=account_id,
                    platform=platform,
                    profile_url=profile_url,
                    tier_config=tier_config
                )

                if demographics:
                    results[platform] = True
                    print(f"  [SUCCESS] Demographics fetched for {platform}")
                else:
                    results[platform] = False
                    print(f"  [FAILED] No demographics data for {platform}")

            except Exception as e:
                results[platform] = False
                print(f"  [ERROR] Failed to fetch {platform} demographics: {e}")

        print("\n" + "=" * 60)
        print(f"[DEMOGRAPHICS FETCH] Completed for {creator['name']}")
        success_count = sum(1 for v in results.values() if v)
        print(f"  Success: {success_count}/{len(results)} platforms")

        return results

    def _calculate_overall_metrics(
        self,
        platform_stats: Dict,
        content_analysis: Dict,
        brand_context: str,
        video_analysis: Optional[Dict] = None
    ) -> Dict:
        """
        Calculate overall brand fit score and metrics

        Args:
            platform_stats: Stats from all platforms
            content_analysis: Content analysis results
            brand_context: Brand context

        Returns:
            Overall metrics dictionary
        """
        # Calculate total reach
        total_followers = sum(
            stats.get('followers_count', 0)
            for stats in platform_stats.values()
        )

        # Get scores from content analysis
        brand_safety = content_analysis.get('brand_safety_score', 3.0)
        authenticity = content_analysis.get('authenticity_score', 3.0)
        natural_alignment_raw = content_analysis.get('natural_alignment_score')

        # Validate and log natural alignment score
        _debug_log_alignment(f"=== Natural Alignment Score Processing ===")
        _debug_log_alignment(f"Raw value from Gemini: {natural_alignment_raw}")

        if natural_alignment_raw is None:
            natural_alignment = 3.0
            _debug_log_alignment(f"⚠️ Score was None, defaulting to 3.0")
            print(f"  [WARNING] Natural alignment score missing from content analysis - defaulting to 3.0")
        elif not isinstance(natural_alignment_raw, (int, float)):
            natural_alignment = 3.0
            _debug_log_alignment(f"❌ Invalid type: {type(natural_alignment_raw)}, defaulting to 3.0")
            print(f"  [ERROR] Natural alignment score has invalid type: {type(natural_alignment_raw)}")
        else:
            natural_alignment = float(natural_alignment_raw)
            _debug_log_alignment(f"✓ Valid numeric value: {natural_alignment}")

            # Validate range
            if natural_alignment < 1.0 or natural_alignment > 5.0:
                _debug_log_alignment(f"❌ Out of range (1-5): {natural_alignment}, clamping")
                print(f"  [ERROR] Natural alignment score out of range: {natural_alignment} (must be 1-5)")
                natural_alignment = max(1.0, min(5.0, natural_alignment))
                _debug_log_alignment(f"Clamped to: {natural_alignment}")

        _debug_log_alignment(f"Final score used: {natural_alignment}")

        # Get custom weights from settings (or use defaults)
        weight_brand_safety = float(self.db.get_setting(self.user_id, "weight_brand_safety", "0.3"))
        weight_authenticity = float(self.db.get_setting(self.user_id, "weight_authenticity", "0.25"))
        weight_natural_alignment = float(self.db.get_setting(self.user_id, "weight_natural_alignment", "0.25"))
        weight_reach = float(self.db.get_setting(self.user_id, "weight_reach", "0.2"))

        # Validate weights sum to 1.0 (within tolerance)
        weight_sum = weight_brand_safety + weight_authenticity + weight_natural_alignment + weight_reach
        if abs(weight_sum - 1.0) > 0.01:
            print(f"  [WARNING] Custom weights sum to {weight_sum:.2f}, not 1.0. Using defaults.")
            _debug_log_alignment(f"Invalid weight sum: {weight_sum}, reverting to defaults")
            weight_brand_safety = 0.3
            weight_authenticity = 0.25
            weight_natural_alignment = 0.25
            weight_reach = 0.2
        else:
            print(f"  [INFO] Using custom weights: Safety={weight_brand_safety}, Auth={weight_authenticity}, Align={weight_natural_alignment}, Reach={weight_reach}")
            _debug_log_alignment(f"Custom weights: Safety={weight_brand_safety}, Auth={weight_authenticity}, Align={weight_natural_alignment}, Reach={weight_reach}")

        # Calculate brand fit score (1-5 scale)
        # Weighted average of different factors
        brand_fit_score = (
            (brand_safety * weight_brand_safety) +
            (authenticity * weight_authenticity) +
            (natural_alignment * weight_natural_alignment) +
            (min(5, total_followers / 100000) * weight_reach)
        )

        _debug_log_alignment(f"=== Brand Fit Score Calculation ===")
        _debug_log_alignment(f"Brand Safety: {brand_safety} × {weight_brand_safety} = {brand_safety * weight_brand_safety:.2f}")
        _debug_log_alignment(f"Authenticity: {authenticity} × {weight_authenticity} = {authenticity * weight_authenticity:.2f}")
        _debug_log_alignment(f"Natural Alignment: {natural_alignment} × {weight_natural_alignment} = {natural_alignment * weight_natural_alignment:.2f}")
        _debug_log_alignment(f"Reach: {min(5, total_followers / 100000)} × {weight_reach} = {min(5, total_followers / 100000) * weight_reach:.2f}")
        _debug_log_alignment(f"Final Brand Fit Score: {brand_fit_score:.1f}/5.0")

        # Identify strengths
        strengths = content_analysis.get('partnership_strengths', [])
        if total_followers > 500000:
            strengths.append(f"Large reach: {total_followers:,} total followers")
        if brand_safety >= 4:
            strengths.append("High brand safety score")
        if natural_alignment >= 4:
            strengths.append("Strong natural alignment - creator already discusses related topics/brands")
        if len(platform_stats) > 2:
            strengths.append(f"Multi-platform presence ({len(platform_stats)} platforms)")

        # Add brand mention insights if available
        brand_mentions = content_analysis.get('brand_mentions', {})
        if brand_mentions:
            if brand_mentions.get('direct_brand_mentions', 0) > 0:
                strengths.append(f"Already mentions brand organically ({brand_mentions['direct_brand_mentions']} times)")
            if brand_mentions.get('competitor_mentions', 0) > 0:
                strengths.append(f"Discusses competitors/similar products ({brand_mentions['competitor_mentions']} mentions)")

        # Identify concerns
        concerns = content_analysis.get('potential_concerns', [])
        if brand_safety < 3:
            concerns.append("Brand safety concerns detected")
        if natural_alignment < 3:
            concerns.append("Limited natural alignment - creator doesn't naturally discuss related topics")
        if total_followers < 10000:
            concerns.append("Limited reach")

        # Generate recommendations (now based on 1-5 scale)
        recommendations = []
        if brand_fit_score >= 4.0:
            recommendations.append("Strong fit for brand partnership")
        elif brand_fit_score >= 3.0:
            recommendations.append("Moderate fit - review content themes alignment")
        else:
            recommendations.append("Limited fit - consider alternative creators")

        engagement_quality = content_analysis.get('audience_engagement_quality', 'medium')
        if engagement_quality == 'high':
            recommendations.append("High audience engagement - good for conversions")

        # Calculate actual cost based on token usage
        analysis_cost = 0.0
        if self._last_token_usage:
            from config import get_model_info
            model_info = get_model_info(DEFAULT_MODEL)
            input_cost = (self._last_token_usage['prompt_tokens'] / 1_000_000) * model_info['cost_per_m_tokens_input']
            output_cost = (self._last_token_usage['candidates_tokens'] / 1_000_000) * model_info['cost_per_m_tokens_output']
            analysis_cost = input_cost + output_cost

        # Add video analysis cost
        if video_analysis:
            video_cost = video_analysis.get('video_cost', 0.0)
            analysis_cost += video_cost

            # Add video insights to concerns/strengths
            video_insights = video_analysis.get('video_insights', [])
            if video_insights:
                # Safely convert brand_safety_score to float, handling string values
                safety_scores = []
                for v in video_insights:
                    score = v.get('brand_safety_score', 3)
                    try:
                        # Convert to float if it's a string
                        safety_scores.append(float(score))
                    except (ValueError, TypeError):
                        # Fallback to default if conversion fails
                        safety_scores.append(3.0)

                avg_video_safety = sum(safety_scores) / len(safety_scores)
                if avg_video_safety >= 4:
                    strengths.append(f"Strong brand safety in video content ({len(video_insights)} videos analyzed)")
                elif avg_video_safety < 3:
                    concerns.append(f"Brand safety concerns in video content ({len(video_insights)} videos analyzed)")

        # Add Deep Research cost
        if self._deep_research_cost > 0:
            analysis_cost += self._deep_research_cost
            print(f"  [COST] Deep Research cost: ${self._deep_research_cost:.4f}")

        return {
            'brand_fit_score': round(brand_fit_score, 1),
            'total_followers': total_followers,
            'brand_safety_score': brand_safety,
            'authenticity_score': authenticity,
            'natural_alignment_score': natural_alignment,
            'strengths': strengths,
            'concerns': concerns,
            'recommendations': recommendations,
            'analysis_cost': analysis_cost
        }

    def _generate_summary(
        self,
        creator_name: str,
        platform_stats: Dict,
        content_analysis: Dict,
        overall_metrics: Dict,
        brand_context: str
    ) -> str:
        """
        Generate executive summary

        Args:
            creator_name: Creator's name
            platform_stats: Platform statistics
            content_analysis: Content analysis
            overall_metrics: Overall metrics
            brand_context: Brand context

        Returns:
            Summary text
        """
        platforms = ', '.join(platform_stats.keys())
        followers = overall_metrics['total_followers']
        fit_score = overall_metrics['brand_fit_score']
        themes = ', '.join(content_analysis.get('content_themes', [])[:3])

        natural_alignment = content_analysis.get('natural_alignment_score', 'N/A')
        brand_mentions = content_analysis.get('brand_mentions', {})

        alignment_note = ""
        if natural_alignment != 'N/A' and natural_alignment >= 4:
            mention_examples = brand_mentions.get('mention_examples', [])
            if mention_examples:
                alignment_note = f"\n\nNatural Alignment Highlights: {', '.join(mention_examples[:3])}"

        summary = f"""{creator_name} is a creator active on {platforms} with a total reach of {followers:,} followers.

Primary Content: {themes or 'Various topics'}

Brand Fit Score: {fit_score}/5

Brand Safety: {content_analysis.get('brand_safety_score', 'N/A')}/5
Authenticity: {content_analysis.get('authenticity_score', 'N/A')}/5
Natural Alignment: {natural_alignment}/5
Engagement Quality: {content_analysis.get('audience_engagement_quality', 'N/A')}{alignment_note}

This creator {'is a strong candidate' if fit_score >= 4.0 else 'shows moderate potential' if fit_score >= 3.0 else 'may not be the best fit'} for partnerships aligned with: {brand_context[:200]}..."""

        return summary
