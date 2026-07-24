from __future__ import annotations

# built-in dependencies
from typing import TYPE_CHECKING, Any, Final, TypedDict, Dict

# project dependencies
from deepface.models.facial_recognition import Buffalo_L
from deepface.models.face_detection import OpenCv, Scrfd
from deepface.models.demography import Age, Gender, Race, Emotion
from deepface.models.spoofing import FasNet
from deepface.modules.exceptions import UnimplementedError

if TYPE_CHECKING:
    from deepface.models.Demography import Demography
    from deepface.models.Detector import Detector
    from deepface.models.FacialRecognition import FacialRecognition

    cached_models: Dict[str, Dict[str, Any]] = {}


class AvailableModels(TypedDict):
    facial_recognition: dict[str, type[FacialRecognition]]
    spoofing: dict[str, type[FasNet.Fasnet]]
    facial_attribute: dict[str, type[Demography]]
    face_detector: dict[str, type[Detector]]


AVAILABLE_MODELS: Final[AvailableModels] = {
    "facial_recognition": {
        "Buffalo_L": Buffalo_L.Buffalo_L,
    },
    "spoofing": {
        "Fasnet": FasNet.Fasnet,
    },
    "facial_attribute": {
        "Emotion": Emotion.EmotionClient,
        "Age": Age.ApparentAgeClient,
        "Gender": Gender.GenderClient,
        "Race": Race.RaceClient,
    },
    "face_detector": {
        "opencv": OpenCv.OpenCvClient,
        "scrfd": lambda: Scrfd.ScrfdClient(model_variant="500m"),
    },
}


def build_model(task: str, model_name: str) -> Any:
    """
    This function loads a pre-trained models as singletonish way
    Parameters:
        task (str): facial_recognition, facial_attribute, face_detector, spoofing
        model_name (str): model identifier
    Returns:
            built model class
    """

    # singleton design pattern
    global cached_models

    if task not in AVAILABLE_MODELS.keys():
        raise UnimplementedError(f"unimplemented task - {task}")

    if "cached_models" not in globals():
        cached_models = {current_task: {} for current_task in AVAILABLE_MODELS.keys()}

    if cached_models[task].get(model_name) is None:
        model = AVAILABLE_MODELS[task].get(model_name)
        if model:
            cached_models[task][model_name] = model()
        else:
            raise UnimplementedError(f"Invalid model_name passed - {task}/{model_name}")

    return cached_models[task][model_name]
