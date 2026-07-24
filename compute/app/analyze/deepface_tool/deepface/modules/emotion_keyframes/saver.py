import os
import json

import cv2

from datetime import datetime

from numpy.distutils.fcompiler import none


class KeyframeSaver:


    def __init__(
        self,
        output_dir,
        source_video=None
    ):
        self.output_dir = output_dir
        self.source_video = source_video
        self.image_dir = output_dir
        self.faces_dir = os.path.join(output_dir, "faces")

        os.makedirs(
            self.image_dir,
            exist_ok=True
        )
        os.makedirs(
            self.faces_dir,
            exist_ok=True
        )




    def save(
        self,
        keyframes
    ):

        results = []
        for index, frame in enumerate(keyframes):
            if frame is None:
                continue
            # 保存全帧关键帧图
            filename = "{:06d}_frame_{:08d}.jpg".format(
                index,
                frame.frame_idx
            )
            image_path = os.path.join(
                self.image_dir,
                filename
            )
            cv2.imwrite(
                image_path,
                frame.frame
            )
            # 如果有对应的人脸裁剪图，也保存
            face_image_name = None
            if frame.face_img is not None:
                face_image_name = "{:06d}_frame_{:08d}.jpg".format(
                    index,
                    frame.frame_idx,
                )
                face_path = os.path.join(
                    self.faces_dir,
                    face_image_name
                )
                cv2.imwrite(
                    face_path,
                    frame.face_img
                )
            result = {
                "type": "emotion_keyframe",
                "frame_id": index,
                "frame_idx": frame.frame_idx,
                "face_id": frame.face_id,
                "face_image": "faces/{}".format(face_image_name) if face_image_name else None,
                "timestamp": self.format_video_time(
                    frame.time_sec
                ),
                "time_sec": round(
                    frame.time_sec,
                    3
                ),
                "datetime": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "source_video": self.source_video,
                "image": filename,
                "emotion": frame.emotion,
                "emotion_score": frame.emotion_scores.get(
                    frame.emotion,
                    0
                ),
                "age": frame.age,
                "gender": frame.gender,
                "is_real": frame.is_real,
                "identity": frame.identity,
                "identity_confidence": frame.identity_confidence,
            }
            results.append(result)

        json_path = os.path.join(
            self.output_dir,
            "keyframes.json"
        )

        class NumpyEncoder(json.JSONEncoder):
            def default(self, obj):
                import numpy as np
                if isinstance(obj, (np.integer,)):
                    return int(obj)
                elif isinstance(obj, (np.floating,)):
                    return float(obj)
                elif isinstance(obj, np.ndarray):
                    return obj.tolist()
                return super().default(obj)

        with open(
            json_path,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                results,
                f,
                ensure_ascii=False,
                indent=4,
                cls=NumpyEncoder
            )
        return json_path
    def format_video_time(self, sec):
        hours = int(sec // 3600)
        minutes = int(
            (sec % 3600) // 60
        )
        seconds = sec % 60
        return (
            f"{hours:02d}:"
            f"{minutes:02d}:"
            f"{seconds:06.3f}"
        )