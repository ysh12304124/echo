"""
# =============================================================================
# SCRFD Face Detection Integration for DeepFace
# =============================================================================
# This module integrates InsightFace's SCRFD face detector into DeepFace's
# face detection framework. It wraps the SCRFD ONNX model into a class that
# inherits from deepface.models.Detector.Detector ABC.
#
# Usage (after registration �� see INSTALL.md):
#   from deepface import DeepFace
#   result = DeepFace.extract_faces(img_path="photo.jpg", detector_backend="scrfd")
#
# Dependencies:
#   pip install onnxruntime numpy opencv-python
#
# Model download:
#   SCRFD models are bundled inside "buffalo_*.zip" packs on InsightFace's
#   v0.7 GitHub release. This module automatically downloads the correct
#   buffalo pack and extracts the detection model.
#
#   buffalo_s.zip  �� det_500m.onnx  �� SCRFD 500M (with keypoints, ~2.5MB)
#   buffalo_m.zip  �� det_2.5g.onnx  �� SCRFD 2.5G (with keypoints, ~5MB)
#   buffalo_l.zip  �� det_10g.onnx   �� SCRFD 10G  (with keypoints, ~18MB)
#
# =============================================================================
"""

# built-in dependencies
import os
import zipfile
from typing import List, Optional, Tuple, Any

# 3rd party dependencies
import numpy as np
from numpy.typing import NDArray
import cv2

# project dependencies (DeepFace)
from deepface.commons import weight_utils, folder_utils
from deepface.models.Detector import Detector, FacialAreaRegion
from deepface.commons.logger import Logger

logger = Logger()


# =============================================================================
# Part 1:  SCRFD �����������棨��ȡ�� InsightFace SCRFD��
# =============================================================================

def _softmax(z: NDArray[Any]) -> NDArray[Any]:
    """2D softmax over axis=1."""
    s = np.max(z, axis=1, keepdims=True)
    e_x = np.exp(z - s)
    return e_x / np.sum(e_x, axis=1, keepdims=True)


def _distance2bbox(
    points: NDArray[Any],
    distance: NDArray[Any],
    max_shape: Optional[Tuple[int, int]] = None,
) -> NDArray[Any]:
    """Decode distance prediction to bounding box (x1, y1, x2, y2)."""
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    if max_shape is not None:
        x1 = np.clip(x1, 0, max_shape[1])
        y1 = np.clip(y1, 0, max_shape[0])
        x2 = np.clip(x2, 0, max_shape[1])
        y2 = np.clip(y2, 0, max_shape[0])
    return np.stack([x1, y1, x2, y2], axis=-1)


def _distance2kps(
    points: NDArray[Any],
    distance: NDArray[Any],
    max_shape: Optional[Tuple[int, int]] = None,
) -> NDArray[Any]:
    """Decode distance prediction to keypoints (x0,y0,...,x4,y4)."""
    preds: List[NDArray[Any]] = []
    for i in range(0, distance.shape[1], 2):
        px = points[:, i % 2] + distance[:, i]
        py = points[:, i % 2 + 1] + distance[:, i + 1]
        if max_shape is not None:
            px = np.clip(px, 0, max_shape[1])
            py = np.clip(py, 0, max_shape[0])
        preds.append(px)
        preds.append(py)
    return np.stack(preds, axis=-1)


