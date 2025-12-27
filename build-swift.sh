#!/bin/bash
# Build script for Swift Dictation app
# Creates a proper macOS app bundle from the Swift Package Manager build

set -e

echo "Building Swift Dictation app..."

# Build the Swift executable
swift build -c release

# Create app bundle structure
APP_NAME="Swift Dictation"
BUNDLE_DIR="dist/${APP_NAME}.app"
CONTENTS_DIR="${BUNDLE_DIR}/Contents"
MACOS_DIR="${CONTENTS_DIR}/MacOS"
RESOURCES_DIR="${CONTENTS_DIR}/Resources"

# Clean and create directories
rm -rf "${BUNDLE_DIR}"
mkdir -p "${MACOS_DIR}"
mkdir -p "${RESOURCES_DIR}"

# Copy executable
cp ".build/release/Dictation" "${MACOS_DIR}/${APP_NAME}"

# Copy Info.plist
cp "Dictation/Info.plist" "${CONTENTS_DIR}/Info.plist"

# Copy icon if exists
if [ -f "Swift_Dictation.icns" ]; then
    cp "Swift_Dictation.icns" "${RESOURCES_DIR}/AppIcon.icns"
    echo "Copied app icon"
fi

# Update executable name in Info.plist
sed -i '' "s/\$(EXECUTABLE_NAME)/${APP_NAME}/g" "${CONTENTS_DIR}/Info.plist"
sed -i '' "s/\$(PRODUCT_BUNDLE_IDENTIFIER)/com.dictation.swift/g" "${CONTENTS_DIR}/Info.plist"
sed -i '' "s/\$(PRODUCT_NAME)/${APP_NAME}/g" "${CONTENTS_DIR}/Info.plist"
sed -i '' "s/\$(MACOSX_DEPLOYMENT_TARGET)/13.0/g" "${CONTENTS_DIR}/Info.plist"

# Create PkgInfo
echo -n "APPL????" > "${CONTENTS_DIR}/PkgInfo"

# Bundle Python environment (minimal - only mlx-whisper dependencies)
echo "Bundling Python environment..."
PYTHON_BUNDLE="${RESOURCES_DIR}/python"
mkdir -p "${PYTHON_BUNDLE}/bin"
mkdir -p "${PYTHON_BUNDLE}/lib"

# Copy Python interpreter from uv's managed location
UV_PYTHON="$HOME/.local/share/uv/python/cpython-3.13.5-macos-aarch64-none"
if [ -d "${UV_PYTHON}" ]; then
    # Copy just the bin and lib directories we need
    cp -R "${UV_PYTHON}/bin" "${PYTHON_BUNDLE}/"
    cp -R "${UV_PYTHON}/lib" "${PYTHON_BUNDLE}/"
    echo "Copied Python 3.13 interpreter"
fi

# Install ONLY mlx-whisper and its dependencies to a clean location
echo "Installing mlx-whisper to bundle..."
uv pip install --target "${PYTHON_BUNDLE}/lib/python3.13/site-packages" \
    mlx-whisper \
    --quiet 2>&1 | grep -v "already satisfied" || true
echo "Bundled Python environment complete"

# Sign the app with entitlements for automation permission
echo "Signing app..."
codesign --force --deep --sign - --entitlements "Dictation.entitlements" "${BUNDLE_DIR}"

echo "Built: ${BUNDLE_DIR}"
echo ""
echo "To install and run:"
echo "  cp -R ${BUNDLE_DIR} ~/Applications/"
echo "  open ~/Applications/${APP_NAME}.app"
