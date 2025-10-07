# Dictation App TODO

## Current Status (2025-10-06)
✅ **Working Features:**
- Parallel chunk recording (press Command multiple times while transcribing)
- Shortcut prevention during typing (Right Command blocked)
- Icon feedback (🎤 ready, 💭 transcribing, ⏸️ paused)
- Transcription timeout (2x audio duration or 120s minimum)
- Long transcript logging (>30s saved to file)
- Menu item to open transcript log

## Next Up

### High Priority
- [ ] **Model selection persistence** - Save user's model choice across app restarts
- [ ] **Better Whisper error handling** - Add retry logic and user notifications for transcription failures
- [ ] **Investigate transcription hang bug** - Some transcriptions hang without timing out (needs reproduction)

### Medium Priority
- [ ] **Add "Clear Log" menu item** - Let users clear transcript log from menu
- [ ] **Log file rotation** - Prevent transcript log from growing indefinitely
- [ ] **Make transcript threshold configurable** - UI preference for 30s threshold

### Low Priority / Future
- [ ] **CGEvents typing migration** - Replace AppleScript with CGEvents (eliminates TOCTOU race)
- [ ] **Model size optimization** - Profile performance, consider smaller default
- [ ] **Background transcription queue** - Show pending chunks in menu

## Known Limitations
- **TOCTOU race (~20ms)** - AppleScript subprocess creates small window where shortcuts can fire during typing
  - Mitigated by poll-wait, but not eliminated
  - Real fix requires CGEvents migration
- **Thread leak on timeout** - Timed-out Whisper threads continue running (mitigated by ThreadPoolExecutor)

## Questions
- Should we default to a smaller model (tiny/base) for better performance?
- Should we add a visual indicator for pending chunks?
- Do we need a preferences UI or are constants in code sufficient?
