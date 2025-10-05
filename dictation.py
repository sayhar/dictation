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

# Global state
is_recording = False
is_transcribing = False
state_lock = threading.Lock()  # Protects state transitions (is_recording, is_transcribing)
audio_lock = threading.Lock()  # Protects audio_data (separate to avoid callback contention)
audio_data = []
model = None
audio_stream = None
right_command_pressed = False
current_model = "small"  # Default model
app_instance = None  # Reference to DictationApp instance for updating icon

def load_model(model_name=None):
    """Load Whisper model"""
    global model, current_model
    if model_name:
        current_model = model_name
    logging.info(f"Loading Whisper model ({current_model})...")
    model = whisper.load_model(current_model)
    logging.info("Model loaded successfully")

def audio_callback(indata, frames, time, status):
    """Callback for audio recording"""
    global is_recording
    # Read recording flag (atomic read of bool is safe)
    # Use separate audio_lock to avoid contention with state transitions
    if is_recording:
        with audio_lock:
            audio_data.append(indata.copy())

# Thread pool executor for running transcription with timeout
# Use max_workers=2 to allow one timeout to run while a new transcription starts
# This prevents blocking the user if a transcription hangs
transcription_executor = ThreadPoolExecutor(max_workers=2)

def run_transcription(temp_path):
    """Run the actual Whisper transcription (called in executor)"""
    return model.transcribe(temp_path, language="en")

def transcribe_audio():
    """Transcribe recorded audio using Whisper"""
    global audio_data, is_transcribing, app_instance

    # NOTE: is_transcribing is already set to True by the caller (event tap callback)
    # This prevents the race condition where multiple threads could start simultaneously

    try:
        # Update icon to show transcribing state
        if app_instance:
            app_instance.title = "💭"  # Thinking emoji

        # Stop stream immediately to free up the recording slot
        # This must happen BEFORE any user can start a new recording
        # Check stream state under lock to avoid race with stream.start()
        with state_lock:
            should_stop = audio_stream and audio_stream.active

        if should_stop:
            try:
                audio_stream.abort()  # Use abort() not stop() - doesn't wait for pending buffers
                logging.info("Audio stream stopped")
            except Exception as e:
                logging.error(f"Failed to stop audio stream: {e}")
                # Continue with transcription - audio already captured

        # Copy audio data and clear for next recording (use audio_lock)
        with audio_lock:
            local_audio_data = audio_data[:]
            audio_data = []  # Clear for next recording

        logging.debug(f"transcribe_audio called, audio_data chunks: {len(local_audio_data)}")

        if len(local_audio_data) == 0:
            logging.warning("No audio data captured")
            return

        # Combine audio chunks
        audio = np.concatenate(local_audio_data, axis=0)
        audio = audio.flatten()
        logging.debug(f"Audio combined, shape: {audio.shape}")

        # Calculate duration
        duration_seconds = len(audio) / SAMPLE_RATE
        logging.debug(f"Audio duration: {duration_seconds:.1f} seconds")

        # Save to temporary file
        temp_path = None
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        # Write WAV file
        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit audio
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio * 32767).astype(np.int16).tobytes())

        logging.debug(f"Saved audio to: {temp_path}")

        # Calculate dynamic timeout: at least 120s, or 2x audio duration, whichever is longer
        # This allows long recordings to complete while catching quick hangs
        timeout_seconds = max(TRANSCRIPTION_TIMEOUT, int(duration_seconds * 2))

        # Transcribe with timeout using ThreadPoolExecutor
        logging.info(f"Starting transcription (audio: {duration_seconds:.1f}s, timeout: {timeout_seconds}s)...")
        future = transcription_executor.submit(run_transcription, temp_path)
        try:
            result = future.result(timeout=timeout_seconds)
            text = result["text"].strip()
            logging.info(f"Transcribed: '{text}'")

            # Log long transcriptions (>60 seconds) to a separate file
            if duration_seconds > 60 and text:
                transcript_log = os.path.expanduser('~/Library/Logs/Dictation_Transcripts.log')
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                with open(transcript_log, 'a') as f:
                    f.write(f"\n{'='*80}\n")
                    f.write(f"[{timestamp}] Duration: {duration_seconds:.1f}s\n")
                    f.write(f"{text}\n")
                logging.info(f"Long transcription ({duration_seconds:.1f}s) saved to transcript log")

            if text:
                # Type the text directly using AppleScript (preserves clipboard)
                # Escape quotes and backslashes for AppleScript
                escaped_text = text.replace('\\', '\\\\').replace('"', '\\"')
                paste_result = subprocess.run([
                    'osascript', '-e',
                    f'tell application "System Events" to keystroke "{escaped_text}"'
                ], capture_output=True, text=True)

                if paste_result.returncode != 0:
                    logging.error(f"Paste failed: {paste_result.stderr}")
                else:
                    logging.info("Text typed successfully")
            else:
                logging.warning("No text transcribed (empty result)")

        except FuturesTimeoutError:
            logging.error(f"Transcription timed out after {timeout_seconds}s")
            rumps.notification(
                title="Dictation",
                subtitle="Transcription timed out",
                message=f"Audio took too long to transcribe. Try a smaller/faster model."
            )
            # KNOWN LIMITATION: Thread leak on timeout
            # future.cancel() only works if the task hasn't started executing yet.
            # Once Whisper is running, the thread continues until completion (potentially 10+ min).
            # This can accumulate zombie threads if multiple timeouts occur.
            # Solution: Use ProcessPoolExecutor for true process termination (planned refactor).
            # For now: max_workers=2 prevents blocking, leaked threads eventually complete.
            was_cancelled = future.cancel()
            if not was_cancelled:
                logging.warning("Could not cancel running transcription thread - it will complete in background")
            else:
                logging.info("Transcription future cancelled successfully")
    except Exception as e:
        logging.error(f"Transcription failed: {e}")
    finally:
        # Clean up temp file
        if temp_path:
            try:
                os.unlink(temp_path)
            except Exception as e:
                logging.warning(f"Failed to delete temp file: {e}")

        # Stream is already stopped at start of function
        # Reset the transcription flag and restore icon
        with state_lock:
            is_transcribing = False
        if app_instance:
            app_instance.title = "🎤"  # Restore default icon
        logging.debug("Transcription completed, ready for next recording")

