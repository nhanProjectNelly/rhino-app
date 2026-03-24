# Re-ID checkpoint: download from GPU server → rhino_app

Use the **latest fine-tuned** prompt-injected weights (e.g. `wildlife_unfreeze`) for set-to-set prediction in the app. The app calls IndivAID `app_reid_top5.py` with your chosen YAML + `TEST.WEIGHT`.

## 1. Files to copy from the server

Typical paths on server (`/opt/rhino/IndivAID`):

| File | Purpose |
|------|---------|
| `logs/rhino_prompt_injected_finetune_wildlife_unfreeze/ViT-B-16_prompt_injected_latest.pth` | Re-ID weights |
| `data/rhino_part_descriptions_four_atrw.json` | Part text for four-part inference (if you evaluated with this + `USE_WHOLE_BODY_ONLY False`) |

The YAML `configs/Rhino/vit_prompt_injected_finetune_wildlife_unfreeze.yml` should already exist in your local **IndivAID** clone (same repo).

## 2. Download (from your laptop)

Replace user/host/paths if different.

```bash
# From project root (or any folder)
mkdir -p rhino_app/backend/checkpoints_reid

scp USER@HOST:/opt/rhino/IndivAID/logs/rhino_prompt_injected_finetune_wildlife_unfreeze/ViT-B-16_prompt_injected_latest.pth \
  rhino_app/backend/checkpoints_reid/

# Optional but recommended if test used four_atrw + not whole-body-only:
scp USER@HOST:/opt/rhino/IndivAID/data/rhino_part_descriptions_four_atrw.json \
  IndivAID/data/
```

Example host from your setup: `nguyenthanh@34.87.108.144`.

## 3. Backend `.env` (rhino_app/backend/.env)

```env
INDIVAID_ROOT=../../IndivAID
MODEL_WEIGHT=checkpoints_reid/ViT-B-16_prompt_injected_latest.pth

# Match server test (four-part text, same as test_prompt_injected.py overrides)
INDIVAID_REID_CONFIG=configs/Rhino/vit_prompt_injected_finetune_wildlife_unfreeze.yml
INDIVAID_REID_TEXT_DESC_PATH=data/rhino_part_descriptions_four_atrw.json
INDIVAID_REID_USE_WHOLE_BODY_ONLY=false

# Full gallery: score each ID by best-matching image (default). Use mean for old pooled behavior.
REID_PID_SCORE_MODE=max
# When Predict does not send per-image descriptions, fall back to image-only ViT
REID_INFER_VISUAL_ONLY=true
```

After **Save** in the describe step, the app sends `description_parts` (LLM output) with **Predict** so query embedding uses the same prompt-injected path as the ATRW gallery (not zero text).

- Paths under `INDIVAID_REID_TEXT_DESC_PATH` are resolved relative to **INDIVAID_ROOT** unless absolute.
- `MODEL_WEIGHT` is relative to **backend/** unless absolute.
- If you omit `INDIVAID_REID_TEXT_DESC_PATH`, the YAML default is used (may differ from server eval).
- If you omit `INDIVAID_REID_USE_WHOLE_BODY_ONLY`, the YAML value is not overridden.

## 4. Gallery + DB for Re-ID (recommended)

Copy **full** ATRW tree (`train/`, `query/`, `gallery/`) into the app and import the DB:

```bash
cd backend                    # from rhino_app/
# or: cd rhino_app/backend    # from repo root
python init_db.py --reset --no-high-quality
python sync_reid_test_data.py --atrw-root ../../IndivAID/data/rhino_atrw_format \
  --descriptions ../../IndivAID/data/rhino_part_descriptions_four_atrw.json
```

DB gets **train + gallery** only. Query images go to **`uploads/reid_query_reference/`** (not DB). See [ATRW_RHINO_PID_TABLE.md](ATRW_RHINO_PID_TABLE.md).

## 5. Optional: error analysis CSV on server

On the server you already used:

```bash
python tools/analyze_test_errors.py \
  --config_file configs/Rhino/vit_prompt_injected_finetune_wildlife_unfreeze.yml \
  --output_dir logs/rhino_finetune/error_debug \
  DATASETS.TEXT_DESC_PATH ./data/rhino_part_descriptions_four_atrw.json \
  DATASETS.USE_WHOLE_BODY_ONLY False \
  TEST.WEIGHT ./logs/rhino_prompt_injected_finetune_wildlife_unfreeze/ViT-B-16_prompt_injected_latest.pth
```

Outputs: `wrong_predictions.csv`, `correct_predictions.csv`, `test_error_analysis.json`. Copy those separately with `scp` if needed.

## 6. `test_prompt_injected.py` unpack error

If `do_inference_prompt_injected` returns 4 values (R1, R5, mAP, F1), unpack four variables or ignore the fourth — e.g. `rank_1, rank5, mAP, _ = ...`.
