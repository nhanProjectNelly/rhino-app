# ai_core — set-to-set Re-ID

Uses **IndivAID** code (`make_model_prompt_injected`, `encode_part_texts`) and your `.pth` checkpoint. Same logic as `IndivAID/app_reid_top5.py` (gallery mean per pid, query set mean, cosine).

**Dependencies** (in addition to backend): PyTorch + torchvision matching IndivAID. Example:

```bash
pip install torch torchvision
```

If PyTorch is missing, the backend falls back to subprocess + `app_reid_top5.py`.
