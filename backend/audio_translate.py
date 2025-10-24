from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

from openai import OpenAI


logger = logging.getLogger(__name__)


@dataclass
class AudioTranslationResult:
    audio_bytes: bytes
    audio_format: str
    timing: Dict[str, float]
    detected_source_language: Optional[str]
    voice: str
    model: str


class AudioTranslator:
    """Wrapper around OpenAI's audio-in/audio-out translation path."""

    def __init__(
        self,
        api_key: str,
        default_model: str,
        default_voice: str,
        timeout: float = 60.0,
    ) -> None:
        self.client = OpenAI(api_key=api_key, timeout=timeout)
        self.default_model = default_model
        self.default_voice = default_voice

    async def translate_audio(
        self,
        audio_bytes: bytes,
        filename: str,
        source_lang: str,
        target_lang: str,
        voice: Optional[str],
    ) -> AudioTranslationResult:
        """Send audio to the GPT Audio endpoint and return the translated audio bytes."""
        if not audio_bytes:
            raise ValueError("Audio payload is empty.")

        voice_id = voice or self.default_voice
        model_name = self.default_model

        # Encode audio for the API. The Responses API expects base64 input in streaming scenarios.
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        system_prompt = (
            "You are a bilingual interpreter. Return only translated speech audio. "
            f"Translate input from {source_lang.upper()} to {target_lang.upper()}. "
            "Preserve intent and natural phrasing. No explanations."
        )

        user_payload = [
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "audio": {
                            "data": audio_b64,
                            "format": "wav",
                        },
                    }
                ],
            },
        ]

        timings = {
            "received_at": time.time(),
            "request_duration_ms": None,
            "first_byte_delta_ms": None,
            "total_latency_ms": None,
        }

        request_start = time.perf_counter()

        response = await asyncio.to_thread(
            self.client.responses.create,
            model=model_name,
            modalities=["text", "audio"],
            audio={"voice": voice_id, "format": "wav"},
            input=user_payload,
        )

        request_elapsed_ms = (time.perf_counter() - request_start) * 1000

        timings["request_duration_ms"] = request_elapsed_ms
        timings["total_latency_ms"] = request_elapsed_ms

        audio_content = self._extract_audio_from_response(response)
        detected_language = self._extract_detected_language(response)

        logger.debug(
            "Audio translation response meta: detected_language=%s model=%s voice=%s",
            detected_language,
            model_name,
            voice_id,
        )

        return AudioTranslationResult(
            audio_bytes=audio_content,
            audio_format="wav",
            timing=timings,
            detected_source_language=detected_language,
            voice=voice_id,
            model=model_name,
        )

    @staticmethod
    def _extract_audio_from_response(response: object) -> bytes:
        """Navigate the Responses object and retrieve the primary audio payload."""
        # The OpenAI client currently returns a pydantic-like object. We keep it flexible.
        try:
            for item in response.output:  # type: ignore[attr-defined]
                if getattr(item, "type", None) == "output_audio":
                    data = item.audio.data  # type: ignore[attr-defined]
                    return base64.b64decode(data)
                if getattr(item, "type", None) == "message":
                    for content in getattr(item, "content", []):
                        if getattr(content, "type", None) == "audio":
                            return base64.b64decode(content.audio.data)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse audio from response: %s", exc)

        raise RuntimeError("Audio output not found in response.")

    @staticmethod
    def _extract_detected_language(response: object) -> Optional[str]:
        """Best-effort extraction of model metadata such as detected language."""
        try:
            usage = getattr(response, "metadata", None) or {}
            if isinstance(usage, dict):
                return usage.get("input_language")
        except Exception:  # noqa: BLE001
            return None
        return None
