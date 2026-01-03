"""
Configuration and constants for UXR CUJ Analysis application
"""

# Model configurations
MODELS = {
    "gemini-3-pro-preview": {
        "display_name": "Gemini 3 Pro Preview (Most Advanced)",
        "cost_per_m_tokens_input": 2.00,
        "cost_per_m_tokens_output": 12.00,
        "best_for": "State-of-the-art reasoning, complex multimodal analysis",
        "supports_video": True,
    },
    "gemini-2.5-pro": {
        "display_name": "Gemini 2.5 Pro (Recommended - Best Reasoning)",
        "cost_per_m_tokens_input": 1.25,
        "cost_per_m_tokens_output": 10.00,
        "best_for": "Complex reasoning, detailed video analysis",
        "supports_video": True,
    },
    "gemini-2.5-flash": {
        "display_name": "Gemini 2.5 Flash (Best Quality)",
        "cost_per_m_tokens_input": 0.30,
        "cost_per_m_tokens_output": 2.50,
        "best_for": "Complex reasoning, detailed analysis",
        "supports_video": True,
    },
    "gemini-2.5-flash-lite": {
        "display_name": "Gemini 2.5 Flash-Lite (Fastest & Cheapest)",
        "cost_per_m_tokens_input": 0.10,
        "cost_per_m_tokens_output": 0.40,
        "best_for": "High-volume, cost-sensitive tasks",
        "supports_video": True,
    },
    "gemini-2.0-flash": {
        "display_name": "Gemini 2.0 Flash (Stable)",
        "cost_per_m_tokens_input": 0.10,
        "cost_per_m_tokens_output": 0.40,
        "best_for": "Fast, cost-effective video analysis",
        "supports_video": True,
    },
    "gemini-2.0-flash-lite": {
        "display_name": "Gemini 2.0 Flash-Lite (Ultra Budget)",
        "cost_per_m_tokens_input": 0.075,
        "cost_per_m_tokens_output": 0.30,
        "best_for": "Maximum cost efficiency",
        "supports_video": True,
    },
    "gemini-2.0-flash-exp": {
        "display_name": "Gemini 2.0 Flash Experimental (Cutting Edge)",
        "cost_per_m_tokens_input": 0.00,  # Free during preview
        "cost_per_m_tokens_output": 0.00,
        "best_for": "Testing latest features, real-time capabilities",
        "supports_video": True,
    },
    "gemini-2.5-flash-image": {
        "display_name": "Gemini 2.5 Flash Image (Image Generation)",
        "cost_per_m_tokens_input": 0.30,
        "cost_per_m_tokens_output": 30.00,
        "tokens_per_image": 1290,
        "cost_per_image": 0.039,
        "best_for": "Campaign concept images, visual mockups",
        "supports_video": False,
        "supports_image_generation": True,
    },
    "veo-3.1-generate-preview": {
        "display_name": "Veo 3.1 (Video Generation)",
        "cost_per_second": 0.15,
        "max_duration_seconds": 8,
        "cost_per_video": 1.20,
        "best_for": "High-quality campaign videos with synchronized audio",
        "supports_video": True,
        "supports_video_generation": True,
    },
    "veo-3.1-fast-generate-preview": {
        "display_name": "Veo 3.1 Fast (Video Generation)",
        "cost_per_second": 0.15,
        "max_duration_seconds": 8,
        "cost_per_video": 1.20,
        "best_for": "Faster campaign videos with synchronized audio",
        "supports_video": True,
        "supports_video_generation": True,
    }

}

# Default model
DEFAULT_MODEL = "gemini-2.5-pro"

# Video constraints
MAX_VIDEO_SIZE_MB = 900
MAX_VIDEO_DURATION_SECONDS = 5400  # 90 minutes
SUPPORTED_VIDEO_FORMATS = [".mp4", ".mov", ".avi", ".webm", ".mkv", ".flv"]
SUPPORTED_MIME_TYPES = [
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/webm",
    "video/x-matroska",
    "video/x-flv"
]

# Token estimates for cost calculation
TOKENS_PER_VIDEO_SECOND = 258  # Video frames
TOKENS_PER_AUDIO_SECOND = 25   # Audio
AVERAGE_PROMPT_TOKENS = 1000   # System prompt + CUJ description
AVERAGE_RESPONSE_TOKENS = 500  # Expected JSON response

