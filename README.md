# Dictation App

A lightweight, local push-to-talk dictation app for macOS using OpenAI's Whisper model.

## Features

- 🎤 **Push-to-talk**: Hold Right Command key to record, release to transcribe
- 🔒 **100% Local**: All transcription happens on your Mac, no internet required
- 🚀 **Multiple Models**: Choose from tiny/base/small/medium/large models (speed vs accuracy)
- 📝 **Auto-type**: Types transcribed text directly (preserves your clipboard)
- 📋 **Long Transcript Log**: Automatically saves transcriptions >60 seconds to `~/Library/Logs/Dictation_Transcripts.log`
- 🎨 **Menu Bar App**: Runs quietly in the background with a clean menu bar interface
- ⚡ **Auto-start**: Can be configured to launch on login

## Installation

### Prerequisites
- macOS (tested on macOS 15+)
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/dictation-app.git
cd dictation-app
```

2. Install dependencies:
```bash
uv sync
```

3. Build the app:
```bash
python setup.py py2app
```

4. Copy to Applications:
```bash
cp -R dist/Dictation.app ~/Applications/
```

5. Grant permissions when prompted:
   - Accessibility (for keyboard monitoring)
   - Microphone (for audio recording)

6. Launch from Applications folder

## Usage

1. Click the 🎤 icon in the menu bar to access settings
2. Choose your preferred model from the Model submenu
3. Hold Right Command key and speak
4. Release to transcribe and auto-type

## Model Comparison

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| Tiny | ~40MB | Fastest | Lowest |
| Base | ~150MB | Fast | Good |
| Small | ~500MB | Balanced | Better |
| Medium | ~1.5GB | Slower | Very Good |
| Large | ~3GB | Slowest | Best |

Models are automatically downloaded to `~/.cache/whisper/` on first use.

## Technical Details

Built with:
- **Whisper**: OpenAI's speech recognition model
- **PyObjC**: Native macOS APIs for keyboard monitoring
- **rumps**: Menu bar app framework
- **sounddevice**: Audio recording
- **py2app**: macOS app bundling

### Why PyObjC instead of pynput?

Standard Python keyboard libraries (like pynput) don't work properly in bundled macOS apps due to accessibility permission issues. This app uses native PyObjC `CGEventTap` APIs which macOS properly recognizes and trusts.

## Files

- `dictation.py` - Main application code
- `setup.py` - py2app build configuration
- `create_icon.py` - Icon generation script
- `~/Library/Logs/Dictation.log` - Debug logs
- `~/Library/Logs/Dictation_Transcripts.log` - Long transcriptions (>60s)

## Auto-start on Login

System Settings → General → Login Items → Add Dictation.app

## Troubleshooting

**App not receiving keyboard events:**
- Remove Dictation from Accessibility permissions
- Quit the app completely
- Re-launch and grant permissions fresh

**Permissions show as "uv" or "Python":**
- This is normal when running via `uv run`
- Build with py2app for proper app attribution

**Event tap fails:**
- Ensure you've granted Accessibility permissions
- Try removing and re-adding the app to permissions
- Check logs: `tail -f ~/Library/Logs/Dictation.log`

## License

MIT
