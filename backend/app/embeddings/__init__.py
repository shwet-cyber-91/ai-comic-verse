"""Image and text embeddings for character memory and continuity.

Two backends behind one interface:
  * ``ClipEmbedder``     - real CLIP, when torch + open_clip are installed
  * ``FallbackEmbedder`` - a 256-d normalised perceptual descriptor (16x16 luma)
                           plus a 32-bin hue histogram. Always available, and
                           good enough to separate "same character, different
                           panel" from "different image entirely".
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional, Protocol, Sequence

import numpy as np
from PIL import Image, ImageOps

from ..config import get_settings
from ..logging_config import get_logger

log = get_logger("embeddings")


class Embedder(Protocol):
    name: str
    dim: int

    def embed_image(self, path: str) -> list[float]: ...

    def embed_pil(self, image: Image.Image) -> list[float]: ...


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    va = np.asarray(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    if va.size == 0 or vb.size == 0 or va.size != vb.size:
        return 0.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    if denom == 0.0:
        return 0.0
    return float(np.dot(va, vb) / denom)


class FallbackEmbedder:
    """Deterministic perceptual descriptor. No model, no download, no GPU."""

    name = "fallback"
    dim = 288

    def embed_image(self, path: str) -> list[float]:
        try:
            with Image.open(path) as handle:
                return self.embed_pil(handle.convert("RGB"))
        except Exception as exc:
            log.warning("could not embed %s: %s", path, exc)
            return [0.0] * self.dim

    def embed_pil(self, image: Image.Image) -> list[float]:
        rgb = image.convert("RGB")

        # structure: 16x16 luma, mean-centred and L2-normalised
        small = ImageOps.autocontrast(ImageOps.grayscale(rgb)).resize((16, 16), Image.LANCZOS)
        luma = np.asarray(small, dtype=np.float32).reshape(-1) / 255.0
        luma = luma - luma.mean()
        norm = float(np.linalg.norm(luma))
        if norm > 1e-6:
            luma = luma / norm

        # colour: 32-bin hue histogram weighted by saturation
        hsv = np.asarray(rgb.resize((64, 64), Image.LANCZOS).convert("HSV"), dtype=np.float32)
        hue = (hsv[..., 0] / 255.0 * 32).astype(np.int32).clip(0, 31)
        sat = hsv[..., 1] / 255.0
        hist = np.bincount(hue.reshape(-1), weights=sat.reshape(-1), minlength=32).astype(np.float32)
        total = float(hist.sum())
        if total > 1e-6:
            hist = hist / total

        vector = np.concatenate([luma, hist])
        if vector.size != self.dim:
            vector = np.resize(vector, self.dim)
        return vector.astype(np.float32).tolist()

    def embed_text(self, text: str) -> list[float]:
        """Hash-based stand-in so the interface is uniform; unused for matching."""
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        seed = int.from_bytes(digest[:8], "big")
        rng = np.random.default_rng(seed)
        return rng.standard_normal(self.dim).astype(np.float32).tolist()


class ClipEmbedder:
    """Real CLIP via open_clip. Imported lazily so torch stays optional."""

    name = "clip"
    _MODEL_NAME = "ViT-B-32"
    _PRETRAINED = "laion2b_s34b_b79k"

    def __init__(self) -> None:
        import open_clip  # noqa: F401  (raises ImportError when missing)
        import torch

        self._torch = torch
        self._open_clip = open_clip
        self._model, _, self._preprocess = open_clip.create_model_and_transforms(
            self._MODEL_NAME, pretrained=self._PRETRAINED
        )
        self._model.eval()
        self.dim = int(getattr(self._model, "embed_dim", 512))

    def _encode(self, batch) -> list[float]:
        with self._torch.no_grad():
            features = self._model.encode_image(batch)
            features = features / features.norm(dim=-1, keepdim=True)
        return features[0].cpu().numpy().astype(np.float32).tolist()

    def embed_image(self, path: str) -> list[float]:
        try:
            with Image.open(path) as handle:
                return self.embed_pil(handle.convert("RGB"))
        except Exception as exc:
            log.warning("could not embed %s: %s", path, exc)
            return [0.0] * self.dim

    def embed_pil(self, image: Image.Image) -> list[float]:
        tensor = self._preprocess(image.convert("RGB")).unsqueeze(0)
        return self._encode(tensor)

    def embed_text(self, text: str) -> list[float]:
        tokens = self._open_clip.tokenize([text])
        with self._torch.no_grad():
            features = self._model.encode_text(tokens)
            features = features / features.norm(dim=-1, keepdim=True)
        return features[0].cpu().numpy().astype(np.float32).tolist()


_embedder: Optional[Embedder] = None


def clip_available() -> bool:
    try:
        import open_clip  # noqa: F401
        import torch  # noqa: F401
    except Exception:
        return False
    return True


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is not None:
        return _embedder

    requested = (get_settings().embedding_backend or "auto").lower()
    if requested == "fallback":
        _embedder = FallbackEmbedder()
    elif requested == "clip":
        try:
            _embedder = ClipEmbedder()
        except Exception as exc:
            log.warning("EMBEDDING_BACKEND=clip but CLIP is unavailable (%s); using fallback", exc)
            _embedder = FallbackEmbedder()
    else:  # auto
        if clip_available():
            try:
                _embedder = ClipEmbedder()
            except Exception as exc:
                log.warning("failed to initialise CLIP (%s); using fallback embedder", exc)
                _embedder = FallbackEmbedder()
        else:
            _embedder = FallbackEmbedder()

    log.info("embedder: %s (dim=%d)", _embedder.name, _embedder.dim)
    return _embedder


def embedder_name() -> str:
    return get_embedder().name


def reset_embedder() -> None:
    global _embedder
    _embedder = None


def resolve_image_path(path_str: str | None) -> Optional[Path]:
    if not path_str:
        return None
    candidate = Path(path_str)
    if candidate.exists():
        return candidate
    fallback = get_settings().storage_dir / path_str
    return fallback if fallback.exists() else None