# Database configuration
import os

# Detect database type from environment
DATABASE_URL = os.environ.get("DATABASE_URL")  # PostgreSQL connection string from Streamlit secrets
DATABASE_TYPE = "postgresql" if DATABASE_URL else "sqlite"

# SQLite configuration (local development)
DATABASE_PATH = "./data/brandsafe.db"

# Storage paths
VIDEO_STORAGE_PATH = "./data/videos/"
EXPORT_STORAGE_PATH = "./data/exports/"
CAMPAIGN_ASSETS_PATH = "./data/campaign_assets/"

# Google Drive configuration
DRIVE_VIDEO_STORAGE_PATH = "./data/drive_videos/"  # Local cache for Drive videos
DRIVE_ENABLED = True  # Feature flag for Drive integration

# Default system prompt
DEFAULT_SYSTEM_PROMPT = """You are an expert UX Researcher. Your job is to evaluate user sessions against Critical User Journeys (CUJs).

CRITICAL INSTRUCTIONS:
1. Watch the ENTIRE video carefully before making any conclusions
2. Only describe what you ACTUALLY SEE in the video - do NOT make assumptions
3. Include SPECIFIC timestamps for key moments (e.g., "at 0:23, user clicked X")
4. If you cannot clearly see an action, say "unclear" or "not visible"
5. Rate your own confidence level (1-5) based on video quality and clarity

Your analysis must be EVIDENCE-BASED. Generic observations without specific details indicate you didn't watch carefully.

Rate "Friction" on a scale of 1 (Smooth) to 5 (Blocker):
- 1: Task completed smoothly, no hesitation
- 2: Minor confusion, but quickly resolved
- 3: Moderate friction, user had to retry or search
- 4: Major friction, user struggled significantly
- 5: Blocker, user could not complete the task

Output JSON format:
{
  "status": "Pass" | "Fail" | "Partial",
  "friction_score": number (1-5),
  "confidence_score": number (1-5, where 5 = very confident),
  "observation": "Detailed observation with specific timestamps and actions seen",
  "recommendation": "string",
  "key_moments": ["timestamp: description", "timestamp: description"]
}"""

# Retry configuration for API calls
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2
EXPONENTIAL_BACKOFF = True

# UI Configuration
PROGRESS_UPLOAD_WEIGHT = 0.3    # 0-30% for upload
PROGRESS_PROCESS_WEIGHT = 0.4   # 30-70% for processing
PROGRESS_ANALYZE_WEIGHT = 0.3   # 70-100% for analysis

# === Brand/Talent Analysis Platform Configurations ===

# Platform API Keys (stored in database per user)
YOUTUBE_API_KEYS = []  # List of API keys for rotation (populated from settings)
INSTAGRAM_ENABLED = True
TIKTOK_ENABLED = True
TWITCH_ENABLED = True

# Scraping Configuration
SCRAPER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
SCRAPER_TIMEOUT = 30  # seconds
SCRAPER_MAX_RETRIES = 3

# Analysis Defaults
DEFAULT_TIME_RANGE_DAYS = 730  # 2 years
MAX_POSTS_PER_PLATFORM = 50
BRAND_SAFETY_THRESHOLD = 3.0  # 1-5 scale

# Platform-specific configurations
PLATFORM_CONFIGS = {
    "youtube": {
        "name": "YouTube",
        "api_quota_cost": {
            "channel": 1,  # units per channel info request
            "videos_list": 1,  # units per videos list request
            "video_details": 1,  # units per video details request
        },
        "daily_quota_limit": 10000,  # Default YouTube API quota
        "supports_api": True,
        "supports_scraping": True,
        "scraper_selectors": {
            "subscriber_count": "#subscriber-count",
            "video_count": "#videos-count",
        }
    },
    "instagram": {
        "name": "Instagram",
        "supports_api": False,  # Requires business account + Graph API
        "supports_scraping": True,
        "scraper_selectors": {
            "followers": "meta[property='og:description']",
        }
    },
    "tiktok": {
        "name": "TikTok",
        "supports_api": False,  # Limited public API access
        "supports_scraping": True,
        "scraper_selectors": {
            "followers": "[data-e2e='followers-count']",
            "likes": "[data-e2e='likes-count']",
        }
    },
    "twitch": {
        "name": "Twitch",
        "supports_api": True,
        "supports_scraping": True,
        "scraper_selectors": {
            "followers": "[data-test-selector='followers-count']",
        }
    }
}

