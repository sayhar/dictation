import Cocoa
import Carbon.HIToolbox

/// Monitors keyboard events to detect Right Command key press/release.
/// Uses Quartz Event Services (CGEventTap) for low-level keyboard monitoring.
///
/// This replicates the Python implementation's event tap behavior:
/// - Fires onKeyDown when Right Command is pressed
/// - Fires onKeyUp when Right Command is released
/// - Handles edge cases like Command+Tab switching away
class KeyboardMonitor {

    // MARK: - Callbacks

    /// Called when Right Command key is pressed down
    var onKeyDown: (() -> Void)?

    /// Called when Right Command key is released
    var onKeyUp: (() -> Void)?

    // MARK: - Private Properties

    /// The event tap for monitoring keyboard events
    private var eventTap: CFMachPort?

    /// Run loop source for the event tap
    private var runLoopSource: CFRunLoopSource?

    /// Tracks whether Right Command is currently held
    private var isRightCommandHeld = false

    /// The Right Command key code
    private static let rightCommandKeyCode: CGKeyCode = 54

    // MARK: - Public Methods

    /// Starts monitoring keyboard events.
    /// Requires Accessibility permissions.
    func start() {
        guard eventTap == nil else {
            NSLog("KeyboardMonitor: already started")
            return
        }

        NSLog("KeyboardMonitor: starting...")

        // Check if we have accessibility permissions first
        let trusted = AXIsProcessTrusted()
        NSLog("KeyboardMonitor: AXIsProcessTrusted = \(trusted)")

        if !trusted {
            NSLog("KeyboardMonitor: NOT TRUSTED - requesting permission (will retry once in 3s)")
            // Request permission with prompt
            let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
            let _ = AXIsProcessTrustedWithOptions(options)

            // Retry once after 3 seconds - if still not trusted, user needs to restart app
            DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) { [weak self] in
                if AXIsProcessTrusted() {
                    NSLog("KeyboardMonitor: Now trusted, starting monitor")
                    self?.start()
                } else {
                    NSLog("KeyboardMonitor: Still not trusted - please grant permission and restart app")
                }
            }
            return
        }

        // Events we want to monitor: flagsChanged for modifier keys
        let eventMask = (1 << CGEventType.flagsChanged.rawValue)
        NSLog("KeyboardMonitor: creating event tap with mask \(eventMask)")

        // Create event tap
        guard let tap = CGEvent.tapCreate(
            tap: .cgSessionEventTap,
            place: .headInsertEventTap,
            options: .defaultTap,
            eventsOfInterest: CGEventMask(eventMask),
            callback: { proxy, type, event, refcon in
                // Get reference to self
                guard let refcon = refcon else { return Unmanaged.passUnretained(event) }
                let monitor = Unmanaged<KeyboardMonitor>.fromOpaque(refcon).takeUnretainedValue()
                return monitor.handleEvent(proxy: proxy, type: type, event: event)
            },
            userInfo: Unmanaged.passUnretained(self).toOpaque()
        ) else {
            NSLog("KeyboardMonitor: FAILED to create event tap even though trusted=\(trusted)")
            promptForAccessibilityPermissions()
            return
        }

        NSLog("KeyboardMonitor: event tap created successfully")
        eventTap = tap

        // Create run loop source
        runLoopSource = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)

        // Add to run loop
        CFRunLoopAddSource(CFRunLoopGetCurrent(), runLoopSource, .commonModes)

        // Enable the tap
        CGEvent.tapEnable(tap: tap, enable: true)
        NSLog("KeyboardMonitor: tap enabled, listening for Right Command key")

        print("Keyboard monitor started")
    }

    /// Stops monitoring keyboard events.
    func stop() {
        if let tap = eventTap {
            CGEvent.tapEnable(tap: tap, enable: false)
        }

        if let source = runLoopSource {
            CFRunLoopRemoveSource(CFRunLoopGetCurrent(), source, .commonModes)
            runLoopSource = nil
        }

        eventTap = nil
        isRightCommandHeld = false

        print("Keyboard monitor stopped")
    }

    // MARK: - Private Methods

    private func handleEvent(
        proxy: CGEventTapProxy,
        type: CGEventType,
        event: CGEvent
    ) -> Unmanaged<CGEvent>? {

        // Handle tap being disabled (system can disable it under load)
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            if let tap = eventTap {
                CGEvent.tapEnable(tap: tap, enable: true)
            }
            return Unmanaged.passUnretained(event)
        }

        // We only care about flagsChanged events (modifier keys)
        guard type == .flagsChanged else {
            return Unmanaged.passUnretained(event)
        }

        let keyCode = event.getIntegerValueField(.keyboardEventKeycode)
        let flags = event.flags

        // Check if this is the Right Command key
        guard keyCode == Self.rightCommandKeyCode else {
            return Unmanaged.passUnretained(event)
        }

        // Determine if Right Command is now pressed or released
        let isCommandPressed = flags.contains(.maskCommand)

        if isCommandPressed && !isRightCommandHeld {
            // Right Command just pressed
            isRightCommandHeld = true
            DispatchQueue.main.async { [weak self] in
                self?.onKeyDown?()
            }
        } else if !isCommandPressed && isRightCommandHeld {
            // Right Command just released
            isRightCommandHeld = false
            DispatchQueue.main.async { [weak self] in
                self?.onKeyUp?()
            }
        }

        // Pass the event through (don't consume it)
        return Unmanaged.passUnretained(event)
    }

    private func promptForAccessibilityPermissions() {
        DispatchQueue.main.async {
            let alert = NSAlert()
            alert.messageText = "Accessibility Permission Required"
            alert.informativeText = "Dictation needs Accessibility permission to detect the Command key.\n\nPlease go to System Settings > Privacy & Security > Accessibility and enable Dictation."
            alert.alertStyle = .warning
            alert.addButton(withTitle: "Open System Settings")
            alert.addButton(withTitle: "Cancel")

            if alert.runModal() == .alertFirstButtonReturn {
                // Open Accessibility settings
                if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
                    NSWorkspace.shared.open(url)
                }
            }
        }
    }
}
