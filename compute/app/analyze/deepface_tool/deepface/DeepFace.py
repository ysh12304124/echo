# built-in dependencies
import os
import warnings
import logging
from typing import Any, Dict, IO, List, Union, Optional, Tuple, cast

# this has to be set before importing tensorflow
os.environ["TF_USE_LEGACY_KERAS"] = "1"

# pylint: disable=wrong-import-position, too-many-positional-arguments

# 3rd party dependencies
from numpy.typing import NDArray

# package dependencies
from deepface.commons import package_utils, folder_utils
from deepface.commons.logger import Logger
import pandas as pd
from numpy.typing import NDArray
from deepface.modules import (
    modeling,
    demography,
    detection,
    recognition,
    streaming,
    preprocessing,
)
from deepface import __version__

logger = Logger()

# -----------------------------------
# configurations for dependencies

# users should install tf_keras package if they are using tf 2.16 or later versions
package_utils.validate_for_keras3()

warnings.filterwarnings("ignore")
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
tf_version = package_utils.get_tf_major_version()
if tf_version == 2:
    tf = __import__("tensorflow")
    tf.get_logger().setLevel(logging.ERROR)
# -----------------------------------

# create required folders if necessary to store model weights
folder_utils.initialize_folder()


def build_model(model_name: str, task: str = "facial_recognition") -> Any:
    """
    This function builds a pre-trained model
    Args:
        model_name (str): model identifier
            - VGG-Face for face recognition
            - Age, Gender, Emotion, Race for facial attributes
            - opencv, scrfd for face detectors
            - Fasnet for spoofing
        task (str): facial_recognition, facial_attribute, face_detector, spoofing
    Returns:
        built_model
    """
    return modeling.build_model(task=task, model_name=model_name)


def analyze(
    img_path: Union[str, NDArray[Any], IO[bytes], List[str], List[NDArray[Any]], List[IO[bytes]]],
    actions: Union[Tuple[str, ...], List[str]] = ("emotion", "age", "gender", "race"),
    enforce_detection: bool = True,
    detector_backend: str = "opencv",
    align: bool = True,
    expand_percentage: int = 0,
    silent: bool = False,
    anti_spoofing: bool = False,
) -> Union[List[Dict[str, Any]], List[List[Dict[str, Any]]]]:
    """
    Analyze facial attributes such as age, gender, emotion, and race in the provided image.
    Args:
        img_path (str, np.ndarray, IO[bytes], list): The exact path to the image, a numpy array
            in BGR format, a file object that supports at least `.read` and is opened in binary
            mode, or a base64 encoded image. If the source image contains multiple faces,
            the result will include information for each detected face.

        actions (tuple): Attributes to analyze. The default is ('age', 'gender', 'emotion', 'race').

        enforce_detection (boolean): If no face is detected in an image, raise an exception.
            Set to False to avoid the exception for low-resolution images (default is True).

        detector_backend (string): face detector backend. Options: 'opencv', 'scrfd' or 'skip'
            (default is opencv).

        align (boolean): Perform alignment based on the eye positions (default is True).

        expand_percentage (int): expand detected facial area with a percentage (default is 0).

        silent (boolean): Suppress or allow some log messages for a quieter analysis process
            (default is False).

        anti_spoofing (boolean): Flag to enable anti spoofing (default is False).

    Returns:
        (List[Dict[str, Any]]): A list of dictionaries, where each dictionary represents
           the analysis results for a detected face.
    """
    return demography.analyze(
        img_path=img_path,
        actions=actions,
        enforce_detection=enforce_detection,
        detector_backend=detector_backend,
        align=align,
        expand_percentage=expand_percentage,
        silent=silent,
        anti_spoofing=anti_spoofing,
    )


