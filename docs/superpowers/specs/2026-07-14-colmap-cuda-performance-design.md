# COLMAP CUDA 性能优化设计

**日期：** 2026-07-14

## 目标

将 200 主机上 250 张连续 JPEG 图片的 COLMAP 处理阶段从当前约 12 分 38 秒降低到 5 分钟以内，同时保持能够稳定生成 FastGS 所需的 sparse/0 和初始点云。

## 当前基线

当前任务使用 250 张、约 956x536 的图片，COLMAP 3.6 的阶段耗时为：

| 阶段 | 耗时 |
| --- | ---: |
| 特征提取 | 约 7 秒 |
| 顺序匹配 | 约 52 秒 |
| Mapper/Bundle Adjustment | 约 11 分 37 秒 |
| 图像去畸变 | 约 1 秒 |
| COLMAP 总计 | 约 12 分 38 秒 |

200 主机有 RTX 3090，但当前 /usr/bin/colmap 显示为 COLMAP 3.6 without CUDA，重建脚本还显式传入了 --no_gpu。因此主要瓶颈是 CPU Mapper 和 Bundle Adjustment，而不是顺序匹配本身。

## 方案

### 独立 CUDA 版 COLMAP

不覆盖系统 /usr/bin/colmap。使用 200 主机已有的 CUDA 12.1 工具链：

    /home/liangjiahua/miniconda3/envs/dgsg/bin/nvcc

从官方 COLMAP release 构建到：

    /home/liangjiahua/colmap-cuda

构建目录和源码放在 /home/liangjiahua/，避免继续占用根分区。旧版 COLMAP 保留作为回退路径。

### 重建命令

重建脚本使用环境变量指定 COLMAP 可执行文件，默认仍可回退到 colmap：

    FASTGS_COLMAP_EXECUTABLE=/home/liangjiahua/colmap-cuda/bin/colmap
    FASTGS_COLMAP_USE_GPU=1

移除强制的 --no_gpu，让 convert 使用 GPU 特征提取和匹配；Mapper 使用 CUDA/PBA 相关参数。

### 分阶段计时

200 端任务日志必须独立记录：

    feature_extraction_seconds
    feature_matching_seconds
    mapper_seconds
    undistortion_seconds
    colmap_total_seconds
    registered_image_count
    points3d_count

COLMAP 失败时保留各阶段 stdout/stderr 和失败命令，但不记录 SSH 密码。

### 参数优化顺序

第一轮只切换 CUDA 版本和 GPU，不降低质量参数，建立可比较的基线。

如果仍超过 5 分钟，按以下顺序逐项优化：

1. 顺序匹配窗口从 10 调整为 8 或 6。
2. SIFT 最大特征数从 8192 调整为 6144 或 4096。
3. 最大匹配数从 32768 调整为 16384 或 8192。
4. 降低局部和全局 Bundle Adjustment 迭代次数。

每轮都检查注册图片数、points3D.bin 点数量、重建输出和 FastGS PLY。若注册率或点数量明显下降，回退上一组参数。

## 兼容和回退

- 不修改 fastgs 环境中的 PyTorch CUDA 依赖。
- 不覆盖系统 COLMAP。
- worker 支持通过环境变量切换 CUDA 版和旧版 COLMAP。
- CUDA 版无法运行时，先记录 GPU/动态库错误，再回退到旧版 CPU COLMAP。
- 用户在 200 机上已有的 convert.py、train.sh 和其他未提交修改必须保留。

## 验证

每次基准使用同一份 250 张 huiyi 数据集和独立任务目录。验收条件：

1. CUDA 版 colmap -h 或版本信息确认构建包含 CUDA。
2. GPU 被 COLMAP 实际使用，而不是只检测到驱动。
3. COLMAP 阶段总耗时不超过 300 秒。
4. 所有或绝大多数输入图片成功注册，具体数量记录在日志中。
5. sparse/0/cameras.bin、images.bin、points3D.bin 均存在且非空。
6. FastGS 能继续生成有效 PLY。
7. 远端 PLY 与 130 端 BlobStore 文件的 SHA256 一致。

本阶段只优化 COLMAP，不改变 FastGS 训练迭代次数和手机渲染协议。

