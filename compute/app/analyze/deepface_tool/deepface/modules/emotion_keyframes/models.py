from dataclasses import dataclass, field
from typing import Dict, Optional, Any, List


@dataclass
class EmotionFrame:

    frame_idx: int

    time_sec: float

    frame: Any

    emotion: str

    emotion_scores: Dict[str, float]

    face_id: int = 0

    identity: Optional[str] = None

    identity_confidence: Optional[float] = None

    face_img: Any = None

    age: Optional[int] = None

    gender: Optional[str] = None

    race: Optional[str] = None

    is_real: Optional[bool] = None



@dataclass
class EmotionSegment:

    emotion: str

    frames: List[EmotionFrame] = field(
        default_factory=list
    )


    def add(self, frame):

        self.frames.append(frame)



    def best_frame(self):

        if not self.frames:
            return None


        return max(
            self.frames,
            key=lambda x:
            x.emotion_scores.get(
                x.emotion,
                0
            )
        )