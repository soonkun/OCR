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


@dataclass
class PreprocessOptions:
    """전처리 단계 토글. 기본값은 고문서 복원에 적합한 설정."""

    grayscale: bool = True
    denoise: bool = True
    upscale: bool = True
    deskew: bool = True
    # 이진화는 기본 OFF. 흐릿한 고문서(얇은 활자)에서는 Sauvola/adaptive 이진화가
    # 획을 끊어 인식률을 크게 떨어뜨린다(실측: 고신뢰 줄 50→14). PP-OCRv5는
    # 그레이/컬러 입력에서 더 잘 동작한다. 얼룩이 심한 문서에서만 UI로 켠다.
    binarize: bool = False

    # 업스케일 목표: 긴 변이 이 픽셀보다 작으면 확대
    upscale_min_long_edge: int = 1600
    # 업스케일 최대 배율 (과도한 확대 방지)
    upscale_max_factor: float = 3.0

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PreprocessOptions":
        data = data or {}
        opt = cls()
        for field in ("grayscale", "denoise", "upscale", "deskew", "binarize"):
            if field in data:
                opt.__dict__[field] = bool(data[field])
        return opt

    def to_dict(self) -> dict[str, Any]:
        return {
            "grayscale": self.grayscale,
            "denoise": self.denoise,
            "upscale": self.upscale,
            "deskew": self.deskew,
            "binarize": self.binarize,
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


def _binarize(gray: np.ndarray) -> np.ndarray:
    if _HAS_SKIMAGE:
        # Sauvola: 조명/얼룩이 불균일한 고문서에 강함
        window = 25
        try:
            thr = threshold_sauvola(gray, window_size=window, k=0.2)
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
    if opt.grayscale or opt.denoise or opt.upscale or opt.deskew or opt.binarize:
        out = _to_gray(out)

    if opt.denoise:
        out = cv2.fastNlMeansDenoising(out, h=10, templateWindowSize=7,
                                       searchWindowSize=21)
    if opt.upscale:
        out = _upscale(out, opt)
    if opt.deskew:
        out = _deskew(out)
    if opt.binarize:
        out = _binarize(out)
    return out
