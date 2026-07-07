"""
LAYER 2: Data Processing & Filtering
=====================================
Pipeline: raw_submissions → processed_submissions

For each new raw submission:
  1. If audio → Google Cloud Speech-to-Text V2 → text in source language
  2. If image → Google Cloud Vision API → text extraction (OCR)
  3. Translate all text to English using Google Cloud Translate V2
  4. Spam filtering
  5. Store in processed_submissions

AI Services (Google Cloud REST APIs with API key):
  - Speech-to-Text V2: speech.googleapis.com/v1/speech:recognize
  - Vision API: vision.googleapis.com/v1/images:annotate
  - Translate V2: translation.googleapis.com/language/translate/v2
  - Fallback: free libraries (speech_recognition, pytesseract, deep-translator)
"""

import re
import os
import io
import json
import base64
import logging
import tempfile
import time
import urllib.request
from pipeline.db import (
    get_connection, fetch_all, fetch_one, execute, execute_returning_uuid,
    insert_status_log,
)
from pipeline.config import GOOGLE_API_KEY

log = logging.getLogger("pipeline.layer2")

# Gemini API config``
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_DELAY = 4  # seconds between retries (free tier: 15 RPM)


def _call_gemini(parts: list, max_tokens: int = 8192) -> str | None:
    """Call Gemini API with retry logic for 503 rate limit errors.
    Returns the text response or None on failure."""
    if not GOOGLE_API_KEY:
        return None

    payload = json.dumps({
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": max_tokens},
    }).encode("utf-8")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GOOGLE_API_KEY}"

    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        try:
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read().decode())
            candidates = result.get("candidates", [])
            if candidates:
                content_parts = candidates[0].get("content", {}).get("parts", [])
                if content_parts:
                    text = content_parts[0].get("text", "").strip()
                    if text:
                        return text
            return None
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < GEMINI_MAX_RETRIES:
                log.info(f"    Gemini 503 (rate limit), retrying in {GEMINI_RETRY_DELAY}s... (attempt {attempt}/{GEMINI_MAX_RETRIES})")
                time.sleep(GEMINI_RETRY_DELAY)
                continue
            raise
    return None


# ── Google Cloud Speech-to-Text V2 ──────────────────────────────────────────

