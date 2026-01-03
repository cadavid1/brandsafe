"""
Gemini API client wrapper with support for video analysis
"""

import json
import time
import warnings
from typing import Dict, Optional, Callable

# Suppress FutureWarning for deprecated google.generativeai package
warnings.filterwarnings('ignore', category=FutureWarning, module='google.generativeai')

import google.generativeai as genai
from google import genai as genai_client
from google.genai import types
from config import (
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
    EXPONENTIAL_BACKOFF
)


class GeminiAPIError(Exception):
    """Custom exception for Gemini API errors"""
    pass


class GeminiClient:
    """Wrapper for Gemini API interactions"""

    def __init__(self, api_key: str):
        """
        Initialize Gemini client

        Args:
            api_key: Google API key
        """
        if not api_key:
            raise GeminiAPIError("API key is required")

        self.api_key = api_key
        genai.configure(api_key=api_key)
        # Initialize client for video generation (Veo API)
        self.client = genai_client.Client(api_key=api_key)

    def upload_video(
        self,
        video_path: str,
        display_name: Optional[str] = None,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> any:
        """
        Upload video file to Gemini API

        Args:
            video_path: Path to video file
            display_name: Optional display name for the file
            progress_callback: Optional callback for upload progress (0-1)

        Returns:
            Uploaded file object

        Raises:
            GeminiAPIError: If upload fails
        """
        try:
            if progress_callback:
                progress_callback(0.1)

            # Upload file
            video_file = genai.upload_file(
                path=video_path,
                display_name=display_name or video_path
            )

            if progress_callback:
                progress_callback(0.5)

            # Wait for processing
            while video_file.state.name == "PROCESSING":
                if progress_callback:
                    progress_callback(0.7)
                time.sleep(1)
                video_file = genai.get_file(video_file.name)

            if video_file.state.name == "FAILED":
                raise GeminiAPIError(f"Video processing failed: {video_file.state}")

            if progress_callback:
                progress_callback(1.0)

            return video_file

        except Exception as e:
            raise GeminiAPIError(f"Video upload failed: {str(e)}")

    def analyze_content(
        self,
        prompt: str,
        system_instruction: str = None,
        response_type: str = "json",
        model_name: str = "gemini-2.0-flash-exp"
    ) -> Dict:
        """
        Analyze text content with Gemini model

        Args:
            prompt: Analysis prompt
            system_instruction: Optional system instruction for the model
            response_type: Response format ("json" or "text")
            model_name: Name of the model to use

        Returns:
            Analysis result as dictionary

        Raises:
            GeminiAPIError: If analysis fails
        """
        try:
            response_mime_type = "application/json" if response_type == "json" else "text/plain"

            # Create model
            model_config = {
                "model_name": model_name,
                "generation_config": {"response_mime_type": response_mime_type}
            }

            if system_instruction:
                model_config["system_instruction"] = system_instruction

            model = genai.GenerativeModel(**model_config)

            # Generate content
            response = model.generate_content(prompt)

            # Parse response
            if response_type == "json":
                try:
                    return json.loads(response.text)
                except json.JSONDecodeError:
                    # Try to extract JSON from text
                    text = response.text.strip()
                    if text.startswith("```json"):
                        text = text[7:]
                    if text.endswith("```"):
                        text = text[:-3]
                    return json.loads(text.strip())
            else:
                return {"text": response.text}

        except Exception as e:
            raise GeminiAPIError(f"Content analysis failed: {str(e)}")

    def analyze_video(
        self,
        video_file: any,
        prompt: str,
        system_instruction: str,
        model_name: str,
        response_mime_type: str = "application/json"
    ) -> Dict:
        """
        Analyze video with Gemini model

        Args:
            video_file: Uploaded video file object
            prompt: Analysis prompt
            system_instruction: System instruction for the model
            model_name: Name of the model to use
            response_mime_type: Expected response format

        Returns:
            Analysis result as dictionary

        Raises:
            GeminiAPIError: If analysis fails
        """
        try:
            # Create model
            model = genai.GenerativeModel(
                model_name=model_name,
                system_instruction=system_instruction,
                generation_config={"response_mime_type": response_mime_type}
            )

            # Generate content
            response = model.generate_content([prompt, video_file])

            # Parse response
            if response_mime_type == "application/json":
                try:
                    return json.loads(response.text)
                except json.JSONDecodeError:
                    # Try to extract JSON from text
                    text = response.text.strip()
                    if text.startswith("```json"):
                        text = text[7:]
                    if text.endswith("```"):
                        text = text[:-3]
                    return json.loads(text.strip())
            else:
                return {"text": response.text}

        except Exception as e:
            raise GeminiAPIError(f"Video analysis failed: {str(e)}")

    def delete_file(self, file_name: str) -> bool:
        """
        Delete uploaded file from Gemini

        Args:
            file_name: Name of file to delete

        Returns:
            True if deleted successfully
        """
        try:
            genai.delete_file(file_name)
            return True
        except Exception:
            return False

    def analyze_video_with_retry(
        self,
        video_path: str,
        prompt: str,
        system_instruction: str,
        model_name: str,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict:
        """
        Complete video analysis pipeline with retry logic

        Args:
            video_path: Path to video file
            prompt: Analysis prompt
            system_instruction: System instruction
            model_name: Model to use
            progress_callback: Optional callback(stage_name, progress)

        Returns:
            Analysis result dictionary

        Raises:
            GeminiAPIError: If all retries fail
        """
        video_file = None
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                # Stage 1: Upload
                if progress_callback:
                    progress_callback("Uploading video to Gemini", 0.0)

                def upload_progress(progress):
                    if progress_callback:
                        progress_callback("Uploading video to Gemini", progress * 0.3)

                video_file = self.upload_video(
                    video_path,
                    progress_callback=upload_progress
                )

                # Stage 2: Analyze
                if progress_callback:
                    progress_callback("Analyzing video", 0.3)

                result = self.analyze_video(
                    video_file,
                    prompt,
                    system_instruction,
                    model_name
                )

                if progress_callback:
                    progress_callback("Analysis complete", 1.0)

                # Cleanup
                if video_file:
                    self.delete_file(video_file.name)

                return result

            except Exception as e:
                last_error = e

                # Cleanup on error
                if video_file:
                    try:
                        self.delete_file(video_file.name)
                    except:
                        pass

                # Retry logic
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_SECONDS
                    if EXPONENTIAL_BACKOFF:
                        delay *= (2 ** attempt)

                    if progress_callback:
                        progress_callback(
                            f"Retry {attempt + 1}/{MAX_RETRIES} in {delay}s",
                            0.0
                        )

                    time.sleep(delay)
                else:
                    raise GeminiAPIError(
                        f"Analysis failed after {MAX_RETRIES} attempts: {str(last_error)}"
                    )

        # Should not reach here, but just in case
        raise GeminiAPIError(f"Analysis failed: {str(last_error)}")

    def generate_image(
        self,
        prompt: str,
        model_name: str = "gemini-2.5-flash-image",
        aspect_ratio: str = "16:9",
        reference_images: list = None,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict:
        """
        Generate image using Gemini image generation models (Nano Banana)

        Args:
            prompt: Text description of desired image
            model_name: Image generation model to use
            aspect_ratio: Aspect ratio (16:9, 1:1, 9:16, 4:3)
            reference_images: Optional list of reference image paths
            progress_callback: Progress callback function

        Returns:
            Dict with 'image_data' (bytes), 'metadata', 'cost'

        Raises:
            GeminiAPIError: If generation fails
        """
        try:
            if progress_callback:
                progress_callback("Initializing image generation", 0.1)

            # Build config using types for Nano Banana
            image_config = types.ImageConfig(
                aspect_ratio=aspect_ratio,
            )

            config = types.GenerateContentConfig(
                response_modalities=["IMAGE"],
                image_config=image_config
            )

            if progress_callback:
                progress_callback("Generating image", 0.3)

            # Generate image using google.genai client
            response = self.client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )

            if progress_callback:
                progress_callback("Processing response", 0.7)

            # Extract image data from response
            if not response.parts:
                raise GeminiAPIError("No image generated in response")

            image_data = None
            for part in response.parts:
                if hasattr(part, 'inline_data'):
                    image_data = part.inline_data.data
                    break

            if not image_data:
                raise GeminiAPIError("Could not extract image data from response")

            if progress_callback:
                progress_callback("Image generation complete", 1.0)

            # Calculate cost (approximately 1290 tokens per image)
            cost = 0.039  # Fixed cost per image for gemini-2.5-flash-image

            return {
                "image_data": image_data,
                "metadata": {
                    "model": model_name,
                    "aspect_ratio": aspect_ratio,
                    "prompt_length": len(prompt)
                },
                "cost": cost
            }

        except GeminiAPIError:
            raise
        except Exception as e:
            raise GeminiAPIError(f"Image generation failed: {str(e)}")

    def generate_video(
        self,
        prompt: str,
        model_name: str = "veo-3.1-fast-generate-preview",
        duration_seconds: int = 8,
        resolution: str = "720p",
        reference_images: list = None,
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict:
        """
        Generate video using Veo 3.1 video generation models

        Args:
            prompt: Text description of desired video (should include Subject, Action, Style, Camera, Ambiance)
            model_name: Video generation model to use
            duration_seconds: Video duration (max 8 seconds)
            resolution: Video resolution (720p or 1080p)
            reference_images: Optional reference images for direction
            progress_callback: Progress callback function

        Returns:
            Dict with 'video_data' (bytes), 'metadata', 'cost', 'thumbnail_data'

        Raises:
            GeminiAPIError: If generation fails
        """
        try:
            if progress_callback:
                progress_callback("Initializing video generation", 0.05)

            # Map resolution to aspect ratio
            aspect_ratio = "16:9"  # Default
            if resolution == "1080p":
                aspect_ratio = "16:9"
            elif resolution == "720p":
                aspect_ratio = "16:9"

            # Build config for Veo 3.1
            config = {
                "aspect_ratio": aspect_ratio,
                "resolution": resolution,
                "duration_seconds": str(duration_seconds)
            }

            # Add reference images if provided
            if reference_images:
                # Upload reference images first
                uploaded_files = []
                for img_path in reference_images:
                    try:
                        img_file = genai.upload_file(path=img_path)
                        uploaded_files.append(img_file)
                    except Exception as e:
                        print(f"Warning: Could not upload reference image {img_path}: {e}")

                if uploaded_files:
                    config["reference_images"] = uploaded_files

            if progress_callback:
                progress_callback("Submitting video generation request", 0.1)

            # Generate video using Veo 3.1 API with the new google.genai client
            # Build config using types
            video_config = types.GenerateVideosConfig(
                aspect_ratio=aspect_ratio,
                resolution=resolution,
            )

            operation = self.client.models.generate_videos(
                model=model_name,
                prompt=prompt,
                config=video_config
            )

            if progress_callback:
                progress_callback("Video generation in progress (this takes 2-5 minutes)", 0.15)

            # Poll for completion
            poll_count = 0
            max_polls = 60  # 10 minutes max (10 second intervals)

            while operation.done is not True:
                if poll_count >= max_polls:
                    raise GeminiAPIError("Video generation timed out after 10 minutes")

                poll_count += 1
                elapsed_seconds = poll_count * 10
                progress = 0.15 + (0.7 * min(poll_count / 30, 1.0))  # Progress up to 0.85

                if progress_callback:
                    progress_callback(f"Generating video ({elapsed_seconds}s elapsed)", progress)

                time.sleep(10)

                # Refresh operation status
                try:
                    operation = self.client.operations.get(operation)

                    # Check for errors during generation
                    if hasattr(operation, 'error') and operation.error:
                        raise GeminiAPIError(f"Video generation failed during polling: {operation.error}")

                except GeminiAPIError:
                    raise
                except Exception as e:
                    raise GeminiAPIError(f"Failed to check operation status: {str(e)}")

            # Check if operation succeeded
            if hasattr(operation, 'error') and operation.error:
                raise GeminiAPIError(f"Video generation failed: {operation.error}")

            if progress_callback:
                progress_callback("Downloading generated video", 0.9)

            # Extract video from operation response
            if not hasattr(operation, 'response') or not operation.response:
                raise GeminiAPIError("No response in completed operation")

            if not hasattr(operation.response, 'generated_videos') or not operation.response.generated_videos:
                raise GeminiAPIError("No generated videos in response")

            # Get first generated video
            generated_video = operation.response.generated_videos[0]

            # Download video data - the API downloads it to the video object
            try:
                self.client.files.download(file=generated_video.video)
            except Exception as e:
                raise GeminiAPIError(f"Failed to download video: {str(e)}")

            # Save to a temporary location first to read the bytes
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp_file:
                temp_path = tmp_file.name

            try:
                generated_video.video.save(temp_path)

                # Read the video data as bytes
                with open(temp_path, 'rb') as f:
                    video_data = f.read()

            except Exception as e:
                raise GeminiAPIError(f"Failed to save video to temp file: {str(e)}")
            finally:
                # Clean up temp file
                if os.path.exists(temp_path):
                    try:
                        os.unlink(temp_path)
                    except:
                        pass

            if not video_data:
                raise GeminiAPIError("Could not download video data")

            if progress_callback:
                progress_callback("Video generation complete", 1.0)

            # Calculate cost based on model
            from config import MODELS
            model_config = MODELS.get(model_name, {})
            cost_per_second = model_config.get('cost_per_second', 0.15)
            cost = cost_per_second * duration_seconds

            return {
                "video_data": video_data,
                "metadata": {
                    "model": model_name,
                    "duration_seconds": duration_seconds,
                    "resolution": resolution,
                    "aspect_ratio": aspect_ratio,
                    "prompt_length": len(prompt)
                },
                "cost": cost,
                "thumbnail_data": None  # Will be generated from video file
            }

        except GeminiAPIError:
            raise
        except Exception as e:
            raise GeminiAPIError(f"Video generation failed: {str(e)}")

    def generate_image_with_retry(
        self,
        prompt: str,
        model_name: str,
        aspect_ratio: str = "16:9",
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict:
        """
        Complete image generation with retry logic

        Args:
            prompt: Image generation prompt
            model_name: Model to use
            aspect_ratio: Aspect ratio
            progress_callback: Optional callback(stage_name, progress)

        Returns:
            Generation result dictionary

        Raises:
            GeminiAPIError: If all retries fail
        """
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                return self.generate_image(
                    prompt=prompt,
                    model_name=model_name,
                    aspect_ratio=aspect_ratio,
                    progress_callback=progress_callback
                )

            except Exception as e:
                last_error = e

                # Retry logic
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_SECONDS
                    if EXPONENTIAL_BACKOFF:
                        delay *= (2 ** attempt)

                    if progress_callback:
                        progress_callback(
                            f"Retry {attempt + 1}/{MAX_RETRIES} in {delay}s",
                            0.0
                        )

                    time.sleep(delay)
                else:
                    raise GeminiAPIError(
                        f"Image generation failed after {MAX_RETRIES} attempts: {str(last_error)}"
                    )

        # Should not reach here, but just in case
        raise GeminiAPIError(f"Image generation failed: {str(last_error)}")

    def generate_video_with_retry(
        self,
        prompt: str,
        model_name: str,
        duration_seconds: int = 8,
        resolution: str = "720p",
        progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> Dict:
        """
        Complete video generation with retry logic and polling

        Args:
            prompt: Video generation prompt
            model_name: Model to use
            duration_seconds: Video duration
            resolution: Video resolution
            progress_callback: Optional callback(stage_name, progress)

        Returns:
            Generation result dictionary

        Raises:
            GeminiAPIError: If all retries fail
        """
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                result = self.generate_video(
                    prompt=prompt,
                    model_name=model_name,
                    duration_seconds=duration_seconds,
                    resolution=resolution,
                    progress_callback=progress_callback
                )
                return result

            except Exception as e:
                last_error = e

                # Retry logic
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_SECONDS
                    if EXPONENTIAL_BACKOFF:
                        delay *= (2 ** attempt)

                    if progress_callback:
                        progress_callback(
                            f"Retry {attempt + 1}/{MAX_RETRIES} in {delay}s",
                            0.0
                        )

                    time.sleep(delay)
                else:
                    raise GeminiAPIError(
                        f"Video generation failed after {MAX_RETRIES} attempts: {str(last_error)}"
                    )

        # Should not reach here, but just in case
        raise GeminiAPIError(f"Video generation failed: {str(last_error)}")


def call_gemini_text(
    api_key: str,
    model_name: str,
    prompt: str,
    system_instruction: str,
    response_mime_type: str = "application/json"
) -> Optional[Dict]:
    """
    Legacy function for text-only Gemini calls (for backward compatibility)

    Args:
        api_key: Google API key
        model_name: Model to use
        prompt: Prompt text
        system_instruction: System instruction
        response_mime_type: Response format

    Returns:
        Response dictionary or None on error
    """
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_instruction,
            generation_config={"response_mime_type": response_mime_type}
        )
        response = model.generate_content(prompt)

        # Extract token usage if available
        result = {}
        if response_mime_type == "application/json":
            result = json.loads(response.text)
        else:
            result = {"text": response.text}

        # Add token usage metadata
        if hasattr(response, 'usage_metadata'):
            result['_usage'] = {
                'prompt_tokens': response.usage_metadata.prompt_token_count,
                'candidates_tokens': response.usage_metadata.candidates_token_count,
                'total_tokens': response.usage_metadata.total_token_count
            }

        return result

    except Exception as e:
        return {"error": str(e)}
