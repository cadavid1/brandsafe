"""
Gemini Deep Research API client using Interactions API
Provides autonomous research capabilities for creator demographic and background analysis
"""

import json
import time
import hashlib
from typing import Dict, List, Optional, Callable
from datetime import datetime, timedelta


class DeepResearchError(Exception):
    """Custom exception for Deep Research errors"""
    pass


# Query templates for different research types
DEMOGRAPHIC_QUERY_TEMPLATE = """
Research the audience demographics for the creator "{creator_name}" on {platform} (profile: {profile_url}).

Find and provide the following information with citations:

1. **Audience Gender Distribution**: Percentage breakdown of female/male/other viewers
2. **Age Distribution**: Percentage in brackets: 13-17, 18-24, 25-34, 35-44, 45-54, 55-64, 65+
3. **Geographic Distribution**: Top 5 countries with percentages, including US percentage
4. **Primary Languages**: Languages spoken by the audience with percentages
5. **Audience Interests**: Top 10 interest categories or topics

For each data point, cite the specific source. If data is not available for a particular metric, clearly indicate "Data Not Available" and explain why.

Return the results in JSON format:
{{
  "gender": {{"female": <number>, "male": <number>, "other": <number>}},
  "age_brackets": {{
    "13-17": <number>, "18-24": <number>, "25-34": <number>,
    "35-44": <number>, "45-54": <number>, "55-64": <number>, "65+": <number>
  }},
  "geography": [
    {{"country": "US", "percentage": <number>}},
    {{"country": "<country>", "percentage": <number>}},
    ...
  ],
  "languages": [
    {{"language": "<language>", "percentage": <number>}},
    ...
  ],
  "interests": ["interest1", "interest2", ...],
  "data_confidence": "high" | "medium" | "low",
  "sources": [
    {{"source": "source name/URL", "data_points": ["gender", "age"]}},
    ...
  ],
  "notes": "Any additional context or caveats about the data"
}}
"""

BACKGROUND_QUERY_TEMPLATE = """
Conduct comprehensive background research on the creator "{creator_name}" across platforms: {platforms}.

Research and provide:

1. **Career History**: When they started creating content, major milestones, growth trajectory
2. **Content Evolution**: How their content themes have changed over time
3. **Past Controversies**: Any brand safety issues, controversies, or public incidents (with dates and sources)
4. **Brand Partnerships**: Past collaborations, sponsored content, partnership outcomes
5. **Reputation Analysis**: Overall sentiment in media coverage, forums, and social media
6. **Authenticity Indicators**: Evidence of ghostwriting, content originality concerns, or authenticity markers

For each finding, provide specific citations with dates and sources.

Return the results in JSON format:
{{
  "career_history": {{
    "started": "<year or date>",
    "milestones": [
      {{"date": "<date>", "event": "<description>", "source": "<source>"}},
      ...
    ],
    "growth_summary": "<text summary>"
  }},
  "content_evolution": [
    {{"period": "<time range>", "themes": ["theme1", ...], "description": "<text>"}},
    ...
  ],
  "controversies": [
    {{"date": "<date>", "description": "<text>", "severity": "high|medium|low", "source": "<source>"}},
    ...
  ],
  "brand_partnerships": [
    {{"brand": "<brand name>", "date": "<date>", "type": "<sponsorship type>", "outcome": "<known outcome>", "source": "<source>"}},
    ...
  ],
  "reputation": {{
    "overall_sentiment": "positive" | "neutral" | "negative" | "mixed",
    "summary": "<text>",
    "media_coverage": "<summary of media mentions>",
    "sources": ["<source1>", "<source2>", ...]
  }},
  "authenticity": {{
    "assessment": "high" | "medium" | "low",
    "indicators": ["<indicator1>", "<indicator2>", ...],
    "concerns": ["<concern1>", ...] or [],
    "sources": ["<source>", ...]
  }},
  "data_confidence": "high" | "medium" | "low",
  "research_date": "<ISO date>",
  "notes": "Any additional context"
}}
"""


