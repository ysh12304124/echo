# Chinese-CLIP Retrieval Benchmark

独立的 Chinese-CLIP 图片检索基准，不修改 Echo 业务检索链路。

## 功能

- 扫描图片目录并为每张图片生成一个 512 维全局向量。
- 文本查询固定返回 Top 20，不做相似度阈值过滤。
- 支持运行时切换 `FP16`、bitsandbytes `INT8`、bitsandbytes `NF4 4-bit`。
- 每次切换会卸载模型、释放 CUDA 缓存、重载模型并重建图片索引。
- 页面每秒刷新 GPU 总显存、本进程分配/保留显存、模型加载与索引耗时。

页面展示的是归一化文本向量与图片向量的余弦相似度，不是概率置信度。

## 启动

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
chmod +x start.sh
./start.sh
```

后台运行时将 PID 写入 `run/server.pid`，可使用 `./stop.sh` 停止。

主要环境变量：

```text
CLIP_DEMO_MODEL_PATH=/path/to/chinese-clip-vit-base-patch16-fp16
CLIP_DEMO_IMAGE_ROOT=/path/to/images
CLIP_DEMO_DEFAULT_QUANTIZATION=nf4
CLIP_DEMO_PORT=8400
CUDA_VISIBLE_DEVICES=1
```

## 测试

```bash
PYTHONPATH=. .venv/bin/pytest
```
