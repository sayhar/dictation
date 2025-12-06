import Foundation

/// Available Whisper models for transcription.
/// Ordered from fastest/smallest to most accurate/largest.
enum WhisperModel: String, CaseIterable, Codable {
    case tiny = "tiny"
    case base = "base"
    case small = "small"
    case medium = "medium"
    case large = "large"

    /// Human-readable name for the menu
    var displayName: String {
        switch self {
        case .tiny: return "Tiny (fastest)"
        case .base: return "Base"
        case .small: return "Small"
        case .medium: return "Medium"
        case .large: return "Large (most accurate)"
        }
    }
}

/// Errors that can occur during transcription
enum TranscriptionError: Error, LocalizedError {
    case noAudioData
    case transcriptionFailed(String)
    case timeout
    case modelNotLoaded

    var errorDescription: String? {
        switch self {
        case .noAudioData:
            return "No audio data to transcribe"
        case .transcriptionFailed(let message):
            return "Transcription failed: \(message)"
        case .timeout:
            return "Transcription timed out"
        case .modelNotLoaded:
            return "Whisper model not loaded"
        }
    }
}

/// Errors related to audio recording
enum AudioError: Error, LocalizedError {
    case microphoneAccessDenied
    case recordingFailed(String)
    case noInputDevice

    var errorDescription: String? {
        switch self {
        case .microphoneAccessDenied:
            return "Microphone access denied"
        case .recordingFailed(let message):
            return "Recording failed: \(message)"
        case .noInputDevice:
            return "No audio input device found"
        }
    }
}
