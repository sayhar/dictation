# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- **Single instance lock** - Prevents multiple app instances from conflicting over audio stream and event tap
- **Transcription timeout** - Dynamic timeout (2x audio duration or 120s minimum) prevents infinite hangs on corrupted/problematic audio
- **Icon feedback** - Menu bar icon changes to 💭 (thinking) during transcription, 🎤 when ready
- **Event consumption** - Right Command key events are consumed, preventing accidental system shortcuts during dictation
- **Long transcript logging** - Transcriptions >60 seconds are automatically saved to `~/Library/Logs/Dictation_Transcripts.log`

### Changed
- **Stream abort instead of stop** - Uses `abort()` instead of `stop()` to avoid waiting for pending buffers (eliminates deadlock)
- **Improved error handling** - Stream stop failures no longer lose user's recording; transcription continues with captured audio
- **Atexit cleanup** - Single instance lock now uses atexit for automatic cleanup on app exit

### Fixed
- **TOCTOU race conditions** - Restored atomic claim pattern with check-and-set inside locks (PR #2)
- **Lock contention in audio callback** - Dual lock strategy (state_lock + audio_lock) eliminates blocking in time-sensitive audio callback
- **Clipboard preservation** - Reverted to AppleScript keystroke approach (preserves clipboard). Event consumption (return None) prevents shortcuts from triggering during dictation
- **Stream state races** - All stream operations now check state under lock to prevent races with start/stop
- **State transitions** - Proper rollback on stream start failure

### Known Limitations
- **Thread leak on timeout** - When transcription times out, the underlying Whisper thread continues running until completion (potentially 10+ minutes). This is mitigated by using `max_workers=2` in ThreadPoolExecutor to prevent blocking. Future refactor will use ProcessPoolExecutor for true process termination.

## [1.0.0] - Initial Release

### Added
- Push-to-talk dictation using Right Command key
- Local Whisper transcription (tiny/base/small/medium/large models)
- Menu bar app interface
- Auto-type transcribed text
- Model selection from menu
- Microphone and accessibility permission handling
- Background operation (no dock icon)
