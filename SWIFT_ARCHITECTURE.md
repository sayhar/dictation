# Swift Dictation Architecture

## Overview

Swift rewrite of a push-to-talk dictation app. Hold Right Command → record audio → release → transcribe with Whisper → paste text.

## Components

```
┌─────────────────────────────────────────────────────────────────┐
│                        AppDelegate                               │
│  - Menu bar UI (NSStatusItem)                                   │
│  - Coordinates recording flow                                    │
│  - Icon states: 🎙️ (ready) → 🔴 (recording) → 💭 (transcribing) │
└─────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ KeyboardMonitor │  │  AudioRecorder  │  │TranscriptionSvc │
│                 │  │                 │  │                 │
│ CGEventTap for  │  │ AVAudioEngine   │  │ Shells out to   │
│ Right Cmd key   │  │ 16kHz mono WAV  │  │ Python/Whisper  │
│                 │  │                 │  │                 │
│ onKeyDown →     │  │ startRecording  │  │ transcribe()    │
│ onKeyUp →       │  │ stopRecording   │  │ async with      │
└─────────────────┘  └─────────────────┘  │ timeout         │
                                          └─────────────────┘
                                                   │
                                                   ▼
                                          ┌─────────────────┐
                                          │  TextInjector   │
                                          │                 │
                                          │ Queue-based     │
                                          │ Cmd+V paste     │
                                          │ Async restore   │
                                          └─────────────────┘
```

## Recording Flow

1. **KeyDown** (Right Command pressed)
   - `AppDelegate.startRecording()`
   - Set `recordingStartTime = Date()`
   - Icon → 🔴
   - `audioRecorder.startRecording()`

2. **KeyUp** (Right Command released)
   - `AppDelegate.stopRecordingAndTranscribe()`
   - Check wall-clock duration: if < 0.5s, discard and reset icon
   - Icon → 💭
   - `audioRecorder.stopRecording()` → returns WAV Data
   - Spawn async Task to transcribe

3. **Transcription** (async)
   - Write WAV to temp file
   - Shell out to: `uv run python -c "import whisper; ..."`
   - Timeout: 15s for short audio, 2x duration for longer
   - On success: `textInjector.typeText(result)`
   - Icon → 🎙️

## Known Issues / Failure Points

### 1. Transcription Hangs Forever
**Symptom:** 💭 icon never goes back to 🎙️
**Root cause:** Whisper hangs on certain audio (short/silent/corrupted)
**Mitigations tried:**
- 0.5s minimum duration check (wall-clock time)
- 15s timeout for short recordings
- SIGKILL instead of SIGTERM

**Still failing because:**
- The timeout/kill mechanism may not be working correctly
- The Python subprocess may spawn child processes that aren't killed
- The async Task may not be properly handling errors

### 2. Permissions Hell
**Symptom:** Every rebuild requires re-granting Accessibility + Microphone
**Root cause:** Ad-hoc code signing changes binary hash each build
**Workaround:** None good - this is macOS security working as designed

### 3. TranscriptionService Architecture
**Current:** Shells out to Python, runs `uv run python -c "..."`
**Problems:**
- Process spawning is complex (bash → uv → python → whisper)
- Killing the bash process may not kill grandchild processes
- Hard to get reliable timeout behavior

**Better approach would be:**
- Use whisper.cpp directly (native, no Python)
- Or: Long-running Python daemon with IPC
- Or: HTTP API to local Python server

## File Structure

```
Dictation/
├── AppDelegate.swift      # Main app, menu bar, flow coordination
├── KeyboardMonitor.swift  # CGEventTap for Right Command
├── AudioRecorder.swift    # AVAudioEngine → WAV
├── TranscriptionService.swift  # Python/Whisper subprocess
├── TextInjector.swift     # CGEvent Cmd+V paste
├── Preferences.swift      # JSON persistence
├── SingleInstanceLock.swift    # File lock
├── Models.swift           # WhisperModel enum, errors
├── Info.plist            # App metadata
└── Dictation.entitlements # Permissions
```

## Recent Fixes (2026-01-06)

### TextInjector Clipboard Bug Fix

**Problem:** Old clipboard content was sometimes pasted instead of transcription.

**Root Causes Identified:**
1. **UI Blocking** - `usleep(500000)` froze the app for 500ms every paste
2. **No Mutual Exclusion** - Rapid dictation caused clipboard corruption via concurrent pastes
3. **Timing Too Short** - 500ms wasn't enough for slow Electron apps (Slack, VS Code, Discord)
4. **No User Detection** - Couldn't detect if user manually copied during paste window
5. **Wrong changeCount Math** - Expected `+1` but clipboard operations add `+3`

**Solution Implemented:**
```swift
// Old approach (BROKEN)
func typeText(_ text: String) {
    saveClipboard()
    setClipboard(text)
    usleep(50000)      // Block 50ms
    simulatePaste()
    usleep(500000)     // Block 500ms - FREEZES UI!
    restoreClipboard() // Too early for slow apps
}

// New approach (FIXED)
func typeText(_ text: String) {
    pendingTexts.append(text)  // Queue it
    processPasteQueue()         // Process serially
}

private func performPaste(_ text: String) {
    saveClipboard()
    setClipboard(text)
    // NO usleep() - NSPasteboard is synchronous!
    simulatePaste()

    // Async restore after 750ms - doesn't block UI
    DispatchQueue.main.asyncAfter(.now() + .microseconds(750000)) {
        if clipboardModifiedByUser() {
            // Skip restore - preserve user's clipboard
            return
        }
        restoreClipboard()
        processPasteQueue() // Process next queued item
    }
}
```

**Key Improvements:**
- Queue-based processing prevents concurrent paste corruption
- Async restoration eliminates UI freezing
- 750ms delay handles slow Electron apps
- changeCount monitoring detects user clipboard changes
- Transient marker (`org.nspasteboard.TransientType`) for clipboard manager etiquette

**Log Output Example:**
```
TextInjector: Queued text (11 chars, 1 items in queue)
TextInjector: Starting paste operation (11 chars, 0 remaining in queue)
TextInjector: Saved clipboard (1 types, changeCount: 42)
TextInjector: Set clipboard with transient marker (changeCount: 42 → 45)
TextInjector: Cmd+V sent, waiting 750ms before restoring clipboard
TextInjector: Restoring clipboard (changeCount: 45 → 45)
TextInjector: Clipboard fully restored (1 types)
```

## Questions for Review

1. **Is shelling out to Python fundamentally flawed?**
   - Process tree killing is unreliable
   - Should we use whisper.cpp instead?

2. **Is the async Task pattern correct?**
   - Are we properly handling cancellation/errors?
   - Could there be retain cycles or zombie tasks?

3. **Is AVAudioEngine the right choice?**
   - The Python version uses sounddevice
   - Could there be buffering issues causing audio length mismatches?

4. **Is the timeout mechanism actually working?**
   - `kill(pid, SIGKILL)` on the Process
   - But what about child processes?

## To Debug

Run from terminal to see logs:
```bash
killall "Swift Dictation"
"$HOME/Applications/Swift Dictation.app/Contents/MacOS/Swift Dictation"
```

Key log messages to look for:
- `Recording duration: X.XXs` - wall clock time
- `Recording too short` - should discard
- `Transcribing X.Xs of audio` - entering transcription
- `TIMEOUT - killing process` - timeout triggered
