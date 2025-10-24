from __future__ import annotations

import dataclasses
import json
import logging
import os
import time
from typing import Dict, Optional

import httpx


logger = logging.getLogger(__name__)


REALTIME_BASE_URL = "https://api.openai.com/v1/realtime/sessions"


@dataclasses.dataclass
class RealtimeSessionConfig:
    model: str
    source_lang: str
    target_lang: str
    voice: Optional[str] = None
    input_audio_format: str = "pcm16"
    output_audio_format: str = "pcm16"
    vad: bool = True


class RealtimeClientManager:
    """Server-side helper for generating short-lived tokens for the browser Realtime client."""

    def __init__(
        self,
        api_key: str,
        default_voice: str,
        default_models: Optional[Dict[str, str]] = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.api_key = api_key
        self.default_voice = default_voice
        self.default_models = default_models or {}
        self.timeout_seconds = timeout_seconds

    def create_session_token(self, session: RealtimeSessionConfig) -> Dict[str, str]:
        """Create a short-lived client token using OpenAI's Realtime Sessions endpoint."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        voice = session.voice or self.default_voice
        instruction = self._build_system_instruction(session.source_lang, session.target_lang)

        body = {
            "model": session.model,
            "voice": voice,
            "input_audio_format": session.input_audio_format,
            "output_audio_format": session.output_audio_format,
            "instructions": instruction,
            "turn_detection": {"type": "server_vad", "threshold": 0.5} if session.vad else None,
        }

        # Remove None values to keep the payload tidy.
        body = {k: v for k, v in body.items() if v is not None}

        logger.debug("Creating realtime session with body=%s", json.dumps(body))

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(REALTIME_BASE_URL, headers=headers, json=body)

        if response.status_code >= 400:
            logger.error("Realtime session creation failed: %s", response.text)
            response.raise_for_status()

        payload = response.json()
        # Standardise keys we expose to the frontend so we can tweak server-side without breaking the UI.
        token_data = {
            "client_secret": payload.get("client_secret", {}).get("value"),
            "expires_at": payload.get("client_secret", {}).get("expires_at"),
            "model": payload.get("model", session.model),
            "voice": voice,
            "instructions": instruction,
            "url": payload.get("url"),
            "created_at": payload.get("created_at", int(time.time())),
        }

        missing = [k for k, v in token_data.items() if v is None]
        if missing:
            logger.warning("Realtime token missing keys: %s", ", ".join(missing))

        return token_data

    @staticmethod
    def _build_system_instruction(source_lang: str, target_lang: str) -> str:
        return (
            "You are a concise interpreter. Translate everything you hear from "
            f"{source_lang.upper()} into {target_lang.upper()}.\n"
            "Preserve tone and timing. Do not add commentary or greetings."
        )

    def default_model_for(self, variant: str) -> str:
        return self.default_models.get(variant) or os.getenv("REALTIME_MODEL", "gpt-4o-realtime-preview")