class ScrfdEngine:
    """
    ONNX-based SCRFD inference engine.

    Supports both batched and non-batched ONNX models with 6, 9, 10, or 15
    output tensors.
    """

    def __init__(
        self,
        model_file: Optional[str] = None,
        session: Optional[Any] = None,
    ) -> None:
        import onnxruntime

        self.model_file = model_file
        self.session = session
        self.batched = False
        self.taskname = "detection"

        if self.session is None:
            assert self.model_file is not None and os.path.exists(self.model_file), (
                f"SCRFD model file not found: {model_file}"
            )
            providers = onnxruntime.get_available_providers()
        self.session = onnxruntime.InferenceSession(
            self.model_file,
            providers=providers,
        )

        self.center_cache: dict = {}
        self.nms_thresh = 0.4
        self._init_vars()

    def _init_vars(self) -> None:
        input_cfg = self.session.get_inputs()[0]
        input_shape = input_cfg.shape

        if isinstance(input_shape[2], str):
            self.input_size: Optional[Tuple[int, int]] = None
        else:
            self.input_size = tuple(input_shape[2:4][::-1])

        self.input_name = input_cfg.name
        outputs = self.session.get_outputs()

        if outputs and len(outputs[0].shape) == 3:
            self.batched = True

        self.output_names = [o.name for o in outputs]
        self.use_kps = False
        self._num_anchors = 1
        self.fmc = 3
        self._feat_stride_fpn = [8, 16, 32]

        num_outputs = len(outputs)
        if num_outputs == 6:
            self.fmc = 3
            self._feat_stride_fpn = [8, 16, 32]
            self._num_anchors = 2
        elif num_outputs == 9:
            self.fmc = 3
            self._feat_stride_fpn = [8, 16, 32]
            self._num_anchors = 2
            self.use_kps = True
        elif num_outputs == 10:
            self.fmc = 5
            self._feat_stride_fpn = [8, 16, 32, 64, 128]
            self._num_anchors = 1
        elif num_outputs == 15:
            self.fmc = 5
            self._feat_stride_fpn = [8, 16, 32, 64, 128]
            self._num_anchors = 1
            self.use_kps = True
        else:
            raise ValueError(
                f"Unexpected number of SCRFD outputs: {num_outputs}. "
                "Expected 6, 9, 10, or 15."
            )

    def prepare(
        self, ctx_id: int = -1,
        nms_thresh: Optional[float] = None,
        input_size: Optional[Tuple[int, int]] = None,
    ) -> None:
        if ctx_id >= 0:
            self.session.set_providers(
                [
                    "CUDAExecutionProvider",
                    "CPUExecutionProvider"
                ]
            )
        else:
            self.session.set_providers(
                ["CPUExecutionProvider"]
            )
        if nms_thresh is not None:
            self.nms_thresh = nms_thresh
        if input_size is not None:
            if self.input_size is not None:
                logger.debug("input_size already set, ignoring custom size")
            else:
                self.input_size = input_size

    def detect(
        self,
        img: NDArray[Any],
        thresh: float = 0.5,
        input_size: Optional[Tuple[int, int]] = None,
        max_num: int = 0,
        metric: str = "default",
    ) -> Tuple[NDArray[Any], Optional[NDArray[Any]]]:
        target_size = input_size if input_size is not None else self.input_size
        assert target_size is not None, "input_size must be provided"

        im_ratio = float(img.shape[0]) / img.shape[1]
        model_ratio = float(target_size[1]) / target_size[0]

        if im_ratio > model_ratio:
            new_height = target_size[1]
            new_width = int(new_height / im_ratio)
        else:
            new_width = target_size[0]
            new_height = int(new_width * im_ratio)

        det_scale = float(new_height) / img.shape[0]
        resized_img = cv2.resize(img, (new_width, new_height))
        det_img = np.zeros((target_size[1], target_size[0], 3), dtype=np.uint8)
        det_img[:new_height, :new_width, :] = resized_img

        scores_list, bboxes_list, kpss_list = self._forward(det_img, thresh)

        if len(scores_list) == 0 or sum(s.size for s in scores_list) == 0:
            return np.empty((0, 5), dtype=np.float32), None

        scores = np.vstack(scores_list)
        scores_ravel = scores.ravel()
        order = scores_ravel.argsort()[::-1]
        bboxes = np.vstack(bboxes_list) / det_scale

        if self.use_kps and kpss_list:
            kpss_all = np.vstack(kpss_list) / det_scale
        else:
            kpss_all = None

        pre_det = np.hstack((bboxes, scores)).astype(np.float32, copy=False)
        pre_det = pre_det[order, :]

        keep = self._nms(pre_det)
        det = pre_det[keep, :]

        if kpss_all is not None:
            kpss_all = kpss_all[order, :, :]
            kpss_all = kpss_all[keep, :, :]

        if max_num > 0 and det.shape[0] > max_num:
            area = (det[:, 2] - det[:, 0]) * (det[:, 3] - det[:, 1])
            img_center = img.shape[0] // 2, img.shape[1] // 2
            offsets = np.vstack([
                (det[:, 0] + det[:, 2]) / 2 - img_center[1],
                (det[:, 1] + det[:, 3]) / 2 - img_center[0],
            ])
            offset_dist_squared = np.sum(np.power(offsets, 2.0), 0)
            values = area if metric == "max" else area - offset_dist_squared * 2.0
            bindex = np.argsort(values)[::-1][0:max_num]
            det = det[bindex, :]
            if kpss_all is not None:
                kpss_all = kpss_all[bindex, :]

        return det, kpss_all

    def _forward(
        self, img: NDArray[Any], thresh: float
    ) -> Tuple[List[NDArray[Any]], List[NDArray[Any]], List[NDArray[Any]]]:
        scores_list: List[NDArray[Any]] = []
        bboxes_list: List[NDArray[Any]] = []
        kpss_list: List[NDArray[Any]] = []

        input_size = tuple(img.shape[0:2][::-1])
        blob = cv2.dnn.blobFromImage(
            img, 1.0 / 128, input_size, (127.5, 127.5, 127.5), swapRB=True
        )
        net_outs = self.session.run(self.output_names, {self.input_name: blob})

        input_height = blob.shape[2]
        input_width = blob.shape[3]
        fmc = self.fmc

        for idx, stride in enumerate(self._feat_stride_fpn):
            if self.batched:
                scores = net_outs[idx][0]
                bbox_preds = net_outs[idx + fmc][0] * stride
                kps_preds = net_outs[idx + fmc * 2][0] * stride if self.use_kps else None
            else:
                scores = net_outs[idx]
                bbox_preds = net_outs[idx + fmc] * stride
                kps_preds = net_outs[idx + fmc * 2] * stride if self.use_kps else None

            height = input_height // stride
            width = input_width // stride
            anchor_key = (height, width, stride)

            if anchor_key in self.center_cache:
                anchor_centers = self.center_cache[anchor_key]
            else:
                anchor_centers = np.stack(
                    np.mgrid[:height, :width][::-1], axis=-1
                ).astype(np.float32)
                anchor_centers = anchor_centers.reshape((-1, 2)) * stride
                if self._num_anchors > 1:
                    anchor_centers = np.stack(
                        [anchor_centers] * self._num_anchors, axis=1
                    ).reshape((-1, 2))
                if len(self.center_cache) < 100:
                    self.center_cache[anchor_key] = anchor_centers

            pos_inds = np.where(scores >= thresh)[0]
            bboxes = _distance2bbox(anchor_centers, bbox_preds)

            scores_list.append(scores[pos_inds])
            bboxes_list.append(bboxes[pos_inds])

            if self.use_kps and kps_preds is not None:
                kpss = _distance2kps(anchor_centers, kps_preds)
                kpss = kpss.reshape((kpss.shape[0], -1, 2))
                kpss_list.append(kpss[pos_inds])

        return scores_list, bboxes_list, kpss_list

    @staticmethod
    def _nms(dets: NDArray[Any]) -> List[int]:
        thresh = 0.4
        x1 = dets[:, 0]
        y1 = dets[:, 1]
        x2 = dets[:, 2]
        y2 = dets[:, 3]
        scores = dets[:, 4]
        areas = (x2 - x1 + 1) * (y2 - y1 + 1)
        order = scores.argsort()[::-1]
        keep: List[int] = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0.0, xx2 - xx1 + 1)
            h = np.maximum(0.0, yy2 - yy1 + 1)
            inter = w * h
            ovr = inter / (areas[i] + areas[order[1:]] - inter)
            inds = np.where(ovr <= thresh)[0]
            order = order[inds + 1]
        return keep


