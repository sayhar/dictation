#!/usr/bin/env python3
"""Create a microphone icon for the Dictation app"""

from PIL import Image, ImageDraw
import os

# Create a 1024x1024 image (macOS will scale it)
size = 1024
img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# Colors - modern blue/purple gradient feel
mic_color = (100, 120, 255)  # Nice blue
background = (255, 255, 255, 0)  # Transparent

# Microphone body (rounded rectangle)
mic_width = 280
mic_height = 400
mic_x = (size - mic_width) // 2
mic_y = 180

# Draw microphone capsule
draw.rounded_rectangle(
    [mic_x, mic_y, mic_x + mic_width, mic_y + mic_height],
    radius=140,
    fill=mic_color,
    outline=None
)

# Microphone stand (vertical line down)
stand_width = 40
stand_x = (size - stand_width) // 2
stand_y = mic_y + mic_height
stand_height = 120

draw.rectangle(
    [stand_x, stand_y, stand_x + stand_width, stand_y + stand_height],
    fill=mic_color
)

# Base (horizontal line)
base_width = 220
base_height = 40
base_x = (size - base_width) // 2
base_y = stand_y + stand_height

draw.rounded_rectangle(
    [base_x, base_y, base_x + base_width, base_y + base_height],
    radius=20,
    fill=mic_color
)

# Save as PNG first
script_dir = os.path.dirname(os.path.abspath(__file__))
png_path = os.path.join(script_dir, "icon.png")
img.save(png_path, 'PNG')
print(f"Created {png_path}")

# Convert to ICNS using macOS sips
iconset_dir = os.path.join(script_dir, "icon.iconset")
os.makedirs(iconset_dir, exist_ok=True)

# Generate all required sizes for iconset
sizes = [16, 32, 64, 128, 256, 512, 1024]
for s in sizes:
    img_resized = img.resize((s, s), Image.Resampling.LANCZOS)
    img_resized.save(os.path.join(iconset_dir, f"icon_{s}x{s}.png"))
    if s <= 512:  # Also create @2x versions
        img_resized_2x = img.resize((s*2, s*2), Image.Resampling.LANCZOS)
        img_resized_2x.save(os.path.join(iconset_dir, f"icon_{s}x{s}@2x.png"))

print("Created iconset")
print(f"Run: iconutil -c icns {iconset_dir}")