def find(
    img_path: Union[str, NDArray[Any], IO[bytes]],
    db_path: str,
    model_name: str = "VGG-Face",
    distance_metric: str = "cosine",
    enforce_detection: bool = True,
    detector_backend: str = "opencv",
    align: bool = True,
    similarity_search: bool = False,
    k: Optional[int] = None,
    expand_percentage: int = 0,
    threshold: Optional[float] = None,
    normalization: str = "base",
    silent: bool = False,
    refresh_database: bool = True,
    anti_spoofing: bool = False,
    batched: bool = False,
) -> Union[List[pd.DataFrame], List[List[Dict[str, Any]]]]:
    """
    Identify individuals in a database
    Args:
        img_path (str or np.ndarray): The exact path to the image, a numpy array in BGR format,
            or a base64 encoded image.
        db_path (string): Path to the folder containing image files.
        model_name (str): Model for face recognition.
        distance_metric (string): Metric for measuring similarity.
        detector_backend (string): face detector backend.
        align (boolean): Perform alignment based on the eye positions.
        expand_percentage (int): expand detected facial area with a percentage.
        normalization (string): Normalize the input image.
        silent (boolean): Suppress or allow some log messages.
        refresh_database (boolean): Synchronizes the images representation (pkl) file.
        anti_spoofing (boolean): Flag to enable anti spoofing.
    Returns:
        results (List[pd.DataFrame]): A list of pandas dataframes.
    """
    return recognition.find(
        img_path=img_path,
        db_path=db_path,
        model_name=model_name,
        distance_metric=distance_metric,
        enforce_detection=enforce_detection,
        detector_backend=detector_backend,
        align=align,
        similarity_search=similarity_search,
        k=k,
        expand_percentage=expand_percentage,
        threshold=threshold,
        normalization=normalization,
        silent=silent,
        refresh_database=refresh_database,
        anti_spoofing=anti_spoofing,
        batched=batched,
    )


def extract_faces(
    img_path: Union[str, NDArray[Any], IO[bytes], List[str], List[NDArray[Any]], List[IO[bytes]]],
    detector_backend: str = "opencv",
    enforce_detection: bool = True,
    align: bool = True,
    expand_percentage: int = 0,
    grayscale: bool = False,
    color_face: str = "rgb",
    normalize_face: bool = True,
    anti_spoofing: bool = False,
) -> Union[List[Dict[str, Any]], List[List[Dict[str, Any]]]]:
    """
    Extract faces from a given image
    Args:
        img_path (str, np.ndarray, IO[bytes], list): image path or array
        detector_backend (string): face detector backend
        enforce_detection (boolean): raise exception if no face detected
        align (bool): enable face alignment
        expand_percentage (int): expand detected facial area
        grayscale (boolean): convert to grayscale
        color_face (string): 'rgb', 'bgr' or 'gray'
        normalize_face (boolean): normalize pixel values
        anti_spoofing (boolean): enable anti spoofing
    Returns:
        results (List[Dict[str, Any]]): A list of dictionaries containing face info
    """
    return detection.extract_faces(
        img_path=img_path,
        detector_backend=detector_backend,
        enforce_detection=enforce_detection,
        align=align,
        expand_percentage=expand_percentage,
        grayscale=grayscale,
        color_face=color_face,
        normalize_face=normalize_face,
        anti_spoofing=anti_spoofing,
    )


def stream(
    db_path: str,
    model_name: str = "VGG-Face",
    detector_backend: str = "opencv",
    distance_metric: str = "cosine",
    enable_face_analysis: bool = True,
    source: Any = 0,
    time_threshold: int = 5,
    frame_threshold: int = 5,
    anti_spoofing: bool = False,
    keyframe_output_dir: Optional[str] = None,
    json_path: Optional[str] = None,
    debug: bool = False,
) -> None:
    """
    Run real time face recognition and facial attribute analysis

    Args:
        db_path (string): Path to the folder containing image files.

        model_name (str): Model for face recognition.

        detector_backend (string): face detector backend. Options: 'opencv', 'scrfd' or 'skip'.

        distance_metric (string): Metric for measuring similarity.

        enable_face_analysis (bool): Flag to enable face analysis (default is True).

        source (Any): The source for the video stream (default is 0, which represents the
            default camera).

        time_threshold (int): The time threshold (in seconds) for face recognition (default is 5).

        frame_threshold (int): The frame threshold for face recognition (default is 5).

        anti_spoofing (boolean): Flag to enable anti spoofing (default is False).

        keyframe_output_dir (str): Directory to save emotion keyframes.

        json_path (str): Path to save the analysis results JSON.

        debug (bool): set this to True to save frame outcomes
    Returns:
        None
    """

    time_threshold = max(time_threshold, 0)
    frame_threshold = max(frame_threshold, 0)

    streaming.analysis(
        db_path=db_path,
        model_name=model_name,
        detector_backend=detector_backend,
        distance_metric=distance_metric,
        enable_face_analysis=enable_face_analysis,
        source=source,
        time_threshold=time_threshold,
        frame_threshold=frame_threshold,
        anti_spoofing=anti_spoofing,
        keyframe_output_dir=keyframe_output_dir,
        json_path=json_path,
        debug=debug,
    )


def cli() -> None:
    """
    command line interface function
    """
    import fire
    fire.Fire()