def _fetch_file_bytes(file_url: str) -> bytes | None:
    """Fetch file bytes from a GCS public URL (https://) or local path (fallback)."""
    if not file_url:
        return None
    if file_url.startswith("http://") or file_url.startswith("https://"):
        try:
            req = urllib.request.Request(file_url, headers={"User-Agent": "PeoplesPriorities/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as e:
            log.warning(f"  [FETCH] Failed to download {file_url}: {e}")
            return None
    # Local fallback (dev)
    if os.path.exists(file_url):
        with open(file_url, "rb") as f:
            return f.read()
    log.warning(f"  [FETCH] File not found: {file_url}")
    return None


def real_asr(file_url: str, language: str) -> str:
    """Speech-to-Text using Gemini 2.5 Flash. Falls back to free speech_recognition API."""
    if not file_url:
        return ""

    log.info(f"  [ASR] Processing audio: {file_url}")

    audio_bytes = _fetch_file_bytes(file_url)
    if not audio_bytes:
        log.warning(f"  [ASR] Could not fetch audio: {file_url}")
        return ""

    lang_map = {
        "en": "en-IN", "english": "en-IN", "hi": "hi-IN", "hindi": "hi-IN",
        "or": "or-IN", "odia": "or-IN", "bn": "bn-IN", "bengali": "bn-IN",
        "ta": "ta-IN", "tamil": "ta-IN", "te": "te-IN", "telugu": "te-IN",
        "mr": "mr-IN", "marathi": "mr-IN", "gu": "gu-IN", "gujarati": "gu-IN",
        "kn": "kn-IN", "kannada": "kn-IN", "ml": "ml-IN", "malayalam": "ml-IN",
        "pa": "pa-IN", "punjabi": "pa-IN",
    }
    google_lang = lang_map.get(language, "en-IN")

    # ── Try 1: Gemini 2.5 Flash for audio (FREE — supports native languages) ──
    if GOOGLE_API_KEY:
        try:
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")
            ext = os.path.splitext(file_url.split("?")[0])[1].lower()
            audio_mime = {".webm": "audio/webm", ".wav": "audio/wav",
                          ".mp3": "audio/mp3", ".ogg": "audio/ogg", ".m4a": "audio/mp4"}
            mime = audio_mime.get(ext, "audio/webm")

            text = _call_gemini([
                {"text": f"Transcribe this audio recording accurately. The speaker may be speaking in {google_lang.split('-')[0]} or any Indian language. "
                         "Provide the transcription in the original language, then translate to English. "
                         "Format: ORIGINAL: <transcription>\nENGLISH: <English translation>"},
                {"inline_data": {"mime_type": mime, "data": audio_b64}},
            ])
            if text:
                log.info(f"  [ASR] Gemini: '{text[:100]}...'")
                return text
        except Exception as e:
            log.warning(f"  [ASR] Gemini failed ({e}), trying free API")

    # ── Try 2: Free speech_recognition library ──
    try:
        import speech_recognition as sr
        from pydub import AudioSegment
        audio = AudioSegment.from_file(io.BytesIO(audio_bytes))
        wav_path = tempfile.mktemp(suffix=".wav")
        audio.export(wav_path, format="wav")
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)
        text = recognizer.recognize_google(audio_data, language=google_lang)
        os.unlink(wav_path)
        log.info(f"  [ASR] Free API: '{text[:80]}...'")
        return text
    except Exception as e:
        log.error(f"  [ASR] All ASR methods failed: {e}")
        return f"[Audio could not be transcribed: {str(e)[:100]}]"


# ── Gemini OCR (+ Vision API + Tesseract fallback) ──────────────────────────

def real_ocr(file_url: str) -> str:
    """Image-to-Text using Gemini (best for handwritten native languages),
    falls back to Vision API, then Tesseract."""
    if not file_url:
        return ""

    log.info(f"  [OCR] Processing image: {file_url}")

    image_bytes = _fetch_file_bytes(file_url)
    if not image_bytes:
        log.warning(f"  [OCR] Could not fetch image: {file_url}")
        return ""

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Detect mime type from URL extension
    ext = os.path.splitext(file_url.split("?")[0])[1].lower()
    mime_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
    mime_type = mime_map.get(ext, "image/jpeg")

    # ── Try 1: Gemini 2.5 Flash (FREE — best for handwritten + native language) ──
    if GOOGLE_API_KEY:
        try:
            text = _call_gemini([
                {"text": "Read ALL the text written in this image carefully. The text may be handwritten in Odia, Hindi, Bengali, or any other Indian language. "
                         "Extract the EXACT text as written, then provide an accurate English translation. "
                         "Format your response as:\nORIGINAL: <exact text from image>\nENGLISH: <English translation>\n"
                         "If the text is already in English, just return it as-is under both ORIGINAL and ENGLISH."},
                {"inline_data": {"mime_type": mime_type, "data": image_b64}},
            ])
            if text:
                log.info(f"  [OCR] Gemini: '{text[:120]}...'")
                return text
        except Exception as e:
            log.warning(f"  [OCR] Gemini failed ({e}), trying Tesseract")

    # ── Try 2: Tesseract OCR (local fallback) ────────────────────────────
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(image_bytes))
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            text = pytesseract.image_to_string(img, lang="eng+hin+ori")
            if text.strip():
                log.info(f"  [OCR] Tesseract: '{text.strip()[:80]}...'")
                return text.strip()
        except Exception as e:
            log.warning(f"  [OCR] Tesseract failed ({e})")
        w, h = img.size
        return f"[Image uploaded: {w}x{h} pixels. Set GOOGLE_API_KEY for Gemini OCR.]"
    except Exception as e:
        log.error(f"  [OCR] All OCR methods failed: {e}")
        return f"[Image could not be processed: {str(e)[:100]}]"


# ── Google Cloud Translate V2 ────────────────────────────────────────────────

def real_translate(text: str, source_lang: str) -> str:
    """Translate to English using Google Cloud Translate V2. Falls back to free library.
    If Gemini OCR already provided ENGLISH: section, extracts that directly."""
    if not text or not text.strip():
        return ""

    # Check if Gemini already provided English translation (format: ORIGINAL: ...\nENGLISH: ...)
    if "ENGLISH:" in text:
        lines = text.split("ENGLISH:")
        if len(lines) >= 2:
            english_part = lines[-1].strip()
            if english_part and len(english_part) > 10:
                log.info(f"  [TRANSLATE] Gemini already provided English: '{english_part[:80]}...'")
                return english_part

    # Check if text contains non-ASCII characters (native language script)
    has_non_ascii = any(ord(c) > 127 for c in text)

    # Only skip translation if source is English AND text is actually ASCII
    if source_lang in ("en", "english") and not has_non_ascii:
        return text
    if not has_non_ascii:
        return text

    log.info(f"  [TRANSLATE] Translating to English (source={source_lang}, has_native_script={has_non_ascii})")

    # Try Gemini 2.5 Flash for translation (FREE)
    if GOOGLE_API_KEY:
        try:
            translated = _call_gemini([
                {"text": f"Translate the following text to English accurately. If it contains multiple languages, translate all parts to English. Return ONLY the English translation, nothing else.\n\nText:\n{text[:5000]}"}
            ])
            if translated:
                log.info(f"  [TRANSLATE] Gemini: '{translated[:80]}...'")
                return translated
        except Exception as e:
            log.warning(f"  [TRANSLATE] Gemini failed ({e}), trying free library")

    # Fallback: deep-translator (free)
    try:
        from deep_translator import GoogleTranslator
        lang_map = {
            "hi": "hi", "hindi": "hi", "or": "or", "odia": "or",
            "bn": "bn", "bengali": "bn", "ta": "ta", "tamil": "ta",
            "te": "te", "telugu": "te", "mr": "mr", "marathi": "mr",
            "gu": "gu", "gujarati": "gu", "kn": "kn", "kannada": "kn",
            "ml": "ml", "malayalam": "ml", "pa": "pa", "punjabi": "pa",
            "ur": "ur", "urdu": "ur", "as": "as", "assamese": "as",
        }
        src = lang_map.get(source_lang, "auto")
        translated = GoogleTranslator(source=src, target="en").translate(text[:5000])
        log.info(f"  [TRANSLATE] Free API: '{translated[:80]}...'")
        return translated
    except Exception as e:
        log.warning(f"  [TRANSLATE] All translation methods failed ({e})")
        return text


