"""저화질 고문서 스캔본을 위한 이미지 전처리.

파이프라인 단계 (모두 옵션으로 on/off 가능):
  1. 그레이스케일 변환
  2. 디노이즈 (fastNlMeansDenoising)
  3. 업스케일 (해상도가 낮을 때 cubic 보간 확대)
  4. 디스큐 (기운 문서를 수평으로 보정)
  5. 이진화 (Sauvola 적응형 임계값; 미설치 시 OpenCV adaptive 폴백)

PP-OCR 계열은 자연 이미지(그레이/컬러)에서 잘 동작하므로 이진화는 기본 OFF다.
흐릿한 활자에서 이진화가 획을 끊어 인식률을 떨어뜨리기 때문(실측 확인).
얼룩·번짐이 심한 문서에서만 UI에서 켠다. 각 단계는 독립적으로 토글된다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

try:  # Sauvola 이진화는 scikit-image가 있을 때만
    from skimage.filters import threshold_sauvola

    _HAS_SKIMAGE = True
except Exception:  # pragma: no cover - 선택적 의존성
    _HAS_SKIMAGE = False


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass
class PreprocessOptions:
    """전처리 단계 토글 + 미세조정 파라미터.

    모든 수치 파라미터의 기본값은 '항등'(밝기0·대비1·감마1·샤픈0)이거나 기존과
    동일(디노이즈강도10·Sauvola k 0.2)이라, 기본값에서는 동작이 이전과 같다.
    문서마다 색감·선명도가 다르므로 UI에서 미세조정할 수 있다.
    """

    grayscale: bool = True
    denoise: bool = True
    upscale: bool = True
    deskew: bool = True
    # 이진화는 기본 OFF. 흐릿한 고문서(얇은 활자)에서는 Sauvola/adaptive 이진화가
    # 획을 끊어 인식률을 크게 떨어뜨린다(실측: 고신뢰 줄 50→14). PP-OCRv5는
    # 그레이/컬러 입력에서 더 잘 동작한다. 얼룩이 심한 문서에서만 UI로 켠다.
    binarize: bool = False

    # ── 미세조정(사진 보정 느낌) ──
    brightness: float = 0.0    # -100 ~ +100 (밝기 가감)
    contrast: float = 1.0      # 0.5 ~ 2.5  (대비 배율)
    gamma: float = 1.0         # 0.4 ~ 2.5  (>1 밝게, <1 어둡게 — 흐린 획 살리기)
    sharpen: float = 0.0       # 0 ~ 2.0    (언샤프 강도)
    denoise_strength: int = 10  # 디노이즈 세기(h). 클수록 강함(획 손상 위험)
    sauvola_k: float = 0.2     # 이진화 임계 계수(작을수록 더 검게)

    # 업스케일 목표: 긴 변이 이 픽셀보다 작으면 확대
    upscale_min_long_edge: int = 1600
    # 업스케일 최대 배율 (과도한 확대 방지)
    upscale_max_factor: float = 3.0

    _NUMERIC = {  # 필드: (저값, 고값)
        "brightness": (-100.0, 100.0), "contrast": (0.5, 2.5),
        "gamma": (0.4, 2.5), "sharpen": (0.0, 2.0),
        "denoise_strength": (0.0, 30.0), "sauvola_k": (0.05, 0.5),
    }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PreprocessOptions":
        data = data or {}
        opt = cls()
        for field in ("grayscale", "denoise", "upscale", "deskew", "binarize"):
            if field in data and data[field] is not None:
                v = data[field]
                opt.__dict__[field] = v if isinstance(v, bool) else \
                    str(v).strip().lower() in ("1", "true", "on", "yes")
        for field, (lo, hi) in cls._NUMERIC.items():
            if field in data and data[field] not in (None, ""):
                try:
                    val = _clamp(float(data[field]), lo, hi)
                    opt.__dict__[field] = int(val) if field == "denoise_strength" else val
                except (TypeError, ValueError):
                    pass
        return opt

    def to_dict(self) -> dict[str, Any]:
        return {
            "grayscale": self.grayscale, "denoise": self.denoise,
            "upscale": self.upscale, "deskew": self.deskew,
            "binarize": self.binarize, "brightness": self.brightness,
            "contrast": self.contrast, "gamma": self.gamma,
            "sharpen": self.sharpen, "denoise_strength": self.denoise_strength,
            "sauvola_k": self.sauvola_k,
        }


def _to_gray(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return img


def _upscale(gray: np.ndarray, opt: PreprocessOptions) -> np.ndarray:
    h, w = gray.shape[:2]
    long_edge = max(h, w)
    if long_edge >= opt.upscale_min_long_edge:
        return gray
    factor = min(opt.upscale_min_long_edge / long_edge, opt.upscale_max_factor)
    new_size = (int(round(w * factor)), int(round(h * factor)))
    return cv2.resize(gray, new_size, interpolation=cv2.INTER_CUBIC)


def _estimate_skew_angle(gray: np.ndarray) -> float:
    """글자 픽셀의 최소 외접 사각형으로 기울기 각도(deg) 추정."""
    # 글자가 흰 배경에 어둡게 있다고 가정 -> 반전 후 이진화
    thr = cv2.threshold(gray, 0, 255,
                        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thr > 0))
    if coords.shape[0] < 50:  # 글자가 거의 없으면 보정하지 않음
        return 0.0
    angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
    # OpenCV의 각도 규약을 [-45, 45] 범위로 정규화
    if angle < -45:
        angle = 90 + angle
    elif angle > 45:
        angle = angle - 90
    return float(angle)


def _deskew(gray: np.ndarray) -> np.ndarray:
    angle = _estimate_skew_angle(gray)
    if abs(angle) < 0.3:  # 미세한 기울기는 무시
        return gray
    h, w = gray.shape[:2]
    center = (w // 2, h // 2)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        gray, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _apply_tone(gray: np.ndarray, opt: PreprocessOptions) -> np.ndarray:
    """밝기·대비·감마 보정(사진 보정 느낌). 모두 기본값이면 그대로 반환."""
    out = gray
    if opt.contrast != 1.0 or opt.brightness != 0.0:
        out = cv2.convertScaleAbs(out, alpha=opt.contrast, beta=opt.brightness)
    if opt.gamma != 1.0:
        inv = 1.0 / max(opt.gamma, 1e-3)
        lut = np.array([((i / 255.0) ** inv) * 255 for i in range(256)],
                       dtype=np.uint8)
        out = cv2.LUT(out, lut)
    return out


def _sharpen(gray: np.ndarray, amount: float) -> np.ndarray:
    """언샤프 마스킹으로 윤곽을 또렷하게. amount=0이면 그대로."""
    if amount <= 0:
        return gray
    blur = cv2.GaussianBlur(gray, (0, 0), sigmaX=2.0)
    return cv2.addWeighted(gray, 1.0 + amount, blur, -amount, 0)


def _binarize(gray: np.ndarray, k: float = 0.2) -> np.ndarray:
    if _HAS_SKIMAGE:
        # Sauvola: 조명/얼룩이 불균일한 고문서에 강함. k가 작을수록 더 검게.
        window = 25
        try:
            thr = threshold_sauvola(gray, window_size=window, k=k)
            binary = (gray > thr).astype(np.uint8) * 255
            return binary
        except Exception:
            pass  # 폴백으로 진행
    # OpenCV adaptive Gaussian 폴백
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY, 31, 10,
    )


def preprocess_image(img: np.ndarray, opt: PreprocessOptions) -> np.ndarray:
    """단일 이미지(BGR 또는 그레이)를 전처리해 OCR 입력 이미지를 반환.

    반환 이미지는 단일 채널(그레이/이진) 또는 원본 BGR일 수 있다.
    PaddleOCR은 양쪽 모두 받아들인다.
    """
    out = img
    tone_changed = (opt.brightness != 0.0 or opt.contrast != 1.0
                    or opt.gamma != 1.0 or opt.sharpen > 0)
    if (opt.grayscale or opt.denoise or opt.upscale or opt.deskew
            or opt.binarize or tone_changed):
        out = _to_gray(out)

    out = _apply_tone(out, opt)            # 밝기·대비·감마
    if opt.denoise and opt.denoise_strength > 0:
        out = cv2.fastNlMeansDenoising(out, h=int(opt.denoise_strength),
                                       templateWindowSize=7, searchWindowSize=21)
    out = _sharpen(out, opt.sharpen)       # 언샤프
    if opt.upscale:
        out = _upscale(out, opt)
    if opt.deskew:
        out = _deskew(out)
    if opt.binarize:
        out = _binarize(out, k=opt.sauvola_k)
    return out
