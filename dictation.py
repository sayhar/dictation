#!/usr/bin/env python3
"""
Push-to-Talk Dictation using Whisper
Hold Right Command key to record and transcribe speech
"""

import whisper
import sounddevice as sd
import numpy as np
import pyperclip
import threading
import tempfile
import wave
import os
import subprocess
import rumps
import logging
import sys
import fcntl
import atexit
import datetime
import queue
import time
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from Quartz import (
    CGEventMaskBit,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventFlagsChanged,
    CGEventTapCreate,
    kCGSessionEventTap,
    kCGHeadInsertEventTap,
    CGEventTapEnable,
    kCGEventTapOptionDefault,
    CFMachPortCreateRunLoopSource,
    CFRunLoopGetCurrent,
    CFRunLoopAddSource,
    kCFRunLoopCommonModes,
)
from Cocoa import NSEvent

# Setup logging
logging.basicConfig(
    filename=os.path.expanduser('~/Library/Logs/Dictation.log'),
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Single instance lock - ensure only one app instance runs at a time
LOCK_FILE = os.path.expanduser('~/Library/Application Support/Dictation.lock')
PREFERENCES_FILE = os.path.expanduser('~/Library/Application Support/Dictation/preferences.json')
lock_file_handle = None

def acquire_single_instance_lock():
    """Try to acquire a lock file to ensure single instance"""
    global lock_file_handle

    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)

    try:
        lock_file_handle = open(LOCK_FILE, 'w')
        fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file_handle.write(str(os.getpid()))
        lock_file_handle.flush()
        logging.info(f"Acquired single instance lock (PID: {os.getpid()})")
        # Register cleanup on exit
        atexit.register(release_single_instance_lock)
        return True
    except (IOError, OSError) as e:
        logging.error(f"Another instance is already running: {e}")
        # Close the file handle if we failed to acquire the lock
        if lock_file_handle:
            try:
                lock_file_handle.close()
            except:
                pass
        rumps.alert(
            title="Dictation Already Running",
            message="Another instance of Dictation is already running. Please quit the other instance first.",
            ok="OK"
        )
        return False

def release_single_instance_lock():
    """Release the single instance lock"""
    global lock_file_handle
    if lock_file_handle:
        try:
            fcntl.flock(lock_file_handle.fileno(), fcntl.LOCK_UN)
            lock_file_handle.close()
            os.unlink(LOCK_FILE)
            logging.info("Released single instance lock")
        except Exception as e:
            logging.warning(f"Failed to release lock: {e}")

def validate_model(model_name):
    """
    Validate model name against VALID_MODELS list.

    Returns:
        str: The validated model name, or 'small' if invalid
    """
    return model_name if model_name in VALID_MODELS else "small"

def load_preferences():
    """Load preferences from JSON file, return defaults if missing/corrupt"""
    defaults = {"model": "small"}

    try:
        if not os.path.exists(PREFERENCES_FILE):
            logging.info("No preferences file found, using defaults")
            return defaults

        with open(PREFERENCES_FILE, 'r') as f:
            prefs = json.load(f)

        # Validate model name
        if "model" in prefs:
            prefs["model"] = validate_model(prefs["model"])
        else:
            prefs["model"] = defaults["model"]

        logging.info(f"Loaded preferences: {prefs}")
        return prefs

    except (json.JSONDecodeError, IOError) as e:
        logging.warning(f"Failed to load preferences: {e}, using defaults")
        return defaults

def save_preferences(prefs_dict):
    """
    Save preferences atomically to avoid corruption.

    Uses atomic file operations: write to temp file, then rename.
    This prevents corruption if the app crashes during save.
    """
    temp_file = None
    try:
        # Create directory if needed
        os.makedirs(os.path.dirname(PREFERENCES_FILE), exist_ok=True)

        # Write to temp file first, then rename (atomic on macOS)
        temp_file = PREFERENCES_FILE + '.tmp'
        with open(temp_file, 'w') as f:
            json.dump(prefs_dict, f, indent=2)

        os.rename(temp_file, PREFERENCES_FILE)  # Atomic operation
        logging.info(f"Saved preferences: {prefs_dict}")

    except Exception as e:
        logging.error(f"Failed to save preferences: {e}")
        # Clean up temp file if it exists
        if temp_file and os.path.exists(temp_file):
            try:
                os.unlink(temp_file)
            except:
                pass