def check_spam(text: str, user_id: str, conn) -> tuple[bool, str]:
    """
    Spam filtering checks:
    1. Too short (< 10 chars)
    2. Gibberish detection (no real words)
    3. Rate limiting (> 5 submissions/day from same user)
    4. Exact duplicate text from same user
    """
    if not text or len(text.strip()) < 10:
        return True, "too_short"

    # Rate limit: max 5 submissions per user per day
    row = fetch_one(conn, """
        SELECT COUNT(*) AS cnt FROM raw_submissions
        WHERE user_id = %s AND DATE(created_at) = CURDATE()
    """, (user_id,))
    if row and row["cnt"] > 5:
        return True, "rate_limit_exceeded"

    # Exact duplicate from same user
    existing = fetch_one(conn, """
        SELECT ps.id FROM processed_submissions ps
        JOIN raw_submissions rs ON ps.raw_submission_id = rs.id
        WHERE ps.user_id = %s AND ps.translated_text_en = %s AND ps.is_spam = FALSE
    """, (user_id, text))
    if existing:
        return True, "exact_duplicate"

    return False, ""


# ── Main Layer 2 Processor ──────────────────────────────────────────────────

def process_submissions(conn) -> int:
    """
    Process all raw_submissions with status='submitted'.
    Returns count of processed submissions.
    """
    # Fetch unprocessed submissions
    submissions = fetch_all(conn, """
        SELECT rs.*, GROUP_CONCAT(sm.media_type) AS media_types,
               GROUP_CONCAT(sm.file_url) AS media_urls
        FROM raw_submissions rs
        LEFT JOIN submission_media sm ON sm.raw_submission_id = rs.id
        WHERE rs.status = 'submitted'
        GROUP BY rs.id
        ORDER BY rs.created_at ASC
    """)

    if not submissions:
        log.info("Layer 2: No new submissions to process")
        return 0

    log.info(f"Layer 2: Processing {len(submissions)} new submissions")
    processed_count = 0

    for idx, sub in enumerate(submissions):
        try:
            _process_one(conn, sub)
            processed_count += 1
            # Pace API calls to avoid Gemini free tier rate limits (15 RPM)
            if idx < len(submissions) - 1 and sub.get("media_types"):
                time.sleep(2)
        except Exception as e:
            log.error(f"  Error processing {sub['tracking_id']}: {e}")
            execute(conn, "UPDATE raw_submissions SET status = 'failed' WHERE id = %s", (sub["id"],))
            insert_status_log(conn, sub["id"], sub["user_id"], "submitted", "failed", str(e))

    log.info(f"Layer 2: Processed {processed_count}/{len(submissions)} submissions")
    return processed_count


