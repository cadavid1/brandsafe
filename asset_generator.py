"""
Campaign Asset Generator - Creates AI-powered campaign assets for creators
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Callable
from datetime import datetime

from gemini_client import GeminiClient, GeminiAPIError
from storage import DatabaseManager
from config import CAMPAIGN_ASSETS_PATH


class AssetGenerator:
    """Generates campaign images and videos using Gemini/Veo models"""

    def __init__(self, api_key: str, db: DatabaseManager):
        """
        Initialize asset generator

        Args:
            api_key: Google API key
            db: Database manager instance
        """
        self.client = GeminiClient(api_key)
        self.db = db

        # Ensure storage directories exist
        Path(CAMPAIGN_ASSETS_PATH).mkdir(parents=True, exist_ok=True)

    def build_campaign_image_prompt(
        self,
        brief: Dict,
        creator: Dict,
        social_accounts: List[Dict],
        report: Optional[Dict] = None
    ) -> str:
        """
        Build intelligent prompt for campaign concept image

        Incorporates:
        - Brand context from brief
        - Creator style and themes
        - Campaign goals
        - Natural fit information from report

        Args:
            brief: Brief/campaign data
            creator: Creator data
            social_accounts: List of social account dicts
            report: Optional creator report with analysis

        Returns:
            Prompt string
        """
        # Extract key information
        brand_name = brief.get('name', 'Brand')
        brand_context = brief.get('brand_context', '')
        brief_description = brief.get('description', '')

        creator_name = creator.get('name', 'Creator')
        primary_platform = creator.get('primary_platform', 'social media')

        # Extract content themes from report if available
        content_themes = []
        if report:
            themes_str = report.get('content_themes', '')
            if themes_str:
                try:
                    content_themes = json.loads(themes_str) if isinstance(themes_str, str) else themes_str
                except:
                    pass

        themes_description = ', '.join(content_themes[:3]) if content_themes else "their typical content style"

        # Build the prompt
        prompt = f"""Create a professional campaign concept image showing {creator_name} featuring {brand_name}.

BRAND CONTEXT:
{brand_context if brand_context else 'A premium brand seeking authentic creator partnerships.'}

CAMPAIGN GOAL:
{brief_description if brief_description else f'Partner with {creator_name} to create engaging branded content.'}

CREATOR STYLE:
{creator_name} is a {primary_platform} creator known for {themes_description}. Their content typically features authentic, engaging storytelling.

VISUAL REQUIREMENTS:
- Show the creator in their typical {primary_platform} content aesthetic
- Feature the brand/product naturally and prominently in the scene
- Professional, polished composition suitable for pitch decks and social media
- Authentic to the creator's style while clearly showcasing the brand partnership opportunity
- Include dynamic energy and engagement that reflects the creator's personality
- Brand-safe, professional quality

STYLE: Photorealistic, professional social media content aesthetic, vibrant and engaging"""

        return prompt

    def build_campaign_video_prompt(
        self,
        video_type: str,
        brief: Dict,
        creator: Dict,
        social_accounts: List[Dict],
        analytics: Dict,
        report: Optional[Dict] = None
    ) -> str:
        """
        Build prompt for campaign video generation following Veo 3.1 best practices

        Structure: Subject -> Action -> Style -> Camera work -> Ambiance

        Args:
            video_type: 'concept' or 'stats'
            brief: Brief/campaign data
            creator: Creator data
            social_accounts: List of social accounts
            analytics: Analytics data by platform
            report: Optional creator report

        Returns:
            Prompt string following Subject-Action-Style-Camera-Ambiance pattern
        """
        brand_name = brief.get('name', 'Brand')
        creator_name = creator.get('name', 'Creator')
        primary_platform = creator.get('primary_platform', 'social media')

        if video_type == 'concept':
            # Campaign concept visualization
            brand_context = brief.get('brand_context', '')
            brief_description = brief.get('description', '')

            # Extract content themes for authenticity
            content_themes = []
            if report:
                themes_str = report.get('content_themes', '')
                if themes_str:
                    try:
                        content_themes = json.loads(themes_str) if isinstance(themes_str, str) else themes_str
                    except:
                        pass
            themes_description = ', '.join(content_themes[:2]) if content_themes else f"{primary_platform} content"

            # Build prompt following Subject -> Action -> Style -> Camera -> Ambiance
            prompt = f"""SUBJECT: A {primary_platform} content creator in their creative workspace featuring {brand_name} products prominently in the scene. The creator is filming or presenting content that naturally showcases the brand.

ACTION: The creator dynamically engages with {brand_name} products while creating their signature {themes_description} content. They present the product authentically, demonstrating genuine enthusiasm. The brand logo or product is clearly visible and naturally integrated into the scene.

STYLE: Professional social media content aesthetic with cinematic production quality. Clean, modern composition with vibrant, engaging colors that match both the creator's personal brand and {brand_name}'s visual identity. Polished yet authentic feel suitable for pitch decks and campaign presentations.

CAMERA WORK: Medium to close-up shots that clearly show both the creator's personality and the {brand_name} product. Smooth camera movements with professional transitions. Dynamic angles that create energy and engagement. Professional lighting setup that highlights key elements.

