"""Continuity checker.

Scores how well a generated panel still looks like the character it is supposed
to depict, using two independent signals:

  1. **Embedding similarity** - cosine between the panel and the character's
     reference/canonical images (CLIP when installed, else the perceptual
     fallback embedder).
  2. **Colour histogram correlation** - comparison over a face-region crop, using
     OpenCV HSV histograms when cv2 is available and a numpy RGB histogram
     otherwise. This catches the failure mode embeddings miss: the right subject
     rendered in the wrong palette.

The panel passes when the weighted score clears ``CONTINUITY_THRESHOLD``.
Failing panels are handed back to the graph for regeneration, up to
``CONTINUITY_MAX_RETRIES`` rounds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

from ..config import get_settings
from ..embeddings import cosine_similarity, get_embedder
from ..logging_config import get_logger

log = get_logger("continuity")


def cv2_available() -> bool:
    try:
        import cv2  # noqa: F401
    except Exception:
        return False
    return True


@dataclass
class ContinuityScore:
    panel_id: str
    score: float
    embedding_score: float
    colour_score: float
    face_found: bool
    best_reference: str | None = None
    passed: bool = False
    details: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 4),
            "embedding_score": round(self.embedding_score, 4),
            "colour_score": round(self.colour_score, 4),
            "face_found": self.face_found,
            "best_reference": self.best_reference,
            "passed": self.passed,
        }


class ContinuityChecker:
    def __init__(
        self,
        threshold: float | None = None,
        clip_weight: float | None = None,
        max_retries: int | None = None,
    ) -> None:
        settings = get_settings()
        self.threshold = settings.continuity_threshold if threshold is None else threshold
        self.clip_weight = settings.continuity_clip_weight if clip_weight is None else clip_weight
        self.max_retries = settings.continuity_max_retries if max_retries is None else max_retries
        self.embedder = get_embedder()
        self._cascade = None

    # -- public ------------------------------------------------------------
    def score_panel(
        self,
        panel_id: str,
        panel_image: str | Path,
        reference_images: Sequence[str],
    ) -> ContinuityScore:
        panel_path = Path(panel_image)
        if not panel_path.exists():
            log.warning("continuity: panel image %s is missing", panel_path)
            return ContinuityScore(
                panel_id=panel_id,
                score=0.0,
                embedding_score=0.0,
                colour_score=0.0,
                face_found=False,
                passed=False,
                details={"error": "panel image not found"},
            )

        usable = [Path(p) for p in reference_images if p and Path(p).exists()]
        if not usable:
            # Nothing to compare against: treat as passed so the pipeline does not
            # spin regenerating a panel that has no character reference at all.
            return ContinuityScore(
                panel_id=panel_id,
                score=1.0,
                embedding_score=1.0,
                colour_score=1.0,
                face_found=False,
                passed=True,
                details={"skipped": "no reference images for this panel"},
            )

        try:
            panel_image_obj = Image.open(panel_path).convert("RGB")
        except Exception as exc:
            log.warning("continuity: cannot read %s: %s", panel_path, exc)
            return ContinuityScore(
                panel_id=panel_id,
                score=0.0,
                embedding_score=0.0,
                colour_score=0.0,
                face_found=False,
                passed=False,
                details={"error": str(exc)},
            )

        panel_embedding = self.embedder.embed_pil(panel_image_obj)
        panel_face, face_found = self._face_region(panel_image_obj)

        best_embedding = 0.0
        best_colour = 0.0
        best_reference: str | None = None
        per_reference: dict[str, dict[str, float]] = {}

        for reference in usable:
            try:
                with Image.open(reference) as handle:
                    reference_image = handle.convert("RGB")
            except Exception as exc:
                log.warning("continuity: cannot read reference %s: %s", reference, exc)
                continue

            embedding_score = self._normalise_embedding(
                cosine_similarity(panel_embedding, self.embedder.embed_pil(reference_image))
            )
            reference_face, _ = self._face_region(reference_image)
            colour_score = self._colour_similarity(panel_face, reference_face)

            per_reference[reference.name] = {
                "embedding": round(embedding_score, 4),
                "colour": round(colour_score, 4),
            }
            combined = self._combine(embedding_score, colour_score)
            if combined > self._combine(best_embedding, best_colour) or best_reference is None:
                best_embedding, best_colour, best_reference = embedding_score, colour_score, reference.name

        score = self._combine(best_embedding, best_colour)
        return ContinuityScore(
            panel_id=panel_id,
            score=score,
            embedding_score=best_embedding,
            colour_score=best_colour,
            face_found=face_found,
            best_reference=best_reference,
            passed=score >= self.threshold,
            details={
                "threshold": self.threshold,
                "embedder": self.embedder.name,
                "opencv": cv2_available(),
                "per_reference": per_reference,
            },
        )

    # -- internals ---------------------------------------------------------
    def _combine(self, embedding_score: float, colour_score: float) -> float:
        weight = max(0.0, min(1.0, self.clip_weight))
        return float(weight * embedding_score + (1.0 - weight) * colour_score)

    def _normalise_embedding(self, cosine: float) -> float:
        """Map cosine onto 0..1.

        CLIP places unrelated images around 0.5-0.7 and same-subject pairs above
        ~0.85, so the raw value is rescaled rather than used directly. The
        fallback embedder spreads wider and can compress the same-character score
        too aggressively if the rescale is too steep; the adjustment below keeps
        valid matches above the threshold while preserving separation.
        """
        if self.embedder.name == "clip":
            return float(np.clip((cosine - 0.55) / 0.35, 0.0, 1.0))
        return float(np.clip((cosine - 0.05) / 0.80, 0.0, 1.0))

    def _face_region(self, image: Image.Image) -> tuple[Image.Image, bool]:
        """Crop the most face-like region, or a sensible fallback box."""
        if cv2_available():
            cascade = self._get_cascade()
            if cascade is not None:
                import cv2

                array = np.asarray(image.convert("RGB"))[:, :, ::-1]
                gray = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
                faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
                if len(faces) > 0:
                    x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
                    pad = int(0.15 * w)
                    box = (
                        max(0, x - pad),
                        max(0, y - pad),
                        min(image.width, x + w + pad),
                        min(image.height, y + h + pad),
                    )
                    return image.crop(box), True

        width, height = image.size
        return image.crop((int(width * 0.28), int(height * 0.10), int(width * 0.72), int(height * 0.55))), False

    def _get_cascade(self):
        if self._cascade is not None:
            return self._cascade
        try:
            import cv2

            path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
            cascade = cv2.CascadeClassifier(str(path))
            self._cascade = None if cascade.empty() else cascade
        except Exception as exc:
            log.debug("no Haar cascade available: %s", exc)
            self._cascade = None
        return self._cascade

    def _colour_similarity(self, a: Image.Image, b: Image.Image) -> float:
        if cv2_available():
            try:
                return self._colour_similarity_cv2(a, b)
            except Exception as exc:  # pragma: no cover - defensive
                log.debug("cv2 histogram failed (%s); using numpy", exc)
        return self._colour_similarity_numpy(a, b)

    def _colour_similarity_cv2(self, a: Image.Image, b: Image.Image) -> float:
        import cv2

        def hist(image: Image.Image) -> np.ndarray:
            small = image.resize((128, 128), Image.LANCZOS)
            hsv = cv2.cvtColor(np.asarray(small), cv2.COLOR_RGB2HSV)
            h = cv2.calcHist([hsv], [0, 1], None, [48, 48], [0, 180, 0, 256])
            cv2.normalize(h, h, 0, 1, cv2.NORM_MINMAX)
            return h

        correlation = cv2.compareHist(hist(a), hist(b), cv2.HISTCMP_CORREL)
        return float(np.clip((correlation + 1.0) / 2.0, 0.0, 1.0))

    def _colour_similarity_numpy(self, a: Image.Image, b: Image.Image) -> float:
        def hist(image: Image.Image) -> np.ndarray:
            small = image.resize((64, 64), Image.LANCZOS)
            array = np.asarray(small, dtype=np.float32)
            bins = (8, 8, 8)
            idx = (array / 256.0 * np.array(bins)).astype(np.int32)
            idx = np.clip(idx, 0, np.array(bins) - 1)
            flat = np.ravel_multi_index(
                (idx[..., 0], idx[..., 1], idx[..., 2]), bins
            ).reshape(-1)
            counts = np.bincount(flat, minlength=int(np.prod(bins))).astype(np.float32)
            total = counts.sum()
            return counts / total if total else counts

        ha, hb = hist(a), hist(b)
        mean_a, mean_b = ha.mean(), hb.mean()
        da, db = ha - mean_a, hb - mean_b
        denom = float(np.sqrt((da**2).sum() * (db**2).sum()))
        if denom == 0.0:
            return 0.0
        correlation = float((da * db).sum() / denom)
        return float(np.clip((correlation + 1.0) / 2.0, 0.0, 1.0))


_checker: ContinuityChecker | None = None


def get_checker() -> ContinuityChecker:
    global _checker
    if _checker is None:
        _checker = ContinuityChecker()
    return _checker


def reset_checker() -> None:
    global _checker
    _checker = None
