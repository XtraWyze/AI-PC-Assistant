# Confidence Gating Quick Reference

## Problem Solved

**Before:** Follow-up listener would hallucinate polite phrases from background noise:
```
[Silence/noise] → Whisper hallucinates → "thank you" / "bye" / "thanks"
```

**After:** Confidence filters reject low-quality transcripts:
```
[Silence/noise] → Whisper transcribes → Confidence check fails → Empty string ""
```

## Implementation

### Mode-Specific Parameters

**Query Mode (Default)**
- Standard Whisper parameters
- No confidence filtering
- Accepts all transcripts (even "thank you")
- Use: Main user queries after wake word

**Followup Mode (Strict)**
- `beam_size=1, temperature=0.0` - Conservative decoding
- `vad_filter=True` - Voice activity detection
- `no_speech_threshold=0.6` - Higher noise rejection
- Confidence filtering enabled
- Use: Follow-up window after assistant response

### Confidence Filters (Followup Only)

Transcript is **REJECTED** if ANY of these are true:

1. **Length Check**: `len(transcript) < 3`
2. **No Speech**: `max_no_speech_prob >= 0.6`
3. **Low Confidence**: `avg_logprob <= -1.0`
4. **Compression**: `compression_ratio > 2.4`

### Hallucination Guard (Followup Only)

Special check for common hallucinated phrases:
- Phrases: `["thank you", "thanks", "bye", "goodbye", "you"]`
- Rejected if EITHER:
  - `avg_logprob <= -0.8` (lower confidence)
  - `no_speech_prob >= 0.4` (moderate noise)

## Debug Logs

### Rejected Hallucination
```
[STT followup] text="thank you" avg_logprob=-0.95 no_speech_prob=0.72 compression=1.05 -> ignored (hallucination:thank you)
```

### Accepted Speech
```
[STT followup] text="what's the weather" avg_logprob=-0.35 no_speech_prob=0.15 -> accepted
```

### Low Confidence
```
[STT followup] text="um" avg_logprob=-1.25 no_speech_prob=0.45 compression=1.85 -> ignored (low_confidence)
```

## Testing

```bash
# Show expected behavior
python scripts/test_confidence_gating.py

# Test full system with real audio
python local_ai_assistant/assistant.py
# Say "hey jarvis", ask question, wait for response
# [Follow-up window] Background noise should NOT trigger "thank you"
```

## Configuration

All thresholds are hardcoded in `stt_whisper.py` `_run_transcription()` method.

To adjust sensitivity:
- **More strict** (fewer false positives): Lower `no_speech_threshold`, lower `avg_logprob` threshold
- **More lenient** (more false positives): Raise thresholds

Current thresholds are tuned to balance false positive rejection vs. real speech acceptance.

## Backwards Compatibility

- Query mode unchanged: All transcripts accepted regardless of confidence
- Hotword confirmation unchanged: No confidence filtering
- Only `mode="followup"` applies confidence gating
- Empty strings handled gracefully everywhere
