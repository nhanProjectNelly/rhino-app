"""
Set-to-set Re-ID: IndivAID prompt-injected ViT, in-process.
Mirrors IndivAID/app_reid_top5.py. Gallery score per pid: **max** (best single image vs query, default)
or **mean** (pooled embedding). Reduces bias when some ids have many generic gallery shots.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
from collections import defaultdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ATRW_PATTERN = re.compile(r"(\d+)_-?\d+_\d+.*")
PART_TYPES = ["left_ear", "right_ear", "head", "body"]


def _atrw_pid_from_path(path: str) -> int:
    stem = Path(path).stem
    m = ATRW_PATTERN.search(stem)
    return int(m.group(1)) if m else -1


def _load_part_descriptions(json_path: str) -> dict:
    if not json_path or not os.path.isfile(json_path):
        return {}
    with open(json_path, encoding="utf-8") as f:
        return json.load(f)


def _get_part_texts_for_path(img_path: str, descriptions: dict) -> dict[str, str]:
    if isinstance(img_path, int):
        raise TypeError(
            "Re-ID got an int where a file path was expected (likely pid). "
            "Fixed: gallery_list must use all_gallery_paths = [path for path, _ in gallery_list]."
        )
    stem = Path(img_path).stem
    key = stem
    if key not in descriptions:
        key = Path(img_path).name
    if key not in descriptions:
        base = re.sub(
            r"_(?:left_ear|right_ear|head|body)(?:_\d+|_fallback)?$",
            "",
            stem,
            flags=re.I,
        )
        key = base
    desc = descriptions.get(key, {}) if isinstance(descriptions.get(key), dict) else {}
    return {
        pt: desc.get(pt, "") if isinstance(desc.get(pt), str) else ""
        for pt in PART_TYPES
    }


class _ReIDEngine:
    """Lazy-loaded model + cfg (invalidated when weight file mtime changes)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._weight_mtime: float = 0.0
        self._weight_path: str = ""
        self._cfg_key: str = ""
        self._model = None
        self._text_encoder = None
        self._device: str = "cpu"
        self._val_transforms = None
        self._num_classes: int = 0
        self._descriptions: dict = {}
        self._cfg = None

    def _load(
        self,
        indivaid_root: Path,
        config_file: str,
        weight_path: Path,
        cfg_overrides: list[str] | None,
        gallery_root: str,
    ) -> None:
        root = str(indivaid_root.resolve())
        if root not in sys.path:
            sys.path.insert(0, root)

        import torch
        from torchvision import transforms

        from config import cfg_base as cfg
        from model.make_model_prompt_injected import make_model_prompt_injected
        from processor.processor_prompt_injected import encode_part_texts

        if config_file:
            cfg.merge_from_file(config_file)
        opts = list(cfg_overrides or [])
        opts.extend(["TEST.WEIGHT", str(weight_path.resolve())])
        cfg.merge_from_list(opts)
        cfg.freeze()

        root_dir = gallery_root
        if isinstance(cfg.DATASETS.ROOT_DIR, (list, tuple)):
            root_dir = root_dir or (cfg.DATASETS.ROOT_DIR[0] if cfg.DATASETS.ROOT_DIR else "")
        else:
            root_dir = root_dir or str(cfg.DATASETS.ROOT_DIR)
        if not root_dir or not os.path.isdir(os.path.join(root_dir, "gallery")):
            raise FileNotFoundError(f"Gallery dir missing under {root_dir}/gallery")
        train_dir = Path(root_dir) / "train"
        if not train_dir.is_dir():
            raise FileNotFoundError(f"Train dir required for num_classes: {train_dir}")
        train_pids = {_atrw_pid_from_path(str(p)) for p in train_dir.glob("*.jpg")}
        train_pids = {p for p in train_pids if p >= 0}
        num_classes = max(len(train_pids), 1)

        text_desc_path = getattr(cfg.DATASETS, "TEXT_DESC_PATH", None) or ""
        if isinstance(text_desc_path, (list, tuple)):
            text_desc_path = text_desc_path[0] if text_desc_path else ""
        self._descriptions = _load_part_descriptions(str(text_desc_path))

        self._val_transforms = transforms.Compose(
            [
                transforms.Resize(cfg.INPUT.SIZE_TEST),
                transforms.ToTensor(),
                transforms.Normalize(mean=cfg.INPUT.PIXEL_MEAN, std=cfg.INPUT.PIXEL_STD),
            ]
        )

        self._num_classes = num_classes
        self._model = make_model_prompt_injected(
            cfg, num_class=num_classes, camera_num=1, view_num=1
        )
        try:
            ckpt = torch.load(str(weight_path), map_location="cpu", weights_only=False)
        except Exception as e:
            raise RuntimeError(
                f"Cannot load Re-ID checkpoint (corrupt or not a PyTorch .pth): {weight_path}. "
                f"Re-download the full file. Underlying error: {e}"
            ) from e
        if isinstance(ckpt, dict) and "state_dict" in ckpt:
            self._model.load_state_dict(ckpt["state_dict"], strict=False)
        else:
            self._model.load_state_dict(ckpt, strict=False)

        self._device = (
            "cuda"
            if torch.cuda.is_available()
            else (
                "mps"
                if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available()
                else "cpu"
            )
        )
        self._model.to(self._device)
        self._model.eval()
        self._text_encoder = self._model.text_encoder
        self._text_encoder.eval()
        self._text_encoder.to(self._device)
        self._cfg = cfg
        self._encode_part_texts = encode_part_texts

        from datasets.bases import read_image

        self._read_image = read_image

        logger.info(
            "ReID engine loaded: device=%s num_classes=%s weight=%s",
            self._device,
            self._num_classes,
            weight_path.name,
        )

    def _ensure(
        self,
        indivaid_root: Path,
        config_file: str,
        weight_path: Path,
        cfg_overrides: list[str] | None,
        gallery_root: str,
    ) -> None:
        wp = weight_path.resolve()
        mtime = wp.stat().st_mtime
        key = f"{config_file}|{wp}|{gallery_root}|{cfg_overrides!s}"
        with self._lock:
            need = (
                self._model is None
                or mtime != self._weight_mtime
                or str(wp) != self._weight_path
                or key != self._cfg_key
            )
            if need:
                self._load(indivaid_root, config_file, wp, cfg_overrides, gallery_root)
                self._weight_mtime = mtime
                self._weight_path = str(wp)
                self._cfg_key = key

    def _load_image_tensor(self, path: str):
        import torch

        img = self._read_image(path)
        t = self._val_transforms(img).unsqueeze(0).to(self._device)
        return t

    def _extract_batch(
        self,
        batch_paths: list[str],
        path_text_overrides: dict[str, dict[str, str]] | None = None,
    ):
        import torch

        for p in batch_paths:
            if not isinstance(p, str):
                logger.error("Re-ID batch expected str paths, got %s: %r", type(p).__name__, p)
                raise TypeError(
                    f"Re-ID internal error: batch path must be str, not {type(p).__name__} ({p!r}). "
                    "Restart the API after updating ai_core/reid_engine.py."
                )
        overrides = path_text_overrides or {}
        part_texts_batch = {pt: [] for pt in PART_TYPES}
        for path in batch_paths:
            np = os.path.normpath(str(Path(path).resolve()))
            od = overrides.get(np) or overrides.get(os.path.normpath(path))
            if od is not None:
                pt = {k: (str(od.get(k, "") or ""))[:2000] for k in PART_TYPES}
            else:
                pt = _get_part_texts_for_path(path, self._descriptions)
            for k in PART_TYPES:
                part_texts_batch[k].append(pt[k])
        imgs = torch.cat([self._load_image_tensor(p) for p in batch_paths], dim=0)
        self._model.eval()
        part_emb = self._encode_part_texts(
            part_texts_batch, self._text_encoder, self._device
        )
        with torch.no_grad():
            feat = self._model(x=imgs, part_text_embeddings=part_emb, quality_cues=None)
        return feat.cpu()

    def _extract_batch_visual_only(self, batch_paths: list[str]):
        """Same backbone without prompt injection — matches query uploads (no description JSON)."""
        import torch

        for p in batch_paths:
            if not isinstance(p, str):
                raise TypeError(f"Re-ID batch path must be str, got {type(p).__name__}")
        imgs = torch.cat([self._load_image_tensor(p) for p in batch_paths], dim=0)
        self._model.eval()
        with torch.no_grad():
            feat = self._model(x=imgs, part_text_embeddings=None, quality_cues=None)
        return feat.cpu()

    def infer(
        self,
        indivaid_root: Path,
        config_file: str,
        weight_path: Path,
        query_path: str,
        gallery_root: str,
        topk: int,
        cfg_overrides: list[str] | None,
        pid_score_mode: str = "max",
        visual_only_retrieval: bool = True,
        query_description_parts_list: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        import torch

        mode = (pid_score_mode or "max").strip().lower()
        if mode not in ("max", "mean"):
            mode = "max"

        self._ensure(indivaid_root, config_file, weight_path, cfg_overrides, gallery_root)
        gallery_dir = os.path.join(gallery_root, "gallery")
        gallery_paths = sorted(Path(gallery_dir).glob("*.jpg"))
        gallery_list: list[tuple[str, int]] = []
        all_gallery_paths: list[str] = []
        for p in gallery_paths:
            sp = os.path.normpath(str(p.resolve()))
            pid = _atrw_pid_from_path(sp)
            if pid >= 0:
                gallery_list.append((sp, pid))
                all_gallery_paths.append(sp)
        if not gallery_list:
            return {"error": "No gallery images", "top_k": [], "query": query_path}

        pid_to_paths: dict[int, list[str]] = defaultdict(list)
        for path, pid in gallery_list:
            pid_to_paths[pid].append(path)
        pids = sorted(pid_to_paths.keys())

        qp = Path(query_path)
        if qp.is_file():
            query_paths = [str(qp)]
        elif qp.is_dir():
            query_paths = sorted(
                str(p)
                for p in qp.iterdir()
                if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")
            )
        else:
            return {"error": "Invalid query path", "top_k": [], "query": query_path}
        if not query_paths:
            return {"error": "No query images", "top_k": [], "query": query_path}

        qlist = query_description_parts_list or []
        use_app_descriptions = len(qlist) == len(query_paths) and any(
            qlist[i]
            and any((str(qlist[i].get(pt, "") or "").strip()) for pt in PART_TYPES)
            for i in range(len(query_paths))
        )

        batch_size = int(self._cfg.TEST.IMS_PER_BATCH)
        gallery_feats = []
        if use_app_descriptions:
            for i in range(0, len(all_gallery_paths), batch_size):
                batch_paths = all_gallery_paths[i : i + batch_size]
                gallery_feats.append(self._extract_batch(batch_paths))
        else:
            extract = (
                self._extract_batch_visual_only
                if visual_only_retrieval
                else self._extract_batch
            )
            for i in range(0, len(all_gallery_paths), batch_size):
                batch_paths = all_gallery_paths[i : i + batch_size]
                gallery_feats.append(extract(batch_paths))
        gallery_feats = torch.cat(gallery_feats, dim=0)
        gallery_feats = torch.nn.functional.normalize(gallery_feats, dim=1)

        pid_to_feat_list: dict[int, list] = defaultdict(list)
        for (_, pid), feat in zip(gallery_list, gallery_feats):
            pid_to_feat_list[pid].append(feat)

        def _rank_pids_for_query(q_vec: "torch.Tensor") -> list[tuple[int, float, str]]:
            """Return [(pid, score, rep_path), ...] sorted by score desc."""
            out: list[tuple[int, float, str]] = []
            for pid in pids:
                G = torch.stack(pid_to_feat_list[pid], dim=0)
                paths = pid_to_paths[pid]
                if mode == "max":
                    sims = (G * q_vec.unsqueeze(0)).sum(dim=1)
                    bi = int(sims.argmax().item())
                    out.append((pid, float(sims[bi].item()), paths[bi]))
                else:
                    f = torch.nn.functional.normalize(G.mean(dim=0, keepdim=True), dim=1).squeeze(0)
                    sc = float((f * q_vec).sum().item())
                    out.append((pid, sc, paths[0]))
            out.sort(key=lambda x: x[1], reverse=True)
            return out

        if use_app_descriptions:
            q_chunks = []
            for i, p in enumerate(query_paths):
                np = os.path.normpath(str(Path(p).resolve()))
                parts = qlist[i] if i < len(qlist) else {}
                if parts and any((str(parts.get(pt, "") or "").strip()) for pt in PART_TYPES):
                    ov = {
                        np: {
                            pt: str(parts.get(pt, "") or "")[:2000]
                            for pt in PART_TYPES
                        }
                    }
                    q_chunks.append(self._extract_batch([p], ov))
                else:
                    q_chunks.append(self._extract_batch_visual_only([p]))
            q_feats = torch.cat(q_chunks, dim=0)
        else:
            extract = (
                self._extract_batch_visual_only
                if visual_only_retrieval
                else self._extract_batch
            )
            q_feats = extract(query_paths)
        q_feat_mean = torch.nn.functional.normalize(
            q_feats.mean(dim=0, keepdim=True), dim=1
        ).squeeze(0)

        ranked_set = _rank_pids_for_query(q_feat_mean)
        top = ranked_set[:topk]
        mean_top1_pid, mean_top1_score = ranked_set[0][0], ranked_set[0][1]
        pid_to_score_set = {pid: sc for pid, sc, _ in ranked_set}

        per_image: list[dict[str, Any]] = []
        from collections import Counter

        for i, path in enumerate(query_paths):
            qf = torch.nn.functional.normalize(q_feats[i : i + 1], dim=1).squeeze(0)
            row = _rank_pids_for_query(qf)
            top1p, top1s = row[0][0], row[0][1]
            top2s = row[1][1] if len(row) > 1 else top1s
            per_image.append(
                {
                    "path": path,
                    "top1_id": int(top1p),
                    "top1_score": float(top1s),
                    "margin": float(top1s - top2s),
                }
            )

        votes = Counter(p["top1_id"] for p in per_image)
        maj_pid, maj_n = votes.most_common(1)[0]
        n_img = len(query_paths)
        conflict = n_img > 1 and len(votes) > 1
        if n_img > 1 and maj_n > n_img / 2:
            finalize_id = int(maj_pid)
            finalize_method = "majority_vote_per_image"
            finalize_score = float(pid_to_score_set.get(int(maj_pid), 0.0))
        else:
            finalize_id = int(mean_top1_pid)
            finalize_method = "mean_set_embedding"
            finalize_score = float(mean_top1_score)

        per_query_debug: list[dict[str, Any]] = []
        for i, _p in enumerate(query_paths):
            parts = qlist[i] if i < len(qlist) else {}
            has_t = bool(
                parts and any((str(parts.get(pt, "") or "").strip()) for pt in PART_TYPES)
            )
            per_query_debug.append(
                {
                    "index": i,
                    "encoding": "text_prompt" if has_t else "visual_only",
                    "chars": {
                        pt: len(str((parts or {}).get(pt, "") or ""))
                        for pt in PART_TYPES
                    },
                }
            )
        reid_debug: dict[str, Any] = {
            "use_app_descriptions": bool(use_app_descriptions),
            "query_images": len(query_paths),
            "description_list_len": len(qlist),
            "lengths_match": len(qlist) == len(query_paths),
            "hint": (
                "OK: LLM descriptions used for query + ATRW JSON for gallery."
                if use_app_descriptions
                else (
                    "No text path: send description_parts_list_json (same length as files) "
                    "after Save/describe, or only visual ViT is used."
                    if visual_only_retrieval
                    else "Gallery/query from JSON paths only (query stems not in JSON → empty text)."
                )
            ),
            "gallery_encoding": (
                "atr_json_part_text" if use_app_descriptions else (
                    "visual_only" if visual_only_retrieval else "atr_json_part_text"
                )
            ),
            "per_query": per_query_debug,
            "pid_score_mode": mode,
        }
        if use_app_descriptions:
            logger.info(
                "Re-ID: app descriptions ON | query=%s imgs | gallery ATRW+text",
                len(query_paths),
            )
        else:
            logger.warning(
                "Re-ID: app descriptions OFF | query=%s | list_len=%s match=%s | visual_only=%s",
                len(query_paths),
                len(qlist),
                len(qlist) == len(query_paths),
                visual_only_retrieval,
            )

        return {
            "query": query_paths,
            "pid_score_mode": mode,
            "visual_only_retrieval": not use_app_descriptions and bool(visual_only_retrieval),
            "query_used_app_descriptions": bool(use_app_descriptions),
            "reid_debug": reid_debug,
            "top_k": [
                {
                    "rank": i + 1,
                    "id": int(pid),
                    "id_name": None,
                    "score": float(score),
                    "representative_image": rep_path,
                }
                for i, (pid, score, rep_path) in enumerate(top)
            ],
            "finalize": {
                "id": finalize_id,
                "score": finalize_score,
                "method": finalize_method,
                "mean_set_top1_id": int(mean_top1_pid),
                "mean_set_score": float(mean_top1_score),
                "majority_id": int(maj_pid),
                "majority_votes": maj_n,
                "per_image_conflict": conflict,
            },
            "per_image": per_image,
        }


_engine = _ReIDEngine()


def run_set_to_set_reid(
    *,
    indivaid_root: Path,
    config_file: str,
    weight_path: Path,
    query_path: str,
    gallery_root: str | None,
    topk: int = 5,
    cfg_overrides: list[str] | None = None,
    pid_score_mode: str = "max",
    visual_only_retrieval: bool = True,
    query_description_parts_list: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """
    Run set-to-set Re-ID. gallery_root must contain gallery/*.jpg (ATRW filenames).
    query_path: single image or directory (mean feature over set).
    """
    if not indivaid_root.is_dir():
        return {"error": "IndivAID root not found", "top_k": [], "query": query_path}
    if not weight_path.is_file():
        return {"error": f"Weight not found: {weight_path}", "top_k": [], "query": query_path}
    if not gallery_root:
        return {"error": "gallery_root required", "top_k": [], "query": query_path}

    try:
        return _engine.infer(
            indivaid_root=indivaid_root,
            config_file=config_file,
            weight_path=weight_path,
            query_path=query_path,
            gallery_root=gallery_root,
            topk=topk,
            cfg_overrides=cfg_overrides,
            pid_score_mode=pid_score_mode,
            visual_only_retrieval=visual_only_retrieval,
            query_description_parts_list=query_description_parts_list,
        )
    except Exception as e:
        logger.exception("ReID infer failed: %s", e)
        return {"error": str(e), "top_k": [], "query": query_path}
