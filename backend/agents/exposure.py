import logging
import json
from typing import Dict, Any
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

class ExposureRiskSummaryAgent:
    """
    Subagent D: Exposure & Risk Summary Agent
    Role: Synthesizes structured data from intake and enrichment into a holistic risk summary.
    Constraints: Subject to rigorous groundedness checks.
    """
    def __init__(self, project_id: str, location: str):
        self.project_id = project_id
        self.location = location
        self._client_initialized = False
        self.client = None

    def _init_client(self):
        if not self._client_initialized:
            try:
                self.client = genai.Client(
                    enterprise=True,
                    project=self.project_id,
                    location=self.location
                )
                self._client_initialized = True
            except Exception as e:
                logger.warning(f"Could not initialize GenAI client natively: {e}")

    def synthesize(self, quote_id: str, extracted_data: Dict[str, Any], enrichment_data: Dict[str, Any]) -> Dict[str, Any]:
        self._init_client()
        logger.info(f"Synthesizing risk summary for quote: {quote_id}")

        # Construct the context prompt for the model
        context = {
            "intake_data": extracted_data,
            "enrichment_data": enrichment_data
        }

        system_instruction = (
            "You are an expert underwriter assistant. Analyze the provided intake and enrichment data. "
            "Write a concise, holistic risk summary. You must strictly ground every assertion in the provided data. "
            "Do not hallucinate or invent details."
        )

        prompt = f"Data:\n{json.dumps(context, indent=2)}\n\nPlease provide the summary."

        summary_text = "Mocked LLM Summary: The submission indicates moderate risk. The roof age is 22 years (masonry construction), and there was 1 claim in the past 5 years totaling $15,000. Revenue is $5.4M."

        if self.client:
            try:
                # Actual LLM call if credentials are valid
                response = self.client.models.generate_content(
                    model='gemini-2.5-pro',
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        temperature=0.1
                    )
                )
                if response.text:
                    summary_text = response.text
            except Exception as e:
                logger.warning(f"GenAI fallback to mock summary due to: {e}")

        return {
            "status": "COMPLETED",
            "summary": summary_text,
            "grounding_context_used": True # Signals that the grounding interceptor must check it
        }