# =============================================================================
# Part 2:  SCRFD ģ�����أ��� buffalo ����ļ�����ȡ��
# =============================================================================

# ע�⣺GitHub v0.7 release ��û�ж����� scrfd_*.onnx �ļ�
# SCRFD ���ģ�ͱ������ buffalo_*.zip �У�����Ƕ�ļ���Ϊ det_*.onnx
# ���ص�ַ��
#   https://github.com/deepinsight/insightface/releases/download/v0.7/

BUFFALO_RELEASE_URL = (
    "https://github.com/deepinsight/insightface/releases/download/v0.7"
)

# buffalo pack ӳ���: variant -> (zip_name, inner_file, output_name)
SCRFD_PACK_MAP = {
    "500m": ("buffalo_s.zip", "det_500m.onnx", "scrfd_500m_bnkps.onnx"),
    "2.5g": ("buffalo_m.zip", "det_2.5g.onnx", "scrfd_2.5g_bnkps.onnx"),
    "10g":  ("buffalo_l.zip", "det_10g.onnx",  "scrfd_10g_bnkps.onnx"),
}

# �Ƽ�����ߴ�
SCRFD_INPUT_SIZES = {
    "500m": (640, 640),
    "2.5g": (640, 640),
    "10g":  (1024, 1024),
}


