# STT Mode Parameter & Spam Filter - Implementation Summary

## Changes Made

### 1. Added Mode Parameter to STT Functions

All STT transcription functions now accept a `mode` parameter:

- **`mode="query"`** (default): Normal user queries, no spam filtering
- **`mode="followup"`**: Follow-up queries, enables repetition spam filtering
- **`mode="hotword_confirm"`**: Hotword confirmation, no spam filtering
- **`mode="debug"`**: Reserved for future debug/filler behavior (currently unused)

**Updated Functions:**
- `transcribe_pcm16(audio_i16, sample_rate=16000, mode="query")`
- `listen_once(timeout_seconds, ..., mode="query")`
- `listen_follow_up(wait_seconds, max_listen_seconds, mode="followup")`

### 2. Repetition Spam Filter

Added `_has_repetition_spam()` helper that detects when any token repeats more than 6 times:

```python
_has_repetition_spam("the the the the the the the")  # True (7 repeats)
_has_repetition_spam("hello world hello world")      # False (2 repeats)
```

- **Applied automatically in `mode="followup"`**
- Ignores single-character tokens
- Logs: `[STT] Ignored: repetition spam - "..."`
- Returns empty string when spam detected

### 3. Empty String Handling

All STT functions now return `""` (empty string) when:
- No speech detected
- Audio too quiet
- Spam filtering triggered (follow-up mode only)
- Confidence filters reject transcript (follow-up mode only)
- Transcription fails

**Updated callers to handle empty strings gracefully:**

- **Main query (`assistant.py`)**: Uses `mode="query"`, no spam filtering, no confidence gating
- **Follow-up (`assistant.py`)**: Uses `mode="followup"`, spam filtered, confidence gated, logs "No follow-up speech detected"
- **Hotword confirm (`hotword_detector_new.py`)**: Uses `mode="hotword_confirm"`, fail-open behavior

### 4. Confidence Gating (Follow-up Mode Only)

Added confidence filtering to `mode="followup"` to prevent hallucinated polite phrases from noise.

**Stricter Whisper Parameters:**
```python
beam_size=1          # Single beam for faster, more conservative results
best_of=1            # No sampling
temperature=0.0      # Deterministic output
vad_filter=True      # Voice activity detection
no_speech_threshold=0.6
log_prob_threshold=-1.0
```

**Rejection Criteria (any true → returns empty string):**
1. Transcript length < 3 characters
2. `max_no_speech_prob >= 0.6`
3. `avg_logprob <= -1.0` (low confidence)
4. `compression_ratio > 2.4` (likely repeated/noise)

**Hallucination Guard:**
- Phrases: `["thank you", "thanks", "bye", "goodbye", "you"]`
- Rejected if `avg_logprob <= -0.8` OR `no_speech_prob >= 0.4`
- Prevents common hallucinations from background noise

**Debug Logs:**
```
[STT followup] text="thank you" avg_logprob=-0.95 no_speech_prob=0.72 compression=1.05 -> ignored (hallucination:thank you)
[STT followup] text="what's the weather" avg_logprob=-0.35 no_speech_prob=0.15 -> accepted
```

### 5. No Filler Text Injection

Confirmed: The codebase does NOT inject filler text like "thank you", "bye", etc.

- `_FILLER_TOKENS` in `commands_toolkit.py` is only for **removing** common words from app names
- No garbage filtering or placeholder text substitution found
- STT functions return authentic transcripts or empty strings only

## Testing

### Test Spam Filter
```bash
python scripts/test_spam_filter.py
```

### Test Confirmation Pipeline
```bash
python scripts/test_confirm.py
```

### Test Full System
```bash
python local_ai_assistant/assistant.py
```

## Behavior Summary

| Mode | Spam Filter | Confidence Gating | Use Case | Caller |
|------|-------------|-------------------|----------|---------|
| `query` | ❌ No | ❌ No | Main user query | `assistant.py` main loop |
| `followup` | ✅ Yes | ✅ Yes | Follow-up after response | `assistant.py` follow-up listener |
| `hotword_confirm` | ❌ No | ❌ No | Whisper confirms wake word | `hotword_detector_new.py` |
| `debug` | 🔧 Reserved | 🔧 Reserved | Future debug/testing | (unused) |

## Example Logs

### Normal Follow-up (Good Confidence)
```
[STT] Listening for follow-up...
[STT followup] text="what about tomorrow" avg_logprob=-0.35 no_speech_prob=0.15 -> accepted
Follow-up heard: what about tomorrow
```

### Hallucination Rejected (Noise)
```
[STT] Listening for follow-up...
[STT followup] text="thank you" avg_logprob=-0.95 no_speech_prob=0.72 compression=1.05 -> ignored (hallucination:thank you)
No follow-up speech detected (timeout or spam filtered).
```

### Spam Filtered
```
[STT] Listening for follow-up...
[STT] Ignored: repetition spam - "the the the the the the the"
No follow-up speech detected (timeout or spam filtered).
```

### Low Confidence Rejected
```
[STT] Listening for follow-up...
[STT followup] text="um" avg_logprob=-1.25 no_speech_prob=0.45 compression=1.85 -> ignored (low_confidence)
No follow-up speech detected (timeout or spam filtered).
```

### Hotword Confirmation
```
[WAKE] scores={'hey jarvis': 0.87} max=0.870
[CONFIRM] transcript="hey jarvis"
[CONFIRM] Matched phrase: 'hey jarvis'
```

## Backwards Compatibility

- `stt_vosk.py` remains functional as a compatibility shim
- All existing code continues to work via re-exports
- Default `mode="query"` preserves original behavior
- Mode parameter is optional (keyword-only)
