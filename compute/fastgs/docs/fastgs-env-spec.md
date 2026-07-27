# FastGS Conda 虚拟环境配置文档

## 基本信息

| 项目 | 值 |
|------|-----|
| 环境名称 | `fastgs` |
| Python 版本 | 3.10.x (conda-forge) |
| PyTorch 版本 | 2.5.1+cu121 |
| CUDA 版本 | 12.1 |
| cuDNN 版本 | 9.1.0 (90100) |
| 操作系统 | Ubuntu Linux (x86_64) |
| GPU 要求 | NVIDIA GPU, CUDA capability ≥ 7.0, 推荐 ≥ 24GB VRAM |

## 目录结构要求

```
<parent>/
├── dgsg-orin/          # DynamicGSG 项目
│   ├── scripts/run_fastgs.py
│   ├── configs/
│   └── data/
└── FastGS/             # FastGS 项目（dgsg-orin 的兄弟目录）
    ├── train.py
    ├── convert_custom_to_colmap.py
    ├── submodules/     # CUDA 扩展源码
    └── ...
```

`run_fastgs.py` 会自动检测 FastGS 的位置（默认为 dgsg-orin 的兄弟目录），也可通过 `--fastgs_dir` 手动指定。

## 创建环境

```bash
# 1. 创建 conda 环境
conda create -n fastgs python=3.10 -c conda-forge
conda activate fastgs

# 2. 安装 PyTorch (CUDA 12.1)
pip install torch==2.5.1+cu121 torchvision==0.20.1+cu121 torchaudio==2.5.1+cu121 \
    --index-url https://download.pytorch.org/whl/cu121
```

## 安装 FastGS CUDA 扩展

三个自定义 CUDA 扩展必须从 FastGS 的 `submodules/` 编译安装：

```bash
cd FastGS/submodules

# 设置 CUDA_HOME（使用 conda 环境自带的 nvcc）
# 如果没有 nvcc，先装: conda install -c nvidia cuda-toolkit=12.1
export CUDA_HOME=$CONDA_PREFIX

pip install --no-build-isolation ./simple-knn
pip install --no-build-isolation ./diff-gaussian-rasterization_fastgs
pip install --no-build-isolation ./fused-ssim
```

**编译产物：**

| 扩展 | 包名 | 功能 |
|------|------|------|
| `diff_gaussian_rasterization_fastgs` | 0.0.0 | 可微高斯光栅化（支持 metric_map） |
| `simple_knn` | 0.0.0 | CUDA KNN（初始点云距离计算） |
| `fused_ssim` | 0.0.0 | 融合 SSIM（比标准实现快 5-8×） |

**编译注意事项：**
- 需要 `--no-build-isolation`，因为 `setup.py` 依赖 `torch`
- 需要 `CUDA_HOME` 指向包含 `nvcc` 的目录
- GCC ≥ 12 与 CUDA 12.1 的 `nvcc` 可能存在兼容性问题

## 安装其他依赖

```bash
pip install numpy scipy opencv-python pillow plyfile pyyaml tqdm wandb websockets ninja
```

或使用导出的 requirements 文件：

```bash
pip install -r docs/requirements_fastgs.txt
```

> 注意：`requirements_fastgs.txt` 不包含 CUDA 扩展（需从 submodules 编译）。

## 验证安装

```bash
python -c "
from diff_gaussian_rasterization_fastgs import GaussianRasterizer
from simple_knn._C import distCUDA2
from fused_ssim import fused_ssim
import torch
print('All FastGS CUDA extensions loaded OK')
print(f'CUDA: {torch.cuda.is_available()}, GPU: {torch.cuda.get_device_name(0)}')
"
```

## 跨环境复用

如果同一台机器上有另一个 Python 3.10 + CUDA 12.1 的 conda 环境（如 `dgsg`），
可以通过 `PYTHONPATH` 直接复用 `fastgs` 环境中编译好的 CUDA 扩展，无需重新编译：

```bash
# 找到 fastgs 环境的 site-packages 路径
FASTGS_SP=$(python -c "import glob; print(glob.glob('$HOME/miniconda3/envs/fastgs/lib/python*/site-packages')[0])")

# 在其他环境中使用
export PYTHONPATH=$FASTGS_SP:$PYTHONPATH
```

`run_fastgs.py` 会自动检测并处理这个路径。

## 完整包列表

### 核心

| 包 | 版本 |
|---|------|
| `torch` | 2.5.1+cu121 |
| `torchvision` | 0.20.1+cu121 |
| `torchaudio` | 2.5.1+cu121 |
| `triton` | 3.1.0 |

### FastGS CUDA 扩展

| 包 | 版本 | 来源 |
|---|------|------|
| `diff_gaussian_rasterization_fastgs` | 0.0.0 | `submodules/` 编译 |
| `simple_knn` | 0.0.0 | `submodules/` 编译 |
| `fused_ssim` | 0.0.0 | `submodules/` 编译 |

### 数据处理

| 包 | 版本 |
|---|------|
| `numpy` | 2.2.6 |
| `scipy` | 1.15.3 |
| `scikit-learn` | 1.7.2 |
| `opencv-python` | 4.13.0.92 |
| `pillow` | 12.0.0 |
| `plyfile` | 1.1.3 |
| `pyyaml` | 6.0.3 |

### 训练辅助

| 包 | 版本 |
|---|------|
| `tqdm` | 4.67.3 |
| `wandb` | 0.25.1 |
| `websockets` | 16.0 |
| `gitpython` | 3.1.46 |
| `ninja` | 1.13.0 |
