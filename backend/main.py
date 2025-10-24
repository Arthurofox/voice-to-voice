import asyncio
import base64
import json
import logging
import os
import sys
import time
from typing import Any, Dict, Optional

import openai
import websockets
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.websockets import WebSocketState

from .audio_translate import AudioTranslationResult, AudioTranslator
from .realtime_client_manager import RealtimeClientManager, RealtimeSessionConfig


load_dotenv()

logger = logging.getLogger("voice-to-voice")
logging.basicConfig(level=logging.INFO)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is missing. Please create a .env file with OPENAI_API_KEY=your-key."
    )


DEFAULT_REALTIME_MODEL = os.getenv("REALTIME_MODEL", "gpt-realtime")
DEFAULT_REALTIME_MINI_MODEL = os.getenv("REALTIME_MINI_MODEL", "gpt-4o-mini-realtime-preview")
DEFAULT_AUDIO_MODEL = os.getenv("AUDIO_MODEL", "gpt-4o-mini")
DEFAULT_VOICE = os.getenv("DEFAULT_VOICE", "verse")
REALTIME_TRANSPORT_MODE = os.getenv("REALTIME_TRANSPORT", "auto").lower()
DEFAULT_TRANSCRIPTION_MODEL = os.getenv("TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe")
DEFAULT_TTS_MODEL = os.getenv("TTS_MODEL", "gpt-4o-mini-tts")


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
        translation_model=DEFAULT_AUDIO_MODEL,
        default_voice=DEFAULT_VOICE,
        transcription_model=DEFAULT_TRANSCRIPTION_MODEL,
        tts_model=DEFAULT_TTS_MODEL,
    )

    def resolve_transport(model: str) -> str:
        if REALTIME_TRANSPORT_MODE in {"webrtc", "websocket"}:
            return REALTIME_TRANSPORT_MODE
        return realtime_manager.resolve_transport(model, fallback="webrtc")

    @app.on_event("startup")
    async def startup_event() -> None:
        logger.info("Local Voice Translator backend starting up.")
        logger.info("Python executable: %s", sys.executable)
        logger.info("OpenAI package location: %s", getattr(openai, "__file__", "unknown"))
        logger.info(
            "Realtime defaults: model=%s mini_model=%s transport=%s",
            DEFAULT_REALTIME_MODEL,
            DEFAULT_REALTIME_MINI_MODEL,
            resolve_transport(DEFAULT_REALTIME_MODEL),
        )
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
            transport = resolve_transport(selection)
            output_format = "g711_ulaw" if transport == "websocket" else "pcm16"
            session_config = RealtimeSessionConfig(
                model=selection,
                source_lang=source_lang,
                target_lang=target_lang,
                voice=voice,
                output_audio_format=output_format,
                transport=transport,
            )
            token_payload = config.create_session_token(session_config)
            token_payload["transport"] = transport
            token_payload["voice"] = session_config.voice or DEFAULT_VOICE
            logger.info(
                "Issued realtime token for model=%s source=%s target=%s transport=%s",
                session_config.model,
                session_config.source_lang,
                session_config.target_lang,
                transport,
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
                "transcription_text": result.transcription_text,
                "translated_text": result.translated_text,
            }

            return JSONResponse(content=payload)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Audio translation failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.get("/realtime/self-test")
    async def realtime_self_test(
        model: Optional[str] = Query(default=None, description="Model to validate"),
        source_lang: str = Query(default="en"),
        target_lang: str = Query(default="fr"),
    ) -> JSONResponse:
        selected_model = model or DEFAULT_REALTIME_MODEL
        transport = resolve_transport(selected_model)
        session_config = RealtimeSessionConfig(
            model=selected_model,
            source_lang=source_lang,
            target_lang=target_lang,
            transport=transport,
        )

        if transport == "webrtc":
            try:
                payload = realtime_manager.create_session_token(session_config)
                detail = {
                    "message": "Ephemeral session minted.",
                    "expires_at": payload.get("expires_at"),
                }
                return JSONResponse(
                    content={"ok": True, "model": selected_model, "transport": transport, "detail": detail}
                )
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(
                    status_code=500,
                    content={
                        "ok": False,
                        "model": selected_model,
                        "transport": transport,
                        "error": str(exc),
                    },
                )

        upstream_headers = [
            ("Authorization", f"Bearer {OPENAI_API_KEY}"),
            ("OpenAI-Beta", "realtime=v1"),
        ]
        ws_url = f"wss://api.openai.com/v1/realtime?model={selected_model}"
        try:
            async with websockets.connect(
                ws_url, extra_headers=upstream_headers, open_timeout=10, subprotocols=["realtime"]
            ) as upstream:
                await upstream.send(json.dumps(realtime_manager.build_session_update(session_config)))
                return JSONResponse(
                    content={
                        "ok": True,
                        "model": selected_model,
                        "transport": transport,
                        "detail": {"message": "WebSocket handshake ok."},
                    }
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Realtime WebSocket self-test failed")
            return JSONResponse(
                status_code=500,
                content={
                    "ok": False,
                    "model": selected_model,
                    "transport": transport,
                    "error": str(exc),
                },
            )

    @app.websocket("/realtime/ws-relay")
    async def realtime_ws_relay(
        websocket: WebSocket,
        model: str = Query(default=DEFAULT_REALTIME_MINI_MODEL),
        source_lang: str = Query(default="en"),
        target_lang: str = Query(default="fr"),
        voice: Optional[str] = Query(default=None),
    ) -> None:
        await websocket.accept()
        resolved_model = model or DEFAULT_REALTIME_MINI_MODEL
        transport = resolve_transport(resolved_model)
        if transport != "websocket":
            await websocket.send_json(
                {"type": "error", "message": f"Model {resolved_model} expects transport '{transport}'."}
            )
            await websocket.close()
            return

        session_config = RealtimeSessionConfig(
            model=resolved_model,
            source_lang=source_lang,
            target_lang=target_lang,
            voice=voice,
            output_audio_format="g711_ulaw",
            transport=transport,
        )
        session_update = realtime_manager.build_session_update(session_config)

        upstream_headers = [
            ("Authorization", f"Bearer {OPENAI_API_KEY}"),
            ("OpenAI-Beta", "realtime=v1"),
        ]
        ws_url = f"wss://api.openai.com/v1/realtime?model={resolved_model}"

        async def forward_client_to_openai(upstream: websockets.WebSocketClientProtocol) -> None:
            try:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        await upstream.close()
                        break
                    data = message.get("text")
                    if data is not None:
                        await upstream.send(data)
                    elif message.get("bytes") is not None:
                        await upstream.send(message["bytes"])
            except WebSocketDisconnect:
                await upstream.close()

        async def forward_openai_to_client(upstream: websockets.WebSocketClientProtocol) -> None:
            try:
                while True:
                    data = await upstream.recv()
                    if isinstance(data, bytes):
                        await websocket.send_bytes(data)
                    else:
                        await websocket.send_text(data)
            except websockets.exceptions.ConnectionClosed:
                if websocket.application_state != WebSocketState.DISCONNECTED:
                    await websocket.close()

        try:
            async with websockets.connect(
                ws_url, extra_headers=upstream_headers, open_timeout=10, subprotocols=["realtime"]
            ) as upstream:
                await upstream.send(json.dumps(session_update))
                await websocket.send_json({"type": "session.ready", "transport": transport})
                await asyncio.gather(
                    forward_client_to_openai(upstream),
                    forward_openai_to_client(upstream),
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Realtime WebSocket relay failed")
            if websocket.application_state != WebSocketState.DISCONNECTED:
                await websocket.send_json({"type": "error", "message": str(exc)})
                await websocket.close()
        finally:
            if websocket.application_state != WebSocketState.DISCONNECTED:
                try:
                    await websocket.close()
                except RuntimeError:
                    pass

    return app


app = create_app()