def download_scrfd_model(
    variant: str,
    target_dir: Optional[str] = None,
) -> str:
    """
    �� InsightFace v0.7 release ���� buffalo ������ȡ SCRFD ģ�͡�

    Args:
        variant: ģ�ͱ��� "500m" | "2.5g" | "10g"
        target_dir: ���Ŀ¼��Ĭ�� ~/.deepface/weights/

    Returns:
        ��ȡ���� .onnx �ļ�����·��
    """
    if target_dir is None:
        target_dir = folder_utils.get_weights_path()
    os.makedirs(target_dir, exist_ok=True)

    if variant not in SCRFD_PACK_MAP:
        raise ValueError(
            f"Unknown SCRFD variant: {variant}. "
            f"Choose from: {list(SCRFD_PACK_MAP.keys())}"
        )

    zip_name, inner_file, output_name = SCRFD_PACK_MAP[variant]
    output_path = os.path.join(target_dir, output_name)

    # �Ѿ�������ֱ�ӷ���
    if os.path.isfile(output_path):
        logger.debug(f"SCRFD {variant} already exists at {output_path}")
        return output_path

    # ���� buffalo zip ��
    zip_url = f"{BUFFALO_RELEASE_URL}/{zip_name}"
    zip_path = os.path.join(target_dir, zip_name)

    if not os.path.isfile(zip_path):
        logger.info(f"Downloading {zip_name} from {zip_url} ...")
        try:
            import urllib.request
            import ssl

            ctx = ssl._create_unverified_context()
            req = urllib.request.Request(zip_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=ctx, timeout=300) as resp:
                data = resp.read()
                with open(zip_path, "wb") as f:
                    f.write(data)
            logger.info(f"Downloaded {zip_name} ({len(data) // 1024} KB)")
        except Exception as e:
            raise RuntimeError(
                f"Failed to download {zip_url}: {e}\n"
                f"Please manually download {zip_name} from:\n"
                f"  {zip_url}\n"
                f"and extract {inner_file}, rename to {output_name},\n"
                f"then place it in {target_dir}"
            ) from e

    # ��ȡ SCRFD ģ��
    try:
        with zipfile.ZipFile(zip_path) as zf:
            if inner_file not in zf.namelist():
                raise ValueError(
                    f"{inner_file} not found in {zip_name}. "
                    f"Contents: {zf.namelist()}"
                )
            zf.extract(inner_file, target_dir)
        os.replace(
            os.path.join(target_dir, inner_file),
            output_path,
        )
        logger.info(f"Extracted {inner_file} -> {output_name}")
    except Exception as e:
        raise RuntimeError(
            f"Failed to extract {inner_file} from {zip_name}: {e}"
        ) from e
    finally:
        # ���� zip ��
        if os.path.isfile(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass

    return output_path


# =============================================================================
# Part 3:  DeepFace �������װ��
# =============================================================================


class ScrfdClient(Detector):
    """
    DeepFace-compatible SCRFD face detector wrapper.

    Usage:
        detector = ScrfdClient(model_variant="500m")
        regions = detector.detect_faces(img_bgr_array)

    Or after registering in modeling.py:
        DeepFace.extract_faces("photo.jpg", detector_backend="scrfd")
    """

    def __init__(
        self,
        model_variant: str = "500m",
        model_path: Optional[str] = None,
        confidence_threshold: float = 0.5,
        input_size: Optional[Tuple[int, int]] = None,
    ) -> None:
        """
        Args:
            model_variant: "500m" | "2.5g" | "10g". Ignored if model_path set.
            model_path: Direct path to an ONNX file. Overrides model_variant.
            confidence_threshold: Score threshold for detection.
            input_size: Inference resolution (W, H). Default per variant.
        """
        self.model_variant = model_variant
        self.confidence_threshold = confidence_threshold

        if model_path is not None:
            self.model_path = model_path
        else:
            self.model_path = download_scrfd_model(variant=model_variant)

        self.input_size = input_size or SCRFD_INPUT_SIZES.get(model_variant, (640, 640))
        self._engine: Optional[ScrfdEngine] = None

    def _ensure_engine(self) -> ScrfdEngine:
        if self._engine is None:
            logger.debug(f"Building SCRFD engine (variant={self.model_variant})")
            self._engine = ScrfdEngine(model_file=self.model_path)
            self._engine.prepare(ctx_id=0)
        return self._engine

    def detect_faces(self, img: NDArray[Any]) -> List[FacialAreaRegion]:
        """
        Detect faces in an image.

        Args:
            img: Pre-loaded BGR image as numpy array (H, W, 3).

        Returns:
            List of FacialAreaRegion objects with bounding box, keypoints,
            and confidence score.
        """
        engine = self._ensure_engine()
        results: List[FacialAreaRegion] = []

        detections, keypoints = engine.detect(
            img,
            thresh=self.confidence_threshold,
            input_size=self.input_size,
        )

        num_faces = detections.shape[0]

        for i in range(num_faces):
            x1, y1, x2, y2, score = detections[i]

            x = int(round(x1))
            y = int(round(y1))
            w = int(round(x2 - x1))
            h = int(round(y2 - y1))

            img_h, img_w = img.shape[:2]
            x = max(0, min(x, img_w - 1))
            y = max(0, min(y, img_h - 1))
            w = min(w, img_w - x)
            h = min(h, img_h - y)

            confidence = min(max(float(score), 0.0), 1.0)

            left_eye = None
            right_eye = None
            nose = None
            mouth_left = None
            mouth_right = None

            if keypoints is not None and i < keypoints.shape[0]:
                kps = keypoints[i]
                # SCRFD 5 ��˳��: left_eye, right_eye, nose, mouth_left, mouth_right
                if kps.shape[0] >= 2:
                    left_eye = (int(round(kps[0, 0])), int(round(kps[0, 1])))
                    right_eye = (int(round(kps[1, 0])), int(round(kps[1, 1])))
                if kps.shape[0] >= 3:
                    nose = (int(round(kps[2, 0])), int(round(kps[2, 1])))
                if kps.shape[0] >= 5:
                    mouth_left = (int(round(kps[3, 0])), int(round(kps[3, 1])))
                    mouth_right = (int(round(kps[4, 0])), int(round(kps[4, 1])))

            facial_area = FacialAreaRegion(
                x=x,
                y=y,
                w=w,
                h=h,
                left_eye=left_eye,
                right_eye=right_eye,
                confidence=confidence,
                nose=nose,
                mouth_left=mouth_left,
                mouth_right=mouth_right,
            )
            results.append(facial_area)

        return results


# =============================================================================
# Part 4:  ����ʹ��ʾ��
# =============================================================================
#
# ���з�ʽ��
#   pip install onnxruntime
#   python Scrfd.py --image photo.jpg --variant 500m


def run_demo(image_path: str, variant: str = "500m") -> None:
    """Detect faces and draw bounding boxes + keypoints."""
    detector = ScrfdClient(model_variant=variant)
    img = cv2.imread(image_path)

    if img is None:
        print(f"Error: Could not load image from {image_path}")
        return

    print(f"Image shape: {img.shape}")
    regions = detector.detect_faces(img)
    print(f"Detected {len(regions)} face(s)")

    for idx, region in enumerate(regions):
        cv2.rectangle(
            img,
            (region.x, region.y),
            (region.x + region.w, region.y + region.h),
            (0, 255, 0),
            2,
        )
        for point in [region.left_eye, region.right_eye,
                      region.nose, region.mouth_left, region.mouth_right]:
            if point is not None:
                cv2.circle(img, point, 3, (0, 0, 255), -1)
        label = f"SCRFD: {region.confidence:.2f}"
        cv2.putText(
            img, label, (region.x, region.y - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1,
        )
        print(f"  Face {idx + 1}: x={region.x}, y={region.y}, "
              f"w={region.w}, h={region.h}, confidence={region.confidence:.3f}")

    output_path = f"scrfd_output_{os.path.basename(image_path)}"
    cv2.imwrite(output_path, img)
    print(f"Output saved to {output_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SCRFD face detection demo")
    parser.add_argument("--image", type=str, required=True, help="Input image path")
    parser.add_argument(
        "--variant", type=str, default="500m",
        choices=list(SCRFD_PACK_MAP.keys()),
        help="SCRFD model variant",
    )
    args = parser.parse_args()
    run_demo(args.image, args.variant)
