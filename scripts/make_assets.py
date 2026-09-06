"""Generate deterministic tray icons and a gentle two-note chime, without dependencies."""
import math
from pathlib import Path
import struct
import wave

root = Path(__file__).resolve().parents[1] / "app"
(root / "icons").mkdir(exist_ok=True)
for name, color in {"running": (48, 164, 108), "attention": (231, 158, 40), "paused": (112, 124, 143)}.items():
    pixels = bytearray()
    size = 32
    for y in range(size - 1, -1, -1):
        for x in range(size):
            distance = ((x - 15.5) ** 2 + (y - 15.5) ** 2) ** .5
            r, g, b = color
            if abs(x - 15.5) < 2 and (8 <= y <= 18 or 22 <= y <= 24):
                r = g = b = 255
            pixels.extend((b, g, r, 255 if distance <= 14 else 0))
    bitmap = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(pixels), 0, 0, 0, 0) + pixels + bytes(4 * size)
    header = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(bitmap), 22)
    (root / "icons" / (name + ".ico")).write_bytes(header + bitmap)
rate = 22050
with wave.open(str(root / "chime.wav"), "wb") as sound:
    sound.setparams((1, 2, rate, 0, "NONE", "not compressed"))
    frames = bytearray()
    for sample in range(int(rate * .9)):
        t = sample / rate
        value = 0.0
        for start, frequency in ((0, 784), (.22, 1046.5)):
            if t >= start:
                age = t - start
                envelope = min(1, age / .015) * math.exp(-age * 7)
                value += .23 * envelope * math.sin(2 * math.pi * frequency * age)
        frames.extend(struct.pack("<h", int(32767 * value)))
    sound.writeframes(frames)
print("Generated three tray icons and chime.wav")

