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

# Set ffmpeg path for bundled app (do this once at startup)
os.environ['PATH'] = '/opt/homebrew/bin:/usr/local/bin:' + os.environ.get('PATH', '')

# Configuration
SAMPLE_RATE = 16000
CHANNELS = 1
kVK_RightCommand = 0x36  # Virtual key code for Right Command

# Global state
is_recording = False
is_transcribing = False
state_lock = threading.Lock()  # Protects all state transitions (replaces transcription_lock and stream_lock)
audio_data = []
model = None
audio_stream = None
right_command_pressed = False
current_model = "small"  # Default model

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
    if is_recording:
        audio_data.append(indata.copy())

def transcribe_audio():
    """Transcribe recorded audio using Whisper"""
    global audio_data, is_transcribing

    # NOTE: is_transcribing is already set to True by the caller (event tap callback)
    # This prevents the race condition where multiple threads could start simultaneously

    # Copy audio data and clear for next recording (minimal critical section)
    with state_lock:
        local_audio_data = audio_data[:]
        audio_data = []  # Clear for next recording

    logging.debug(f"transcribe_audio called, audio_data chunks: {len(local_audio_data)}")

    # Stop stream immediately after capturing data (outside lock to avoid blocking)
    if audio_stream and audio_stream.active:
        try:
            audio_stream.stop()
            logging.info("Audio stream stopped")
        except Exception as e:
            logging.error(f"Failed to stop audio stream: {e}")

    if len(local_audio_data) == 0:
        logging.warning("No audio data captured")
        with state_lock:
            is_transcribing = False
        return

    try:
        # Combine audio chunks
        audio = np.concatenate(local_audio_data, axis=0)
        audio = audio.flatten()
        logging.debug(f"Audio combined, shape: {audio.shape}")

        # Calculate duration
        duration_seconds = len(audio) / SAMPLE_RATE
        logging.debug(f"Audio duration: {duration_seconds:.1f} seconds")

        # Save to temporary file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            temp_path = f.name

        # Write WAV file
        with wave.open(temp_path, 'wb') as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # 16-bit audio
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio * 32767).astype(np.int16).tobytes())

        logging.debug(f"Saved audio to: {temp_path}")

        # Transcribe
        logging.info("Starting transcription...")
        result = model.transcribe(temp_path, language="en")
        text = result["text"].strip()
        logging.info(f"Transcribed: '{text}'")

        # Log long transcriptions (>60 seconds) to a separate file
        if duration_seconds > 60 and text:
            transcript_log = os.path.expanduser('~/Library/Logs/Dictation_Transcripts.log')
            import datetime
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

        # Clean up temp file
        try:
            os.unlink(temp_path)
        except Exception as e:
            logging.warning(f"Failed to delete temp file: {e}")

    except Exception as e:
        logging.error(f"Transcription failed: {e}")
    finally:
        # Stream is already stopped at line 91 (right after data capture)
        # Just reset the transcription flag
        with state_lock:
            is_transcribing = False
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
                    if audio_stream and not audio_stream.active:
                        try:
                            audio_stream.start()
                            logging.info(f"Audio stream started, active={audio_stream.active}")
                        except Exception as e:
                            logging.error(f"Failed to start audio stream: {e}")
                            # Rollback on failure
                            with state_lock:
                                is_recording = False
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

                # Spawn transcription thread outside lock
                if should_transcribe:
                    logging.info("Recording stopped (Command released)")
                    threading.Thread(target=transcribe_audio, daemon=True).start()
    except Exception as e:
        logging.error(f"Error in key_event_callback: {e}")

    # Return the event unmodified
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
        # Just call rumps.quit_application directly - no cleanup
        # The OS will handle resource cleanup
        rumps.quit_application()

if __name__ == "__main__":
    DictationApp().run()
