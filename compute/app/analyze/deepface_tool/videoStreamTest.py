
from deepface import DeepFace
# 视频/视频流人脸检测+表情分析
DeepFace.stream(
    db_path="E:\\testData\\DataBase",
    source="E:\\testData\\video\\test10.mp4",
    detector_backend="scrfd",
    anti_spoofing=True,
    model_name="Buffalo_L",
    time_threshold=0,
    frame_threshold=1,
    keyframe_output_dir="E:\\testData\\img\\frames\\test10",
)

