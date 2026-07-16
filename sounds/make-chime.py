#!/usr/bin/env python3
"""make-chime.py: generate the cute little chime claude-beep plays.

Two quick rising notes with a soft sine body, a touch of second and third
harmonic for sparkle, and an exponential decay so it reads as a chirp rather
than a beep. Stdlib only. Re-run after tweaking NOTES to taste:

    python3 make-chime.py && pw-play claude-done.wav
"""
import math
import struct
import wave

RATE = 48000
# (frequency Hz, start seconds, length seconds, peak volume)
# E6 -> A6, a rising fourth: bright, friendly, resolves upward.
NOTES = [
    (1318.51, 0.000, 0.16, 0.55),
    (1760.00, 0.085, 0.22, 0.62),
]
# Harmonic, relative amplitude. A little 2nd/3rd makes it twinkle like a bell
# instead of sounding like a test tone.
PARTIALS = [(1, 1.0), (2, 0.22), (3, 0.07)]
LENGTH = 0.36


def sample(t):
    v = 0.0
    for freq, start, dur, peak in NOTES:
        if not (start <= t < start + dur):
            continue
        age = t - start
        # Quick attack keeps the transient crisp; exponential decay is the chirp.
        attack = min(1.0, age / 0.006)
        decay = math.exp(-age / (dur * 0.34))
        for mult, amp in PARTIALS:
            v += peak * attack * decay * amp * math.sin(
                2 * math.pi * freq * mult * age)
    return v


def main():
    frames = bytearray()
    n = int(RATE * LENGTH)
    for i in range(n):
        v = sample(i / RATE)
        # Gentle fade-out over the tail so it never clicks at the end.
        tail = min(1.0, (n - i) / (RATE * 0.03))
        s = max(-1.0, min(1.0, v * 0.4 * tail))
        frames += struct.pack('<hh', int(s * 32767), int(s * 32767))

    with wave.open('claude-done.wav', 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    print(f'wrote claude-done.wav ({len(frames)} bytes, {LENGTH}s)')


if __name__ == '__main__':
    main()
