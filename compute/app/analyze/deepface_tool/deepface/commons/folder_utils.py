import os
from deepface.commons.logger import Logger

logger = Logger()


def initialize_folder() -> None:
    """
    Initialize the folder for storing model weights in the local project directory.
    """
    weights_path = get_weights_path()
    if not os.path.exists(weights_path):
        os.makedirs(weights_path, exist_ok=True)
        logger.info(f"Weights directory {weights_path} has been created")


def get_weights_path() -> str:
    """
    Get the path to the local weights directory.
    Uses DEEPFACE_WEIGHTS_PATH env var if set, otherwise
    resolves relative to the deepface package (project root/weights/).
    
    Returns:
        str: the weights directory path.
    """
    env_path = os.getenv("DEEPFACE_WEIGHTS_PATH")
    if env_path:
        return env_path
    
    # Resolve relative to this file: ../../weights/
    module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(os.path.dirname(module_dir), "weights")


def get_deepface_home() -> str:
    """
    Get the project root directory (parent of deepface/ package).
    This is used by weight_utils for backward compatibility.
    
    Returns:
        str: the project root directory.
    """
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
