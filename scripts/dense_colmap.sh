#!/usr/bin/env bash
# dense_colmap.sh — video → dense point cloud PLY
# Usage: bash dense_colmap.sh <video_file> <output_dir>
#
# Requires: colmap (brew install colmap  OR  apt install colmap)
# On RunPod: apt-get install -y colmap

set -e

VIDEO="$1"
OUTDIR="$2"

if [[ -z "$VIDEO" || -z "$OUTDIR" ]]; then
  echo "Usage: $0 <video> <output_dir>"
  exit 1
fi

mkdir -p "$OUTDIR/frames" "$OUTDIR/sparse" "$OUTDIR/dense"

echo "[dense] Extracting frames…"
ffmpeg -i "$VIDEO" -vf "fps=2,scale=960:720" -q:v 2 "$OUTDIR/frames/%04d.jpg" -y -loglevel warning
echo "[dense] $(ls "$OUTDIR/frames/" | wc -l) frames extracted"

echo "[dense] COLMAP feature extraction…"
colmap feature_extractor \
  --database_path "$OUTDIR/database.db" \
  --image_path "$OUTDIR/frames" \
  --ImageReader.single_camera 1 \
  --ImageReader.camera_model SIMPLE_RADIAL \
  --SiftExtraction.use_gpu 0

echo "[dense] COLMAP matching…"
colmap sequential_matcher \
  --database_path "$OUTDIR/database.db" \
  --SequentialMatching.overlap 10

echo "[dense] COLMAP sparse reconstruction…"
colmap mapper \
  --database_path "$OUTDIR/database.db" \
  --image_path "$OUTDIR/frames" \
  --output_path "$OUTDIR/sparse"

echo "[dense] Dense stereo (patch match)…"
colmap patch_match_stereo \
  --workspace_path "$OUTDIR/dense" \
  --workspace_format COLMAP \
  --PatchMatchStereo.geom_consistency true \
  --input_path "$OUTDIR/sparse/0"

echo "[dense] Stereo fusion → PLY…"
colmap stereo_fusion \
  --workspace_path "$OUTDIR/dense" \
  --workspace_format COLMAP \
  --input_type geometric \
  --output_path "$OUTDIR/cloud.ply"

echo "[dense] Done. Dense PLY: $OUTDIR/cloud.ply"
echo "[dense] Point count: $(python3 -c "from plyfile import PlyData; print(f'{len(PlyData.read(\"$OUTDIR/cloud.ply\")[\"vertex\"]):,}')" 2>/dev/null || echo "unknown")"
