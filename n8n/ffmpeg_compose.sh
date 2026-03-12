#!/bin/bash
# FFmpeg Video Composition Script for n8n
#
# Combines background video, TTS audio, background audio, and
# screenshot overlays into a final Reddit video.
#
# Usage:
#   ./ffmpeg_compose.sh \
#     --work-dir /tmp/reddit_video_job123 \
#     --width 1080 \
#     --height 1920 \
#     --opacity 0.9 \
#     --bg-audio-volume 0.15 \
#     --output /output/final.mp4

set -euo pipefail

# Defaults
WIDTH=1080
HEIGHT=1920
OPACITY=0.9
BG_AUDIO_VOLUME=0.15
OUTPUT="output.mp4"
WORK_DIR="."

while [[ $# -gt 0 ]]; do
  case $1 in
    --work-dir) WORK_DIR="$2"; shift 2;;
    --width) WIDTH="$2"; shift 2;;
    --height) HEIGHT="$2"; shift 2;;
    --opacity) OPACITY="$2"; shift 2;;
    --bg-audio-volume) BG_AUDIO_VOLUME="$2"; shift 2;;
    --output) OUTPUT="$2"; shift 2;;
    *) echo "Unknown option: $1"; exit 1;;
  esac
done

AUDIO_DIR="$WORK_DIR/audio"
IMG_DIR="$WORK_DIR/screenshots"
BG_VIDEO="$WORK_DIR/background.mp4"
BG_AUDIO="$WORK_DIR/background.mp3"
SCREENSHOT_WIDTH=$(( WIDTH * 45 / 100 ))

echo "=== Reddit Video Composition ==="
echo "Work dir: $WORK_DIR"
echo "Resolution: ${WIDTH}x${HEIGHT}"
echo "Opacity: $OPACITY"

# Step 1: Crop background video to target aspect ratio
echo "[1/5] Cropping background video..."
ffmpeg -y -hide_banner -loglevel warning \
  -i "$BG_VIDEO" \
  -vf "crop=ih*(${WIDTH}/${HEIGHT}):ih,scale=${WIDTH}:${HEIGHT}" \
  -an \
  -c:v libx264 -preset fast -crf 18 \
  -threads "$(nproc)" \
  "$WORK_DIR/background_cropped.mp4"

# Step 2: Concatenate all TTS audio files
echo "[2/5] Concatenating TTS audio..."
CONCAT_LIST="$WORK_DIR/audio_concat.txt"
> "$CONCAT_LIST"

# Title audio first
if [ -f "$AUDIO_DIR/title.mp3" ]; then
  echo "file '$AUDIO_DIR/title.mp3'" >> "$CONCAT_LIST"
fi

# Comment/story audio files in order
for mp3 in $(ls "$AUDIO_DIR"/[0-9]*.mp3 2>/dev/null | sort -V); do
  # Add silence between clips
  if [ -f "$AUDIO_DIR/silence.mp3" ]; then
    echo "file '$AUDIO_DIR/silence.mp3'" >> "$CONCAT_LIST"
  fi
  echo "file '$mp3'" >> "$CONCAT_LIST"
done

ffmpeg -y -hide_banner -loglevel warning \
  -f concat -safe 0 \
  -i "$CONCAT_LIST" \
  -c copy \
  "$WORK_DIR/tts_combined.mp3"

# Step 3: Mix TTS audio with background audio
echo "[3/5] Mixing audio tracks..."
if [ -f "$BG_AUDIO" ]; then
  ffmpeg -y -hide_banner -loglevel warning \
    -i "$WORK_DIR/tts_combined.mp3" \
    -i "$BG_AUDIO" \
    -filter_complex "[1:a]volume=${BG_AUDIO_VOLUME}[bg];[0:a][bg]amix=inputs=2:duration=first[out]" \
    -map "[out]" \
    -b:a 192k \
    "$WORK_DIR/mixed_audio.mp3"
else
  cp "$WORK_DIR/tts_combined.mp3" "$WORK_DIR/mixed_audio.mp3"
fi

# Step 4: Build overlay filter for screenshots
echo "[4/5] Building video overlays..."

# Read durations JSON (created by n8n workflow)
DURATIONS_FILE="$WORK_DIR/durations.json"

if [ ! -f "$DURATIONS_FILE" ]; then
  echo "Error: durations.json not found. Create it with audio durations."
  echo 'Expected format: [{"file": "title", "start": 0, "end": 3.5}, {"file": "0", "start": 3.5, "end": 8.2}]'
  exit 1
fi

# Build FFmpeg filter_complex for image overlays
INPUTS="-i $WORK_DIR/background_cropped.mp4 -i $WORK_DIR/mixed_audio.mp3"
FILTER=""
INPUT_IDX=2
OVERLAY_CHAIN="[0:v]"

# Parse durations.json and build overlay filters
while IFS= read -r line; do
  FILE=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['file'])")
  START=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['start'])")
  END=$(echo "$line" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['end'])")

  if [ "$FILE" = "title" ]; then
    IMG_PATH="$IMG_DIR/title.png"
  else
    IMG_PATH="$IMG_DIR/comment_${FILE}.png"
  fi

  if [ -f "$IMG_PATH" ]; then
    INPUTS="$INPUTS -i $IMG_PATH"
    FILTER="${FILTER}[${INPUT_IDX}:v]scale=${SCREENSHOT_WIDTH}:-1,colorchannelmixer=aa=${OPACITY}[img${INPUT_IDX}];"
    FILTER="${FILTER}${OVERLAY_CHAIN}[img${INPUT_IDX}]overlay=(main_w-overlay_w)/2:(main_h-overlay_h)/2:enable='between(t,${START},${END})'[v${INPUT_IDX}];"
    OVERLAY_CHAIN="[v${INPUT_IDX}]"
    INPUT_IDX=$((INPUT_IDX + 1))
  fi
done < <(python3 -c "
import json, sys
with open('$DURATIONS_FILE') as f:
    for item in json.load(f):
        print(json.dumps(item))
")

# Remove trailing semicolon
FILTER="${FILTER%;}[out_v]"
# Fix: rename last overlay output
FILTER=$(echo "$FILTER" | sed "s/\[v$((INPUT_IDX - 1))\];$/[out_v]/")

# Step 5: Render final video
echo "[5/5] Rendering final video..."
eval ffmpeg -y -hide_banner -loglevel warning \
  $INPUTS \
  -filter_complex "\"${FILTER}\"" \
  -map '"[out_v]"' -map '1:a' \
  -c:v libx264 -preset fast -crf 18 \
  -b:a 192k \
  -threads "$(nproc)" \
  -shortest \
  "\"$OUTPUT\""

echo "=== Done! Output: $OUTPUT ==="
echo "{\"output\": \"$OUTPUT\", \"status\": \"completed\"}"
