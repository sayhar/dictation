# Testing Checklist

## Critical Bugs - Never Allow Regression

These are bugs that **must never return**. Test these before every release.

### 1. ❌ Command Key Shortcuts During Typing
**Bug:** If user holds Right Command while transcription completes, typing triggers shortcuts (Cmd+T, Cmd+A, etc.)

**Test:**
1. Hold Right Command
2. Say "test tab new"
3. **Keep holding** Right Command during transcription
4. ✅ PASS: App waits for key release, then types "test tab new" normally
5. ❌ FAIL: Letters trigger shortcuts (new tab opens, etc.)

**Status:** 🔴 BROKEN - Fix in progress

---

### 2. ❌ TOCTOU Race Conditions
**Bug:** Multiple transcription threads can start simultaneously due to check-then-use pattern

**Test:**
1. Rapidly press and release Right Command multiple times (3-4 times in 1 second)
2. Check logs for "Transcription already in progress, ignoring release"
3. ✅ PASS: Only one transcription runs, others are rejected
4. ❌ FAIL: Multiple "Starting transcription" messages in logs

**How to check logs:**
```bash
tail -f ~/Library/Logs/Dictation.log
```

**Status:** ✅ FIXED (PR #5)

---

### 3. ❌ Audio Callback Deadlock
**Bug:** Audio callback blocks on lock acquisition, causing audio glitches/drops

**Test:**
1. Hold Right Command and speak for 10+ seconds
2. Release and check transcription quality
3. ✅ PASS: Audio is complete, no gaps or stuttering in transcription
4. ❌ FAIL: Transcription has gaps or missing words

**Status:** ✅ FIXED (PR #2 - dual lock strategy)

---

### 4. ❌ Clipboard Destroyed
**Bug:** Dictation temporarily destroys clipboard contents

**Test:**
1. Copy "ORIGINAL TEXT" to clipboard
2. Hold Right Command, say "hello world", release
3. After transcription completes, paste (Cmd+V)
4. ✅ PASS: "ORIGINAL TEXT" is pasted (clipboard preserved)
5. ❌ FAIL: "hello world" is pasted (clipboard was overwritten)

**Status:** ✅ FIXED (PR #5 - reverted to keystroke approach)

---

### 7. ❌ Old Clipboard Content Pasted
**Bug:** Sometimes old clipboard content gets pasted instead of transcription

**Test:**
1. Copy "ORIGINAL TEXT" to clipboard
2. Hold Right Command, say "hello world", release
3. Text should appear: "hello world"
4. Press Cmd+V again
5. ✅ PASS: "ORIGINAL TEXT" is pasted (clipboard was properly restored)
6. ❌ FAIL: "hello world" or some other old content is pasted

**Root Causes Fixed (2026-01-06):**
- Clipboard restored too early (500ms → 750ms async)
- No mutual exclusion for rapid dictation (added queue system)
- Main thread blocking caused UI freezes (removed usleep)
- Didn't detect user clipboard changes (added changeCount monitoring)

**Status:** ✅ FIXED (2026-01-06 - TextInjector rewrite with queue-based paste operations)

---

### 5. ❌ Stream Stop Deadlock
**Bug:** Using `stream.stop()` blocks waiting for buffers, preventing new recordings

**Test:**
1. Record a short utterance (1-2 seconds)
2. Immediately after release, try to start a new recording
3. ✅ PASS: New recording starts immediately
4. ❌ FAIL: Delay before new recording starts, or app hangs

**Status:** ✅ FIXED (PR #3 - using `abort()` instead)

---

### 6. ❌ Multiple App Instances Fight Over Audio
**Bug:** Running two instances causes audio stream conflicts

**Test:**
1. Launch Dictation.app
2. Try to launch it again
3. ✅ PASS: Alert "Another instance is already running", second instance exits
4. ❌ FAIL: Both instances run, audio recording fails

**Status:** ✅ FIXED (PR #5 - single instance lock)

---

## Feature Tests

### Transcription Timeout
**Test:**
1. Record 30 seconds of audio (or create corrupted audio file)
2. Verify timeout triggers after 120s or 2x audio duration (whichever is longer)
3. ✅ PASS: Notification "Transcription timed out"
4. ❌ FAIL: App hangs indefinitely

**Status:** ✅ IMPLEMENTED (PR #5)

**Known Limitation:** Timed-out thread continues in background (can't kill it)

---

### Icon Feedback
**Test:**
1. Hold Right Command → Icon should be 🎤 (ready)
2. Release (start transcribing) → Icon should change to 💭 (thinking)
3. Transcription completes → Icon should return to 🎤
4. ✅ PASS: Icon changes as expected
5. ❌ FAIL: Icon stuck or doesn't change

**Status:** ✅ IMPLEMENTED (PR #5)

---

### Event Consumption
**Test:**
1. Focus a browser with tabs
2. Hold Right Command, say "test", release
3. ✅ PASS: "test" is typed, no system shortcuts triggered
4. ❌ FAIL: System menu appears or other Command-related behavior

**Status:** ✅ IMPLEMENTED (PR #3)

---

## Performance Tests

### Long Recording (>30 seconds)
**Test:**
1. Hold Right Command and speak continuously for 90 seconds
2. Release and wait for transcription
3. ✅ PASS: Full transcription appears, saved to ~/Library/Logs/Dictation_Transcripts.log
4. ❌ FAIL: Transcription incomplete or missing

---

### Rapid Start/Stop
**Test:**
1. Rapidly press/release Right Command 10 times (short recordings)
2. ✅ PASS: All recordings processed, no crashes
3. ❌ FAIL: App crashes or recordings lost

---

## How to Run Tests

### Automated (Future)
```bash
# TODO: Create automated test suite
uv run pytest tests/
```

### Manual Testing
1. Follow each test case above
2. Mark status: ✅ PASS or ❌ FAIL
3. Check logs: `tail -f ~/Library/Logs/Dictation.log`

---

## Before Every Release

- [ ] All "Critical Bugs" tests pass
- [ ] All "Feature Tests" pass
- [ ] No new errors in logs during testing
- [ ] README updated with new features
- [ ] CHANGELOG updated

---

## Regression Tracking

When a bug is found:
1. Add it to "Critical Bugs" section
2. Write a test case
3. Mark status 🔴 BROKEN
4. Fix the bug
5. Update status ✅ FIXED with PR number
6. Test before every future release
