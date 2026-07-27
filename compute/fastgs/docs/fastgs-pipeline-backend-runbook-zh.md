# FastGS 解耦流水线后端运行手册

## 任务目录

后端为每个任务创建唯一目录：

```text
/home/liangjiahua/FastGS/jobs/<job_id>/
```

上传以下内容：

```text
input/*.jpg
imu_manifest.json
```

所有文件上传并校验完成后再创建：

```text
job.ready
```

后端不要在上传过程中启动流水线。

## 启动完整流程

默认严格模式：任一阶段失败都停止后续阶段，重力对齐失败不会自动使用原始 COLMAP。

```bash
python /home/liangjiahua/FastGS/scripts/run_pipeline.py \
  --job-dir /home/liangjiahua/FastGS/jobs/<job_id> \
  --fastgs-dir /home/liangjiahua/FastGS \
  --iterations 30000 \
  --timeout-seconds 1800
```

只有产品明确允许“不做重力对齐也继续训练”时才增加：

```bash
--allow-alignment-fallback
```

此时对齐阶段会写 `completed_with_warnings`，并在 `alignment_meta.json` 中记录 `fallback_reason`。

## 阶段顺序

```text
run_colmap.py
    -> colmap_raw/
align_colmap.py
    -> colmap_gravity_aligned/
run_fastgs.py
    -> fastgs_model/
run_prune.py
    -> fastgs_model/geometric_pruned/
export_outputs.py
    -> outputs/
```

FastGS 直接读取已经完成 undistortion 的 `colmap_gravity_aligned/`，不会重复调用 COLMAP 转换。

## 状态读取

阶段状态文件：

```text
stages/colmap/status.json
stages/alignment/status.json
stages/fastgs/status.json
stages/prune/status.json
stages/export/status.json
```

允许进入下一阶段的状态：

```text
completed
completed_with_warnings
```

必须停止的状态：

```text
failed
cancelled
```

根目录的 `events.jsonl` 用于查看阶段开始、完成和失败事件。后端也可以读取 `result.json`，使用以下字段向用户展示错误：

```json
{
  "status": "failed",
  "stage": "alignment",
  "error_code": "GRAVITY_ALIGNMENT_ERROR",
  "error": "no valid matched IMU acceleration"
}
```

## COLMAP 注册规则

注册成功率按下面的公式计算：

```text
registered_image_count / input_image_count
```

低于 `0.8` 时任务失败。达到 `0.8` 时允许继续，但 `poses.json` 只包含已注册图片，未注册图片写入 `unregistered_images`。

## 最终产物

```text
outputs/point_cloud.ply
outputs/poses.json
outputs/poses.txt
outputs/anchor.json
outputs/result.json
```

后端和手机端优先使用 `poses.json`。`poses.txt` 只用于兼容旧读取端。未注册图片没有虚构 pose。

## 断点恢复

仅当前置阶段的产物和状态仍然有效时才允许恢复：

```bash
python /home/liangjiahua/FastGS/scripts/run_pipeline.py \
  --job-dir /home/liangjiahua/FastGS/jobs/<job_id> \
  --fastgs-dir /home/liangjiahua/FastGS \
  --resume-from alignment
```

可选值为 `colmap`、`alignment`、`fastgs`、`prune`、`export`。恢复不会覆盖 `colmap_raw/`，但会重新生成从指定阶段开始的后续产物。`export` 恢复前必须存在有效的 `geometric_pruned/` 产物；不会回退到训练原始 PLY。

剪枝阶段默认最多删除 1% 高斯，并强制执行 800 次受限微调。微调不执行 densification 和 opacity reset。可通过 `--prune-max-ratio` 和 `--prune-finetune-iterations` 调整，但微调次数必须为正数。

## 远程调用建议

130 机后端通过 SSH 执行上述命令并轮询状态。使用 SSH key，不要把密码写入代码、环境文件或命令行历史。任务目录和结果文件使用唯一 `job_id` 隔离，任务完成后再下载 `outputs/`。
