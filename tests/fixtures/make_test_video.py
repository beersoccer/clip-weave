"""Run once to create tests/fixtures/test_5s.mp4 (5-second black video)."""
import subprocess
from pathlib import Path

output = Path(__file__).parent / "test_5s.mp4"
if not output.exists():
    subprocess.run([
        "ffmpeg", "-f", "lavfi", "-i", "color=c=black:s=720x1280:d=5",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
        "-t", "5", "-c:v", "libx264", "-c:a", "aac",
        str(output), "-y"
    ], check=True)
    print(f"Created {output}")
else:
    print(f"Already exists: {output}")
