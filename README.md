# Dictation App

A lightweight, local push-to-talk dictation app for macOS using OpenAI's Whisper model.

## Features

- 🎤 **Push-to-talk**: Hold Right Command key to record, release to transcribe
- 🔒 **100% Local**: All transcription happens on your Mac, no internet required
- 🚀 **Multiple Models**: Choose from tiny/base/small/medium/large models (speed vs accuracy)
- 💾 **Model Persistence**: Your model selection is remembered across app restarts
- 📝 **Auto-type**: Types transcribed text directly (preserves your clipboard)
- 📋 **Long Transcript Log**: Automatically saves transcriptions >30 seconds to `~/Library/Logs/Dictation_Transcripts.log` (access via menu)
- 🎨 **Menu Bar App**: Runs quietly in the background with a clean menu bar interface
- 💭 **Visual Feedback**: Icon changes to show transcription status (💭 thinking, 🎤 ready)
- ⏱️ **Timeout Protection**: Automatic timeout prevents hangs on problematic audio (note: timed-out transcriptions continue in background - see CHANGELOG)
- 🔄 **Auto-retry**: Failed transcriptions automatically retry up to 3 times
- 🛡️ **Single Instance**: Prevents conflicts from multiple app instances running simultaneously
- ⚡ **Auto-start**: Can be configured to launch on login

## Installation

### Prerequisites
- macOS 13.0+ (tested on macOS 15+)
- [Homebrew](https://brew.sh)
- **ffmpeg** (required for audio processing)

### Swift Version (Recommended)

The Swift version is faster, more native, and fully self-contained.

1. **Install dependencies**:
```bash
brew install ffmpeg
```

2. **Clone and build**:
```bash
git clone https://github.com/sayhar/dictation-app.git
cd dictation-app
git checkout swift-rewrite
./build-swift.sh
```

3. **Install the app**:
```bash
cp -R "dist/Swift Dictation.app" ~/Applications/
open ~/Applications/"Swift Dictation.app"
```

### Python Version (Legacy)

The original Python implementation.

**Prerequisites:**
- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager
- ffmpeg

1. **Install dependencies**:
```bash
brew install uv ffmpeg
```

2. **Clone and build**:
```bash
git clone https://github.com/sayhar/dictation-app.git
cd dictation-app
uv sync
uv run python setup.py py2app
```

3. **Install the app**:
```bash
cp -R dist/Dictation.app ~/Applications/
open ~/Applications/Dictation.app
```

### Post-Installation

**Grant permissions** when prompted:
- **Accessibility** (required for keyboard monitoring)
- **Microphone** (required for audio recording)

If the app doesn't request permissions automatically:
- Go to System Settings → Privacy & Security → Accessibility
- Click the "+" button and add the app
- Do the same for Microphone

**First run**: The app will download the selected Whisper model (~500MB for "small") on first use. This happens in the background and is cached to `~/.cache/huggingface/`.

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

### Swift Version
Built with:
- **mlx-whisper**: Metal-accelerated Whisper (30-40% faster on Apple Silicon)
- **AVFoundation**: Native audio recording
- **CoreGraphics**: Event tap for keyboard monitoring
- **AppKit**: Menu bar interface
- **ffmpeg**: Audio format handling (required dependency)

### Python Version
Built with:
- **openai-whisper**: OpenAI's speech recognition model
- **PyObjC**: Native macOS APIs for keyboard monitoring
- **rumps**: Menu bar app framework
- **sounddevice**: Audio recording
- **py2app**: macOS app bundling

### Why Native APIs?

Standard Python keyboard libraries (like pynput) don't work properly in bundled macOS apps due to accessibility permission issues. Both versions use native `CGEventTap` APIs which macOS properly recognizes and trusts.

## Files

- `dictation.py` - Main application code
- `setup.py` - py2app build configuration
- `create_icon.py` - Icon generation script
- `~/Library/Logs/Dictation.log` - Debug logs
- `~/Library/Logs/Dictation_Transcripts.log` - Long transcriptions (>30s)

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
