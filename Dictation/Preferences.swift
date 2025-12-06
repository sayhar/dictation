import Foundation

/// Manages user preferences with persistence to disk.
/// Preferences are stored in ~/Library/Application Support/Dictation/preferences.json
class Preferences {

    // MARK: - Singleton

    static let shared = Preferences()

    // MARK: - Properties

    /// The currently selected Whisper model
    var selectedModel: WhisperModel {
        didSet {
            save()
        }
    }

    // MARK: - Private

    private let preferencesURL: URL

    private struct PreferencesData: Codable {
        var selectedModel: WhisperModel
    }

    // MARK: - Initialization

    private init() {
        // Setup preferences directory
        let appSupport = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Dictation")

        // Create directory if needed
        try? FileManager.default.createDirectory(
            at: appSupport,
            withIntermediateDirectories: true
        )

        preferencesURL = appSupport.appendingPathComponent("preferences.json")

        // Load existing preferences or use defaults
        if let data = try? Data(contentsOf: preferencesURL),
           let prefs = try? JSONDecoder().decode(PreferencesData.self, from: data) {
            selectedModel = prefs.selectedModel
        } else {
            selectedModel = .base  // Default model
        }
    }

    // MARK: - Persistence

    private func save() {
        let data = PreferencesData(selectedModel: selectedModel)

        do {
            let encoded = try JSONEncoder().encode(data)
            try encoded.write(to: preferencesURL)
        } catch {
            print("Failed to save preferences: \(error)")
        }
    }
}