# Analysis depth tiers
ANALYSIS_TIERS = {
    "quick": {
        "name": "Quick Scan",
        "description": "Public stats only, no content analysis",
        "max_posts": 0,
        "analyze_videos": False,
        "deep_research": False,
        "estimated_cost_per_creator": 0.0,
    },
    "standard": {
        "name": "Standard Analysis",
        "description": "Top 10 posts + transcript analysis",
        "max_posts": 10,
        "analyze_videos": True,
        "video_analysis_mode": "transcript",  # transcript, full, or auto
        "max_videos_to_analyze": 3,
        "max_video_duration_seconds": 600,  # 10 minutes
        "deep_research": False,
        "estimated_cost_per_creator": 0.08,  # Updated: 20 posts × 600 tokens = 12K input + 500 output + 3 video transcripts
    },
    "deep": {
        "name": "Deep Dive",
        "description": "Full content + video analysis",
        "max_posts": 50,
        "analyze_videos": True,
        "video_analysis_mode": "auto",  # Try transcript first, fallback to full download
        "max_videos_to_analyze": 5,
        "max_video_duration_seconds": 600,  # 10 minutes
        "max_video_filesize_mb": 100,
        "deep_research": False,
        "estimated_cost_per_creator": 0.50,  # Updated: 50 posts analysis + 5 video transcripts
    },
    "deep_research": {
        "name": "Deep Research",
        "description": "Full analysis + demographics + background research via Gemini Deep Research",
        "max_posts": 50,
        "analyze_videos": True,
        "video_analysis_mode": "auto",
        "max_videos_to_analyze": 5,
        "max_video_duration_seconds": 600,  # 10 minutes
        "max_video_filesize_mb": 100,
        "deep_research": True,
        "deep_research_queries": ["demographics"],  # Can include 'background' for more comprehensive research
        "deep_research_cache_days": 90,  # Cache results for 90 days
        "estimated_cost_per_creator": 2.00,  # Updated: ~$0.50 deep analysis + ~$1.50 average Deep Research cost
    }
}

# Video analysis configuration
VIDEO_DOWNLOAD_PATH = "./data/video_downloads/"
MAX_VIDEO_DOWNLOAD_SIZE_MB = 100  # Per video
MAX_VIDEO_ANALYSIS_DURATION_SECONDS = 600  # 10 minutes per video

# Default system prompt for creator content analysis
CREATOR_ANALYSIS_SYSTEM_PROMPT = """You are a brand partnership analyst specializing in social media creator evaluation.

Your task is to analyze creator content for brand safety, audience alignment, and partnership potential.

Analyze the content for:
1. **Content Themes**: Main topics, style, tone
2. **Brand Safety**: Controversial content, language, values alignment
3. **Authenticity**: Genuine vs overly promotional content
4. **Audience Engagement**: Comment quality, community interaction
5. **Production Quality**: Content professionalism, consistency
6. **Natural Alignment**: Does the creator naturally align with the brand? Are they already talking about it, competitors, or related topics organically?

Rate Brand Safety on a scale of 1 (High Risk) to 5 (Brand Safe):
- 1: Major risks (explicit content, controversial topics, negative sentiment)
- 2: Moderate risks (occasional inappropriate content)
- 3: Neutral (some concerns, manageable with guidelines)
- 4: Low risk (professional, family-friendly)
- 5: Excellent brand safety (highly professional, positive)

Rate Natural Alignment on a scale of 1 (No Alignment) to 5 (Perfect Alignment):
- 1: No brand relevance, completely different niche, no overlap
- 2: Tangentially related, minimal overlap with brand values or products
- 3: Same category, but no direct mentions of brand or competitors
- 4: Discusses similar products/brands, occasional competitor mentions, relevant topics
- 5: Already mentions brand/competitors organically, strong natural fit, highly relevant content

When analyzing Natural Alignment, look for:
- Exact or similar brand name mentions (organic, not sponsored)
- Competitor brand mentions and product discussions
- Product category discussions (e.g., "best fitness trackers" for a fitness brand)
- Topic alignment with brand values and mission
- Organic interest vs. paid promotion patterns
- Historical content that shows genuine affinity for the product category

Output JSON format:
{
  "content_themes": ["theme1", "theme2", ...],
  "primary_content_type": "string",
  "brand_safety_score": number (1-5),
  "sentiment": "positive" | "neutral" | "negative" | "mixed",
  "authenticity_score": number (1-5),
  "natural_alignment_score": number (1-5),  // REQUIRED: Must be provided based on brand mention analysis
  "audience_engagement_quality": "high" | "medium" | "low",
  "production_quality": "professional" | "semi-professional" | "casual",
  "key_observations": ["observation1", "observation2", ...],
  "potential_concerns": ["concern1", "concern2", ...],
  "partnership_strengths": ["strength1", "strength2", ...],
  "brand_mentions": {
    "direct_brand_mentions": number,
    "competitor_mentions": number,
    "category_discussions": number,
    "mention_examples": ["example1", "example2", ...]
  }
}

CRITICAL REQUIREMENTS:
- natural_alignment_score is REQUIRED and must be a number between 1 and 5
- brand_mentions object is REQUIRED with all fields (direct_brand_mentions, competitor_mentions, category_discussions, mention_examples)
- All scores must be numeric values, not strings or null
- Use the full 1-5 scale: don't default to 3.0 unless truly neutral
"""


