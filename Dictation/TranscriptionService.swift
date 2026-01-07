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

    /// Warmup completion tracking
    private var isPythonWarmedUp = false
    private var warmupCompletionHandlers: [(Bool) -> Void] = []
    private let warmupLock = NSLock()

    /// Callback for warmup status updates (called on main thread)
    var onWarmupStatusChange: ((Bool) -> Void)?

    // MARK: - Initialization

    init() {
        logPath = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Logs/Dictation_Transcripts.log")

        // Pre-warm Python on startup (background thread)
        Task.detached(priority: .utility) {
            await self.prewarmPython()
        }
    }

    /// Pre-warms Python interpreter by importing mlx_whisper.
    /// This eliminates cold-start delay on first transcription.
    private func prewarmPython() async {
        guard let resourcePath = Bundle.main.resourcePath else {
            notifyWarmupComplete(success: false)
            return
        }
        let pythonPath = "\(resourcePath)/python/bin/python3"

        let process = Process()
        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = ["-c", "import mlx_whisper; print('ready')"]

        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe

        do {
            NSLog("TranscriptionService: Pre-warming Python (importing mlx_whisper)...")
            let start = Date()
            try process.run()
            process.waitUntilExit()
            let elapsed = Date().timeIntervalSince(start)

            let success = process.terminationStatus == 0
            NSLog("TranscriptionService: Python pre-warm \(success ? "completed" : "failed") in %.1fs", elapsed)
            notifyWarmupComplete(success: success)
        } catch {
            NSLog("TranscriptionService: Python pre-warm failed: \(error)")
            notifyWarmupComplete(success: false)
        }
    }

    /// Notifies waiting tasks that warmup is complete
    private func notifyWarmupComplete(success: Bool) {
        warmupLock.lock()
        isPythonWarmedUp = success
        let handlers = warmupCompletionHandlers
        warmupCompletionHandlers.removeAll()
        warmupLock.unlock()

        // Notify completion handlers
        for handler in handlers {
            handler(success)
        }

        // Notify status change callback on main thread
        if let callback = onWarmupStatusChange {
            DispatchQueue.main.async {
                callback(success)
            }
        }
    }

    /// Waits for Python warmup to complete before proceeding
    private func waitForWarmup() async throws {
        warmupLock.lock()
        let alreadyWarmed = isPythonWarmedUp
        warmupLock.unlock()

        if alreadyWarmed {
            return // Already warmed up, proceed immediately
        }

        NSLog("TranscriptionService: Waiting for Python pre-warm to complete...")

        // Wait for warmup completion
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            warmupLock.lock()
            if isPythonWarmedUp {
                // Completed while we were acquiring lock
                warmupLock.unlock()
                continuation.resume()
            } else {
                // Still warming up, add handler
                warmupCompletionHandlers.append { success in
                    if success {
                        continuation.resume()
                    } else {
                        continuation.resume(throwing: TranscriptionError.modelNotLoaded)
                    }
                }
                warmupLock.unlock()
            }
        }
    }

    // MARK: - Public Methods

    /// Transcribes audio data using the specified Whisper model.
    /// - Parameters:
    ///   - audioData: WAV audio data to transcribe
    ///   - model: Whisper model to use
    /// - Returns: Transcribed text
    func transcribe(audioData: Data, model: WhisperModel) async throws -> String {
        // Wait for Python warmup to complete before transcribing
        // This prevents resource contention on first transcription
        try await waitForWarmup()

        // Calculate audio duration for timeout
        let audioDuration = calculateAudioDuration(from: audioData)
        // Short recordings get 30s timeout (accounts for Python cold start), longer ones get 2x duration or 120s minimum
        let timeout: TimeInterval = audioDuration < 5 ? 30 : max(baseTimeout, audioDuration * 2)

        NSLog("TranscriptionService: Transcribing %.1fs of audio with %@ model (timeout: %.0fs)", audioDuration, model.rawValue, timeout)
        NSLog("TranscriptionService: Audio data size: %d bytes", audioData.count)

        // Extract raw PCM data from WAV (skip 44-byte header)
        let rawPCM = audioData.subdata(in: 44..<audioData.count)

        // Try transcription with retries
        var lastError: Error?
        for attempt in 1...maxRetries {
            do {
                let text = try await runWhisperTranscription(
                    audioData: rawPCM,
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
        audioData: Data,
        model: WhisperModel,
        timeout: TimeInterval
    ) async throws -> String {
        // No ffmpeg needed! We pass raw PCM data directly to Python

        let process = Process()
        let inputPipe = Pipe()
        let outputPipe = Pipe()
        let errorPipe = Pipe()

        // Use bundled Python from app Resources
        guard let resourcePath = Bundle.main.resourcePath else {
            throw TranscriptionError.transcriptionFailed("Cannot find app resources")
        }
        let pythonPath = "\(resourcePath)/python/bin/python3"

        // Python script that reads raw PCM from stdin and transcribes
        // No ffmpeg subprocess - direct numpy → mlx-whisper
        let pythonScript = """
import sys
import numpy as np
import mlx_whisper

# Read raw PCM data from stdin (16-bit little-endian)
raw_data = sys.stdin.buffer.read()
# Convert to numpy float32 array normalized to [-1, 1]
audio = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
# Transcribe directly (no ffmpeg!)
result = mlx_whisper.transcribe(audio, path_or_hf_repo='\(model.mlxRepo)')
print(result['text'])
"""

        process.executableURL = URL(fileURLWithPath: pythonPath)
        process.arguments = ["-c", pythonScript]
        process.standardInput = inputPipe
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
                // Capture PID before checking (prevents TOCTOU race)
                let pid = process.processIdentifier
                guard pid > 0 && process.isRunning else { return }

                NSLog("TranscriptionService: TIMEOUT - killing PID \(pid)")
                kill(pid, SIGKILL)
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

                // Write raw PCM data to stdin, then close
                inputPipe.fileHandleForWriting.write(audioData)
                try? inputPipe.fileHandleForWriting.close()
            } catch {
                // Clean up pipes to prevent file descriptor leak
                try? inputPipe.fileHandleForWriting.close()
                try? outputPipe.fileHandleForReading.closeFile()
                try? errorPipe.fileHandleForReading.closeFile()

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
