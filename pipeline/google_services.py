"""
Google Services Layer — single entry point for all Google/GCP calls.
=====================================================================
Two modes (set GOOGLE_MODE in .env):

  dev   → free/offline stand-ins, NO GCP credentials required:
            • ASR       : SpeechRecognition + free Google web endpoint
            • Translate : deep-translator (free Google Translate web)
            • Embeddings: fastembed local model (ONNX, no torch, no key)
  cloud → official GCP APIs via a service account (production on Google Cloud):
            • ASR       : Cloud Speech-to-Text
            • Translate : Cloud Translation
            • Embeddings: Vertex AI text embeddings

  OCR (Google Cloud Vision) is REST-based and identical in both modes — it only
  needs GOOGLE_VISION_API_KEY.

Every function degrades gracefully: on any failure it logs and returns an empty
result (or None) so the pipeline never crashes on one bad submission.
"""
import os
import base64
import logging
import tempfile

from pipeline.config import (
    GOOGLE_MODE, UPLOAD_BASE_DIR, FFMPEG_PATH, FFPROBE_PATH,
    GOOGLE_VISION_API_KEY, GCP_PROJECT, GCP_LOCATION,
    EMBEDDING_MODEL_DEV, EMBEDDING_MODEL_CLOUD,
)

log = logging.getLogger("pipeline.google")

IS_CLOUD = GOOGLE_MODE == "cloud"


# ── Shared helpers ──────────────────────────────────────────────────────────

def resolve_media_path(file_url: str) -> str:
    """Map a stored '/uploads/{id}/{file}' URL to an absolute disk path."""
    rel = file_url.strip("/")
    if rel.startswith("uploads/"):
        rel = rel[len("uploads/"):]
    return os.path.join(UPLOAD_BASE_DIR, *rel.split("/"))


# Language code maps
_ASR_LANG_MAP = {
    "en": "en-IN", "english": "en-IN", "hi": "hi-IN", "hindi": "hi-IN",
    "or": "or-IN", "odia": "or-IN", "bn": "bn-IN", "bengali": "bn-IN",
    "ta": "ta-IN", "tamil": "ta-IN", "te": "te-IN", "telugu": "te-IN",
    "mr": "mr-IN", "marathi": "mr-IN", "gu": "gu-IN", "gujarati": "gu-IN",
    "kn": "kn-IN", "kannada": "kn-IN", "ml": "ml-IN", "malayalam": "ml-IN",
    "pa": "pa-IN", "punjabi": "pa-IN", "as": "as-IN", "assamese": "as-IN",
    "ur": "ur-IN", "urdu": "ur-IN",
}
_TRANSLATE_LANG_MAP = {
    "hi": "hi", "hindi": "hi", "or": "or", "odia": "or", "bn": "bn", "bengali": "bn",
    "ta": "ta", "tamil": "ta", "te": "te", "telugu": "te", "mr": "mr", "marathi": "mr",
    "gu": "gu", "gujarati": "gu", "kn": "kn", "kannada": "kn", "ml": "ml", "malayalam": "ml",
    "pa": "pa", "punjabi": "pa", "ur": "ur", "urdu": "ur", "as": "as", "assamese": "as",
}


# ── ASR : audio → text (source language) ────────────────────────────────────

_FFMPEG_CONFIGURED = False


def _configure_ffmpeg():
    global _FFMPEG_CONFIGURED
    if _FFMPEG_CONFIGURED:
        return
    try:
        from pydub import AudioSegment
        if FFMPEG_PATH and os.path.exists(FFMPEG_PATH):
            AudioSegment.converter = FFMPEG_PATH
        if FFPROBE_PATH and os.path.exists(FFPROBE_PATH):
            AudioSegment.ffprobe = FFPROBE_PATH
    except Exception as e:
        log.warning(f"  [ASR] Could not configure ffmpeg for pydub: {e}")
    _FFMPEG_CONFIGURED = True


def transcribe_audio(file_url: str, language: str) -> str:
    """Audio → transcript in the spoken language. Empty string on failure."""
    path = resolve_media_path(file_url)
    if not os.path.exists(path):
        log.warning(f"  [ASR] Audio file not found: {path}")
        return ""
    return _asr_cloud(path, language) if IS_CLOUD else _asr_dev(path, language)


def _asr_dev(path: str, language: str) -> str:
    wav_path = None
    try:
        import speech_recognition as sr
        from pydub import AudioSegment
        _configure_ffmpeg()
        audio = AudioSegment.from_file(path)
        wav_path = tempfile.mktemp(suffix=".wav")
        audio.export(wav_path, format="wav")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
        google_lang = _ASR_LANG_MAP.get((language or "en").lower(), "en-IN")
        text = recognizer.recognize_google(audio_data, language=google_lang)
        log.info(f"  [ASR/dev] Transcribed ({google_lang}): '{text[:80]}...'")
        return text
    except Exception as e:
        log.error(f"  [ASR/dev] Failed: {type(e).__name__}: {str(e)[:120]}")
        return ""
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except OSError:
                pass


def _asr_cloud(path: str, language: str) -> str:
    """Google Cloud Speech-to-Text. Converts to LINEAR16 WAV via pydub first."""
    wav_path = None
    try:
        from pydub import AudioSegment
        from google.cloud import speech
        _configure_ffmpeg()
        audio = AudioSegment.from_file(path).set_channels(1)
        wav_path = tempfile.mktemp(suffix=".wav")
        audio.export(wav_path, format="wav")

        client = speech.SpeechClient()
        with open(wav_path, "rb") as f:
            content = f.read()
        google_lang = _ASR_LANG_MAP.get((language or "en").lower(), "en-IN")
        cfg = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=audio.frame_rate,
            language_code=google_lang,
            enable_automatic_punctuation=True,
        )
        resp = client.recognize(config=cfg, audio=speech.RecognitionAudio(content=content))
        text = " ".join(r.alternatives[0].transcript for r in resp.results if r.alternatives)
        log.info(f"  [ASR/cloud] Transcribed ({google_lang}): '{text[:80]}...'")
        return text.strip()
    except Exception as e:
        log.error(f"  [ASR/cloud] Failed: {type(e).__name__}: {str(e)[:150]}")
        return ""
    finally:
        if wav_path and os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except OSError:
                pass