def get_model_list():
    """Get list of model IDs for dropdown"""
    return list(MODELS.keys())


def get_model_display_names():
    """Get list of display names for models"""
    return [MODELS[model]["display_name"] for model in MODELS.keys()]


def get_model_info(model_id):
    """Get configuration for a specific model"""
    return MODELS.get(model_id, MODELS[DEFAULT_MODEL])


def estimate_cost(video_duration_seconds, model_id=DEFAULT_MODEL):
    """
    Estimate the cost of analyzing a video

    Args:
        video_duration_seconds: Duration of video in seconds
        model_id: Model to use for analysis

    Returns:
        dict with cost breakdown
    """
    model_info = get_model_info(model_id)

    # Calculate input tokens
    video_tokens = video_duration_seconds * (TOKENS_PER_VIDEO_SECOND + TOKENS_PER_AUDIO_SECOND)
    total_input_tokens = video_tokens + AVERAGE_PROMPT_TOKENS

    # Calculate costs
    input_cost = (total_input_tokens / 1_000_000) * model_info["cost_per_m_tokens_input"]
    output_cost = (AVERAGE_RESPONSE_TOKENS / 1_000_000) * model_info["cost_per_m_tokens_output"]
    total_cost = input_cost + output_cost

    return {
        "input_tokens": int(total_input_tokens),
        "output_tokens": AVERAGE_RESPONSE_TOKENS,
        "total_tokens": int(total_input_tokens + AVERAGE_RESPONSE_TOKENS),
        "input_cost": input_cost,
        "output_cost": output_cost,
        "total_cost": total_cost,
        "model": model_id,
        "model_display_name": model_info["display_name"]
    }


def format_cost(cost):
    """Format cost as currency string"""
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def estimate_image_generation_cost(num_images: int = 1, model_id: str = "gemini-2.5-flash-image"):
    """
    Estimate the cost of generating images

    Args:
        num_images: Number of images to generate
        model_id: Model to use for generation

    Returns:
        dict with cost breakdown
    """
    model_info = get_model_info(model_id)

    cost_per_image = model_info.get("cost_per_image", 0.039)
    total_cost = cost_per_image * num_images

    return {
        "num_images": num_images,
        "cost_per_image": cost_per_image,
        "total_cost": total_cost,
        "model": model_id,
        "model_display_name": model_info["display_name"]
    }


def estimate_video_generation_cost(duration_seconds: int = 8, model_id: str = "veo-3.1-fast-generate-preview"):
    """
    Estimate the cost of generating a video

    Args:
        duration_seconds: Video duration in seconds
        model_id: Model to use for generation

    Returns:
        dict with cost breakdown
    """
    model_info = get_model_info(model_id)

    cost_per_second = model_info.get("cost_per_second", 0.15)
    total_cost = cost_per_second * duration_seconds

    return {
        "duration_seconds": duration_seconds,
        "cost_per_second": cost_per_second,
        "total_cost": total_cost,
        "model": model_id,
        "model_display_name": model_info["display_name"]
    }
