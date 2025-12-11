"""
Creator analysis orchestration engine
Coordinates multi-platform data fetching, analysis, and report generation
"""

import json
from typing import Dict, List, Optional, Callable
from datetime import datetime

from storage import get_db
from platform_clients import get_platform_client, PlatformClientError
from gemini_client import GeminiClient, GeminiAPIError
from youtube_video_handler import get_video_content, cleanup_video_file, YouTubeVideoError
from config import (
    ANALYSIS_TIERS,
    DEFAULT_TIME_RANGE_DAYS,
    CREATOR_ANALYSIS_SYSTEM_PROMPT,
    DEFAULT_MODEL,
    VIDEO_DOWNLOAD_PATH
)


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
            gemini_api_key: Gemini API key for content analysis
            youtube_api_keys: List of YouTube API keys for rotation
        """
        self.gemini_client = GeminiClient(gemini_api_key)
        self.youtube_api_keys = youtube_api_keys or []
        self.db = get_db()
        self._last_token_usage = None

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

            # Get analysis tier config
            tier_config = ANALYSIS_TIERS.get(analysis_depth, ANALYSIS_TIERS["standard"])
            print(f"[CONFIG] Analysis depth: {analysis_depth}")
            print(f"[CONFIG] Max posts per platform: {tier_config['max_posts']}")
            print(f"[CONFIG] Analyze videos: {tier_config['analyze_videos']}")

            # Step 1: Get creator and brief info
            if progress_callback:
                progress_callback("Loading creator information", 0.0)

            print(f"\n[STEP 1/5] Loading creator information...")
            creator = self.db.get_creator(creator_id)
            if not creator:
                raise CreatorAnalysisError(f"Creator not found: {creator_id}")
            print(f"[SUCCESS] Found creator: {creator['name']}")

            # Fetch brief
            print(f"[STEP 1/5] Loading brief information...")
            conn = self.db._get_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT id, user_id, name, description, brand_context, status, created_at, updated_at
                FROM briefs WHERE id = ?
            """, (brief_id,))
            row = cursor.fetchone()
            conn.close()

            if row:
                brief = {
                    'id': row['id'],
                    'user_id': row['user_id'],
                    'name': row['name'],
                    'description': row['description'],
                    'brand_context': row['brand_context'],
                    'status': row['status'],
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                }
            else:
                brief = None

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
                    # Get platform client
                    if platform == 'youtube':
                        print(f"  [INFO] Using YouTube API (keys available: {len(self.youtube_api_keys)})")
                        client = get_platform_client(platform, api_keys=self.youtube_api_keys)
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
        # Prepare content summary for Gemini
        content_summary = []
        for post in posts[:20]:  # Limit to top 20 posts to save on tokens
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

            result = call_gemini_text(
                api_key=self.gemini_client.api_key,
                model_name=DEFAULT_MODEL,
                prompt=prompt,
                system_instruction=CREATOR_ANALYSIS_SYSTEM_PROMPT,
                response_mime_type="application/json"
            )

            if result and 'error' not in result:
                # Store token usage for cost calculation
                if '_usage' in result:
                    self._last_token_usage = result['_usage']
                    print(f"  [TOKENS] Input: {result['_usage']['prompt_tokens']}, Output: {result['_usage']['candidates_tokens']}, Total: {result['_usage']['total_tokens']}")
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

        # Get brand safety score from content analysis
        brand_safety = content_analysis.get('brand_safety_score', 3.0)
        authenticity = content_analysis.get('authenticity_score', 3.0)

        # Calculate brand fit score (1-5 scale)
        # Weighted average of different factors
        brand_fit_score = (
            (brand_safety * 0.4) +  # 40% weight on brand safety
            (authenticity * 0.3) +  # 30% weight on authenticity
            (min(5, total_followers / 100000) * 0.3)  # 30% weight on reach (scaled)
        )

        # Identify strengths
        strengths = content_analysis.get('partnership_strengths', [])
        if total_followers > 500000:
            strengths.append(f"Large reach: {total_followers:,} total followers")
        if brand_safety >= 4:
            strengths.append("High brand safety score")
        if len(platform_stats) > 2:
            strengths.append(f"Multi-platform presence ({len(platform_stats)} platforms)")

        # Identify concerns
        concerns = content_analysis.get('potential_concerns', [])
        if brand_safety < 3:
            concerns.append("Brand safety concerns detected")
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
                avg_video_safety = sum(v.get('brand_safety_score', 3) for v in video_insights) / len(video_insights)
                if avg_video_safety >= 4:
                    strengths.append(f"Strong brand safety in video content ({len(video_insights)} videos analyzed)")
                elif avg_video_safety < 3:
                    concerns.append(f"Brand safety concerns in video content ({len(video_insights)} videos analyzed)")

        return {
            'brand_fit_score': round(brand_fit_score, 1),
            'total_followers': total_followers,
            'brand_safety_score': brand_safety,
            'authenticity_score': authenticity,
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

        summary = f"""{creator_name} is a creator active on {platforms} with a total reach of {followers:,} followers.

Primary Content: {themes or 'Various topics'}

Brand Fit Score: {fit_score}/10

Brand Safety: {content_analysis.get('brand_safety_score', 'N/A')}/5
Authenticity: {content_analysis.get('authenticity_score', 'N/A')}/5
Engagement Quality: {content_analysis.get('audience_engagement_quality', 'N/A')}

This creator {'is a strong candidate' if fit_score >= 7 else 'shows moderate potential' if fit_score >= 5 else 'may not be the best fit'} for partnerships aligned with: {brand_context[:200]}..."""

        return summary
