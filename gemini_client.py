"""
Gemini API client wrapper with support for video analysis
"""

import json
import time
from typing import Dict, Optional, Callable
import google.generativeai as genai
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
