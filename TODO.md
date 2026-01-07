# Dictation App TODO

## Current Status (2026-01-06)
✅ **Swift Version - Production Ready (v2.0.0-swift)**
- Merged to main branch
- Eliminated ffmpeg dependency
- Bundled Python environment (813MB)
- Fixed all critical bugs from Python version
- Python pre-warming for instant first-run

## Recently Fixed (2026-01-06)

### Critical Clipboard Bug Fixes
- ✅ **Queue-based mutual exclusion** - Prevents concurrent paste operations from corrupting clipboard
- ✅ **Async clipboard restoration** - No more UI freezing (removed 500ms blocking delay)
- ✅ **Extended delay to 750ms** - Handles slow Electron apps (Slack, VS Code, Discord)
- ✅ **Transient clipboard marker** - Good clipboard manager citizen (org.nspasteboard.TransientType)
- ✅ **User clipboard detection** - Skips restore if user manually copied during paste window
- ✅ **Comprehensive logging** - Track all paste operations for debugging

**The Fix:**
Old code had multiple race conditions:
1. Blocked main thread for 500ms (UI freeze)
2. No mutual exclusion for rapid dictation
3. Restored clipboard too early for slow apps
4. Didn't detect user clipboard modifications

New code uses queue-based paste operations with async 750ms restoration.

## Known Issues

### Minor (Not Blocking)
1. `showError()` method exists but never called (line 237-246, AppDelegate.swift)
2. WAV header parsing lacks validation (no RIFF/WAVE magic byte checks)
3. Some magic numbers not extracted to constants (50ms, 100ms delays)
4. No unit tests (manual testing only)
5. TranscriptionService warnings (Sendable, try? expressions) - cosmetic only

## Future Improvements

### High Priority
- [ ] Restore parallel chunk recording - Python version had this, Swift doesn't yet
- [ ] Add unit tests - At least for data transformation logic
- [ ] Proper code signing - Developer cert to avoid permission resets

### Medium Priority
- [ ] Migrate to whisper.cpp - Eliminate Python dependency entirely (would reduce 813MB → ~100MB)
- [ ] Extract magic numbers to constants
- [ ] Add WAV header validation
- [ ] Fix TranscriptionService warnings

### Low Priority
- [ ] Make 750ms clipboard delay configurable via preferences
- [ ] Add visual indicator for pending clipboard operations
- [ ] Consider app-specific timing (detect Slack vs TextEdit, adjust delays)
- [ ] Implement clipboard change monitoring instead of fixed delays

## Questions
- Should we make the 750ms delay user-configurable?
- Is whisper.cpp migration worth the effort? (Performance vs complexity)
- Do we need clipboard manager detection (Alfred, Maccy, etc.)?
