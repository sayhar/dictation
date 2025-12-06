import Cocoa
import AVFoundation

/// Main application delegate for the Dictation menu bar app.
/// This is a "background" app (LSUIElement) that lives in the menu bar only.
@main
class AppDelegate: NSObject, NSApplicationDelegate {

    // Entry point - @main requires this to actually run the app
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.run()
    }

    // MARK: - Properties

    /// The status bar item (menu bar icon)
    private var statusItem: NSStatusItem!

    /// Menu shown when clicking the status bar icon
    private var statusMenu: NSMenu!

    /// Manages keyboard event monitoring (Right Command key)
    private let keyboardMonitor = KeyboardMonitor()

    /// Manages audio recording
    private let audioRecorder = AudioRecorder()

    /// Handles Whisper transcription
    private let transcriptionService = TranscriptionService()

    /// Handles typing transcribed text
    private let textInjector = TextInjector()

    /// User preferences
    private let preferences = Preferences.shared

    /// Current recording state
    private var isRecording = false

    /// When recording started (for minimum duration check)
    private var recordingStartTime: Date?

    // MARK: - Application Lifecycle

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSLog("AppDelegate: applicationDidFinishLaunching called")

        // Check for single instance
        guard SingleInstanceLock.acquire() else {
            NSLog("AppDelegate: another instance running, exiting")
            showAlreadyRunningAlert()
            NSApp.terminate(nil)
            return
        }

        NSLog("AppDelegate: setting up status item")
        setupStatusItem()
        NSLog("AppDelegate: requesting microphone permission")
        requestMicrophonePermission()
        NSLog("AppDelegate: setting up keyboard monitor")
        setupKeyboardMonitor()

        NSLog("AppDelegate: startup complete")
        print("Dictation app started successfully")
    }

    func applicationWillTerminate(_ notification: Notification) {
        SingleInstanceLock.release()
        keyboardMonitor.stop()
    }

    // MARK: - Setup

    private func setupStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)

        if let button = statusItem.button {
            // Use a different icon to distinguish from Python version
            // 🎙️ (studio microphone) vs 🎤 (hand microphone)
            button.title = "🎙️"
        }

        buildMenu()
    }

    private func buildMenu() {
        statusMenu = NSMenu()

        // Model selection submenu
        let modelMenuItem = NSMenuItem(title: "Model", action: nil, keyEquivalent: "")
        let modelSubmenu = NSMenu()

        for model in WhisperModel.allCases {
            let item = NSMenuItem(
                title: model.displayName,
                action: #selector(selectModel(_:)),
                keyEquivalent: ""
            )
            item.representedObject = model
            item.state = (model == preferences.selectedModel) ? .on : .off
            modelSubmenu.addItem(item)
        }

        modelMenuItem.submenu = modelSubmenu
        statusMenu.addItem(modelMenuItem)

        statusMenu.addItem(NSMenuItem.separator())

        // Open transcript log
        statusMenu.addItem(NSMenuItem(
            title: "Open Transcript Log",
            action: #selector(openTranscriptLog),
            keyEquivalent: ""
        ))

        statusMenu.addItem(NSMenuItem.separator())

        // Quit
        statusMenu.addItem(NSMenuItem(
            title: "Quit",
            action: #selector(quitApp),
            keyEquivalent: "q"
        ))

        statusItem.menu = statusMenu
    }

    private func setupKeyboardMonitor() {
        keyboardMonitor.onKeyDown = { [weak self] in
            self?.startRecording()
        }

        keyboardMonitor.onKeyUp = { [weak self] in
            self?.stopRecordingAndTranscribe()
        }

        keyboardMonitor.start()
    }

    // MARK: - Recording Flow

    private func startRecording() {
        NSLog("AppDelegate: startRecording called, isRecording=\(isRecording)")
        guard !isRecording else {
            NSLog("AppDelegate: already recording, ignoring")
            return
        }
        isRecording = true

        DispatchQueue.main.async {
            self.statusItem.button?.title = "🔴"
        }

        recordingStartTime = Date()
        audioRecorder.startRecording()
        NSLog("AppDelegate: recording started")
    }

    private func stopRecordingAndTranscribe() {
        NSLog("AppDelegate: stopRecordingAndTranscribe called, isRecording=\(isRecording)")
        guard isRecording else {
            NSLog("AppDelegate: not recording, ignoring")
            return
        }
        isRecording = false

        // Check wall-clock duration FIRST - before anything else
        let minDurationSeconds = 0.5
        if let startTime = recordingStartTime {
            let elapsed = Date().timeIntervalSince(startTime)
            NSLog("AppDelegate: Recording duration: %.2fs", elapsed)
            if elapsed < minDurationSeconds {
                NSLog("AppDelegate: Recording too short (%.2fs < %.2fs), discarding", elapsed, minDurationSeconds)
                _ = audioRecorder.stopRecording()  // Stop but discard
                resetIcon()
                return
            }
        }

        DispatchQueue.main.async {
            self.statusItem.button?.title = "💭"
        }

        guard let audioData = audioRecorder.stopRecording() else {
            NSLog("AppDelegate: No audio data captured")
            resetIcon()
            return
        }

        NSLog("AppDelegate: Recording stopped, transcribing \(audioData.count) bytes...")

        // Transcribe in background
        Task {
            do {
                let text = try await transcriptionService.transcribe(
                    audioData: audioData,
                    model: preferences.selectedModel
                )

                if !text.isEmpty {
                    await MainActor.run {
                        textInjector.typeText(text)
                    }
                }
            } catch {
                print("Transcription error: \(error)")
            }

            await MainActor.run {
                self.resetIcon()
            }
        }
    }

    private func resetIcon() {
        statusItem.button?.title = "🎙️"
    }

    // MARK: - Menu Actions

    @objc private func selectModel(_ sender: NSMenuItem) {
        guard let model = sender.representedObject as? WhisperModel else { return }

        preferences.selectedModel = model

        // Update checkmarks
        if let modelSubmenu = sender.menu {
            for item in modelSubmenu.items {
                item.state = (item.representedObject as? WhisperModel == model) ? .on : .off
            }
        }

        print("Model changed to: \(model.rawValue)")
    }

    @objc private func openTranscriptLog() {
        let logPath = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Dictation_Transcripts.log")

        if FileManager.default.fileExists(atPath: logPath.path) {
            NSWorkspace.shared.open(logPath)
        } else {
            let alert = NSAlert()
            alert.messageText = "No Transcript Log"
            alert.informativeText = "The transcript log will be created after your first long recording (>30 seconds)."
            alert.runModal()
        }
    }

    @objc private func quitApp() {
        NSApp.terminate(nil)
    }

    // MARK: - Helpers

    private func showAlreadyRunningAlert() {
        let alert = NSAlert()
        alert.messageText = "Dictation Already Running"
        alert.informativeText = "Another instance of Dictation is already running."
        alert.alertStyle = .warning
        alert.runModal()
    }

    private func requestMicrophonePermission() {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            NSLog("AppDelegate: Microphone already authorized")
        case .notDetermined:
            NSLog("AppDelegate: Requesting microphone permission")
            AVCaptureDevice.requestAccess(for: .audio) { granted in
                NSLog("AppDelegate: Microphone permission \(granted ? "granted" : "denied")")
            }
        case .denied, .restricted:
            NSLog("AppDelegate: Microphone permission denied/restricted")
        @unknown default:
            break
        }
    }
}
