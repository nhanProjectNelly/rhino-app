"""Re-ID: in-process via ai_core (IndivAID pipeline) or subprocess fallback."""
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)
_RHINO_APP = Path(__file__).resolve().parents[3]  # rhino_app/ (parent of backend)


def run_reid_top5(
    config_file: str,
    weight_path: str | Path,
    query_path: str,
    gallery_root: str | None = None,
    topk: int = 5,
    cfg_overrides: list[str] | None = None,
    query_description_parts_list: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    wp = Path(weight_path)
    if not wp.is_absolute():
        wp = (Path(__file__).resolve().parents[2] / wp).resolve()

    if not wp.exists():
        return {"error": f"Weight file not found: {wp}", "top_k": [], "query": query_path}

    ind_root = settings.indivaid_root
    if not ind_root.is_dir():
        return {
            "error": f"IndivAID not found (resolved to {ind_root}). Set INDIVAID_ROOT in .env relative to backend/, e.g. ../../IndivAID",
            "top_k": [],
            "query": query_path,
        }

    gr = gallery_root
    if gr and not Path(gr).is_absolute():
        gr = str((settings.UPLOAD_DIR / gr).resolve())

    if gr and (Path(gr) / "train").is_dir():
        if str(_RHINO_APP) not in sys.path:
            sys.path.insert(0, str(_RHINO_APP))
        try:
            from ai_core.reid_engine import run_set_to_set_reid

            return run_set_to_set_reid(
                indivaid_root=ind_root,
                config_file=config_file,
                weight_path=wp,
                query_path=query_path,
                gallery_root=gr,
                topk=topk,
                cfg_overrides=cfg_overrides,
                pid_score_mode=(settings.REID_PID_SCORE_MODE or "max").strip().lower(),
                visual_only_retrieval=bool(settings.REID_INFER_VISUAL_ONLY),
                query_description_parts_list=query_description_parts_list,
            )
        except ImportError as e:
            logger.warning("ai_core / torch unavailable (%s), using subprocess", e)
        except Exception as e:
            logger.warning("ai_core Re-ID error (%s), using subprocess", e)

    app_script = ind_root / "app_reid_top5.py"
    if not app_script.is_file():
        return {
            "error": f"app_reid_top5.py not found under {ind_root}",
            "top_k": [],
            "query": query_path,
        }
    weight_str = str(wp.resolve())
    cmd = [sys.executable, str(app_script), "--config_file", config_file]
    if cfg_overrides:
        cmd.extend(cfg_overrides)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        out_path = tf.name
    cmd.extend(
        [
            "TEST.WEIGHT",
            weight_str,
            "--query",
            query_path,
            "--output",
            out_path,
            "--topk",
            str(topk),
        ]
    )
    if gr:
        cmd.extend(["--gallery-root", gr])
    out_file = Path(out_path)
    try:
        subprocess.run(
            cmd,
            cwd=str(ind_root),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if out_file.is_file():
            with open(out_file) as f:
                data = json.load(f)
            return data
        return {"error": "No output", "top_k": [], "query": query_path}
    except subprocess.TimeoutExpired:
        return {"error": "Prediction timeout", "top_k": [], "query": query_path}
    except Exception as e:
        return {"error": str(e), "top_k": [], "query": query_path}
    finally:
        try:
            out_file.unlink(missing_ok=True)
        except OSError:
            logger.warning("Could not remove temp Re-ID output %s", out_path)
