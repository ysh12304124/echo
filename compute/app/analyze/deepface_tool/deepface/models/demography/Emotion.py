# built-in dependencies
import os
from typing import List, Union, Any

import numpy as np
from numpy.typing import NDArray
import cv2

from deepface.commons import folder_utils
from deepface.models.Demography import Demography
from deepface.commons.logger import Logger

logger = Logger()

labels = ["angry", "disgust", "fear", "happy", "neutral", "sad", "surprise"]


class EmotionClient(Demography):
    def __init__(self) -> None:
        self.model_name = "Emotion"
        self.img_size = 260
        self.session = None
        self.load_model()

    def load_model(self) -> None:
        import onnxruntime
        model_path = os.path.join(folder_utils.get_weights_path(), "enet_b2_7.onnx")
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"Emotion model not found at {model_path}.")
        sess_options = onnxruntime.SessionOptions()
        sess_options.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_BASIC
        cuda_options = {"arena_extend_strategy": "kSameAsRequested", "cudnn_conv_algo_search": "HEURISTIC"}
        providers = [
            "CUDAExecutionProvider",
            "CPUExecutionProvider"
        ]
        self.session = onnxruntime.InferenceSession(
            model_path, sess_options=sess_options, providers=providers
        )
        logger.debug(f"Emotion model loaded: {model_path}")

    def _preprocess(self, img):
        x = cv2.resize(img, (self.img_size, self.img_size)).astype(np.float32)  # img is already [0, 1]
        x[..., 0] = (x[..., 0] - 0.485) / 0.229
        x[..., 1] = (x[..., 1] - 0.456) / 0.224
        x[..., 2] = (x[..., 2] - 0.406) / 0.225
        return x.transpose(2, 0, 1)[np.newaxis, ...]

    def predict(self, img):
        imgs = np.array(img)
        if imgs.ndim == 3:
            imgs = np.expand_dims(imgs, axis=0)
        results = []
        for i in range(imgs.shape[0]):
            processed = self._preprocess(imgs[i])
            logits = self.session.run(None, {"input": processed})[0][0]
            exp = np.exp(logits - np.max(logits))
            probs = exp / exp.sum()
            results.append(probs)
        return results[0] if len(results) == 1 else np.array(results)
