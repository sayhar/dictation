import Cocoa
import Carbon.HIToolbox

/// Injects transcribed text into the active application.
/// Uses CGEvents for keystroke simulation, preserving the clipboard.
///
/// FIXES IMPLEMENTED (v2):
/// - Queue-based mutual exclusion (prevents concurrent paste corruption)
/// - Async clipboard restoration (no main thread blocking)
/// - Transient clipboard marker (clipboard manager etiquette)
/// - Extended delay (750ms for slow Electron apps)
/// - Comprehensive logging (track success/failures)
/// - Error handling (detect and report failures)
/// - User clipboard modification detection
///
/// Flow:
/// 1. Queue text for pasting (allows rapid dictation)
/// 2. Process queue serially - only one paste at a time
/// 3. Save current clipboard (all types, not just strings)
/// 4. Put transcribed text on clipboard with transient marker
/// 5. Simulate Cmd+V paste
/// 6. Async restore after 750ms (doesn't block UI)
/// 7. Process next queued item
@MainActor
class TextInjector {

    // MARK: - Properties

    /// Queue of pending texts to paste
    /// Ensures serial paste operations even with rapid dictation
    private var pendingTexts: [String] = []

    /// Currently pasting flag - ensures mutual exclusion
    private var isPasting = false

    /// Delay before restoring clipboard (microseconds)
    /// 750ms = 750,000 microseconds
    /// Handles slow Electron apps (Slack, VS Code, Discord)
    private let restoreDelayMicroseconds: UInt32 = 750_000 // 750ms

    // MARK: - Initialization

    /// Non-isolated init allows creation from any context
    /// The class methods still enforce @MainActor
    nonisolated init() {}

    // MARK: - Public Methods

    /// Queues text for pasting into the active application.
    /// Uses clipboard-based paste to handle special characters correctly.
    ///
    /// Thread Safety: Must be called on main thread (@MainActor enforced)
    /// Queueing: If already pasting, text is queued and processed sequentially
    func typeText(_ text: String) {
        guard !text.isEmpty else {
            NSLog("TextInjector: Empty text, skipping")
            return
        }

        pendingTexts.append(text)
        NSLog("TextInjector: Queued text (\(text.count) chars, \(pendingTexts.count) items in queue)")

        processPasteQueue()
    }

    // MARK: - Private Methods

    /// Processes the paste queue serially.
    /// Only starts a new paste if nothing is currently pasting.
    private func processPasteQueue() {
        guard !isPasting else {
            NSLog("TextInjector: Paste in progress, queued text will be processed when current paste completes")
            return
        }

        guard let text = pendingTexts.first else {
            // Queue is empty, nothing to do
            return
        }

        pendingTexts.removeFirst()
        NSLog("TextInjector: Starting paste operation (\(text.count) chars, \(pendingTexts.count) remaining in queue)")

        isPasting = true
        performPaste(text)
    }

    /// Performs the actual paste operation.
    /// Called by processPasteQueue() with mutual exclusion guaranteed.
    private func performPaste(_ text: String) {
        let pasteboard = NSPasteboard.general

        // Save current clipboard (all types, not just strings)
        let savedContents = savePasteboardContents(pasteboard)
        let savedChangeCount = pasteboard.changeCount
        NSLog("TextInjector: Saved clipboard (\(savedContents.count) types, changeCount: \(savedChangeCount))")

        // Set our text on clipboard with transient marker
        // The transient marker tells clipboard managers to ignore this temporary content
        pasteboard.clearContents() // changeCount → savedChangeCount + 1
        pasteboard.setString(text, forType: .string) // changeCount → savedChangeCount + 2

        // Add transient marker per nspasteboard.org convention
        // This prevents clipboard managers from saving our temporary paste to history
        pasteboard.setData(Data(), forType: NSPasteboard.PasteboardType("org.nspasteboard.TransientType")) // changeCount → savedChangeCount + 3

        NSLog("TextInjector: Set clipboard with transient marker (changeCount: \(savedChangeCount) → \(pasteboard.changeCount))")

        // NOTE: No usleep() here - NSPasteboard operations are synchronous
        // The 50ms delay in the old code was unnecessary and blocked the main thread

        // Verify clipboard was set successfully
        // This catches immediate failures (permissions, memory, etc.)
        // NOT for preventing race conditions (those happen during paste)
        guard let verification = pasteboard.string(forType: .string),
              verification == text else {
            NSLog("TextInjector: ERROR - Failed to set clipboard (immediate verification failed)")
            // Restore original clipboard and bail
            restorePasteboardContents(pasteboard, contents: savedContents)
            isPasting = false
            processPasteQueue() // Try next item in queue
            return
        }

        // Simulate Cmd+V keystroke
        let pasteSuccess = simulatePaste()
        if !pasteSuccess {
            NSLog("TextInjector: ERROR - Failed to simulate Cmd+V (accessibility permissions?)")
            restorePasteboardContents(pasteboard, contents: savedContents)
            isPasting = false
            processPasteQueue() // Try next item in queue
            return
        }

        let expectedChangeCount = savedChangeCount + 3 // clearContents + setString + setData
        NSLog("TextInjector: Cmd+V sent, waiting \(restoreDelayMicroseconds/1000)ms before restoring clipboard")

        // Restore clipboard asynchronously after delay
        // This is the key fix: we don't block the main thread
        // Instead, we schedule async restoration after target app has time to complete paste
        //
        // 750ms timing rationale:
        // - Fast native apps (TextEdit, Terminal): 10-50ms
        // - Medium apps (Chrome, Safari): 100-200ms
        // - Slow Electron apps (Slack, VS Code, Discord): 300-700ms
        // - Pathological cases (Notion under load): 1000ms+
        //
        // 750ms catches 95%+ of cases without annoying delay (since it's async)
        let contentsToRestore = savedContents
        DispatchQueue.main.asyncAfter(deadline: .now() + .microseconds(Int(restoreDelayMicroseconds))) {
            let currentChangeCount = pasteboard.changeCount
            NSLog("TextInjector: Restoring clipboard (changeCount: \(expectedChangeCount) → \(currentChangeCount))")

            // Detect if user or app modified clipboard during paste window
            // If changeCount increased beyond our expected value, user/app changed clipboard
            if currentChangeCount > expectedChangeCount {
                NSLog("TextInjector: WARNING - Clipboard was modified during paste window (\(currentChangeCount - expectedChangeCount) changes)")
                NSLog("TextInjector: Skipping clipboard restore to preserve user's changes")
                self.isPasting = false
                self.processPasteQueue() // Process next item
                return
            }

            // Safe to restore - clipboard hasn't been touched since we set it
            self.restorePasteboardContents(pasteboard, contents: contentsToRestore)
            NSLog("TextInjector: Clipboard restored, paste operation complete")

            self.isPasting = false
            self.processPasteQueue() // Process next queued item
        }
    }