def _process_one(conn, sub: dict):
    """Process a single submission through the full Layer 2 pipeline."""
    sub_id = sub["id"]
    user_id = sub["user_id"]
    tracking = sub["tracking_id"]
    input_type = sub["input_type"]
    raw_text = sub["raw_text"] or ""
    lang = sub["raw_language"] or "en"

    log.info(f"  Processing {tracking} (type={input_type}, lang={lang})")

    # Update status to 'processing'
    execute(conn, "UPDATE raw_submissions SET status = 'processing' WHERE id = %s", (sub_id,))
    insert_status_log(conn, sub_id, user_id, "submitted", "processing", "Layer 2 pipeline started")

    # ── Step 1: Extract text from all input types ────────────────────────
    extracted_parts = []
    processing_method = "direct_text"

    # Text input
    if raw_text.strip():
        extracted_parts.append(raw_text.strip())

    # Audio input
    media_types = (sub.get("media_types") or "").split(",")
    media_urls = (sub.get("media_urls") or "").split(",")
    has_audio = "audio" in media_types
    has_image = "image" in media_types

    if has_audio:
        audio_idx = media_types.index("audio")
        audio_url = media_urls[audio_idx] if audio_idx < len(media_urls) else ""
        asr_text = real_asr(audio_url, lang)
        if asr_text:
            extracted_parts.append(asr_text)
        processing_method = "asr" if not raw_text.strip() else "direct_text_asr"

        # Log ASR pipeline stage
        execute_returning_uuid(conn, """
            INSERT INTO processing_queue (id, raw_submission_id, stage, status, input_payload, output_payload, started_at, completed_at)
            VALUES (%s, %s, 'asr', 'completed', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (sub_id, json.dumps({"audio_url": audio_url}), json.dumps({"text": asr_text[:500]})))

    # Image input (OCR)
    if has_image:
        img_idx = media_types.index("image")
        img_url = media_urls[img_idx] if img_idx < len(media_urls) else ""
        ocr_text = real_ocr(img_url)
        if ocr_text:
            extracted_parts.append(ocr_text)
        if processing_method == "direct_text":
            processing_method = "ocr" if not raw_text.strip() else "direct_text_ocr"
        elif processing_method == "asr":
            processing_method = "asr_ocr"
        elif processing_method == "direct_text_asr":
            processing_method = "direct_text_asr_ocr"

        execute_returning_uuid(conn, """
            INSERT INTO processing_queue (id, raw_submission_id, stage, status, input_payload, output_payload, started_at, completed_at)
            VALUES (%s, %s, 'ocr', 'completed', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """, (sub_id, json.dumps({"image_url": img_url}), json.dumps({"text": ocr_text[:500]})))

    # Combine all extracted text
    original_text = " | ".join(extracted_parts) if extracted_parts else raw_text

    # ── Step 2: Translate to English ─────────────────────────────────────
    translated = real_translate(original_text, lang)

    execute_returning_uuid(conn, """
        INSERT INTO processing_queue (id, raw_submission_id, stage, status, input_payload, output_payload, started_at, completed_at)
        VALUES (%s, %s, 'translate', 'completed', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (sub_id, json.dumps({"source_lang": lang}), json.dumps({"translated": translated[:500]})))

    # ── Step 3: Spam check ───────────────────────────────────────────────
    is_spam, spam_reason = check_spam(translated, user_id, conn)

    execute_returning_uuid(conn, """
        INSERT INTO processing_queue (id, raw_submission_id, stage, status, input_payload, output_payload, started_at, completed_at)
        VALUES (%s, %s, 'spam_check', 'completed', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (sub_id, json.dumps({"text_length": len(translated)}), json.dumps({"is_spam": is_spam, "reason": spam_reason})))

    # ── Step 4: Check if issue is specific enough ────────────────────────
    is_specific = len(translated.split()) >= 5  # At least 5 words

    # ── Step 5: Store processed submission ───────────────────────────────
    pin = sub["submission_pin_code"]
    pin_data = fetch_one(conn, "SELECT * FROM pin_code_directory WHERE pin_code = %s", (pin,))

    # If PIN not in local cache, use data from raw_submissions (already filled by API service)
    if not pin_data:
        pin_data = {
            "postal_name": sub.get("sub_postal_name"),
            "locality": sub.get("sub_locality"),
            "city": sub.get("sub_city"),
            "district": sub.get("sub_district"),
            "state": sub.get("sub_state"),
        }

    # Constituency comes from raw_submissions (user selected it explicitly)
    constituency = sub.get("sub_constituency", "")

    new_status = "processed"
    if is_spam:
        new_status = "failed"

    execute_returning_uuid(conn, """
        INSERT INTO processed_submissions
            (id, raw_submission_id, user_id, original_text, original_language,
             translated_text_en, processing_method,
             pin_code, postal_name, locality, city, district, state, constituency,
             is_spam, spam_reason, is_specific_issue, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        sub_id, user_id, original_text, lang,
        translated, processing_method,
        pin,
        pin_data["postal_name"] if pin_data else None,
        pin_data["locality"] if pin_data else None,
        pin_data["city"] if pin_data else None,
        pin_data["district"] if pin_data else None,
        pin_data["state"] if pin_data else None,
        constituency,
        is_spam, spam_reason, is_specific, new_status,
    ))

    # Update raw submission status
    execute(conn, "UPDATE raw_submissions SET status = %s WHERE id = %s", (new_status, sub_id))
    insert_status_log(conn, sub_id, user_id, "processing", new_status,
                      f"Spam={is_spam} ({spam_reason})" if is_spam else "Layer 2 complete")

    if is_spam:
        log.info(f"  {tracking}: SPAM detected ({spam_reason})")
    else:
        log.info(f"  {tracking}: Processed OK → '{translated[:60]}...'")