AMBIANCE: Bright, energetic, and professional atmosphere. Well-lit setting with warm, inviting tones. The mood conveys authentic partnership potential between creator and brand, creating excitement for a successful collaboration. Natural lighting mixed with professional setup creates aspirational yet achievable aesthetic."""

        else:  # 'stats' - Creator stats & highlights
            # Gather stats
            total_followers = 0
            platforms_str = []

            for platform, platform_analytics in analytics.items():
                followers = platform_analytics.get('followers_count', 0) or 0
                total_followers += followers
                if followers > 0:
                    platforms_str.append(f"{platform.title()}: {followers:,}")

            overall_score = report.get('overall_score', 0) if report else 0
            platforms_display = ', '.join(platforms_str) if platforms_str else primary_platform.title()

            # Build prompt following Subject -> Action -> Style -> Camera -> Ambiance
            prompt = f"""SUBJECT: A dynamic data visualization dashboard showcasing {creator_name}'s creator statistics and performance metrics. Platform icons for {platforms_display} are prominently displayed alongside key numbers and graphs.

ACTION: Statistics and metrics animate onto screen in a compelling sequence. Follower count of {total_followers:,} appears with rising number animation. Platform icons pulse and glow as their individual metrics appear. Engagement charts grow and fill in. Progress bars for the overall score of {overall_score:.1f}/5.0 animate to completion. All elements build momentum toward the final impressive summary view.

STYLE: Modern, sleek data visualization with professional motion graphics. Clean design with a sophisticated color palette of professional blues, energetic greens, and accent colors. High-end presentation quality suitable for marketing pitches and investor decks. Minimalist yet impactful visual design.

CAMERA WORK: Static but with animated elements creating dynamic feel. Smooth zoom-ins on key statistics for emphasis. Transition effects between different data views. Camera subtly pushes in as statistics build to create momentum and excitement.

