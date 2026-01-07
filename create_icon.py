#!/usr/bin/env python3
"""Extract the 🎙️ emoji and use it as the app icon"""

import os
import subprocess

# Create a simple approach: render the emoji using macOS built-in tools
script_dir = os.path.dirname(os.path.abspath(__file__))
iconset_dir = os.path.join(script_dir, "icon.iconset")
os.makedirs(iconset_dir, exist_ok=True)

# Use macOS's built-in emoji rendering via Swift
swift_code = '''
import Cocoa
import Foundation

let emoji = "🎙️"
let sizes = [16, 32, 64, 128, 256, 512, 1024]

for size in sizes {
    let image = NSImage(size: NSSize(width: size, height: size))
    image.lockFocus()

    // Draw white background (will be made transparent later)
    NSColor.clear.setFill()
    NSRect(x: 0, y: 0, width: CGFloat(size), height: CGFloat(size)).fill()

    // Draw emoji centered
    let attributes: [NSAttributedString.Key: Any] = [
        .font: NSFont.systemFont(ofSize: CGFloat(size) * 0.8),
    ]
    let string = NSAttributedString(string: emoji, attributes: attributes)
    let stringSize = string.size()
    let x = (CGFloat(size) - stringSize.width) / 2
    let y = (CGFloat(size) - stringSize.height) / 2
    string.draw(at: NSPoint(x: x, y: y))

    image.unlockFocus()

    // Save as PNG
    if let tiffData = image.tiffRepresentation,
       let bitmapImage = NSBitmapImageRep(data: tiffData),
       let pngData = bitmapImage.representation(using: .png, properties: [:]) {
        let path = "icon.iconset/icon_\\(size)x\\(size).png"
        try? pngData.write(to: URL(fileURLWithPath: path))

        // Also create @2x versions for smaller sizes
        if size <= 512 {
            let size2x = size * 2
            let image2x = NSImage(size: NSSize(width: size2x, height: size2x))
            image2x.lockFocus()
            NSColor.clear.setFill()
            NSRect(x: 0, y: 0, width: CGFloat(size2x), height: CGFloat(size2x)).fill()
            let attributes2x: [NSAttributedString.Key: Any] = [
                .font: NSFont.systemFont(ofSize: CGFloat(size2x) * 0.8),
            ]
            let string2x = NSAttributedString(string: emoji, attributes: attributes2x)
            let stringSize2x = string2x.size()
            let x2x = (CGFloat(size2x) - stringSize2x.width) / 2
            let y2x = (CGFloat(size2x) - stringSize2x.height) / 2
            string2x.draw(at: NSPoint(x: x2x, y: y2x))
            image2x.unlockFocus()

            if let tiffData2x = image2x.tiffRepresentation,
               let bitmapImage2x = NSBitmapImageRep(data: tiffData2x),
               let pngData2x = bitmapImage2x.representation(using: .png, properties: [:]) {
                let path2x = "icon.iconset/icon_\\(size)x\\(size)@2x.png"
                try? pngData2x.write(to: URL(fileURLWithPath: path2x))
            }
        }
    }
}

print("✓ Created emoji iconset")
'''

# Write Swift script to temp file
swift_file = "/tmp/create_emoji_icon.swift"
with open(swift_file, "w") as f:
    f.write(swift_code)

# Run Swift script
print("Rendering 🎙️ emoji at multiple sizes...")
result = subprocess.run(
    ["swift", swift_file],
    cwd=script_dir,
    capture_output=True,
    text=True
)

if result.returncode == 0:
    print(result.stdout)

    # Also create the 1024px version as icon.png for preview
    subprocess.run([
        "cp",
        "icon.iconset/icon_1024x1024.png",
        "icon.png"
    ], cwd=script_dir)

    print(f"\nNext steps:")
    print(f"  iconutil -c icns icon.iconset")
    print(f"  mv icon.icns Swift_Dictation.icns")
    print(f"  ./build-swift.sh")
else:
    print(f"Error: {result.stderr}")
