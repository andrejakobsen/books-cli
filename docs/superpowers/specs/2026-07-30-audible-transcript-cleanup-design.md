# Audible transcript cleanup — design

## Problem

Audible clips are cut on time boundaries, so a transcription often begins in the
middle of a sentence and ends on a half-started one. The resulting highlight text
reads raggedly.

## Solution

Add a pure helper `clean_transcript(text: str) -> str` in
`books/commands/audible/transcribe.py` that trims dangling partial sentences from
the start and end. Apply it by wrapping every backend's output in
`make_transcriber` (`return lambda path: clean_transcript(base(path))`) so `local`,
`openai`, and `google` all benefit and each backend body stays untouched.

Cleaning happens **before** the text is cached, so re-runs serve already-clean text.
Books already cached keep their stored (uncleaned) text until re-transcribed.

## Rules

Applied to the stripped text; sentence terminators are `.`, `!`, `?`.

1. **Leading trim (only if partial).** Find the first alphabetic character. Trim only
   when **both** hold: (a) that character is lowercase, and (b) the fragment ending at
   the first terminator has **fewer than 5 words**. When trimming, drop everything up to
   and including that terminator, then skip any trailing closing quotes/brackets and
   whitespace, keeping the remainder. An uppercase start, or a long (≥ 5 word) lowercase
   fragment, is left alone (it is probably a real sentence).
2. **Trailing trim (always).** Cut everything after the last terminator, keeping the
   terminator plus any immediately-following closing quote/bracket. Whisper's `...`/`…`
   ends in `.` so it counts as complete.
3. **Safety net.** Each step applies only if a terminator exists and the result is
   non-empty. A clip with no terminator at all (one continuous fragment) is returned
   untrimmed. Nothing ever reduces the text to empty.

**Quote handling.** Boundaries extend over trailing `"` `'` `”` `’` `)` `]` so
`...she turned." Then he—` trims the dangling `Then he—`, and on the leading side
`talking." She left` keeps `She left`.

## Testing

Unit tests for `clean_transcript`:

- lowercase short fragment (< 5 words) at start is trimmed
- lowercase long fragment (≥ 5 words) at start is kept
- uppercase start is preserved
- trailing fragment after last terminator is dropped
- closing-quote boundaries (leading and trailing)
- no-punctuation passthrough (safety net)
- empty / whitespace input
- idempotency (cleaning twice == cleaning once)

Update `test_make_transcriber_dispatches` to reflect that `make_transcriber` now
returns a wrapper that applies `clean_transcript` to each backend's output.
