#!/usr/bin/env python3
"""
fp.py — Floor Plan CLI
======================
One-command orchestration for the full training/eval/deploy loop.

Usage:
  python fp.py train              # spin up RunPod pod, train, download model
  python fp.py eval scan.ply      # evaluate a scan with current model
  python fp.py dense video.mp4    # dense COLMAP reconstruction → PLY
  python fp.py prep               # preprocess all scans in data/scans/ → training data
  python fp.py deploy             # build + push Docker image
  python fp.py status             # show active RunPod pods

All RunPod interaction uses the GraphQL API — no UI needed.
Logs stream live to your terminal.
"""

import os, sys, json, time, argparse, subprocess, textwrap
import requests

# ── Config ────────────────────────────────────────────────────────────────────
RUNPOD_KEY   = os.environ.get('RUNPOD_API_KEY', '')
DOCKER_IMAGE = 'schwengerryan7/spatiallm:latest'
GPU_TYPE     = 'NVIDIA A40'          # ~$0.39/hr; change to "NVIDIA A100" for speed
DATA_DIR     = os.path.join(os.path.dirname(__file__), 'data', 'scans')
CKPT_DIR     = os.path.join(os.path.dirname(__file__), 'models', 'roomformer')
GQL_URL      = 'https://api.runpod.io/graphql'

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CKPT_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# RunPod GraphQL helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _gql(query: str, variables: dict = None):
    if not RUNPOD_KEY:
        sys.exit('[fp] Set RUNPOD_API_KEY environment variable first.')
    r = requests.post(
        GQL_URL,
        json={'query': query, 'variables': variables or {}},
        headers={'Authorization': f'Bearer {RUNPOD_KEY}'},
        timeout=30,
    )
    data = r.json()
    if 'errors' in data:
        sys.exit(f"[fp] RunPod API error: {data['errors']}")
    return data['data']


def create_pod(name='fp-training'):
    print(f'[fp] Creating {GPU_TYPE} pod "{name}"…')
    data = _gql("""
        mutation CreatePod($input: PodFindAndDeployOnDemandInput!) {
          podFindAndDeployOnDemand(input: $input) {
            id
            machine { podHostId }
          }
        }
    """, {'input': {
        'name':              name,
        'imageName':         DOCKER_IMAGE,
        'gpuTypeId':         GPU_TYPE,
        'gpuCount':          1,
        'containerDiskInGb': 100,
        'volumeInGb':        50,
        'minVcpuCount':      4,
        'minMemoryInGb':     15,
        'volumeMountPath':   '/workspace',
        'ports':             '22/tcp',
        'startSsh':          True,
        'cloudType':         'SECURE',
    }})
    pod_id = data['podFindAndDeployOnDemand']['id']
    print(f'[fp] Pod created: {pod_id}')
    return pod_id


def get_pod(pod_id: str):
    data = _gql("""
        query GetPod($id: String!) {
          pod(input: { podId: $id }) {
            id desiredStatus
            runtime {
              ports { ip port type }
            }
          }
        }
    """, {'id': pod_id})
    return data.get('pod')


