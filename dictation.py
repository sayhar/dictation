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

# Set ffmpeg path for bundled app (do this once at startup)
os.environ['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + os.environ.get('PATH', '')

# Configuration
SAMPLE_RATE = 16000
CHANNELS = 1
kVK_RightCommand = 0x36  # Virtual key code for Right Command
TRANSCRIPTION_TIMEOUT = 120  # seconds - max time for transcription

# Global state (queue-based architecture)
command_queue = queue.Queue()  # Commands from event tap
recording_buffer = None  # None = not recording, list = currently recording
recording_lock = threading.Lock()  # Protects recording_buffer
model = None
audio_stream = None
right_command_pressed = False
current_model = "small"  # Default model
app_instance = None  # Reference to DictationApp instance for updating icon

# Thread pool executor for running transcription with timeout
# Use max_workers=2 to allow one timeout to run while a new transcription starts
transcription_executor = ThreadPoolExecutor(max_workers=2)

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
    """
    global recording_buffer  # Declare at function start
    state = 'IDLE'  # States: IDLE, RECORDING, TRANSCRIBING
    pending_text = None  # Text waiting for Command release
    command_held = False  # Is Right Command currently pressed?

    logging.info("State manager started")

    while True:
        try:
            # ALWAYS BLOCK - no timeouts, no polling!
            # This is 0% CPU whether idle, recording, or transcribing
            msg = command_queue.get()

            logging.debug(f"State manager: state={state}, msg={msg}, command_held={command_held}")

            # Handle COMMAND_DOWN
            if msg == 'COMMAND_DOWN':
                command_held = True

                if state == 'IDLE':
                    # Start recording
                    state = 'RECORDING'
                    with recording_lock:
                        recording_buffer = []

                    if audio_stream and not audio_stream.active:
                        try:
                            audio_stream.start()
                            logging.info("Recording started")
                            if app_instance:
                                app_instance.title = "🎤"
                        except Exception as e:
                            logging.error(f"Failed to start audio stream: {e}")
                            with recording_lock:
                                recording_buffer = None
                            state = 'IDLE'

                elif state == 'TRANSCRIBING':
                    # User pressed Command while transcribing - ignore for now
                    logging.debug("Command pressed during transcription - ignoring")

            # Handle COMMAND_UP
            elif msg == 'COMMAND_UP':
                command_held = False

                if state == 'RECORDING':
                    # Stop recording, start transcription
                    state = 'TRANSCRIBING'

                    # Stop audio stream and wait for it to actually stop
                    if audio_stream and audio_stream.active:
                        try:
                            audio_stream.stop()  # Blocks until stream is stopped
                            logging.info("Recording stopped")
                        except Exception as e:
                            logging.error(f"Failed to stop audio stream: {e}")

                    # Wait for any in-flight callbacks to complete
                    # The callback might have been scheduled before stop() was called
                    # 50ms = 5 callback cycles at 100/sec - very safe
                    import time
                    time.sleep(0.05)

                    # Now grab the recorded audio
                    with recording_lock:
                        recorded_audio = recording_buffer[:]
                        recording_buffer = None  # Stop recording

                    # Update icon
                    if app_instance:
                        app_instance.title = "💭"

                    # Spawn transcription thread
                    def do_transcription():
                        try:
                            result = transcribe_recorded_audio(recorded_audio)
                            command_queue.put(('TRANSCRIPTION_DONE', result))
                        except Exception as e:
                            logging.error(f"Transcription failed: {e}")
                            command_queue.put(('TRANSCRIPTION_DONE', ""))

                    threading.Thread(target=do_transcription, daemon=True).start()
                    logging.info("Transcription started")

                # If we have pending text, type it now
                if pending_text:
                    type_text(pending_text)
                    pending_text = None
                    if app_instance:
                        app_instance.title = "🎤"
                    logging.info("Typed pending text after Command release")

            # Handle TRANSCRIPTION_DONE
            elif isinstance(msg, tuple) and msg[0] == 'TRANSCRIPTION_DONE':
                text = msg[1]

                if command_held:
                    # User is still holding Command - queue the text
                    pending_text = text
                    if app_instance:
                        app_instance.title = "⏸️"  # Paused icon
                    logging.info(f"Transcription done, but Command held - text queued (length: {len(text)})")
                else:
                    # Safe to type immediately
                    type_text(text)
                    if app_instance:
                        app_instance.title = "🎤"
                    logging.info("Transcription done, text typed")

                state = 'IDLE'

        except Exception as e:
            logging.error(f"State manager error: {e}", exc_info=True)
            # Reset state to IDLE on errors
            state = 'IDLE'
            pending_text = None

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
                if duration_seconds > 60 and text:
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

    CRITICAL: This should only be called when Command is NOT held.
    The state manager ensures this by checking command_held before calling.
    """
    if not text:
        return

    # Escape for AppleScript
    escaped_text = text.replace('\\', '\\\\').replace('"', '\\"')

    logging.info(f"Typing text: {len(text)} chars")
    result = subprocess.run([
        'osascript', '-e',
        f'tell application "System Events" to keystroke "{escaped_text}"'
    ], capture_output=True, text=True)

    if result.returncode != 0:
        logging.error(f"Failed to type text: {result.stderr}")
    else:
        logging.info("Text typed successfully")


def key_event_callback(proxy, event_type, event, refcon):
    """Callback for CGEvent tap - just posts commands to queue"""
    global right_command_pressed

    try:
        from Quartz import CGEventGetFlags, kCGEventFlagMaskCommand

        if event_type == kCGEventFlagsChanged:
            flags = CGEventGetFlags(event)
            command_pressed = (flags & kCGEventFlagMaskCommand) != 0
            left_cmd = command_pressed and (flags & 0x0008) != 0
            right_cmd = command_pressed and not left_cmd

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

        # Create model selection submenu
        self.model_menu = {
            "tiny": rumps.MenuItem("Tiny (fastest, lowest accuracy)", callback=self.change_model),
            "base": rumps.MenuItem("Base (fast)", callback=self.change_model),
            "small": rumps.MenuItem("Small (balanced)", callback=self.change_model),
            "medium": rumps.MenuItem("Medium (slower, better)", callback=self.change_model),
            "large": rumps.MenuItem("Large (slowest, best)", callback=self.change_model),
        }

        # Mark current model
        self.model_menu["small"].state = True

        self.menu = [
            rumps.MenuItem("Status: Loading...", callback=None),
            None,  # Separator
            rumps.MenuItem("Hotkey: Right Command (hold)", callback=None),
            None,
            ["Model", list(self.model_menu.values())],
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

        # Reload model in background
        def reload():
            load_model(model_name)
            logging.info(f"Switched to {model_name} model")

        threading.Thread(target=reload, daemon=True).start()

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
