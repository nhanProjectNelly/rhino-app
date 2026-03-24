"""In-process Re-ID using IndivAID prompt-injected ViT (same pipeline as app_reid_top5)."""

__all__ = ["run_set_to_set_reid"]


def run_set_to_set_reid(*args, **kwargs):
    from ai_core.reid_engine import run_set_to_set_reid as _fn

    return _fn(*args, **kwargs)
