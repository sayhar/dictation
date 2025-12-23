import Foundation

/// Handles transcription of audio data using Whisper.
/// This implementation calls out to the Python whisper CLI for transcription,
/// which allows us to leverage the existing Python infrastructure.
///
/// Future improvement: Integrate whisper.cpp directly for native performance.
class TranscriptionService {

    // MARK: - Properties

    /// Maximum retries for failed transcriptions
    private let maxRetries = 3

    /// Base timeout in seconds (minimum)
    private let baseTimeout: TimeInterval = 120

    /// Log file path for long transcriptions
    private let logPath: URL

    // MARK: - Initialization

    init() {
        logPath = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Dictation_Transcripts.log")
    }

    // MARK: - Public Methods

    /// Transcribes audio data using the specified Whisper model.
    /// - Parameters:
    ///   - audioData: WAV audio data to transcribe
    ///   - model: Whisper model to use
    /// - Returns: Transcribed text
    func transcribe(audioData: Data, model: WhisperModel) async throws -> String {
        // Calculate audio duration for timeout
        let audioDuration = calculateAudioDuration(from: audioData)
        // Short recordings get 15s timeout, longer ones get 2x duration or 120s minimum
        let timeout: TimeInterval = audioDuration < 5 ? 15 : max(baseTimeout, audioDuration * 2)

        NSLog("TranscriptionService: Transcribing %.1fs of audio with %@ model (timeout: %.0fs)", audioDuration, model.rawValue, timeout)
        NSLog("TranscriptionService: Audio data size: %d bytes", audioData.count)

        // Write audio to temp file
        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString)
            .appendingPathExtension("wav")

        try audioData.write(to: tempURL)

        defer {
            try? FileManager.default.removeItem(at: tempURL)
        }

        // Try transcription with retries
        var lastError: Error?
        for attempt in 1...maxRetries {
            do {
                let text = try await runWhisperTranscription(
                    audioPath: tempURL.path,
                    model: model,
                    timeout: timeout
                )

                // Log long transcriptions
                if audioDuration > 30 {
                    logTranscription(text: text, duration: audioDuration, model: model)
                }

                return text.trimmingCharacters(in: .whitespacesAndNewlines)

            } catch {
                lastError = error
                print("Transcription attempt \(attempt) failed: \(error)")

                if attempt < maxRetries {
                    // Wait before retry
                    try? await Task.sleep(nanoseconds: 1_000_000_000)  // 1 second
                }
            }
        }

        throw lastError ?? TranscriptionError.transcriptionFailed("Unknown error")
    }

    // MARK: - Private Methods

    private func runWhisperTranscription(
        audioPath: String,
        model: WhisperModel,
        timeout: TimeInterval
    ) async throws -> String {
        // Use Python whisper via command line
        // This leverages the existing Python environment and model cache
        let process = Process()
        let outputPipe = Pipe()
        let errorPipe = Pipe()

        // Use the system Python with mlx-whisper installed
        // We invoke it through a shell to ensure proper PATH
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        // Build the Python script as a separate string to avoid multi-line escaping issues
        // MLX Whisper is 30-40% faster on Apple Silicon (uses Metal GPU)
        let pythonScript = """
            import mlx_whisper
            result = mlx_whisper.transcribe('\(audioPath)', path_or_hf_repo='\(model.mlxRepo)')
            print(result['text'])
            """

        // Use bundled Python from app Resources
        guard let resourcePath = Bundle.main.resourcePath else {
            throw TranscriptionError.transcriptionFailed("Cannot find app resources")
        }
        let pythonPath = "\(resourcePath)/python/bin/python3"
        let escapedScript = pythonScript.replacingOccurrences(of: "'", with: "'\\''")

        process.arguments = ["-c", "\"\(pythonPath)\" -c '\(escapedScript)'"]

        // Set environment to include ffmpeg path (needed by mlx_whisper for audio loading)
        var environment = ProcessInfo.processInfo.environment
        let ffmpegPaths = "/opt/homebrew/bin:/usr/local/bin"
        if let existingPath = environment["PATH"] {
            environment["PATH"] = "\(ffmpegPaths):\(existingPath)"
        } else {
            environment["PATH"] = ffmpegPaths
        }
        process.environment = environment

        process.standardOutput = outputPipe
        process.standardError = errorPipe

        return try await withCheckedThrowingContinuation { continuation in
            var hasResumed = false
            let resumeLock = NSLock()

            func safeResume(with result: Result<String, Error>) {
                resumeLock.lock()
                defer { resumeLock.unlock() }
                guard !hasResumed else { return }
                hasResumed = true
                switch result {
                case .success(let value):
                    continuation.resume(returning: value)
                case .failure(let error):
                    continuation.resume(throwing: error)
                }
            }

            // Create timeout task - use SIGKILL to force kill
            let timeoutTask = DispatchWorkItem {
                if process.isRunning {
                    NSLog("TranscriptionService: TIMEOUT - killing process")
                    kill(process.processIdentifier, SIGKILL)
                }
            }
            DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: timeoutTask)

            process.terminationHandler = { proc in
                timeoutTask.cancel()

                let outputData = outputPipe.fileHandleForReading.readDataToEndOfFile()
                let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()

                let output = String(data: outputData, encoding: .utf8) ?? ""
                let errorOutput = String(data: errorData, encoding: .utf8) ?? ""

                if proc.terminationStatus == 0 {
                    safeResume(with: .success(output))
                } else if proc.terminationReason == .uncaughtSignal {
                    safeResume(with: .failure(TranscriptionError.timeout))
                } else {
                    safeResume(with: .failure(TranscriptionError.transcriptionFailed(errorOutput)))
                }
            }

            do {
                try process.run()
            } catch {
                timeoutTask.cancel()
                safeResume(with: .failure(error))
            }
        }
    }

    private func calculateAudioDuration(from wavData: Data) -> TimeInterval {
        // WAV header: sample rate at bytes 24-27, data size at bytes 40-43
        guard wavData.count > 44 else { return 0 }

        let sampleRate = wavData.withUnsafeBytes { ptr -> UInt32 in
            ptr.load(fromByteOffset: 24, as: UInt32.self).littleEndian
        }

        let dataSize = wavData.withUnsafeBytes { ptr -> UInt32 in
            ptr.load(fromByteOffset: 40, as: UInt32.self).littleEndian
        }

        // 16-bit mono = 2 bytes per sample
        let sampleCount = dataSize / 2
        return TimeInterval(sampleCount) / TimeInterval(sampleRate)
    }

    private func logTranscription(text: String, duration: TimeInterval, model: WhisperModel) {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"

        let entry = """
        [\(formatter.string(from: Date()))] Model: \(model.rawValue), Duration: \(String(format: "%.1f", duration))s
        \(text)

        ---

        """

        if FileManager.default.fileExists(atPath: logPath.path) {
            if let handle = try? FileHandle(forWritingTo: logPath) {
                handle.seekToEndOfFile()
                handle.write(entry.data(using: .utf8)!)
                try? handle.close()
            }
        } else {
            try? entry.write(to: logPath, atomically: true, encoding: .utf8)
        }
    }
}