# ── Translation : any language → English ────────────────────────────────────

def translate_to_english(text: str, source_lang: str) -> str:
    """Translate to English. Returns input unchanged if already English."""
    if not text or not text.strip():
        return ""
    lang = (source_lang or "").lower()
    has_non_ascii = any(ord(c) > 127 for c in text)
    if lang in ("en", "english") and not has_non_ascii:
        return text
    if not has_non_ascii and lang not in _TRANSLATE_LANG_MAP:
        return text
    return _translate_cloud(text, lang) if IS_CLOUD else _translate_dev(text, lang)


def _translate_dev(text: str, lang: str) -> str:
    try:
        from deep_translator import GoogleTranslator
        src = _TRANSLATE_LANG_MAP.get(lang, "auto")
        out = GoogleTranslator(source=src, target="en").translate(text[:5000])
        if out and out.strip():
            log.info(f"  [TRANSLATE/dev] → '{out[:80]}...'")
            return out
        return text
    except Exception as e:
        log.warning(f"  [TRANSLATE/dev] Failed ({type(e).__name__}: {str(e)[:100]}), keeping original")
        return text


def _translate_cloud(text: str, lang: str) -> str:
    try:
        from google.cloud import translate_v2 as translate
        client = translate.Client()
        result = client.translate(text[:5000], target_language="en")
        out = result.get("translatedText") or ""
        if out.strip():
            log.info(f"  [TRANSLATE/cloud] → '{out[:80]}...'")
            return out
        return text
    except Exception as e:
        log.warning(f"  [TRANSLATE/cloud] Failed ({type(e).__name__}: {str(e)[:120]}), keeping original")
        return text


# ── OCR : image → text (Google Cloud Vision REST, both modes) ───────────────

def ocr_image(file_url: str) -> str:
    path = resolve_media_path(file_url)
    if not os.path.exists(path):
        log.warning(f"  [OCR] Image file not found: {path}")
        return ""
    if not GOOGLE_VISION_API_KEY:
        log.warning("  [OCR] GOOGLE_VISION_API_KEY not set — skipping OCR. "
                    "Add it to coz_code_scheduler/.env to enable image processing.")
        return ""
    try:
        import requests
        with open(path, "rb") as f:
            content_b64 = base64.b64encode(f.read()).decode("utf-8")
        payload = {"requests": [{
            "image": {"content": content_b64},
            "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
            "imageContext": {"languageHints": ["en", "hi", "or"]},
        }]}
        url = f"https://vision.googleapis.com/v1/images:annotate?key={GOOGLE_VISION_API_KEY}"
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        result = (resp.json().get("responses") or [{}])[0]
        if "error" in result:
            log.error(f"  [OCR] Vision API error: {result['error'].get('message', '')[:150]}")
            return ""
        text = (result.get("fullTextAnnotation") or {}).get("text", "").strip()
        log.info(f"  [OCR] Extracted: '{text[:80]}...'" if text else "  [OCR] No text detected")
        return text
    except Exception as e:
        log.error(f"  [OCR] Failed: {type(e).__name__}: {str(e)[:120]}")
        return ""


# ── Embeddings : text → vector (for semantic clustering, Layer 3) ───────────

_fastembed_model = None


def embed_texts(texts: list) -> list | None:
    """
    Return a list of embedding vectors (one per input text), or None if the
    embedding backend is unavailable (caller then falls back to TF-IDF).
    """
    if not texts:
        return []
    return _embed_cloud(texts) if IS_CLOUD else _embed_dev(texts)


def _embed_dev(texts: list):
    """Local multilingual embeddings via fastembed (ONNX, no key, offline)."""
    global _fastembed_model
    try:
        if _fastembed_model is None:
            from fastembed import TextEmbedding
            log.info(f"  [EMBED/dev] Loading local model {EMBEDDING_MODEL_DEV} (first run downloads it)...")
            _fastembed_model = TextEmbedding(model_name=EMBEDDING_MODEL_DEV)
        # e5-family models need a "passage:" prefix; paraphrase models do not.
        docs = [f"passage: {t}" for t in texts] if "e5" in EMBEDDING_MODEL_DEV.lower() else list(texts)
        return [vec.tolist() for vec in _fastembed_model.embed(docs)]
    except Exception as e:
        log.warning(f"  [EMBED/dev] Unavailable ({type(e).__name__}: {str(e)[:120]}) — falling back to TF-IDF")
        return None


def _embed_cloud(texts: list):
    """Vertex AI text embeddings."""
    try:
        import vertexai
        from vertexai.language_models import TextEmbeddingModel
        vertexai.init(project=GCP_PROJECT, location=GCP_LOCATION)
        model = TextEmbeddingModel.from_pretrained(EMBEDDING_MODEL_CLOUD)
        # Vertex allows up to 250 texts/request; batch to be safe.
        out = []
        for i in range(0, len(texts), 250):
            batch = texts[i:i + 250]
            out.extend([e.values for e in model.get_embeddings(batch)])
        return out
    except Exception as e:
        log.warning(f"  [EMBED/cloud] Unavailable ({type(e).__name__}: {str(e)[:120]}) — falling back to TF-IDF")
        return None
