try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass


class DataPartition(StrEnum):
    WORK = "work"
    QUALITY_TIME = "quality_time"


class TimeScene(StrEnum):
    MEETING = "meeting"
    ONSITE = "onsite"
    QUALITY_TIME = "quality_time"


class MemoryType(StrEnum):
    TIME = "time"
    SPACE = "space"


class MemoryStatus(StrEnum):
    NOT_STARTED = "not_started"
    RECORDING = "recording"
    PAUSED = "paused"
    UPLOADING = "uploading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EvidenceType(StrEnum):
    VISUAL = "visual"
    TRANSCRIPT = "transcript"
    OCR = "ocr"
    SPATIAL = "spatial"
    USER_NOTE = "user_note"


class ConfidenceLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class QueryScope(StrEnum):
    GLOBAL_WORK = "global_work"
    MEMORY = "memory"
    SPACE = "space"


class QueryResultStatus(StrEnum):
    CONFIRMED = "confirmed"
    POSSIBLE = "possible"
    NOT_FOUND = "not_found"


class SpaceQuality(StrEnum):
    EXCELLENT = "excellent"
    GOOD = "good"
    RETRY_REQUIRED = "retry_required"


class SpaceSceneType(StrEnum):
    """空间记忆场景类型：由手机端在开始录制时选择，决定后期渲染的默认模式。

    - LARGE：大场景（房间/走廊等）→ 手机端默认「路径浏览」
    - OBJECT：单物体环绕 → 手机端默认「物体环绕」
    """
    LARGE = "large"
    OBJECT = "object"


class EventType(StrEnum):
    SPEAKER_CHANGE = "speaker_change"
    WHITEBOARD_CHANGE = "whiteboard_change"
    DECISION = "decision"
    COMMITMENT = "commitment"
    DISPUTE = "dispute"
    SPACE_SWITCH = "space_switch"
    TEXT_APPEAR = "text_appear"
    DEVICE_APPEAR = "device_appear"
    PERSON_INTERACTION = "person_interaction"
    BUSINESS_SEMANTIC = "business_semantic"
    REQUEST_EXPRESSION = "request_expression"
    INTEREST_EXPRESSION = "interest_expression"
    WORK_SHOWCASE = "work_showcase"
    USER_COMMITMENT = "user_commitment"
    JOINT_ACTIVITY = "joint_activity"
    MANUAL_MARK = "manual_mark"


class BindingType(StrEnum):
    MEMORY_LEVEL = "memory_level"
    EVENT_LEVEL = "event_level"
    EVIDENCE_LEVEL = "evidence_level"
    CANDIDATE = "candidate"


class EntityType(StrEnum):
    PERSON = "person"
    PROJECT = "project"
    DEVICE = "device"
    LOCATION = "location"
    SPACE = "space"
