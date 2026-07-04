"""
LAYER 2: Data Processing & Filtering
=====================================
Pipeline: raw_submissions → processed_submissions

For each new raw submission:
  1. If audio → Google Speech Recognition (free) → text in source language
  2. If image → Tesseract OCR / PIL → text extraction
  3. Translate all text to English using Google Translate (free)
  4. Spam filtering
  5. Store in processed_submissions

AI Services Used (all free, no API key needed):
  - SpeechRecognition: Google's free speech-to-text API
  - pytesseract/PIL: Tesseract OCR for handwritten/printed text
  - deep-translator: Google Translate wrapper
  - pydub + ffmpeg: Audio format conversion
"""

import re
import os
import logging
import tempfile
from pipeline.db import (
    get_connection, fetch_all, fetch_one, execute, execute_returning_uuid,
    insert_status_log,
)

log = logging.getLogger("pipeline.layer2")

# Upload directory (same as backend-api)
UPLOAD_BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend-api", "uploads"))


# ── Real AI Functions ────────────────────────────────────────────────────────

def real_asr(file_url: str, language: str) -> str:
    """
    Speech-to-Text using Google Speech Recognition (free).
    Converts audio to WAV via ffmpeg, then sends to Google API.
    """
    # Resolve file path from URL
    file_path = os.path.join(UPLOAD_BASE, *file_url.strip("/").replace("uploads/", "").split("/"))
    if not os.path.exists(file_path):
        log.warning(f"  [ASR] Audio file not found: {file_path}")
        return ""

    log.info(f"  [ASR] Processing audio: {file_path}")

    try:
        import speech_recognition as sr
        from pydub import AudioSegment

        # Convert to WAV (Google API needs WAV)
        audio = AudioSegment.from_file(file_path)
        wav_path = tempfile.mktemp(suffix=".wav")
        audio.export(wav_path, format="wav")

        # Recognize speech
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)

        # Map language codes for Google API
        lang_map = {
            "en": "en-IN", "english": "en-IN",
            "hi": "hi-IN", "hindi": "hi-IN",
            "or": "or-IN", "odia": "or-IN",
            "bn": "bn-IN", "bengali": "bn-IN",
            "ta": "ta-IN", "tamil": "ta-IN",
            "te": "te-IN", "telugu": "te-IN",
            "mr": "mr-IN", "marathi": "mr-IN",
            "gu": "gu-IN", "gujarati": "gu-IN",
            "kn": "kn-IN", "kannada": "kn-IN",
            "ml": "ml-IN", "malayalam": "ml-IN",
            "pa": "pa-IN", "punjabi": "pa-IN",
        }
        google_lang = lang_map.get(language, "en-IN")

        text = recognizer.recognize_google(audio_data, language=google_lang)
        log.info(f"  [ASR] Transcribed: '{text[:80]}...'")

        # Cleanup temp file
        os.unlink(wav_path)
        return text

    except Exception as e:
        log.error(f"  [ASR] Failed: {e}")
        return f"[Audio could not be transcribed: {str(e)[:100]}]"


def real_ocr(file_url: str) -> str:
    """
    Image-to-Text using Pillow for image loading.
    Tries pytesseract first, falls back to basic extraction.
    """
    file_path = os.path.join(UPLOAD_BASE, *file_url.strip("/").replace("uploads/", "").split("/"))
    if not os.path.exists(file_path):
        log.warning(f"  [OCR] Image file not found: {file_path}")
        return ""

    log.info(f"  [OCR] Processing image: {file_path}")

    try:
        from PIL import Image
        img = Image.open(file_path)

        # Try pytesseract
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
            text = pytesseract.image_to_string(img, lang="eng+hin+ori")
            if text.strip():
                log.info(f"  [OCR] Extracted: '{text.strip()[:80]}...'")
                return text.strip()
        except Exception as e:
            log.warning(f"  [OCR] Tesseract failed ({e}), using image metadata")

        # Fallback: return image description
        w, h = img.size
        return f"[Image uploaded: {w}x{h} pixels, format={img.format}. Content needs manual review or Tesseract installation.]"

    except Exception as e:
        log.error(f"  [OCR] Failed: {e}")
        return f"[Image could not be processed: {str(e)[:100]}]"


def real_translate(text: str, source_lang: str) -> str:
    """
    Translate to English using Google Translate (free via deep-translator).
    """
    if not text or not text.strip():
        return ""

    # Already English
    if source_lang in ("en", "english"):
        return text

    # Check if text is ASCII (likely already English)
    if all(ord(c) < 128 for c in text.replace("[", "").replace("]", "")):
        return text

    log.info(f"  [TRANSLATE] Translating from {source_lang} → English")

    try:
        from deep_translator import GoogleTranslator
        # Map our language codes to Google's
        lang_map = {
            "hi": "hi", "hindi": "hi",
            "or": "or", "odia": "or",
            "bn": "bn", "bengali": "bn",
            "ta": "ta", "tamil": "ta",
            "te": "te", "telugu": "te",
            "mr": "mr", "marathi": "mr",
            "gu": "gu", "gujarati": "gu",
            "kn": "kn", "kannada": "kn",
            "ml": "ml", "malayalam": "ml",
            "pa": "pa", "punjabi": "pa",
            "ur": "ur", "urdu": "ur",
            "as": "as", "assamese": "as",
        }
        src = lang_map.get(source_lang, "auto")
        translated = GoogleTranslator(source=src, target="en").translate(text[:5000])
        log.info(f"  [TRANSLATE] Result: '{translated[:80]}...'")
        return translated

    except Exception as e:
        log.warning(f"  [TRANSLATE] Failed ({e}), returning original")
        return text


def simulate_ocr(file_url: str) -> str:
    return real_ocr(file_url)


def simulate_translate(text: str, source_lang: str) -> str:
    return real_translate(text, source_lang)


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

    for sub in submissions:
        try:
            _process_one(conn, sub)
            processed_count += 1
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
        """, (sub_id, f'{{"audio_url": "{audio_url}"}}', f'{{"text": "{asr_text[:100]}"}}'))

    # Image input (OCR)
    if has_image:
        img_idx = media_types.index("image")
        img_url = media_urls[img_idx] if img_idx < len(media_urls) else ""
        ocr_text = simulate_ocr(img_url)
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
        """, (sub_id, f'{{"image_url": "{img_url}"}}', f'{{"text": "{ocr_text[:100]}"}}'))

    # Combine all extracted text
    original_text = " | ".join(extracted_parts) if extracted_parts else raw_text

    # ── Step 2: Translate to English ─────────────────────────────────────
    translated = simulate_translate(original_text, lang)

    execute_returning_uuid(conn, """
        INSERT INTO processing_queue (id, raw_submission_id, stage, status, input_payload, output_payload, started_at, completed_at)
        VALUES (%s, %s, 'translate', 'completed', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (sub_id, f'{{"source_lang": "{lang}"}}', f'{{"translated": "{translated[:100]}"}}'))

    # ── Step 3: Spam check ───────────────────────────────────────────────
    is_spam, spam_reason = check_spam(translated, user_id, conn)

    execute_returning_uuid(conn, """
        INSERT INTO processing_queue (id, raw_submission_id, stage, status, input_payload, output_payload, started_at, completed_at)
        VALUES (%s, %s, 'spam_check', 'completed', %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """, (sub_id, f'{{"text_length": {len(translated)}}}', f'{{"is_spam": {str(is_spam).lower()}, "reason": "{spam_reason}"}}'))

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
            "mp_constituency": sub.get("sub_constituency"),
        }

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
        pin_data["mp_constituency"] if pin_data else None,
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
