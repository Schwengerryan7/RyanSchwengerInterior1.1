#!/usr/bin/env python3
"""
eval_floorplan.py — Quick local evaluation of a PLY scan.
Prints IoU and a summary without needing RunPod.
"""

import os, sys, json, argparse
import numpy as np

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--ply',      required=True)
    p.add_argument('--expected', default=None, help='Ground truth floor_plan.json')
    args = p.parse_args()

    # Try to import project modules
    repo_root = os.path.dirname(os.path.dirname(__file__))
    sys.path.insert(0, os.path.join(repo_root, 'gaussian-splat'))

    from handler_floorplan import _load_ply, _clean_pcd, _orient_z_up, _make_density_image

    print(f'[eval] Loading {args.ply}…')
    xyz, rgb = _load_ply(args.ply)
    xyz, rgb = _clean_pcd(xyz, rgb)
    xyz, rgb = _orient_z_up(xyz, rgb)
    print(f'[eval] {len(xyz):,} points after cleaning')

    density_img, mn, span = _make_density_image(xyz, None)
    if density_img is None:
        print('[eval] Too few wall/floor points — check point cloud quality')
        return

    # Save density image for inspection
    from PIL import Image
    from scipy.ndimage import gaussian_filter
    blurred = gaussian_filter(density_img, sigma=2.0)
    blurred = np.clip(blurred / (blurred.max() + 1e-8), 0, 1)
    arr     = (blurred * 255).astype(np.uint8)
    out_png = args.ply.replace('.ply', '_density.png')
    Image.fromarray(np.stack([arr,arr,arr], axis=2)).save(out_png)
    print(f'[eval] Density image saved → {out_png}')
    print(f'[eval] Spatial extent: {span[0]:.1f}m × {span[1]:.1f}m')

    wall_frac  = float((density_img > 0.1).mean())
    print(f'[eval] Wall coverage: {wall_frac*100:.1f}% of top-down image')

    if wall_frac < 0.05:
        print('[eval] WARNING: Very sparse point cloud — dense COLMAP recommended')
        print('[eval]          Run: python fp.py dense <video.mp4>')
    elif wall_frac < 0.15:
        print('[eval] Coverage moderate — results may be partial')
    else:
        print('[eval] Coverage looks good — should produce a solid floor plan')

    # If ground truth provided, compute simple IoU
    if args.expected and os.path.exists(args.expected):
        print(f'[eval] Comparing against {args.expected}…')
        # (Full IoU computation requires running the model — add later)
        print('[eval] Ground truth comparison requires running the full model.')
        print('[eval] Run: python fp.py train  to fine-tune, then re-evaluate.')


if __name__ == '__main__':
    main()