# Set ffmpeg path for bundled app (do this once at startup)
os.environ['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + os.environ.get('PATH', '')

# Configuration
SAMPLE_RATE = 16000
CHANNELS = 1
kVK_RightCommand = 0x36  # Virtual key code for Right Command
kCGEventFlagMaskCommandLeft = 0x0008  # Left Command key bit in event flags
TRANSCRIPTION_TIMEOUT = 120  # seconds - max time for transcription
TRANSCRIPT_LOG_THRESHOLD = 30  # seconds - log transcriptions longer than this
VALID_MODELS = ["tiny", "base", "small", "medium", "large"]  # Available Whisper models

# Global state (queue-based architecture)
command_queue = queue.Queue()  # Commands from event tap
recording_buffer = None  # None = not recording, list = currently recording
recording_lock = threading.Lock()  # Protects recording_buffer
model = None
audio_stream = None
right_command_pressed = False
typing_in_progress = False  # Flag to block Right Command during typing
current_model = "small"  # Default model
app_instance = None  # Reference to DictationApp instance for updating icon

# Thread pool executor for running transcription with timeout
# Use max_workers=2 to allow one timeout to run while a new transcription starts
transcription_executor = ThreadPoolExecutor(max_workers=2)

def is_command_physically_held():
    """
    Check if Right Command key is physically pressed RIGHT NOW.

    This queries the actual hardware state from the HID system, not our event queue.
    Returns True if Right Command is currently held, False otherwise.
    """
    try:
        from Quartz import CGEventSourceFlagsState, kCGEventSourceStateHIDSystemState, kCGEventFlagMaskCommand

        # Get current modifier flags from HID system
        flags = CGEventSourceFlagsState(kCGEventSourceStateHIDSystemState)

        # Check if any Command key is pressed
        if not (flags & kCGEventFlagMaskCommand):
            return False

        # Check if it's Right Command (not Left)
        # If Left Command flag is NOT set, then it must be Right Command
        try:
            from Quartz import kCGEventFlagMaskCommandLeft
            left_cmd = (flags & kCGEventFlagMaskCommandLeft) != 0
            return not left_cmd  # True if Right Command is pressed
        except ImportError:
            # Fallback if we can't distinguish - assume it's Right Command
            return True

    except Exception as e:
        logging.error(f"Error checking physical Command state: {e}")
        return False  # Assume not held on error

def load_model(model_name=None):
    """Load Whisper model"""
    global model, current_model
    if model_name:
        current_model = model_name
    logging.info(f"Loading Whisper model ({current_model})...")
    model = whisper.load_model(current_model)
    logging.info("Model loaded successfully")

def audio_callback(indata, frames, time, status):
    """
    Callback for audio recording (runs on sounddevice thread)

    This is called ~100 times/second when audio stream is active.
    Simply appends audio data to the recording buffer - no complex logic.
    """
    with recording_lock:
        if recording_buffer is not None:
            recording_buffer.append(indata.copy())

def state_manager():
    """
    Main state machine - runs on dedicated thread.

    Handles all state transitions in one place.
    Purely event-driven - 0% CPU when blocked on queue.get()

    Supports parallel chunk recording: User can press Command again
    while previous chunks are still transcribing. Chunks always type
    in the order they were recorded, even if transcription finishes
    out-of-order.
    """
    global recording_buffer

    # Recording state - track with simple flag, not complex state machine
    is_recording = False
    current_chunk_id = None  # ID of chunk currently being recorded

    # Sequencing: ensures chunks type in order
    next_chunk_to_record = 0  # Next chunk ID to assign when recording starts
    next_chunk_to_type = 0     # Next chunk ID that should be typed
    pending_chunks = {}        # {chunk_id: text} - completed chunks waiting to type

    def try_type_pending_chunks():
        """
        Try to type chunks in order. Returns True if any progress was made.
        Stops on first timeout (keeps remaining chunks queued).
        """
        nonlocal next_chunk_to_type
        made_progress = False

        while next_chunk_to_type in pending_chunks:
            chunk_text = pending_chunks[next_chunk_to_type]

            if chunk_text:
                success = type_text(chunk_text)
                if success:
                    # Typed successfully, remove from queue
                    made_progress = True
                    del pending_chunks[next_chunk_to_type]
                    next_chunk_to_type += 1
                else:
                    # Timeout - Command still held, stop trying
                    logging.info(f"Typing deferred at chunk {next_chunk_to_type} - will retry later")
                    if app_instance:
                        app_instance.title = "⏸️"
                    break
            else:
                # Empty chunk - skip and advance (this IS progress!)
                made_progress = True
                del pending_chunks[next_chunk_to_type]
                next_chunk_to_type += 1

        return made_progress

    logging.info("State manager started (parallel chunk recording enabled)")

    while True:
        try:
            # ALWAYS BLOCK - no timeouts, no polling!
            # This is 0% CPU whether idle, recording, or transcribing
            msg = command_queue.get()
            logging.debug(f"State manager received: {msg}")

            # Handle COMMAND_DOWN
            if msg == 'COMMAND_DOWN':
                # Always allow recording, even if transcribing previous chunks!
                # This enables natural chunking: press → release → press → release
                if not is_recording:
                    is_recording = True
                    current_chunk_id = next_chunk_to_record
                    next_chunk_to_record += 1

                    with recording_lock:
                        recording_buffer = []

                    if audio_stream and not audio_stream.active:
                        try:
                            audio_stream.start()
                            logging.info(f"Recording started (chunk {current_chunk_id})")
                            if app_instance:
                                app_instance.title = "🎤"
                        except Exception as e:
                            logging.error(f"Failed to start audio stream: {e}")
                            with recording_lock:
                                recording_buffer = None
                            is_recording = False
                    else:
                        # This shouldn't happen - stream should be inactive when starting new recording
                        logging.warning(f"Recording new chunk {current_chunk_id} but stream already active - unexpected state")

            # Handle COMMAND_UP
            elif msg == 'COMMAND_UP':
                if is_recording:
                    # Stop recording, start transcription
                    is_recording = False
                    chunk_id = current_chunk_id
                    current_chunk_id = None

                    # Stop audio stream and wait for it to actually stop
                    if audio_stream and audio_stream.active:
                        try:
                            audio_stream.stop()  # Blocks until stream is stopped
                            logging.info(f"Recording stopped (chunk {chunk_id})")
                        except Exception as e:
                            logging.error(f"Failed to stop audio stream: {e}")

                    # Wait for any in-flight callbacks to complete
                    # The callback might have been scheduled before stop() was called
                    # 50ms = 5 callback cycles at 100/sec - very safe
                    time.sleep(0.05)

                    # Now grab the recorded audio
                    with recording_lock:
                        recorded_audio = recording_buffer[:]
                        recording_buffer = None  # Stop recording

                    # Update icon to show transcribing
                    if app_instance:
                        app_instance.title = "💭"

                    # Spawn transcription thread
                    # IMPORTANT: Capture chunk_id in closure properly
                    def do_transcription(cid=chunk_id, audio=recorded_audio):
                        try:
                            result = transcribe_recorded_audio(audio)
                            command_queue.put(('CHUNK_DONE', cid, result))
                        except Exception as e:
                            logging.error(f"Transcription failed for chunk {cid}: {e}")
                            command_queue.put(('CHUNK_DONE', cid, ""))

                    threading.Thread(target=do_transcription, daemon=True).start()
                    logging.info(f"Transcription started for chunk {chunk_id}")

                elif pending_chunks and not is_recording:
                    # User released Command and we have pending chunks - retry typing them
                    logging.debug("COMMAND_UP with pending chunks - attempting to type")
                    if try_type_pending_chunks():
                        if app_instance:
                            app_instance.title = "🎤"
                        logging.info(f"Typed pending chunks up to {next_chunk_to_type - 1}")

            # Handle CHUNK_DONE: A transcription finished
            elif isinstance(msg, tuple) and msg[0] == 'CHUNK_DONE':
                chunk_id, text = msg[1], msg[2]

                # Store chunk (even if empty - needed for sequencing)
                pending_chunks[chunk_id] = text
                logging.info(f"Chunk {chunk_id} transcription done (text length: {len(text)})")

                # Type chunks in order if NOT actively recording
                # This is state-based (deterministic), not racy physical check
                if not is_recording:
                    if try_type_pending_chunks():
                        if app_instance:
                            app_instance.title = "🎤"
                        logging.info(f"Typed chunks up to {next_chunk_to_type - 1}")
                else:
                    # Currently recording - defer typing to avoid interruption
                    # Chunks will be typed when recording stops
                    if app_instance:
                        app_instance.title = "⏸️"  # Paused icon
                    logging.info(f"Chunk {chunk_id} queued (is_recording={is_recording})")

        except Exception as e:
            logging.error(f"State manager error: {e}", exc_info=True)
            # Reset recording state on errors but preserve pending chunks
            is_recording = False
            current_chunk_id = None

def transcribe_recorded_audio(audio_chunks):
    """
    Transcribe audio chunks (runs in background thread).

    This is the actual Whisper transcription with timeout handling.
    Posts result back to command_queue when done.
    """
    if len(audio_chunks) == 0:
        logging.warning("No audio data captured")
        return ""

    try:
        # Combine audio chunks
        audio = np.concatenate(audio_chunks, axis=0)
        audio = audio.flatten()
        duration_seconds = len(audio) / SAMPLE_RATE
        logging.debug(f"Audio combined: {duration_seconds:.1f}s")

        # Save to temporary file
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                temp_path = f.name

            with wave.open(temp_path, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes((audio * 32767).astype(np.int16).tobytes())

            # Calculate timeout
            timeout_seconds = max(TRANSCRIPTION_TIMEOUT, int(duration_seconds * 2))

            # Transcribe with timeout
            logging.info(f"Starting transcription (audio: {duration_seconds:.1f}s, timeout: {timeout_seconds}s)")
            future = transcription_executor.submit(lambda: model.transcribe(temp_path, language="en"))

            try:
                result = future.result(timeout=timeout_seconds)
                text = result["text"].strip()
                logging.info(f"Transcribed: '{text}'")

                # Log long transcriptions
                if duration_seconds > TRANSCRIPT_LOG_THRESHOLD and text:
                    transcript_log = os.path.expanduser('~/Library/Logs/Dictation_Transcripts.log')
                    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    with open(transcript_log, 'a') as f:
                        f.write(f"\n{'='*80}\n")
                        f.write(f"[{timestamp}] Duration: {duration_seconds:.1f}s\n")
                        f.write(f"{text}\n")

                return text

            except FuturesTimeoutError:
                logging.error(f"Transcription timed out after {timeout_seconds}s")
                rumps.notification(
                    title="Dictation",
                    subtitle="Transcription timed out",
                    message=f"Audio took too long to transcribe. Try a smaller/faster model."
                )
                future.cancel()
                return ""

        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    logging.warning(f"Failed to delete temp file: {e}")

    except Exception as e:
        logging.error(f"Transcription error: {e}")
        return ""

def type_text(text):
    """
    Type text using AppleScript keystroke.

    Waits for Command to be released before typing to prevent shortcuts.
    Sets typing_in_progress flag to block Right Command events during typing.

    Returns:
        True if text was typed successfully
        False if Command still held after timeout (text should stay queued)
    """
    global typing_in_progress

    if not text:
        return True  # Empty text = success

    # Poll-wait for Command to be released
    # This reduces (but doesn't eliminate) the race window for shortcuts.
    #
    # KNOWN LIMITATION (TOCTOU race):
    # - We check Command state, then start AppleScript subprocess
    # - AppleScript takes ~10-50ms to start and execute
    # - User can press Command during that window → shortcuts may fire
    # - Race window: ~20ms (much better than no check, but not atomic)
    # - Long-term fix: Migrate to CGEvents typing (no subprocess, atomic)
    max_wait_iterations = 20  # 200ms max wait (20 * 10ms)
    for i in range(max_wait_iterations):
        if not is_command_physically_held():
            break  # Command released, safe to type
        time.sleep(0.01)  # Wait 10ms
        if i == 0:
            logging.debug("Waiting for Command to be released before typing...")
    else:
        # Loop completed without break = timeout, Command still held
        logging.warning(f"Timeout waiting for Command release after {max_wait_iterations * 10}ms - deferring text")
        return False  # Don't type, keep text queued

    # Command was released, safe to type now
    typing_in_progress = True

    try:
        # Escape for AppleScript
        escaped_text = text.replace('\\', '\\\\').replace('"', '\\"')

        logging.info(f"Typing text: {len(text)} chars (Right Command blocked)")
        result = subprocess.run([
            'osascript', '-e',
            f'tell application "System Events" to keystroke "{escaped_text}"'
        ], capture_output=True, text=True)

        if result.returncode != 0:
            logging.error(f"Failed to type text: {result.stderr}")
            return False
        else:
            logging.info("Text typed successfully")
            return True
    finally:
        # Always clear flag, even if typing failed
        typing_in_progress = False
        logging.debug("Typing completed, Right Command unblocked")


def key_event_callback(proxy, event_type, event, refcon):
    """Callback for CGEvent tap - posts commands to queue and blocks Right Command during typing"""
    global right_command_pressed, typing_in_progress

    try:
        from Quartz import CGEventGetFlags, CGEventSetFlags, kCGEventFlagMaskCommand

        # Two-layer defense against Command shortcuts during typing:
        # 1. Strip flags from key events (handles Command already held BEFORE typing)
        # 2. Block flag change events (prevents NEW Command presses during typing)

        # Layer 1: Strip Command flag from key events during typing
        if typing_in_progress and event_type in (kCGEventKeyDown, kCGEventKeyUp):
            flags = CGEventGetFlags(event)
            if flags & kCGEventFlagMaskCommand:
                # Check if it's Right Command (not Left)
                left_cmd = (flags & kCGEventFlagMaskCommandLeft) != 0
                right_cmd = not left_cmd

                if right_cmd:
                    # Strip Command flag from the event
                    new_flags = flags & ~kCGEventFlagMaskCommand
                    CGEventSetFlags(event, new_flags)
                    logging.debug("Stripped Right Command flag from key event during typing")
                    return event  # Pass through with modified flags

        # Layer 2: Block Command flag changes during typing
        if event_type == kCGEventFlagsChanged:
            flags = CGEventGetFlags(event)
            command_pressed = (flags & kCGEventFlagMaskCommand) != 0
            left_cmd = command_pressed and (flags & kCGEventFlagMaskCommandLeft) != 0
            right_cmd = command_pressed and not left_cmd

            # Block Right Command during typing
            # Left Command is NOT blocked - provides safety valve (Cmd+Q still works)
            if typing_in_progress:
                if right_cmd:
                    # Block Command press during typing
                    logging.debug("Blocked Right Command press during typing")
                    return None  # Consume the event
                elif not command_pressed and right_command_pressed:
                    # Command was released during typing - consume but update state
                    logging.debug("Right Command released during typing (updating state)")
                    right_command_pressed = False
                    return None  # Consume without sending COMMAND_UP

            if right_cmd and not right_command_pressed:
                right_command_pressed = True
                command_queue.put('COMMAND_DOWN')
                return None  # Consume event

            elif not right_cmd and right_command_pressed:
                right_command_pressed = False
                command_queue.put('COMMAND_UP')
                return None  # Consume event

    except Exception as e:
        logging.error(f"Error in key_event_callback: {e}")

    return event  # Pass through other events

class DictationApp(rumps.App):
    def __init__(self):
        super(DictationApp, self).__init__("🎤", quit_button=None)

        # Load saved preferences
        prefs = load_preferences()
        saved_model = prefs.get("model", "small")

        # Update global current_model with saved preference
        global current_model
        current_model = saved_model

        # Create model selection submenu
        self.model_menu = {
            "tiny": rumps.MenuItem("Tiny (fastest, lowest accuracy)", callback=self.change_model),
            "base": rumps.MenuItem("Base (fast)", callback=self.change_model),
            "small": rumps.MenuItem("Small (balanced)", callback=self.change_model),
            "medium": rumps.MenuItem("Medium (slower, better)", callback=self.change_model),
            "large": rumps.MenuItem("Large (slowest, best)", callback=self.change_model),
        }

        # Mark saved model as selected
        if saved_model in self.model_menu:
            self.model_menu[saved_model].state = True
        else:
            # Fallback to small if invalid
            self.model_menu["small"].state = True

        self.menu = [
            rumps.MenuItem("Status: Loading...", callback=None),
            None,  # Separator
            rumps.MenuItem("Hotkey: Right Command (hold)", callback=None),
            None,
            ["Model", list(self.model_menu.values())],
            None,
            rumps.MenuItem("Open Transcription Log", callback=self.open_transcript_log),
            None,
            "Quit"
        ]

        # Keep reference to event tap so it doesn't get garbage collected
        self.event_tap = None
        self.audio_stream = None

        # Setup event tap first (on main thread)
        self.setup_event_tap()

        # Start loading in background
        threading.Thread(target=self.init_app, daemon=True).start()

    def change_model(self, sender):
        """Change the Whisper model"""
        # Note: Model switching is safe - the model is only used during transcription
        # and each transcription gets a reference to the model at the start

        # Uncheck all models
        for item in self.model_menu.values():
            item.state = False

        # Check the selected model
        sender.state = True

        # Extract model name from menu item title
        model_name = sender.title.split()[0].lower()

        logging.info(f"Switching to {model_name} model...")

        # Save preference
        save_preferences({"model": model_name})

        # Reload model in background
        def reload():
            load_model(model_name)
            logging.info(f"Switched to {model_name} model")

        threading.Thread(target=reload, daemon=True).start()

    def open_transcript_log(self, _):
        """Open the transcription log file in default text editor"""
        transcript_log = os.path.expanduser('~/Library/Logs/Dictation_Transcripts.log')

        # Create empty file if it doesn't exist
        if not os.path.exists(transcript_log):
            with open(transcript_log, 'w') as f:
                f.write(f"# Dictation Transcripts\n# Transcriptions longer than {TRANSCRIPT_LOG_THRESHOLD}s are logged here\n\n")

        # Open in default editor
        result = subprocess.run(['open', transcript_log], capture_output=True, text=True)
        if result.returncode != 0:
            logging.error(f"Failed to open transcript log: {result.stderr}")
            rumps.notification(
                title="Dictation",
                subtitle="Error opening log",
                message="Could not open transcript log file"
            )
        else:
            logging.info("Opened transcription log")

    def setup_event_tap(self):
        """Setup event tap on main thread (required for run loop)"""
        logging.info("Starting keyboard event tap on main thread...")

        # Create event tap for key down and key up events
        event_mask = (
            CGEventMaskBit(kCGEventKeyDown) |
            CGEventMaskBit(kCGEventKeyUp) |
            CGEventMaskBit(kCGEventFlagsChanged)
        )

        self.event_tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            event_mask,
            key_event_callback,
            None
        )

        if self.event_tap is None:
            logging.error("Failed to create event tap! Need accessibility permissions.")
        else:
            # Create a run loop source and add it to the current run loop
            from Quartz import kCFRunLoopDefaultMode
            run_loop_source = CFMachPortCreateRunLoopSource(None, self.event_tap, 0)
            CFRunLoopAddSource(CFRunLoopGetCurrent(), run_loop_source, kCFRunLoopDefaultMode)
            CGEventTapEnable(self.event_tap, True)
            logging.info("Keyboard event tap started successfully on main thread")

    def init_app(self):
        """Initialize the app (load model, start listeners)"""
        global audio_stream

        # Load model
        load_model()

        # Update status
        self.menu["Status: Loading..."].title = "Status: Ready"

        # Create audio stream but don't start until recording
        self.audio_stream = sd.InputStream(
            callback=audio_callback,
            channels=CHANNELS,
            samplerate=SAMPLE_RATE
        )
        audio_stream = self.audio_stream  # Keep global reference for callbacks
        logging.info("Audio stream created (will start on key press)")

        # Start state manager thread
        threading.Thread(target=state_manager, daemon=True).start()
        logging.info("State manager thread started")

    @rumps.clicked("Quit")
    def quit_app(self, _):
        """Quit the app"""
        logging.info("Quit requested")
        release_single_instance_lock()
        rumps.quit_application()

if __name__ == "__main__":
    # Ensure only one instance runs at a time
    if not acquire_single_instance_lock():
        sys.exit(1)

    # atexit will handle cleanup automatically
    app_instance = DictationApp()
    app_instance.run()
