# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed
- **Critical clipboard bug** - Fixed race condition where old clipboard content was pasted instead of transcription
  - Implemented queue-based mutual exclusion for paste operations
  - Changed to async clipboard restoration (750ms) to eliminate UI freezing
  - Removed blocking `usleep()` calls that froze the app
  - Added user clipboard modification detection (skips restore if user manually copied)
  - Added transient clipboard marker for clipboard manager etiquette
  - Fixed changeCount math (now correctly expects +3 instead of +1)

## [2.0.0-swift] - 2026-01-06

### Swift Rewrite - Complete

Complete rewrite in Swift for better performance and native macOS integration.

### Added
- **Bundled Python environment** - Self-contained 813MB app bundle with Python 3.13 and mlx-whisper
- **Python pre-warming** - Background task pre-loads mlx-whisper on launch for instant first-run
- **Direct PCM pipeline** - Eliminated ffmpeg dependency, direct 16kHz mono PCM to Python stdin
- **@MainActor thread safety** - Proper Swift concurrency with actor isolation
- **Queue-based text injection** - Serial paste operations prevent concurrent clipboard corruption

### Changed
- **Language: Python → Swift** - Entire app rewritten in Swift 5.9+
- **Audio: sounddevice → AVFoundation** - Native AVAudioEngine for recording
- **UI: rumps → AppKit** - Native NSStatusItem menu bar interface
- **Keyboard: PyObjC → CoreGraphics** - Native CGEventTap for keyboard monitoring
- **Text injection: AppleScript → CGEvents** - Native Cmd+V simulation with clipboard preservation
- **No system dependencies** - Removed ffmpeg requirement, fully self-contained

### Fixed
- **First-run hang** - Pre-warming eliminates 15-20s hang on first transcription
- **Duration check bug** - Now uses wall-clock time instead of audio buffer length
- **Pipe leak** - Proper cleanup of file descriptors
- **Clipboard race** - Fixed timing issues with slow Electron apps
- **Process race** - Added mutual exclusion for subprocess management
- **State machine bugs** - Proper lifecycle management in Swift

### Known Limitations
- **813MB bundle size** - Bundled Python + mlx-whisper packages (trade-off for no dependencies)
- **Hardcoded Python path** - build-swift.sh assumes uv Python 3.13.5 location

## [1.0.0] - Python Version

### Added
- **Single instance lock** - Prevents multiple app instances from conflicting over audio stream and event tap
- **Transcription timeout** - Dynamic timeout (2x audio duration or 120s minimum) prevents infinite hangs on corrupted/problematic audio
- **Icon feedback** - Menu bar icon changes to 💭 (thinking) during transcription, 🎤 when ready
- **Event consumption** - Right Command key events are consumed, preventing accidental system shortcuts during dictation
- **Long transcript logging** - Transcriptions >30 seconds are automatically saved to `~/Library/Logs/Dictation_Transcripts.log`
- **Transcript log menu item** - "Open Transcription Log" menu item provides one-click access to saved long dictations (PR #10)
- **Model selection persistence** - Selected Whisper model now persists across app restarts via `~/Library/Application Support/Dictation/preferences.json` (PR #12)
- **Retry logic for transcription** - Automatic retry (up to 3 attempts) for failed Whisper transcriptions with detailed error logging (PR #13)

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
