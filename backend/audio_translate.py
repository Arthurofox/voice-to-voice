from __future__ import annotations

import asyncio
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
    transcription_text: str
    translated_text: str


class AudioTranslator:
    """Wrapper around OpenAI's audio-in/audio-out translation path."""

    def __init__(
        self,
        api_key: str,
        translation_model: str,
        default_voice: str,
        transcription_model: Optional[str] = None,
        tts_model: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.client = OpenAI(api_key=api_key, timeout=timeout)
        self.translation_model = translation_model
        self.default_voice = default_voice
        self.transcription_model = transcription_model or "gpt-4o-mini-transcribe"
        self.tts_model = tts_model or "gpt-4o-mini-tts"

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
        translation_model = self.translation_model

        timings = {"received_at": time.time()}

        # Stage 1: transcription
        pipeline_start = time.perf_counter()
        transcription_start = pipeline_start
        transcription = await asyncio.to_thread(
            self.client.audio.transcriptions.create,
            model=self.transcription_model,
            file=(filename, audio_bytes, "audio/wav"),
            language=source_lang,
        )
        transcription_elapsed = (time.perf_counter() - transcription_start) * 1000
        timings["transcription_duration_ms"] = transcription_elapsed

        transcript_text = getattr(transcription, "text", None) or ""
        detected_language = getattr(transcription, "language", None)
        if not transcript_text.strip():
            raise RuntimeError("Transcription returned empty text.")

        # Stage 2: translation (text→text)
        translation_prompt = (
            f"Translate the following speech from {source_lang.upper()} to {target_lang.upper()}.\n"
            "Return only the translated text with natural phrasing."
        )
        translation_start = time.perf_counter()
        translation_response = await asyncio.to_thread(
            self.client.responses.create,
            model=translation_model,
            instructions=translation_prompt,
            input=transcript_text,
        )
        translation_elapsed = (time.perf_counter() - translation_start) * 1000
        timings["translation_duration_ms"] = translation_elapsed

        translated_text = translation_response.output_text().strip()
        if not translated_text:
            raise RuntimeError("Translation response did not include text output.")

        # Stage 3: TTS
        tts_start = time.perf_counter()
        speech_response = await asyncio.to_thread(
            self.client.audio.speech.create,
            model=self.tts_model,
            voice=voice_id,
            input=translated_text,
            response_format="wav",
        )
        audio_content = speech_response.read()
        tts_elapsed = (time.perf_counter() - tts_start) * 1000
        timings["tts_duration_ms"] = tts_elapsed
        timings["total_latency_ms"] = (time.perf_counter() - pipeline_start) * 1000

        return AudioTranslationResult(
            audio_bytes=audio_content,
            audio_format="wav",
            timing=timings,
            detected_source_language=detected_language or source_lang,
            voice=voice_id,
            model=translation_model,
            transcription_text=transcript_text,
            translated_text=translated_text,
        )

    @staticmethod
    def _extract_detected_language(response: object) -> Optional[str]:
        """Retained for compatibility; currently unused."""
        try:
            usage = getattr(response, "metadata", None) or {}
            if isinstance(usage, dict):
                return usage.get("input_language")
        except Exception:  # noqa: BLE001
            return None
        return None
