import AVFoundation
import Accelerate

/// Records audio from the microphone and provides WAV data for transcription.
/// Uses AVAudioEngine for modern, efficient audio capture.
class AudioRecorder {

    // MARK: - Properties

    /// Audio engine for capturing audio
    private let audioEngine = AVAudioEngine()

    /// Buffer to accumulate recorded audio samples
    private var audioBuffer: [Float] = []

    /// Lock for thread-safe buffer access
    private let bufferLock = NSLock()

    /// Whether we're currently recording
    private var isRecording = false

    /// Sample rate for recording (Whisper expects 16kHz)
    private let sampleRate: Double = 16000

    // MARK: - Public Methods

    /// Starts recording audio from the microphone.
    func startRecording() {
        guard !isRecording else { return }

        // Check microphone permission - must be pre-authorized
        // (We request permission at app startup, not during recording)
        guard AVCaptureDevice.authorizationStatus(for: .audio) == .authorized else {
            NSLog("AudioRecorder: Microphone not authorized, cannot record")
            return
        }

        // Clear previous recording
        bufferLock.lock()
        audioBuffer.removeAll()
        bufferLock.unlock()

        // Configure audio session
        let inputNode = audioEngine.inputNode
        let inputFormat = inputNode.inputFormat(forBus: 0)

        // Create format for our desired sample rate (16kHz mono)
        guard let outputFormat = AVAudioFormat(
            commonFormat: .pcmFormatFloat32,
            sampleRate: sampleRate,
            channels: 1,
            interleaved: false
        ) else {
            print("Failed to create output format")
            return
        }

        // Install tap to capture audio
        // We need to convert from input format to 16kHz mono
        guard let converter = AVAudioConverter(from: inputFormat, to: outputFormat) else {
            print("Failed to create audio converter")
            return
        }

        inputNode.installTap(onBus: 0, bufferSize: 4096, format: inputFormat) { [weak self] buffer, time in
            self?.processAudioBuffer(buffer, converter: converter, outputFormat: outputFormat)
        }

        // Start the engine
        do {
            try audioEngine.start()
            isRecording = true
            print("Audio recording started")
        } catch {
            print("Failed to start audio engine: \(error)")
        }
    }

    /// Stops recording and returns the audio data as WAV.
    /// Returns nil if no audio was captured.
    func stopRecording() -> Data? {
        guard isRecording else { return nil }

        // Always clear flag, even if stop/removeTap throws
        defer { isRecording = false }

        // Stop the engine and remove tap
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)

        // Get the recorded samples
        bufferLock.lock()
        let samples = audioBuffer
        bufferLock.unlock()

        guard !samples.isEmpty else {
            print("No audio samples captured")
            return nil
        }

        print("Captured \(samples.count) samples (\(Double(samples.count) / sampleRate) seconds)")

        // Convert to WAV format
        return createWAVData(from: samples)
    }

    // MARK: - Private Methods

    private func processAudioBuffer(
        _ buffer: AVAudioPCMBuffer,
        converter: AVAudioConverter,
        outputFormat: AVAudioFormat
    ) {
        // Calculate output buffer size
        let ratio = outputFormat.sampleRate / buffer.format.sampleRate
        let outputFrameCapacity = AVAudioFrameCount(Double(buffer.frameLength) * ratio)

        guard let outputBuffer = AVAudioPCMBuffer(
            pcmFormat: outputFormat,
            frameCapacity: outputFrameCapacity
        ) else { return }

        // Convert the audio
        var error: NSError?
        let status = converter.convert(to: outputBuffer, error: &error) { inNumPackets, outStatus in
            outStatus.pointee = .haveData
            return buffer
        }

        guard status != .error, error == nil else {
            print("Audio conversion error: \(error?.localizedDescription ?? "unknown")")
            return
        }

        // Extract samples and add to buffer
        guard let channelData = outputBuffer.floatChannelData?[0] else { return }
        let frameLength = Int(outputBuffer.frameLength)

        bufferLock.lock()
        for i in 0..<frameLength {
            audioBuffer.append(channelData[i])
        }
        bufferLock.unlock()
    }

    /// Creates a WAV file from float samples (16kHz, mono, 16-bit PCM).
    private func createWAVData(from samples: [Float]) -> Data {
        var data = Data()

        let sampleRate: UInt32 = 16000
        let channels: UInt16 = 1
        let bitsPerSample: UInt16 = 16
        let byteRate = sampleRate * UInt32(channels) * UInt32(bitsPerSample / 8)
        let blockAlign = channels * (bitsPerSample / 8)
        let dataSize = UInt32(samples.count * 2)  // 16-bit = 2 bytes per sample
        let fileSize = 36 + dataSize

        // RIFF header
        data.append(contentsOf: "RIFF".utf8)
        data.append(contentsOf: withUnsafeBytes(of: fileSize.littleEndian) { Array($0) })
        data.append(contentsOf: "WAVE".utf8)

        // fmt chunk
        data.append(contentsOf: "fmt ".utf8)
        data.append(contentsOf: withUnsafeBytes(of: UInt32(16).littleEndian) { Array($0) })  // chunk size
        data.append(contentsOf: withUnsafeBytes(of: UInt16(1).littleEndian) { Array($0) })   // PCM format
        data.append(contentsOf: withUnsafeBytes(of: channels.littleEndian) { Array($0) })
        data.append(contentsOf: withUnsafeBytes(of: sampleRate.littleEndian) { Array($0) })
        data.append(contentsOf: withUnsafeBytes(of: byteRate.littleEndian) { Array($0) })
        data.append(contentsOf: withUnsafeBytes(of: blockAlign.littleEndian) { Array($0) })
        data.append(contentsOf: withUnsafeBytes(of: bitsPerSample.littleEndian) { Array($0) })

        // data chunk
        data.append(contentsOf: "data".utf8)
        data.append(contentsOf: withUnsafeBytes(of: dataSize.littleEndian) { Array($0) })

        // Convert float samples to 16-bit PCM
        for sample in samples {
            // Clamp to [-1, 1] and convert to Int16
            let clamped = max(-1.0, min(1.0, sample))
            let int16Value = Int16(clamped * 32767.0)
            data.append(contentsOf: withUnsafeBytes(of: int16Value.littleEndian) { Array($0) })
        }

        return data
    }
}
