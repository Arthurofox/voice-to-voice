import base64
import datetime as dt
import json
import os
from typing import Any, Dict, List, Optional

import requests
import streamlit as st
import streamlit.components.v1 as components
from audio_recorder_streamlit import audio_recorder


BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")
REALTIME_STATIC_URL = f"{BACKEND_URL}/frontend/static/realtime.html"

VOICES = [
    ("verse", "Verse (default)"),
    ("alloy", "Alloy"),
    ("aria", "Aria"),
]

LANGUAGE_OPTIONS = {
    "EN → FR": ("en", "fr"),
    "FR → EN": ("fr", "en"),
}

MODE_OPTIONS = {
    "Realtime (gpt-realtime) — WebRTC": {
        "model": os.environ.get("REALTIME_MODEL", "gpt-realtime"),
        "transport": "webrtc",
    },
    "Realtime-Mini — WebSocket": {
        "model": os.environ.get("REALTIME_MINI_MODEL", "gpt-4o-mini-realtime-preview"),
        "transport": "websocket",
    },
    "Audio (Direct)": {
        "model": None,
        "transport": None,
    },
}


def append_log(message: str, payload: Optional[Dict[str, Any]] = None) -> None:
    logs: List[Dict[str, Any]] = st.session_state.setdefault("logs", [])
    logs.append(
        {
            "timestamp": dt.datetime.now().strftime("%H:%M:%S"),
            "message": message,
            "payload": payload or {},
        }
    )
    st.session_state["logs"] = logs[-10:]


def fetch_realtime_token(model: str, source: str, target: str, voice: str) -> Dict[str, Any]:
    params = {
        "model": model,
        "source_lang": source,
        "target_lang": target,
        "voice": voice,
    }
    response = requests.get(f"{BACKEND_URL}/realtime/token", params=params, timeout=15)
    response.raise_for_status()
    token = response.json()
    append_log(
        "Realtime token issued",
        {
            "model": model,
            "transport": token.get("transport"),
            "expires": token.get("expires_at"),
        },
    )
    return token


def render_logs() -> None:
    st.subheader("Event Log")
    logs: List[Dict[str, Any]] = st.session_state.get("logs", [])
    if not logs:
        st.info("No events yet. Interact with the translator to see live updates.")
        return
    for entry in reversed(logs):
        st.write(f"[{entry['timestamp']}] {entry['message']}")
        if entry["payload"]:
            st.caption(json.dumps(entry["payload"], indent=2))


def ensure_preflight_checklist() -> None:
    if st.session_state.get("preflight_checked"):
        return

    with st.expander("First-run checklist (required)", expanded=True):
        st.markdown(
            "- Python 3.10+ recommended with an active virtualenv.\n"
            "- Dependencies installed via `pip install -r requirements.txt`.\n"
            "- `.env` contains your `OPENAI_API_KEY`.\n"
            "- Browser mic permissions allowed for localhost.\n"
            "- Backend running: `uvicorn backend.main:app --reload`.\n"
            "- Streamlit running: `streamlit run frontend/streamlit_app.py`."
        )
        acknowledged = st.checkbox("I have completed the setup above.")
        if acknowledged:
            st.session_state["preflight_checked"] = True
            append_log("Prerequisites confirmed by user")


