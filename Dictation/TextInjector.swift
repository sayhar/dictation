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

    /// Types the given text into the active application.
    /// Uses clipboard-based paste to handle special characters correctly.
    func typeText(_ text: String) {
        guard !text.isEmpty else { return }

        // Save current clipboard
        let pasteboard = NSPasteboard.general
        let savedContents = savePasteboardContents(pasteboard)

        // Set our text on clipboard
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)

        // Small delay to ensure clipboard is ready
        usleep(50000)  // 50ms

        // Simulate Cmd+V
        simulatePaste()

        // Small delay before restoring clipboard
        usleep(100000)  // 100ms

        // Restore original clipboard
        restorePasteboardContents(pasteboard, contents: savedContents)
    }

    // MARK: - Private Methods

    /// Simulates Cmd+V keystroke to paste from clipboard.
    private func simulatePaste() {
        let source = CGEventSource(stateID: .hidSystemState)

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

        // Post the events
        keyDown.post(tap: .cgAnnotatedSessionEventTap)
        keyUp.post(tap: .cgAnnotatedSessionEventTap)
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
