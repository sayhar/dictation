import Foundation

/// Ensures only one instance of the app runs at a time.
/// Uses a file-based lock in /tmp, matching the Python implementation.
enum SingleInstanceLock {

    private static let lockPath = "/tmp/dictation_app.lock"
    private static var lockFileHandle: FileHandle?

    /// Attempts to acquire the single-instance lock.
    /// Returns true if successful, false if another instance is running.
    static func acquire() -> Bool {
        let fileManager = FileManager.default

        // Create lock file if it doesn't exist
        if !fileManager.fileExists(atPath: lockPath) {
            fileManager.createFile(atPath: lockPath, contents: nil)
        }

        // Try to open and lock the file
        guard let handle = FileHandle(forWritingAtPath: lockPath) else {
            return false
        }

        // Try to get an exclusive lock (non-blocking)
        let fd = handle.fileDescriptor
        let result = flock(fd, LOCK_EX | LOCK_NB)

        if result == 0 {
            // Lock acquired successfully
            lockFileHandle = handle

            // Write our PID to the file
            let pidData = "\(ProcessInfo.processInfo.processIdentifier)\n".data(using: .utf8)!
            handle.truncateFile(atOffset: 0)
            handle.write(pidData)

            return true
        } else {
            // Lock failed - another instance is running
            try? handle.close()
            return false
        }
    }

    /// Releases the lock when the app terminates.
    static func release() {
        if let handle = lockFileHandle {
            let fd = handle.fileDescriptor
            flock(fd, LOCK_UN)
            try? handle.close()
            lockFileHandle = nil
        }

        // Clean up the lock file
        try? FileManager.default.removeItem(atPath: lockPath)
    }
}
