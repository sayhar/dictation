import Cocoa
import Carbon.HIToolbox

/// Injects transcribed text into the active application.
/// Uses CGEvents for keystroke simulation, preserving the clipboard.
///
/// This replicates the Python implementation's approach:
/// 1. Save current clipboard
/// 2. Put transcribed text on clipboard
/// 3. Simulate Cmd+V paste
/// 4. Restore original clipboard
class TextInjector {

    // MARK: - Public Methods

    /// Types text using osascript subprocess (same as Python app).
    func typeText(_ text: String) {
        guard !text.isEmpty else { return }

        // Escape for AppleScript (same as Python)
        let escaped = text
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")

        // Call osascript directly (subprocess, not NSAppleScript)
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        process.arguments = ["-e", "tell application \"System Events\" to keystroke \"\(escaped)\""]

        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            NSLog("TextInjector: osascript failed: \(error)")
        }
    }

    // MARK: - Private Methods

    /// Simulates Cmd+V keystroke to paste from clipboard.
    private func simulatePaste() {
        // Use combinedSessionState for better compatibility
        let source = CGEventSource(stateID: .combinedSessionState)

        // Key down for 'v' with Command modifier
        guard let keyDown = CGEvent(keyboardEventSource: source, virtualKey: CGKeyCode(kVK_ANSI_V), keyDown: true) else {
            NSLog("TextInjector: Failed to create key down event")
            return
        }
        keyDown.flags = .maskCommand

        // Key up for 'v' with Command modifier
        guard let keyUp = CGEvent(keyboardEventSource: source, virtualKey: CGKeyCode(kVK_ANSI_V), keyDown: false) else {
            NSLog("TextInjector: Failed to create key up event")
            return
        }
        keyUp.flags = .maskCommand

        // Post to cghidEventTap for broader compatibility
        keyDown.post(tap: .cghidEventTap)
        usleep(10000)  // 10ms between key events
        keyUp.post(tap: .cghidEventTap)

        NSLog("TextInjector: Posted Cmd+V events")
    }

    /// Saves all pasteboard contents for later restoration.
    private func savePasteboardContents(_ pasteboard: NSPasteboard) -> [(NSPasteboard.PasteboardType, Data)] {
        var contents: [(NSPasteboard.PasteboardType, Data)] = []

        guard let types = pasteboard.types else { return contents }

        for type in types {
            if let data = pasteboard.data(forType: type) {
                contents.append((type, data))
            }
        }

        return contents
    }

    /// Restores previously saved pasteboard contents.
    private func restorePasteboardContents(
        _ pasteboard: NSPasteboard,
        contents: [(NSPasteboard.PasteboardType, Data)]
    ) {
        pasteboard.clearContents()

        for (type, data) in contents {
            pasteboard.setData(data, forType: type)
        }
    }
}