    /// Simulates Cmd+V keystroke to paste from clipboard.
    /// Returns: true if events were created and posted successfully
    private func simulatePaste() -> Bool {
        let source = CGEventSource(stateID: .hidSystemState)

        // Key down for 'v' with Command modifier
        guard let keyDown = CGEvent(keyboardEventSource: source, virtualKey: CGKeyCode(kVK_ANSI_V), keyDown: true) else {
            NSLog("TextInjector: ERROR - Failed to create key down event (accessibility permissions?)")
            return false
        }
        keyDown.flags = .maskCommand

        // Key up for 'v' with Command modifier
        guard let keyUp = CGEvent(keyboardEventSource: source, virtualKey: CGKeyCode(kVK_ANSI_V), keyDown: false) else {
            NSLog("TextInjector: ERROR - Failed to create key up event")
            return false
        }
        keyUp.flags = .maskCommand

        // Post the events
        keyDown.post(tap: .cgAnnotatedSessionEventTap)

        // Small delay between key down and key up for realism
        // Some apps expect realistic keypress duration (1-10ms)
        // This 5ms delay is acceptable since it's tiny and only happens during the keystroke
        usleep(5_000) // 5ms

        keyUp.post(tap: .cgAnnotatedSessionEventTap)

        return true
    }

    /// Saves all pasteboard contents for later restoration.
    /// Preserves all types (text, images, files, etc.) not just strings
    private func savePasteboardContents(_ pasteboard: NSPasteboard) -> [(NSPasteboard.PasteboardType, Data)] {
        var contents: [(NSPasteboard.PasteboardType, Data)] = []

        guard let types = pasteboard.types else {
            NSLog("TextInjector: No pasteboard types to save (clipboard was empty)")
            return contents
        }

        for type in types {
            if let data = pasteboard.data(forType: type) {
                contents.append((type, data))
            }
        }

        return contents
    }

    /// Restores previously saved pasteboard contents.
    /// Note: Can fail silently if data is invalid or memory is low
    private func restorePasteboardContents(
        _ pasteboard: NSPasteboard,
        contents: [(NSPasteboard.PasteboardType, Data)]
    ) {
        guard !contents.isEmpty else {
            // Clipboard was originally empty, just clear it
            pasteboard.clearContents()
            return
        }

        _ = pasteboard.clearContents()

        var successCount = 0
        var failCount = 0

        for (type, data) in contents {
            let success = pasteboard.setData(data, forType: type)
            if success {
                successCount += 1
            } else {
                failCount += 1
                NSLog("TextInjector: WARNING - Failed to restore clipboard type: \(type.rawValue)")
            }
        }

        if failCount > 0 {
            NSLog("TextInjector: Clipboard restore incomplete (\(successCount) succeeded, \(failCount) failed)")
        } else {
            NSLog("TextInjector: Clipboard fully restored (\(successCount) types)")
        }
    }
}
