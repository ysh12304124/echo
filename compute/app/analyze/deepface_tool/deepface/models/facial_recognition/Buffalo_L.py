# built-in dependencies
import os
import zipfile
from typing import List, Union, Any

# third-party dependencies
import numpy as np
from numpy.typing import NDArray

# project dependencies
from deepface.commons import folder_utils
from deepface.commons.logger import Logger
from deepface.models.FacialRecognition import FacialRecognition
from deepface.modules.exceptions import InvalidEmbeddingsShapeError

logger = Logger()


class Buffalo_L(FacialRecognition):
    def __init__(self) -> None:
        self.session = None
        self.input_shape = (112, 112)
        self.output_shape = 512
        self.model_name = "Buffalo_L"
        self.input_name = None
        self.output_name = None
        self.load_model()

    def load_model(self) -> None:
        import onnxruntime

        model_file = "w600k_r50.onnx"
        zip_file = "buffalo_l.zip"
        weights_dir = folder_utils.get_weights_path()
        model_path = os.path.join(weights_dir, model_file)

        # Extract from buffalo_l.zip if not already extracted
        if not os.path.isfile(model_path):
            zip_path = os.path.join(weights_dir, zip_file)
            if os.path.isfile(zip_path):
                logger.info(f"Extracting {model_file} from {zip_file}...")
                with zipfile.ZipFile(zip_path) as zf:
                    zf.extract(model_file, weights_dir)
                logger.info(f"Extracted {model_file}")
            else:
                raise FileNotFoundError(
                    f"{model_file} not found at {model_path}. "
                    f"Please download buffalo_l.zip from "
                    f"https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip "
                    f"and place it in {weights_dir}"
                )

        logger.debug(f"Loading model from {model_path}")
        providers = [
            "CUDAExecutionProvider",
            "CPUExecutionProvider"
        ]
        self.session = onnxruntime.InferenceSession(model_path, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        logger.debug(f"Model input: {self.input_name}, output: {self.output_name}")

    def preprocess(self, img: NDArray[Any]) -> NDArray[Any]:
        if img.ndim != 3 or img.shape[2] != 3:
            raise InvalidEmbeddingsShapeError(
                f"Input must be (112, 112, 3). Got {img.shape}"
            )
        # Denormalize from [0, 1] to [0, 255], then normalize to [-1, 1]
        img = img.astype(np.float32) * 255.0
        img = (img - 127.5) / 127.5
        # HWC (112, 112, 3) to CHW (3, 112, 112) with batch dim (1, 3, 112, 112)
        return np.expand_dims(np.transpose(img, (2, 0, 1)), axis=0)

    def forward(self, img: NDArray[Any]) -> Union[List[float], List[List[float]]]:
        if self.session is None:
            raise RuntimeError("Model not loaded.")
        single = img.ndim == 3
        if single:
            img = np.expand_dims(img, axis=0)
        embeddings = []
        for i in range(img.shape[0]):
            out = self.session.run(
                [self.output_name], {self.input_name: self.preprocess(img[i])}
            )[0]
            embeddings.append(out.flatten().tolist())
        return embeddings[0] if single else embeddings