class DeepResearchClient:
    """
    Client for Gemini Deep Research API (Interactions API)

    Uses background execution and polling for long-running research tasks.
    """

    def __init__(self, api_key: str):
        """
        Initialize Deep Research client

        Args:
            api_key: Gemini API key
        """
        self.api_key = api_key
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        self.agent_id = "deep-research-pro-preview-12-2025"

        # Try importing requests
        try:
            import requests
            self.requests = requests
            self.api_available = True
        except ImportError:
            print("Requests library not installed. Install with: pip install requests")
            self.api_available = False

    def _make_request(self, method: str, endpoint: str, data: dict = None, stream: bool = False):
        """Make HTTP request to Interactions API"""
        if not self.api_available:
            raise DeepResearchError("Requests library not installed")

        url = f"{self.base_url}/{endpoint}"
        headers = {
            'x-goog-api-key': self.api_key,
            'Content-Type': 'application/json'
        }

        try:
            if method == 'POST':
                response = self.requests.post(url, headers=headers, json=data, stream=stream)
            elif method == 'GET':
                response = self.requests.get(url, headers=headers, stream=stream)
            else:
                raise DeepResearchError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response

        except self.requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_data = e.response.json()
                error_detail = error_data.get('error', {}).get('message', str(e))
            except:
                error_detail = str(e)
            raise DeepResearchError(f"Deep Research API error: {error_detail}")
        except Exception as e:
            raise DeepResearchError(f"Deep Research request failed: {e}")

    def start_research(self, query: str, output_schema: Optional[Dict] = None) -> str:
        """
        Start a background research task

        Args:
            query: Research query/prompt
            output_schema: Optional JSON schema for structured output

        Returns:
            interaction_id for polling results
        """
        data = {
            'agent': self.agent_id,
            'input': {
                'type': 'text',
                'text': query  # Direct text field, no parts array
            },
            'background': True  # Required for long-running tasks
        }

        # Add output schema if provided
        if output_schema:
            data['agent_config'] = {
                'type': 'deep-research',
                'output_format': {
                    'type': 'json',
                    'schema': output_schema
                }
            }

        try:
            # Debug: print the actual data being sent
            import json as json_module
            print(f"  [DEBUG] Sending request data: {json_module.dumps(data, indent=2)}")

            response = self._make_request('POST', 'interactions', data=data)
            result = response.json()

            # Debug: print the response
            print(f"  [DEBUG] API Response: {json_module.dumps(result, indent=2)}")

            # Extract interaction ID from response - it's in the 'id' field
            interaction_id = result.get('id', '')
            if not interaction_id:
                print(f"  [DEBUG] Failed to extract interaction ID from response")
                print(f"  [DEBUG] Response keys: {list(result.keys())}")
                print(f"  [DEBUG] 'id' field value: {result.get('id', 'NOT PRESENT')}")
                raise DeepResearchError("Failed to get interaction ID from response")

            print(f"  [DEBUG] Extracted interaction ID: {interaction_id}")
            return interaction_id

        except Exception as e:
            raise DeepResearchError(f"Failed to start research: {e}")

    def poll_research(self, interaction_id: str, timeout: int = 1800, db_manager=None) -> Dict:
        """
        Poll for research completion (blocking)

        Args:
            interaction_id: ID from start_research()
            timeout: Maximum time to wait in seconds (default 30 minutes)
            db_manager: Optional DatabaseManager instance for connection refresh

        Returns:
            Research results dictionary with status and result
        """
        start_time = time.time()
        poll_interval = 5  # Start with 5 second intervals

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise DeepResearchError(f"Research timeout after {timeout}s")

            # Refresh database connection periodically to prevent timeouts
            if db_manager:
                try:
                    db_manager.refresh_connection_if_needed(refresh_interval_seconds=300)
                except Exception as refresh_error:
                    print(f"  [WARNING] Failed to refresh DB connection: {refresh_error}")

            # Get current status
            try:
                response = self._make_request('GET', f'interactions/{interaction_id}')
                result = response.json()

                # Check status - it's a string field, not a dict
                status = result.get('status', 'unknown')

                if status == 'completed':
                    # Extract result
                    output = result.get('output', {})
                    parts = output.get('parts', [])

                    # Get text from parts
                    result_text = ''
                    for part in parts:
                        if 'text' in part:
                            result_text += part['text']

                    # Try to parse as JSON
                    try:
                        result_data = json.loads(result_text)
                    except json.JSONDecodeError:
                        result_data = {'raw_text': result_text}

                    # Extract usage metadata
                    usage = result.get('usage', {})

                    return {
                        'status': 'completed',
                        'result': result_data,
                        'raw_text': result_text,
                        'input_tokens': usage.get('inputTokenCount', 0),
                        'output_tokens': usage.get('outputTokenCount', 0),
                        'total_tokens': usage.get('totalTokenCount', 0)
                    }

                elif status == 'failed':
                    error_msg = result.get('error', 'Unknown error')
                    return {
                        'status': 'failed',
                        'error': error_msg
                    }

                elif status in ['in_progress', 'pending']:
                    # Still running, wait and retry
                    print(f"  [DEEP RESEARCH] Status: {status}, elapsed: {int(elapsed)}s")
                    time.sleep(poll_interval)

                    # Increase poll interval gradually (max 30s)
                    poll_interval = min(poll_interval + 5, 30)

                else:
                    print(f"  [DEEP RESEARCH] Unknown status: {status}")
                    time.sleep(poll_interval)

            except KeyboardInterrupt:
                print(f"\n  [INTERRUPTED] Research still running with ID: {interaction_id}")
                print(f"  You can resume later by polling this ID")
                raise
            except DeepResearchError:
                raise
            except Exception as e:
                raise DeepResearchError(f"Error polling research: {e}")

    def research_creator_demographics(
        self,
        creator_name: str,
        platform: str,
        profile_url: str,
        timeout: int = 1800,
        db_manager=None
    ) -> Dict:
        """
        Research creator audience demographics

        Args:
            creator_name: Creator's name
            platform: Platform name (instagram, tiktok, etc.)
            profile_url: Profile URL
            timeout: Maximum wait time in seconds
            db_manager: Optional DatabaseManager instance for connection refresh

        Returns:
            Demographic data dictionary
        """
        query = DEMOGRAPHIC_QUERY_TEMPLATE.format(
            creator_name=creator_name,
            platform=platform,
            profile_url=profile_url
        )

        print(f"  [DEEP RESEARCH] Starting demographic research for {creator_name} on {platform}...")
        interaction_id = self.start_research(query)
        print(f"  [DEEP RESEARCH] Research started, ID: {interaction_id}")

        result = self.poll_research(interaction_id, timeout=timeout, db_manager=db_manager)

        if result['status'] == 'failed':
            raise DeepResearchError(f"Research failed: {result.get('error', 'Unknown error')}")

        # Add metadata
        result['result']['query_type'] = 'demographics'
        result['result']['creator_name'] = creator_name
        result['result']['platform'] = platform
        result['result']['collected_at'] = datetime.now().isoformat()

        return result

    def research_creator_background(
        self,
        creator_name: str,
        platforms: List[str],
        timeout: int = 1800
    ) -> Dict:
        """
        Research creator background and history

        Args:
            creator_name: Creator's name
            platforms: List of platforms they're active on
            timeout: Maximum wait time in seconds

        Returns:
            Background research dictionary
        """
        platforms_str = ', '.join(platforms)
        query = BACKGROUND_QUERY_TEMPLATE.format(
            creator_name=creator_name,
            platforms=platforms_str
        )

        print(f"  [DEEP RESEARCH] Starting background research for {creator_name}...")
        interaction_id = self.start_research(query)
        print(f"  [DEEP RESEARCH] Research started, ID: {interaction_id}")

        result = self.poll_research(interaction_id, timeout=timeout)

        if result['status'] == 'failed':
            raise DeepResearchError(f"Research failed: {result.get('error', 'Unknown error')}")

        # Add metadata
        result['result']['query_type'] = 'background'
        result['result']['creator_name'] = creator_name
        result['result']['platforms'] = platforms

        return result

    @staticmethod
    def generate_query_hash(query_text: str) -> str:
        """Generate unique hash for query deduplication"""
        return hashlib.sha256(query_text.encode()).hexdigest()

    @staticmethod
    def calculate_cost(input_tokens: int, output_tokens: int) -> float:
        """
        Calculate Deep Research cost

        Pricing (as of Dec 2024):
        - Input: $2.00 per 1M tokens
        - Output: $12.00 per 1M tokens

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Total cost in USD
        """
        input_cost = (input_tokens / 1_000_000) * 2.00
        output_cost = (output_tokens / 1_000_000) * 12.00
        return input_cost + output_cost
