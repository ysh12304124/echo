# DeepFace Tools

基于 DeepFace 源码二次开发的人脸检测、身份识别、表情分析工具集，支持视频流实时处理与情绪关键帧提取。

## 特性

- **人脸检测**: SCRFD（默认）、OpenCV
- **身份识别**: Buffalo_L（InsightFace w600k_r50，ONNX Runtime，GPU加速）
- **表情分析**: EmotiEffLib EfficientNet-B2（AffectNet 训练，约90%准确率）
- **人脸属性**: 年龄、性别、种族分析
- **活体检测**: FasNet 反欺诈
- **情绪关键帧**: 基于情绪变化自动提取关键帧 + 人脸聚类
- **未注册人脸**: 自动聚类保存到 _unregistered/ 目录

## 目录结构

`
D:\deepface-tools\
├── deepface/                  # 核心模块
│   ├── DeepFace.py            # 入口: analyze(), stream(), build_model()
│   ├── commons/               # 通用工具
│   ├── config/                # 配置
│   ├── models/                # 模型实现
│   │   ├── demography/        # Age, Gender, Race, Emotion
│   │   ├── face_detection/    # SCRFD, OpenCV
│   │   ├── facial_recognition/# Buffalo_L, VGGFace
│   │   └── spoofing/          # FasNet
│   └── modules/               # 业务逻辑
│       └── emotion_keyframes/ # 情绪关键帧提取
├── weights/                   # 模型权重文件
├── deepface_all.py            # 单文件整合版
├── run_stream.py              # 视频流分析入口
├── requirements.txt
└── README.md
`

## 快速开始

### 1. 安装依赖

pip install -r requirements.txt

### 2. 运行视频流分析

from deepface import DeepFace

DeepFace.stream(
    db_path="E:\\testData\\DataBase",
    source="E:\\testData\\video\\test9.mp4",
    detector_backend="scrfd",
    anti_spoofing=True,
    model_name="Buffalo_L",
    time_threshold=0,
    frame_threshold=1,
    keyframe_output_dir="frames/test9",
)

### 3. 单文件版（复制到其他项目使用）

deepface_all.py 包含了全部代码，复制到目标项目后：

import os
os.environ["DEEPFACE_WEIGHTS_PATH"] = "D:\\path\\to\\weights"

from deepface_all import DeepFace
DeepFace.stream(...)

## 核心参数

| 参数 | 说明 | 可选值 |
|---|---|---|
| detector_backend | 人脸检测器 | scrfd, opencv |
| model_name | 身份识别模型 | Buffalo_L |
| distance_metric | 特征距离度量 | cosine |
| anti_spoofing | 活体检测 | True, False |

## 输出说明

- JSON 结果: 情绪关键帧的详细分析数据
- 关键帧图片: keyframe_output_dir/faces/ 目录下
- 未注册人脸: db_path/_unregistered/ 目录下，按聚类分组

## 环境变量

| 变量 | 说明 |
|---|---|
| DEEPFACE_WEIGHTS_PATH | 指定权重文件目录 |
| TF_FORCE_GPU_ALLOW_GROWTH | TensorFlow 显存按需分配 |
