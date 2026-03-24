#!/usr/bin/env bash
# Example: copy latest wildlife_unfreeze Re-ID checkpoint (+ optional four-part JSON) from GPU server.
# Edit SSH_USER, SSH_HOST, REMOTE_INDIVAID, LOCAL_* before running.
set -euo pipefail

SSH_USER="${SSH_USER:-nguyenthanh}"
SSH_HOST="${SSH_HOST:-34.87.108.144}"
REMOTE_INDIVAID="${REMOTE_INDIVAID:-/opt/rhino/IndivAID}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RHINO_APP="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND="$RHINO_APP/backend"
CKPT_DIR="$BACKEND/checkpoints_reid"
mkdir -p "$CKPT_DIR"

REMOTE_PTH="$REMOTE_INDIVAID/logs/rhino_prompt_injected_finetune_wildlife_unfreeze/ViT-B-16_prompt_injected_latest.pth"
LOCAL_PTH="$CKPT_DIR/ViT-B-16_prompt_injected_latest.pth"

echo "scp $SSH_USER@$SSH_HOST:$REMOTE_PTH -> $LOCAL_PTH"
scp "$SSH_USER@$SSH_HOST:$REMOTE_PTH" "$LOCAL_PTH"

# Optional: four-part descriptions (path relative to IndivAID root on both sides)
INDIVAID_ROOT="${INDIVAID_ROOT:-$RHINO_APP/../IndivAID}"
if [[ -d "$INDIVAID_ROOT" ]]; then
  REMOTE_JSON="$REMOTE_INDIVAID/data/rhino_part_descriptions_four_atrw.json"
  LOCAL_JSON="$INDIVAID_ROOT/data/rhino_part_descriptions_four_atrw.json"
  mkdir -p "$(dirname "$LOCAL_JSON")"
  echo "scp four_atrw JSON -> $LOCAL_JSON"
  scp "$SSH_USER@$SSH_HOST:$REMOTE_JSON" "$LOCAL_JSON" || true
fi

echo "Done. Set in backend/.env:"
echo "  MODEL_WEIGHT=checkpoints_reid/ViT-B-16_prompt_injected_latest.pth"
echo "  INDIVAID_REID_CONFIG=configs/Rhino/vit_prompt_injected_finetune_wildlife_unfreeze.yml"
echo "  INDIVAID_REID_TEXT_DESC_PATH=data/rhino_part_descriptions_four_atrw.json"
echo "  INDIVAID_REID_USE_WHOLE_BODY_ONLY=false"
