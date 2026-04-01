"""
Function Registry module.

Provides the BedrockLLMClient for calling Amazon Bedrock foundation models,
along with retry logic, fallback handling, and a factory function.
"""

import json
import os
import time

import boto3

BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0"
)
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")

MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 1.0

FALLBACK_REVIEW_DECISION = json.dumps(
    {
        "status": "Review",
        "reason": "LLM unavailable. Automatically flagged for manual compliance review.",
        "clauses": [],
        "confidence": 0.0,
        "rules_used": [],
    }
)


class LLMFailureError(Exception):
    """Raised when the Bedrock LLM invocation fails after all retries."""


def get_bedrock_client(region: str | None = None) -> "BedrockLLMClient":
    """
    Factory that creates a BedrockLLMClient using the configured AWS region.

    Args:
        region: AWS region override. Falls back to the ``AWS_REGION`` env var.

    Returns:
        An initialised BedrockLLMClient instance.
    """
    return BedrockLLMClient(region=region or AWS_REGION)


class BedrockLLMClient:
    """Thin wrapper around Amazon Bedrock ``invoke_model`` with retry and fallback."""

    def __init__(
        self,
        region: str = AWS_REGION,
        model_id: str = BEDROCK_MODEL_ID,
    ) -> None:
        """
        Initialise the client.

        Args:
            region: AWS region for the Bedrock runtime endpoint.
            model_id: Foundation model identifier (e.g. ``anthropic.claude-3-sonnet-…``).
        """
        self.model_id = model_id
        self.client = boto3.client("bedrock-runtime", region_name=region)

    def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
    ) -> str:
        """
        Call Bedrock ``invoke_model`` with retry logic.

        Args:
            system_prompt: System-level instruction for the model.
            user_prompt: User-facing prompt / query content.
            max_tokens: Maximum tokens in the response.

        Returns:
            The model's text response as a string.

        Raises:
            LLMFailureError: After ``MAX_RETRIES`` consecutive failures.
        """
        payload = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [
                    {"role": "user", "content": user_prompt},
                ],
            }
        )

        last_error: Exception | None = None

        for attempt in range(1, MAX_RETRIES + 2):  # 1 initial + MAX_RETRIES retries
            try:
                response = self.client.invoke_model(
                    modelId=self.model_id,
                    contentType="application/json",
                    accept="application/json",
                    body=payload,
                )
                body = json.loads(response["body"].read())
                return body["content"][0]["text"]

            except Exception as exc:
                last_error = exc
                if attempt <= MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * attempt)

        raise LLMFailureError(
            f"Bedrock invocation failed after {MAX_RETRIES + 1} attempts: {last_error}"
        ) from last_error

    def invoke_with_fallback(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 1024,
    ) -> str:
        """
        Attempt an LLM invocation; on failure return a hardcoded REVIEW decision.

        Args:
            system_prompt: System-level instruction for the model.
            user_prompt: User-facing prompt / query content.
            max_tokens: Maximum tokens in the response.

        Returns:
            Model response on success, or ``FALLBACK_REVIEW_DECISION`` JSON
            string when the LLM is unavailable.
        """
        try:
            return self.invoke(system_prompt, user_prompt, max_tokens)
        except LLMFailureError:
            return FALLBACK_REVIEW_DECISION