def wait_for_pod(pod_id: str, timeout=300):
    print('[fp] Waiting for pod to start…', end='', flush=True)
    for _ in range(timeout // 5):
        pod = get_pod(pod_id)
        if pod and pod.get('runtime'):
            ports = pod['runtime'].get('ports', [])
            for p in ports:
                if p.get('type') == 'tcp' and p.get('port') == 22:
                    print(f"\n[fp] Pod ready — {p['ip']}:{p['port']}")
                    return p['ip'], p['port']
        print('.', end='', flush=True)
        time.sleep(5)
    sys.exit('\n[fp] Timed out waiting for pod.')


def stop_pod(pod_id: str):
    _gql("""
        mutation StopPod($id: String!) { podStop(input: { podId: $id }) { id } }
    """, {'id': pod_id})
    print(f'[fp] Pod {pod_id} stopped.')


def terminate_pod(pod_id: str):
    _gql("""
        mutation TerminatePod($id: String!) { podTerminate(input: { podId: $id }) }
    """, {'id': pod_id})
    print(f'[fp] Pod {pod_id} terminated.')


def list_pods():
    data = _gql("""
        query { myself { pods { id name desiredStatus
          runtime { ports { ip port type } }
        }}}
    """)
    return data['myself']['pods']


# ═══════════════════════════════════════════════════════════════════════════════
# SSH helpers — sync files, run remote commands, stream logs
# ═══════════════════════════════════════════════════════════════════════════════

SSH_OPTS = [
    '-o', 'StrictHostKeyChecking=no',
    '-o', 'ConnectTimeout=15',
    '-o', 'ServerAliveInterval=30',
]

def _ssh_cmd(host, port):
    return ['ssh', '-p', str(port)] + SSH_OPTS + [f'root@{host}']


def ssh_exec(host, port, cmd: str, stream=True):
    """Run a command on the pod; stream=True prints output live."""
    full = _ssh_cmd(host, port) + [cmd]
    if stream:
        proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        for line in iter(proc.stdout.readline, b''):
            print(line.decode(), end='')
        proc.wait()
        return proc.returncode
    else:
        return subprocess.run(full, capture_output=True, text=True)


def rsync_up(host, port, local_path, remote_path):
    print(f'[fp] Uploading {local_path} → pod:{remote_path}')
    cmd = ['rsync', '-avz', '--progress',
           '-e', f'ssh -p {port} ' + ' '.join(SSH_OPTS),
           local_path, f'root@{host}:{remote_path}']
    subprocess.run(cmd, check=True)


def rsync_down(host, port, remote_path, local_path):
    print(f'[fp] Downloading pod:{remote_path} → {local_path}')
    cmd = ['rsync', '-avz', '--progress',
           '-e', f'ssh -p {port} ' + ' '.join(SSH_OPTS),
           f'root@{host}:{remote_path}', local_path]
    subprocess.run(cmd, check=True)


# ═══════════════════════════════════════════════════════════════════════════════
# Commands
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_status(args):
    pods = list_pods()
    if not pods:
        print('[fp] No active pods.')
        return
    for p in pods:
        ports = (p.get('runtime') or {}).get('ports', [])
        ssh_port = next((x['port'] for x in ports if x.get('type') == 'tcp'), '—')
        print(f"  {p['id']}  {p['name']:20s}  {p['desiredStatus']:10s}  ssh:{ssh_port}")


def cmd_train(args):
    """
    Full training loop:
    1. Create GPU pod
    2. Upload training data + scripts
    3. Run fine-tuning (logs streamed live)
    4. Download best checkpoint
    5. Terminate pod
    """
    scans = [d for d in os.listdir(DATA_DIR)
             if os.path.isdir(os.path.join(DATA_DIR, d))]
    if not scans:
        sys.exit(f'[fp] No training scans found in {DATA_DIR}/\n'
                 f'     Add scan folders with cloud.ply + floor_plan.json')

    print(f'[fp] Training on {len(scans)} scans: {scans}')

    pod_id = create_pod('fp-training')
    try:
        host, port = wait_for_pod(pod_id)
        time.sleep(5)  # let SSH daemon start

        # Upload data + training script
        rsync_up(host, port, DATA_DIR + '/', '/workspace/training_data/')
        rsync_up(host, port,
                 os.path.join(os.path.dirname(__file__), 'scripts/'),
                 '/workspace/scripts/')

        # Install any extra deps, then train
        print('\n[fp] ── Training started (logs streaming) ──────────────────')
        rc = ssh_exec(host, port,
            'cd /workspace && '
            'pip install -q wandb 2>/dev/null; '
            'python scripts/train_roomformer.py '
            '  --data /workspace/training_data '
            '  --output /workspace/checkpoints '
            f' --epochs {args.epochs} '
            f' --lr {args.lr}'
        )
        print(f'\n[fp] ── Training finished (exit {rc}) ──────────────────────')

        # Download best checkpoint
        os.makedirs(CKPT_DIR, exist_ok=True)
        rsync_down(host, port,
                   '/workspace/checkpoints/best.pth',
                   os.path.join(CKPT_DIR, 'finetuned_best.pth'))
        print(f'[fp] Checkpoint saved → {CKPT_DIR}/finetuned_best.pth')

    finally:
        terminate_pod(pod_id)


def cmd_eval(args):
    """Evaluate a PLY scan with the current model — runs locally."""
    ply = args.ply
    if not os.path.exists(ply):
        sys.exit(f'[fp] File not found: {ply}')

    print(f'[fp] Evaluating {ply}…')
    script = os.path.join(os.path.dirname(__file__), 'scripts', 'eval_floorplan.py')
    subprocess.run([sys.executable, script, '--ply', ply], check=True)


def cmd_dense(args):
    """Run dense COLMAP reconstruction on a video → PLY."""
    video = args.video
    if not os.path.exists(video):
        sys.exit(f'[fp] File not found: {video}')

    out_name = os.path.splitext(os.path.basename(video))[0]
    out_dir  = os.path.join(DATA_DIR, out_name)
    os.makedirs(out_dir, exist_ok=True)

    print(f'[fp] Dense COLMAP reconstruction: {video} → {out_dir}/')
    script = os.path.join(os.path.dirname(__file__), 'scripts', 'dense_colmap.sh')
    subprocess.run(['bash', script, video, out_dir], check=True)
    print(f'[fp] Done. PLY at {out_dir}/cloud.ply')
    print(f'[fp] Open the floor plan tab, drop the PLY, annotate, then save floor_plan.json')
    print(f'[fp] to {out_dir}/floor_plan.json to add it to training data.')


def cmd_prep(args):
    """Pre-process all scans → density images for RoomFormer training."""
    print(f'[fp] Preprocessing scans in {DATA_DIR}…')
    script = os.path.join(os.path.dirname(__file__), 'scripts', 'prep_training_data.py')
    subprocess.run([sys.executable, script, '--data', DATA_DIR], check=True)


def cmd_deploy(args):
    """Build + push Docker image. Then update your RunPod endpoint image."""
    print('[fp] Building Docker image…')
    build_ctx = os.path.join(os.path.dirname(__file__), 'gaussian-splat')
    subprocess.run([
        'docker', 'build',
        '-f', os.path.join(build_ctx, 'Dockerfile.spatiallm'),
        '-t', DOCKER_IMAGE,
        build_ctx,
    ], check=True)
    print('[fp] Pushing to Docker Hub…')
    subprocess.run(['docker', 'push', DOCKER_IMAGE], check=True)
    print('[fp] Done. Go to RunPod → your floor plan endpoint → Update → Save.')


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(
        prog='python fp.py',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent("""\
            Floor Plan CLI — full pipeline in one command.

            Examples:
              python fp.py train                 # train on data/scans/
              python fp.py train --epochs 100    # more epochs
              python fp.py eval my_scan.ply      # evaluate a scan
              python fp.py dense room_video.mp4  # dense COLMAP → PLY
              python fp.py prep                  # preprocess scans
              python fp.py deploy                # build + push Docker
              python fp.py status                # list RunPod pods
        """),
    )
    sub = p.add_subparsers(dest='command', required=True)

    sub.add_parser('status', help='List active RunPod pods')

    t = sub.add_parser('train', help='Fine-tune RoomFormer on data/scans/')
    t.add_argument('--epochs', type=int, default=50)
    t.add_argument('--lr',     type=float, default=1e-5)

    e = sub.add_parser('eval', help='Evaluate a PLY scan locally')
    e.add_argument('ply', help='Path to .ply file')

    d = sub.add_parser('dense', help='Dense COLMAP reconstruction from video')
    d.add_argument('video', help='Path to video file')

    sub.add_parser('prep', help='Preprocess scans → training images')
    sub.add_parser('deploy', help='Build + push Docker image')

    args = p.parse_args()
    {
        'status': cmd_status,
        'train':  cmd_train,
        'eval':   cmd_eval,
        'dense':  cmd_dense,
        'prep':   cmd_prep,
        'deploy': cmd_deploy,
    }[args.command](args)


if __name__ == '__main__':
    main()
