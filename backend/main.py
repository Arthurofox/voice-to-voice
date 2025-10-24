import base64
import logging
import os
import time
from typing import Any, Dict, Optional
import sys

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from .audio_translate import AudioTranslationResult, AudioTranslator
from .realtime_client_manager import RealtimeClientManager, RealtimeSessionConfig
import openai


load_dotenv()

logger = logging.getLogger("voice-to-voice")
logging.basicConfig(level=logging.INFO)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is missing. Please create a .env file with OPENAI_API_KEY=your-key."
    )


DEFAULT_REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-4o-realtime-preview")
DEFAULT_REALTIME_MINI_MODEL = os.getenv("REALTIME_MINI_MODEL", "gpt-4o-realtime-mini")
DEFAULT_AUDIO_MODEL = os.getenv("AUDIO_MODEL", "gpt-4o-audio-preview")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "verse")


def create_app() -> FastAPI:
    allowed_origins = [
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ]

    app = FastAPI(title="Local Voice Translator", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    static_dir = os.path.join(os.path.dirname(__file__), "..", "frontend", "static")
    static_dir = os.path.abspath(static_dir)
    if os.path.isdir(static_dir):
        app.mount("/frontend/static", StaticFiles(directory=static_dir), name="static")

    realtime_manager = RealtimeClientManager(
        api_key=OPENAI_API_KEY,
        default_voice=DEFAULT_VOICE,
        default_models={
            "realtime": DEFAULT_REALTIME_MODEL,
            "realtime_mini": DEFAULT_REALTIME_MINI_MODEL,
        },
    )

    translator = AudioTranslator(
        api_key=OPENAI_API_KEY,
        default_voice=DEFAULT_VOICE,
        default_model=DEFAULT_AUDIO_MODEL,
    )

    @app.on_event("startup")
    async def startup_event() -> None:
        logger.info("Local Voice Translator backend starting up.")
        logger.info("Python executable: %s", sys.executable)
        logger.info("OpenAI package location: %s", getattr(openai, "__file__", "unknown"))
        if "venv" not in sys.executable:
            logger.warning(
                "Backend is not running inside a virtual environment. Activate your venv to avoid SDK mismatches."
            )
        print(
            "\nQuick Start:\n"
            "  • Backend running at http://127.0.0.1:8000\n"
            "  • Streamlit UI: http://127.0.0.1:8501\n"
            "  • Standalone realtime page: http://127.0.0.1:8000/frontend/static/realtime.html\n"
            "Ensure your .env includes OPENAI_API_KEY.\n"
        )

    @app.middleware("http")
    async def request_timer(request: Request, call_next):  # type: ignore[override]
        request_id = f"{time.time_ns()}"
        logger.info("Started %s %s (request_id=%s)", request.method, request.url.path, request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "Completed %s %s in %.1f ms (request_id=%s)",
                request.method,
                request.url.path,
                elapsed_ms,
                request_id,
            )
        return response

    def get_realtime_manager() -> RealtimeClientManager:
        return realtime_manager

    def get_translator() -> AudioTranslator:
        return translator

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok"}

    @app.get("/realtime/token")
    async def issue_realtime_token(
        model: Optional[str] = Query(default=None, description="Realtime model identifier"),
        source_lang: str = Query(default="en", description="Source language (ISO-639-1)"),
        target_lang: str = Query(default="fr", description="Target language (ISO-639-1)"),
        voice: Optional[str] = Query(default=None, description="Voice identifier override"),
        config: RealtimeClientManager = Depends(get_realtime_manager),
    ) -> Dict[str, Any]:
        try:
            selection = model or DEFAULT_REALTIME_MODEL
            output_format = "g711_ulaw" if selection and "mini" in selection else "pcm16"
            session_config = RealtimeSessionConfig(
                model=selection,
                source_lang=source_lang,
                target_lang=target_lang,
                voice=voice,
                output_audio_format=output_format,
            )
            token_payload = config.create_session_token(session_config)
            logger.info(
                "Issued realtime token for model=%s source=%s target=%s",
                session_config.model,
                session_config.source_lang,
                session_config.target_lang,
            )
            return token_payload
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to issue realtime token")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/audio/translate")
    async def audio_translate(
        source_lang: str = Query(default="en", description="Source language code"),
        target_lang: str = Query(default="fr", description="Target language code"),
        voice: Optional[str] = Query(default=None, description="Voice identifier for output audio"),
        audio_file: UploadFile = File(description="Recorded audio (wav/pcm)"),
        translation_service: AudioTranslator = Depends(get_translator),
    ) -> JSONResponse:
        try:
            file_bytes = await audio_file.read()
            timing_start = time.perf_counter()
            result: AudioTranslationResult = await translation_service.translate_audio(
                audio_bytes=file_bytes,
                filename=audio_file.filename or "input.wav",
                source_lang=source_lang,
                target_lang=target_lang,
                voice=voice,
            )
            total_elapsed_ms = (time.perf_counter() - timing_start) * 1000
            logger.info(
                "Audio translation complete source=%s target=%s duration=%.1fms",
                source_lang,
                target_lang,
                total_elapsed_ms,
            )

            payload = {
                "audio_base64": base64.b64encode(result.audio_bytes).decode("utf-8"),
                "audio_format": result.audio_format,
                "timing": result.timing,
                "detected_source_language": result.detected_source_language,
                "model": result.model,
                "voice": result.voice,
            }

            return JSONResponse(content=payload)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Audio translation failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


app = create_app()
