import os
from pathlib import Path
from pydantic_settings import BaseSettings

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
# backend/ folder (for resolving INDIVAID_ROOT relative to .env docs, not CWD)
_BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    SECRET_KEY: str = "rhino-app-secret-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 1 week
    OPENAI_API_KEY: str = ""
    DATABASE_URL: str = "sqlite+aiosqlite:///./rhino.db"
    UPLOAD_DIR: Path = _BACKEND_ROOT / "uploads"
    INDIVAID_ROOT: Path = Path("../IndivAID")
    # IndivAID checkpoint: .pth/.pt file or directory (latest file in dir)
    MODEL_WEIGHT: str = "production_checkpoint"
    # Re-ID: config under INDIVAID_ROOT (e.g. configs/Rhino/vit_prompt_injected_finetune_wildlife_unfreeze.yml)
    INDIVAID_REID_CONFIG: str = "configs/Rhino/vit_prompt_injected.yml"
    # Optional overrides so inference matches training (four-part text vs whole-body)
    INDIVAID_REID_TEXT_DESC_PATH: str = ""
    # "true" / "false" / empty (empty = do not override YAML)
    INDIVAID_REID_USE_WHOLE_BODY_ONLY: str = ""
    # Per-query-image score below this → copy to uploads/reid_demo_not_in_gallery/ for demo
    REID_LOW_SCORE_THRESHOLD: float = 0.28
    # max = best gallery image per ID (fairer with uneven images/id); mean = legacy pooled embedding
    REID_PID_SCORE_MODE: str = "max"
    # Query uploads have no part-text JSON → zeros collapsed to same embedding; use image-only ViT for retrieval
    REID_INFER_VISUAL_ONLY: bool = True

    class Config:
        env_file = ".env"

    @property
    def indivaid_root(self) -> Path:
        """IndivAID repo: resolve paths in .env relative to backend/, not process CWD."""
        p = Path(self.INDIVAID_ROOT)
        if p.is_absolute():
            return p.resolve()
        r = (_BACKEND_DIR / p).resolve()
        if r.is_dir():
            return r
        sibling = (_BACKEND_DIR.parent.parent / "IndivAID").resolve()
        if sibling.is_dir():
            return sibling
        return r

    @property
    def model_weight_path(self) -> Path | None:
        """Absolute path to checkpoint. If directory, use latest .pth/.pt file."""
        p = Path(self.MODEL_WEIGHT)
        if not p.is_absolute():
            # Prefer backend/ then rhino_app root (checkpoints_reid often under backend/)
            for base in (_BACKEND_DIR, _BACKEND_ROOT):
                cand = (base / self.MODEL_WEIGHT).resolve()
                if cand.exists():
                    p = cand
                    break
            else:
                p = (_BACKEND_DIR / self.MODEL_WEIGHT).resolve()
        if not p.exists():
            return None
        if p.is_file():
            return p
        # Directory: find latest .pth or .pt (by mtime)
        candidates = list(p.glob("*.pth")) + list(p.glob("*.pt"))
        if not candidates:
            return None
        return max(candidates, key=lambda x: x.stat().st_mtime)


settings = Settings()
settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
(settings.UPLOAD_DIR / "gallery").mkdir(exist_ok=True)
(settings.UPLOAD_DIR / "predict").mkdir(exist_ok=True)
(settings.UPLOAD_DIR / "crops").mkdir(exist_ok=True)
(settings.UPLOAD_DIR / "reid_demo_not_in_gallery").mkdir(exist_ok=True)
