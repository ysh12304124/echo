# COLMAP CPU/GPU 三组对照实验计划

## 目的

在同一个具有公开轨迹真值的数据集上，对比以下三套流程：

1. 旧版 COLMAP 3.6，CPU 特征提取、CPU 匹配、CPU Bundle Adjustment。
2. COLMAP 3.13，CPU 特征提取、CPU 匹配、CPU Bundle Adjustment。
3. COLMAP 3.13，GPU 特征提取、GPU 匹配、Ceres CUDA dense Bundle Adjustment。

三套流程均使用相同的图片、顺序匹配策略、相机模型、FastGS 训练迭代次数和测试视角。

## 数据集

使用 TUM RGB-D Freiburg1 desk 的公开 RGB 视频和 ground-truth 轨迹：

- 视频：`datasets/tum/desk-rgb.avi`
- 轨迹：`datasets/tum/desk-groundtruth.txt`
- 实验图片：从视频按每两帧抽取 300 张图片。
- 每张图片通过时间戳匹配最近的 ground-truth 位姿。
- 每 8 张图片抽取 1 张作为测试视角，其余用于训练。

本实验只使用 RGB 图片进行 COLMAP 和 3DGS，深度数据不参与重建。

## 软件配置

- 旧版 COLMAP：`/usr/bin/colmap`。
- 新版 CPU COLMAP：`/home/liangjiahua/colmap-cuda/bin/colmap`。
- 新版 GPU COLMAP：`/home/liangjiahua/colmap-cuda-ceres/bin/colmap`。
- CUDA Ceres：`/home/liangjiahua/ceres-cuda`，版本 2.2.0。
- FastGS：`/home/liangjiahua/FastGS`，环境 `fastgs`。

由于 Ceres 2.2 不包含 cuDSS sparse solver，本实验通过提高 COLMAP 的 dense GPU solver 图像阈值，使 300 张图片的 BA 走 CUDA dense Schur。日志中的 cuDSS fallback 只表示稀疏 CUDA 求解器不可用，不表示 CUDA dense solver 未启用。

## 执行流程

1. 准备图片和 ground-truth manifest。
2. 对每一组独立运行 COLMAP 特征提取、顺序匹配、Mapper 和去畸变。
3. 自动选择 COLMAP 输出中注册图像最多的重建。COLMAP 可能同时输出多个 reconstruction，不能固定使用 `sparse/0`。
4. 使用 FastGS 训练 10000 次，输出 Gaussian PLY。
5. 使用同一组 ground-truth 相机位姿渲染 38 个测试视角。
6. 保存每个阶段日志、计时和最终汇总 JSON。

## 评价指标

- COLMAP 阶段耗时：特征提取、匹配、Mapper、去畸变和总耗时。
- 注册图像数。
- COLMAP 初始点数、平均重投影误差、平均 track length。
- FastGS 训练耗时和最终 Gaussian 数量。
- 相机中心：Sim(3) 对齐后的 RMSE 和中位数误差。
- 姿态：连续帧相对旋转 RMSE 和中位数误差。绝对旋转误差不作为主指标，避免 TUM 与 COLMAP 相机坐标轴约定差异造成误判。
- 渲染质量：38 个 ground-truth 测试视角的 PSNR 和 SSIM。

## 输出位置

实验输出位于：

`/home/liangjiahua/experiments/colmap-comparison`

主要文件：

- `legacy_cpu/colmap.log`
- `new_cpu/colmap.log`
- `new_gpu/colmap.log`
- 每组的 `colmap_metrics.json`、`timings.json`、`training.log`
- 总评估：`evaluation.json`

## 已知限制

- TUM ground-truth 轨迹用于位姿和渲染评估，不代表手机 IMU 位姿；本实验目标是比较 COLMAP/3DGS 流程。
- 单目 COLMAP 存在尺度不确定性，因此位置误差先做 Sim(3) 对齐。
- 当前 GPU BA 是 CUDA dense Schur，不是 cuDSS sparse BA；后续如升级到支持 cuDSS 的 Ceres 版本，可单独增加 sparse GPU 对照。