AMBIANCE: Professional, impressive, and data-driven atmosphere. Confident and aspirational mood that conveys the creator's strong performance and potential. Clean, high-tech environment with perfect lighting that makes all text and numbers crystal clear. The overall feeling is "this creator is a strong performer worth investing in"."""

        return prompt

    def generate_campaign_image(
        self,
        user_id: int,
        brief_id: int,
        creator_id: int,
        custom_prompt: Optional[str] = None,
        aspect_ratio: str = "16:9",
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict:
        """
        Generate campaign concept image

        Args:
            user_id: User ID
            brief_id: Brief ID
            creator_id: Creator ID
            custom_prompt: Optional custom prompt (overrides default)
            aspect_ratio: Image aspect ratio
            progress_callback: Progress callback

        Returns:
            Dict with asset_id, file_path, cost, metadata
        """
        try:
            # Fetch data for prompt building
            if progress_callback:
                progress_callback("Fetching campaign data", 0.05)

            brief = self.db.get_brief(brief_id)
            creator = self.db.get_creator(creator_id)
            social_accounts = self.db.get_social_accounts(creator_id)
            report = self.db.get_creator_report(brief_id, creator_id)

            # Build prompt
            if custom_prompt:
                prompt = custom_prompt
            else:
                if progress_callback:
                    progress_callback("Building generation prompt", 0.1)

                social_accounts_list = social_accounts.to_dict('records') if not social_accounts.empty else []
                prompt = self.build_campaign_image_prompt(
                    brief,
                    creator,
                    social_accounts_list,
                    report
                )

            # Generate image
            if progress_callback:
                progress_callback("Generating image", 0.2)

            def gen_progress(message, progress):
                if progress_callback:
                    # Map 0.2-0.8 range
                    progress_callback(message, 0.2 + (progress * 0.6))

            result = self.client.generate_image_with_retry(
                prompt=prompt,
                model_name="gemini-2.5-flash-image",
                aspect_ratio=aspect_ratio,
                progress_callback=gen_progress
            )

            # Save image file
            if progress_callback:
                progress_callback("Saving image file", 0.85)

            file_path = self._save_asset_file(
                user_id=user_id,
                asset_type='images',
                asset_data=result['image_data'],
                file_extension='png'
            )

            # Save to database
            if progress_callback:
                progress_callback("Saving to database", 0.9)

            asset_id = self.db.save_campaign_asset(
                user_id=user_id,
                brief_id=brief_id,
                creator_id=creator_id,
                asset_type='image',
                asset_subtype='concept',
                file_path=file_path,
                thumbnail_path=None,
                prompt_used=prompt,
                model_used="gemini-2.5-flash-image",
                generation_params={'aspect_ratio': aspect_ratio},
                cost=result['cost'],
                status='completed',
                error_message=None,
                metadata=result['metadata']
            )

            if progress_callback:
                progress_callback("Image generation complete", 1.0)

            return {
                'asset_id': asset_id,
                'file_path': file_path,
                'cost': result['cost'],
                'metadata': result['metadata']
            }

        except GeminiAPIError as e:
            raise e
        except Exception as e:
            raise Exception(f"Image generation failed: {str(e)}")

    def generate_campaign_video(
        self,
        user_id: int,
        brief_id: int,
        creator_id: int,
        video_type: str = "concept",
        custom_prompt: Optional[str] = None,
        duration_seconds: int = 8,
        resolution: str = "720p",
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict:
        """
        Generate campaign video

        Args:
            user_id: User ID
            brief_id: Brief ID
            creator_id: Creator ID
            video_type: 'concept' or 'stats'
            custom_prompt: Optional custom prompt
            duration_seconds: Video duration (max 8)
            progress_callback: Progress callback

        Returns:
            Dict with asset_id, file_path, thumbnail_path, cost, metadata
        """
        try:
            # Fetch data
            if progress_callback:
                progress_callback("Fetching campaign data", 0.03)

            brief = self.db.get_brief(brief_id)
            creator = self.db.get_creator(creator_id)
            social_accounts_df = self.db.get_social_accounts(creator_id)

            # Get analytics
            analytics_data = {}
            if not social_accounts_df.empty:
                for _, acc in social_accounts_df.iterrows():
                    analytics = self.db.get_latest_analytics(acc['id'])
                    if analytics:
                        analytics_data[acc['platform']] = analytics

            report = self.db.get_creator_report(brief_id, creator_id)

            # Build prompt
            if custom_prompt:
                prompt = custom_prompt
            else:
                if progress_callback:
                    progress_callback("Building generation prompt", 0.05)

                social_accounts_list = social_accounts_df.to_dict('records') if not social_accounts_df.empty else []
                prompt = self.build_campaign_video_prompt(
                    video_type,
                    brief,
                    creator,
                    social_accounts_list,
                    analytics_data,
                    report
                )

            # Generate video
            if progress_callback:
                progress_callback("Generating video (this may take 2-5 minutes)", 0.1)

            def gen_progress(message, progress):
                if progress_callback:
                    # Map 0.1-0.85 range
                    progress_callback(message, 0.1 + (progress * 0.75))

            result = self.client.generate_video_with_retry(
                prompt=prompt,
                model_name="veo-3.1-fast-generate-preview",
                duration_seconds=duration_seconds,
                resolution=resolution,
                progress_callback=gen_progress
            )

            # Save video file
            if progress_callback:
                progress_callback("Saving video file", 0.9)

            file_path = self._save_asset_file(
                user_id=user_id,
                asset_type='videos',
                asset_data=result['video_data'],
                file_extension='mp4'
            )

            # Create thumbnail
            if progress_callback:
                progress_callback("Creating thumbnail", 0.93)

            thumbnail_path = self._create_video_thumbnail(file_path)

            # Save to database
            if progress_callback:
                progress_callback("Saving to database", 0.95)

            asset_id = self.db.save_campaign_asset(
                user_id=user_id,
                brief_id=brief_id,
                creator_id=creator_id,
                asset_type='video',
                asset_subtype=video_type,
                file_path=file_path,
                thumbnail_path=thumbnail_path,
                prompt_used=prompt,
                model_used="veo-3.1-fast-generate-preview",
                generation_params={
                    'duration_seconds': duration_seconds,
                    'resolution': resolution
                },
                cost=result['cost'],
                status='completed',
                error_message=None,
                metadata=result['metadata']
            )

            if progress_callback:
                progress_callback("Video generation complete", 1.0)

            return {
                'asset_id': asset_id,
                'file_path': file_path,
                'thumbnail_path': thumbnail_path,
                'cost': result['cost'],
                'metadata': result['metadata']
            }

        except GeminiAPIError as e:
            raise e
        except Exception as e:
            raise Exception(f"Video generation failed: {str(e)}")

    def _save_asset_file(
        self,
        user_id: int,
        asset_type: str,
        asset_data: bytes,
        file_extension: str
    ) -> str:
        """
        Save asset file to disk and return path

        Args:
            user_id: User ID
            asset_type: 'images' or 'videos'
            asset_data: Raw file data
            file_extension: File extension without dot

        Returns:
            File path
        """
        # Create user directory
        user_dir = Path(CAMPAIGN_ASSETS_PATH) / str(user_id) / asset_type
        user_dir.mkdir(parents=True, exist_ok=True)

        # Generate filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"asset_{timestamp}.{file_extension}"
        file_path = user_dir / filename

        # Write file
        with open(file_path, 'wb') as f:
            f.write(asset_data)

        return str(file_path)

    def _create_video_thumbnail(self, video_path: str) -> str:
        """
        Create thumbnail from video and return path

        Args:
            video_path: Path to video file

        Returns:
            Path to thumbnail file
        """
        try:
            # Try using opencv if available
            import cv2

            # Open video
            cap = cv2.VideoCapture(video_path)

            # Get frame from 1 second in
            fps = cap.get(cv2.CAP_PROP_FPS)
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(fps))

            # Read frame
            ret, frame = cap.read()
            cap.release()

            if ret:
                # Save thumbnail
                thumbnail_path = video_path.replace('.mp4', '_thumb.jpg')
                cv2.imwrite(thumbnail_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                return thumbnail_path

        except ImportError:
            pass
        except Exception as e:
            print(f"Warning: Could not create thumbnail: {e}")

        # If opencv not available or failed, return None
        return None
