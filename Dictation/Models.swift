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

    /// MLX Whisper HuggingFace repo name for this model
    /// Uses English-only models (.en) for tiny/base/small/medium - faster & more accurate for English
    /// Large uses v3-turbo (no .en variant exists for large)
    var mlxRepo: String {
        switch self {
        case .tiny: return "mlx-community/whisper-tiny.en-mlx"
        case .base: return "mlx-community/whisper-base.en-mlx"
        case .small: return "mlx-community/whisper-small.en-mlx"
        case .medium: return "mlx-community/whisper-medium.en-mlx"
        case .large: return "mlx-community/whisper-large-v3-turbo"
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