def main() -> None:
    st.set_page_config(page_title="Local Voice Translator", layout="wide")
    st.title("Local Voice Translator (EN ⇄ FR)")
    st.caption("Compare GPT-4o Realtime, Realtime-Mini, and direct audio translation locally.")

    ensure_preflight_checklist()

    selected_direction = st.radio("Language direction", list(LANGUAGE_OPTIONS.keys()))
    source_lang, target_lang = LANGUAGE_OPTIONS[selected_direction]

    voice_options = [label for _, label in VOICES]
    selected_voice_label = st.selectbox("Output voice", voice_options, index=0)
    selected_voice = next(code for code, label in VOICES if label == selected_voice_label)

    mode = st.radio("Mode", tuple(MODE_OPTIONS.keys()), help="Select a translation path to test.")
    mode_config = MODE_OPTIONS[mode]

    if mode != "Audio (Direct)":
        realtime_model = mode_config["model"]
        transport = mode_config["transport"]

        if transport == "webrtc":
            st.markdown(
                "1. Click **Connect (WebRTC)** to mint an ephemeral token.\n"
                "2. Allow microphone access when prompted.\n"
                "3. Speak in the source language and listen for the translated reply.\n"
                "_Note_: If the browser blocks audio, refresh and retry."
            )
        else:
            st.markdown(
                "Realtime-Mini uses a **WebSocket** transport via the local relay.\n"
                "1. Click **Connect (WebSocket)** to set up the relay.\n"
                "2. Allow microphone access.\n"
                "3. Use the panel controls to start/stop talking; translated audio streams back over the same socket."
            )
            st.info(
                "WebRTC is not available for this model. The widget will manage fallback automatically.",
                icon="ℹ️",
            )

        token_container = st.empty()
        connect_col, disconnect_col = st.columns(2)

        connect_label = "Connect (WebRTC)" if transport == "webrtc" else "Connect (WebSocket)"

        if connect_col.button(connect_label, type="primary"):
            try:
                token = fetch_realtime_token(realtime_model, source_lang, target_lang, selected_voice)
                st.session_state["realtime_session"] = token
                expires = token.get("expires_at", "soon")
                token_container.success(
                    f"Session ready for {realtime_model} via {transport.upper()}. Expires at {expires}."
                )
            except requests.HTTPError as exc:
                st.error(f"Failed to fetch token: {exc.response.text}")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Token request failed: {exc}")

        if disconnect_col.button("Disconnect"):
            st.session_state.pop("realtime_session", None)
            token_container.info("Realtime session reset. Generate a new token to reconnect.")
            append_log("Realtime session cleared")

        token = st.session_state.get("realtime_session")
        if not token:
            st.warning("Mint a realtime token to start streaming.")
        else:
            params = (
                f"source={source_lang}&target={target_lang}"
                f"&voice={selected_voice}&model={realtime_model}&transport={transport}"
            )
            fragment = ""
            if transport == "webrtc":
                client_secret = token.get("client_secret")
                if not client_secret:
                    st.error("No client secret returned for WebRTC session. Regenerate the token.")
                    st.stop()
                fragment = f"#token={client_secret}"
            iframe_src = f"{REALTIME_STATIC_URL}?{params}{fragment}"
            iframe_html = (
                f'<iframe src="{iframe_src}" width="100%" height="580" frameborder="0" '
                'allow="microphone; autoplay; clipboard-write"></iframe>'
            )
            components.html(iframe_html, height=600)
            st.info(
                "Keep this tab focused to reduce audio glitches. Latency stats and fallbacks appear inside the panel."
            )

    elif mode == "Audio (Direct)":
        st.markdown(
            "Record a short utterance (≤15 seconds). When you release the record button, a WAV clip "
            "is produced and can be sent for translation."
        )

        audio_bytes = audio_recorder(
            text="Tap to record / tap again to stop",
            recording_color="#e07a5f",
            neutral_color="#3d405b",
            icon_name="microphone",
        )

        if audio_bytes:
            st.audio(audio_bytes, format="audio/wav")
            st.success("Clip captured. Click translate to send it to the backend.")

            if st.button("Translate clip", type="primary"):
                append_log("Sending audio clip to backend", {"mode": "audio_direct"})
                files = {"audio_file": ("recording.wav", audio_bytes, "audio/wav")}
                params = {
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "voice": selected_voice,
                }
                try:
                    response = requests.post(
                        f"{BACKEND_URL}/audio/translate",
                        params=params,
                        files=files,
                        timeout=90,
                    )
                    response.raise_for_status()
                    payload = response.json()
                    translation_audio = base64.b64decode(payload["audio_base64"])
                    st.audio(translation_audio, format="audio/wav")
                    st.success(
                        f"Translated audio ready using voice `{payload.get('voice')}` "
                        f"and model `{payload.get('model')}`."
                    )

                    st.caption(
                        f"Transcription ({payload.get('detected_source_language', source_lang).upper()}): "
                        f"`{payload.get('transcription_text', '').strip() or '—'}`"
                    )
                    st.caption(
                        f"Translation ({target_lang.upper()}): "
                        f"`{payload.get('translated_text', '').strip() or '—'}`"
                    )

                    timing = payload.get("timing", {})
                    timing_summary = {
                        "Transcription (ms)": round(timing.get("transcription_duration_ms", 0), 1),
                        "Translation (ms)": round(timing.get("translation_duration_ms", 0), 1),
                        "TTS (ms)": round(timing.get("tts_duration_ms", 0), 1),
                        "Total latency (ms)": round(timing.get("total_latency_ms", 0), 1),
                    }
                    st.json(timing_summary)
                    append_log("Audio translation completed", timing)
                except requests.HTTPError as exc:
                    st.error(f"Translation failed: {exc.response.text}")
                    append_log("Audio translation failed", {"status": exc.response.status_code})
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Unexpected error: {exc}")
                    append_log("Audio translation failed", {"error": str(exc)})
        else:
            st.info("Idle. Tap the record button above to capture audio.")

    render_logs()


if __name__ == "__main__":
    main()