def key_event_callback(proxy, event_type, event, refcon):
    """Callback for CGEvent tap to monitor keyboard events"""
    global is_recording, is_transcribing, audio_data, right_command_pressed

    try:
        from Quartz import CGEventGetFlags, kCGEventFlagMaskCommand

        # For modifier keys, check the flags instead of keycode
        if event_type == kCGEventFlagsChanged:
            flags = CGEventGetFlags(event)
            command_pressed = (flags & kCGEventFlagMaskCommand) != 0
            # Left Command has flag 0x0008, Right Command does NOT have 0x0008
            left_cmd = command_pressed and (flags & 0x0008) != 0
            right_cmd = command_pressed and not left_cmd

            logging.debug(f"Flags changed: flags={hex(flags)}, command={command_pressed}, left={left_cmd}, right={right_cmd}")

            # Only respond to Right Command
            if right_cmd and not right_command_pressed:
                right_command_pressed = True

                # Check state and claim recording slot (minimal critical section)
                should_start = False
                with state_lock:
                    if not is_recording and not is_transcribing:
                        is_recording = True
                        should_start = True
                    elif is_transcribing:
                        logging.debug("Cannot start recording: transcription in progress")

                # Start stream outside lock to avoid blocking
                if should_start:
                    logging.info("Recording started (Command pressed)")
                    # Check stream state (protected implicitly - audio_stream only set during init)
                    if audio_stream and not audio_stream.active:
                        try:
                            audio_stream.start()
                            logging.info(f"Audio stream started, active={audio_stream.active}")
                        except Exception as e:
                            logging.error(f"Failed to start audio stream: {e}")
                            # Rollback on failure
                            with state_lock:
                                is_recording = False

                # Consume the Right Command key event (don't pass to system)
                return None
            elif not right_cmd and right_command_pressed:
                right_command_pressed = False

                # Check state and transition to transcription (minimal critical section)
                should_transcribe = False
                with state_lock:
                    if is_recording and not is_transcribing:
                        is_recording = False
                        is_transcribing = True
                        should_transcribe = True
                    elif is_transcribing:
                        logging.warning("Transcription already in progress, ignoring release")

                # Spawn transcription thread (will stop stream immediately)
                if should_transcribe:
                    logging.info("Recording stopped (Command released)")
                    threading.Thread(target=transcribe_audio, daemon=True).start()

                # Consume the Right Command release event
                return None
    except Exception as e:
        logging.error(f"Error in key_event_callback: {e}")

    # Pass through other events unmodified
    return event

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
        global is_transcribing

        # Check if transcription is in progress
        with state_lock:
            if is_transcribing:
                logging.warning("Cannot switch model while transcription is in progress")
                rumps.notification(
                    title="Dictation",
                    subtitle="Cannot switch model",
                    message="Please wait for current transcription to complete"
                )
                return

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
