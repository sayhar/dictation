"""
Setup script for creating standalone Dictation.app
"""
from setuptools import setup

APP = ['dictation.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'alias': True,  # Use alias mode to avoid recursion issues
    'iconfile': 'icon.icns',
    'plist': {
        'CFBundleName': 'Dictation',
        'CFBundleDisplayName': 'Dictation',
        'CFBundleIdentifier': 'com.local.dictation',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,  # Run as background app (no dock icon)
        'NSMicrophoneUsageDescription': 'Dictation needs microphone access to record your speech.',
    },
    'packages': ['whisper', 'sounddevice', 'pyperclip', 'numpy', 'rumps', 'Quartz', 'Cocoa'],
    'includes': ['_sounddevice_data', 'sounddevice', 'cffi', 'rumps', 'Quartz', 'Cocoa'],
}

setup(
    name='Dictation',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
