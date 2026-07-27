"""独立时间记忆分析适配器。

功能：
1. 直接调用同一工程中的 ``speaker_video_pipeline.py``；
2. 返回对话 JSON、CSV、人脸目录及逐句对话；
3. 提供同步、异步和兼容任务入口；
4. 不依赖 app.callback、app.logging_setup 或 app.analyze。

推荐目录：
    project/
    ├─ time_memory.py
    ├─ test_time_memory.py
    ├─ speaker_video_pipeline.py
    ├─ models/
    ├─ LR-ASD/
    ├─ DATA/
    └─ outputs/
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import re
import shlex
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


LOGGER = logging.getLogger("time_memory")

_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def _configure_logging() -> None:
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )
    )
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


_configure_logging()


def _project_root() -> Path:
    return Path(__file__).resolve().parent


def _safe_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" .")
    return (cleaned or "video")[:120]


def _resolve_path(
    value: str | Path | None,
    default: Path | None = None,
) -> Path | None:
    if value is None or not str(value).strip():
        return default.expanduser().resolve() if default is not None else None
    return Path(value).expanduser().resolve()


def _find_pipeline_script(options: Mapping[str, Any]) -> Path:
    configured = (
        options.get("speaker_pipeline_script")
        or options.get("pipeline_script")
        or os.getenv("TIME_MEMORY_SPEAKER_PIPELINE_SCRIPT")
    )
    if configured:
        script = Path(str(configured)).expanduser().resolve()
        if not script.is_file():
            raise FileNotFoundError(f"说话人脚本不存在：{script}")
        return script

    root = _project_root()
    candidates = [
        root / "speaker_video_pipeline.py",
        Path.cwd() / "speaker_video_pipeline.py",
        root / "speaker_video_pipeline(8).py",
        root / "speaker_video_pipeline(6).py",
        Path.cwd() / "speaker_video_pipeline(8).py",
        Path.cwd() / "speaker_video_pipeline(6).py",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        "找不到 speaker_video_pipeline.py。"
        "请把它放在 time_memory.py 同目录，"
        "或传入 speaker_pipeline_script。"
    )


def _load_module(script: Path) -> Any:
    module_name = (
        "_time_memory_pipeline_"
        + str(abs(hash((str(script), script.stat().st_mtime_ns))))
    )
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached

    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载脚本：{script}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _supported_options(module: Any) -> set[str]:
    builder = getattr(module, "build_parser", None)
    if not callable(builder):
        return set()

    parser = builder()
    return {
        option
        for action in getattr(parser, "_actions", [])
        for option in getattr(action, "option_strings", [])
    }


def _append_value(
    argv: list[str],
    supported: set[str],
    name: str,
    value: Any,
) -> None:
    if value is None:
        return
    if supported and name not in supported:
        return
    argv.extend([name, str(value)])


def _append_flag(
    argv: list[str],
    supported: set[str],
    name: str,
    enabled: bool,
) -> None:
    if not enabled:
        return
    if supported and name not in supported:
        return
    argv.append(name)


def _run_pipeline_main(
    module: Any,
    argv: Sequence[str],
) -> int | None:
    entry = getattr(module, "main", None)
    if not callable(entry):
        entry = getattr(module, "pipeline_main", None)
    if not callable(entry):
        raise AttributeError(
            "speaker_video_pipeline.py 中不存在 main(argv) "
            "或 pipeline_main(argv)"
        )

    try:
        return entry(list(argv))
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 1


def _read_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"未生成结果 JSON：{path}")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"结果 JSON 无法读取：{path}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("结果 JSON 顶层必须是对象")
    return payload


def _normalize_segments(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("segments")
    if raw is None:
        raw = payload.get("messages")
    if not isinstance(raw, list):
        raise RuntimeError("结果中没有 segments/messages 列表")

    segments: list[dict[str, Any]] = []
    for index, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise RuntimeError(f"第 {index} 条对话不是对象")

        audio = item.get("audio") if isinstance(item.get("audio"), dict) else {}
        start_raw = item.get(
            "start",
            item.get("start_sec", audio.get("start", 0.0)),
        )
        end_raw = item.get(
            "end",
            item.get("end_sec", audio.get("end", start_raw)),
        )

        try:
            start = float(start_raw or 0.0)
            end = float(end_raw if end_raw is not None else start)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"第 {index} 条对话时间无效") from exc

        if end < start:
            start, end = end, start

        normalized = dict(item)
        normalized.update(
            {
                "start": start,
                "end": end,
                "speaker": str(
                    item.get("speaker")
                    or audio.get("speaker")
                    or item.get("raw_speaker")
                    or "unknown"
                ),
                "text": str(
                    item.get("text")
                    or audio.get("text")
                    or audio.get("asr_text")
                    or ""
                ),
                "fusion_source": str(
                    item.get("fusion_source")
                    or audio.get("text_source")
                    or audio.get("source")
                    or "speaker_video_pipeline"
                ),
            }
        )
        segments.append(normalized)

    if not segments:
        raise RuntimeError("没有生成有效对话")
    return segments


def _find_face_dir(
    output_dir: Path,
    output_json: Path,
    requested: Path,
    payload: Mapping[str, Any],
) -> Path | None:
    candidates: list[Path] = [
        requested,
        output_dir / "faces",
        output_dir / "speaker_chat_avatars",
        output_dir / f"{output_json.stem}_avatars",
        output_json.parent / f"{output_json.stem}_avatars",
    ]

    avatar_dir = payload.get("avatar_dir")
    if avatar_dir:
        path = Path(str(avatar_dir))
        if not path.is_absolute():
            path = output_json.parent / path
        candidates.append(path)

    avatar_map = payload.get("avatar_map")
    if isinstance(avatar_map, dict):
        for value in avatar_map.values():
            if not value:
                continue
            path = Path(str(value))
            if not path.is_absolute():
                path = output_json.parent / path
            candidates.append(path.parent)

    checked: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved in checked:
            continue
        checked.add(resolved)
        if resolved.is_dir():
            return resolved
    return None


def _collect_faces(
    payload: Mapping[str, Any],
    output_json: Path,
    face_dir: Path | None,
) -> list[dict[str, Any]]:
    faces: list[dict[str, Any]] = []
    used: set[Path] = set()

    avatar_map = payload.get("avatar_map")
    if isinstance(avatar_map, dict):
        for person, value in avatar_map.items():
            if not value:
                continue
            path = Path(str(value))
            if not path.is_absolute():
                path = output_json.parent / path
            path = path.resolve()
            if path.is_file():
                used.add(path)
                faces.append(
                    {
                        "name": str(person),
                        "crop_path": str(path),
                        "confidence": "high",
                    }
                )

    if face_dir is not None:
        for path in sorted(face_dir.rglob("*")):
            resolved = path.resolve()
            if (
                path.is_file()
                and path.suffix.lower() in _IMAGE_SUFFIXES
                and resolved not in used
            ):
                faces.append(
                    {
                        "name": path.stem,
                        "crop_path": str(resolved),
                        "confidence": "high",
                    }
                )
    return faces


def _build_result(
    video_path: Path,
    output_dir: Path,
    output_json: Path,
    output_csv: Path,
    face_dir: Path | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    segments = _normalize_segments(payload)

    persons: list[str] = []
    for segment in segments:
        speaker = str(segment["speaker"])
        if speaker not in persons:
            persons.append(speaker)

    transcript = " ".join(
        str(segment.get("text") or "").strip()
        for segment in segments
        if str(segment.get("text") or "").strip()
    )

    evidence_entries = [
        {
            "type": "transcript",
            "start_ms": round(float(segment["start"]) * 1000),
            "end_ms": round(float(segment["end"]) * 1000),
            "speaker": str(segment["speaker"]),
            "text": str(segment.get("text") or ""),
            "raw_speaker": segment.get("raw_speaker"),
            "fusion_source": segment.get(
                "fusion_source",
                "speaker_video_pipeline",
            ),
        }
        for segment in segments
    ]

    first_seen: set[str] = set()
    key_moments: list[dict[str, Any]] = []
    for entry in evidence_entries:
        speaker = str(entry["speaker"])
        if speaker in first_seen:
            continue
        first_seen.add(speaker)
        key_moments.append(
            {
                "timestamp_ms": entry["start_ms"],
                "label": f"{speaker}首次发言",
            }
        )

    events = [
        {
            "event_type": "speaking",
            "start_ms": entry["start_ms"],
            "end_ms": entry["end_ms"],
            "label": f"{entry['speaker']}：{entry['text']}",
            "confidence": "high",
        }
        for entry in evidence_entries
    ]

    pipeline_info = payload.get("pipeline")
    if not isinstance(pipeline_info, dict):
        pipeline_info = {}

    return {
        "identify_brief": f"{len(persons)}位说话人 · {len(segments)}段对话",
        "navigation_summary": {
            "persons": persons,
            "topics": ["多人对话"] if len(persons) > 1 else ["个人讲述"],
            "spaces": [],
            "key_moments": key_moments,
            "evidence_entries": evidence_entries,
            "suggested_questions": [
                "每位说话人分别说了什么？",
                "有哪些明确要求和承诺？",
            ],
        },
        "key_frames": [],
        "events": events,
        "faces": _collect_faces(payload, output_json, face_dir),
        "audio_evidence": {
            "video_name": video_path.name,
            "speaker_count": len(persons),
            "transcript": transcript,
            "segments": segments,
        },
        "speaker_summary": (
            payload.get("speaker_summary")
            if isinstance(payload.get("speaker_summary"), dict)
            else {}
        ),
        "moss_correction": {
            "text_corrections": int(
                pipeline_info.get("moss_text_corrections") or 0
            ),
            "speaker_corrections": int(
                pipeline_info.get("moss_speaker_corrections") or 0
            ),
            "speaker_mapping": (
                pipeline_info.get("moss_chunk_speaker_mapping") or {}
            ),
        },
        "video_path": str(video_path),
        "output_dir": str(output_dir),
        "speaker_chat_json": str(output_json),
        "speaker_chat_csv": (
            str(output_csv) if output_csv.is_file() else None
        ),
        "speaker_face_dir": (
            str(face_dir) if face_dir is not None else None
        ),
        "conversation": segments,
    }


def _run_analysis_sync(
    video_path: Path,
    options: Mapping[str, Any],
) -> dict[str, Any]:
    script = _find_pipeline_script(options)
    module = _load_module(script)
    supported = _supported_options(module)

    project_root = _project_root()
    output_root = _resolve_path(
        options.get("output_root")
        or os.getenv("TIME_MEMORY_OUTPUT_ROOT"),
        project_root / "outputs" / "time_memory",
    )
    assert output_root is not None

    output_dir = output_root / _safe_name(video_path.stem)
    output_dir.mkdir(parents=True, exist_ok=True)

    output_json = _resolve_path(
        options.get("output_json"),
        output_dir / "speaker_chat.json",
    )
    output_csv = _resolve_path(
        options.get("output_csv"),
        output_dir / "speaker_chat.csv",
    )
    requested_faces = _resolve_path(
        options.get("faces_dir"),
        output_dir / "faces",
    )
    assert output_json is not None
    assert output_csv is not None
    assert requested_faces is not None

    models_root = _resolve_path(
        options.get("models_root")
        or os.getenv("TIME_MEMORY_MODELS_ROOT"),
        project_root / "models",
    )
    lrasd_root = _resolve_path(
        options.get("lrasd_root")
        or os.getenv("TIME_MEMORY_LRASD_ROOT"),
        project_root / "LR-ASD",
    )
    assert models_root is not None
    assert lrasd_root is not None

    visual_script = _resolve_path(
        options.get("visual_script")
        or os.getenv("TIME_MEMORY_VISUAL_SCRIPT")
    )

    argv: list[str] = []
    _append_value(argv, supported, "--video", video_path)
    _append_value(argv, supported, "--output-root", output_root)
    _append_value(argv, supported, "--output-json", output_json)
    _append_value(argv, supported, "--output-csv", output_csv)
    _append_value(argv, supported, "--faces-dir", requested_faces)
    _append_value(argv, supported, "--models-root", models_root)
    _append_value(argv, supported, "--asr-model", models_root / "asr")
    _append_value(argv, supported, "--vad-model", models_root / "vad")
    _append_value(argv, supported, "--punc-model", models_root / "punc")
    _append_value(
        argv,
        supported,
        "--pyannote-model",
        options.get("pyannote_model"),
    )
    _append_value(
        argv,
        supported,
        "--asr-device",
        options.get("asr_device", "cuda:0"),
    )
    _append_value(
        argv,
        supported,
        "--diarization-device",
        options.get("diarization_device", "cpu"),
    )
    _append_value(
        argv,
        supported,
        "--visual-device",
        options.get("visual_device", "cuda:0"),
    )
    _append_value(
        argv,
        supported,
        "--num-speakers",
        options.get("num_speakers"),
    )
    _append_value(argv, supported, "--lrasd-root", lrasd_root)
    _append_value(
        argv,
        supported,
        "--lrasd-weight",
        lrasd_root / "weight" / "pretrain_AVA.model",
    )
    _append_value(
        argv,
        supported,
        "--visual-python",
        options.get("visual_python", sys.executable),
    )
    _append_value(argv, supported, "--visual-script", visual_script)
    _append_flag(
        argv,
        supported,
        "--skip-moss",
        bool(options.get("skip_moss", True)),
    )
    _append_flag(
        argv,
        supported,
        "--skip-visual",
        bool(options.get("skip_visual", False)),
    )

    extra_args = options.get("pipeline_extra_args")
    if isinstance(extra_args, str) and extra_args.strip():
        argv.extend(shlex.split(extra_args, posix=os.name != "nt"))
    elif isinstance(extra_args, (list, tuple)):
        argv.extend(str(item) for item in extra_args)

    LOGGER.info("调用说话人分析脚本：%s", script)
    LOGGER.info("视频：%s", video_path)
    LOGGER.info("输出目录：%s", output_dir)

    return_code = _run_pipeline_main(module, argv)
    if return_code not in (None, 0):
        raise RuntimeError(
            f"speaker_video_pipeline 返回失败状态：{return_code}"
        )

    payload = _read_payload(output_json)
    face_dir = _find_face_dir(
        output_dir,
        output_json,
        requested_faces,
        payload,
    )

    result = _build_result(
        video_path,
        output_dir,
        output_json,
        output_csv,
        face_dir,
        payload,
    )
    LOGGER.info(
        "分析完成：%s；JSON=%s；人脸目录=%s",
        result["identify_brief"],
        result["speaker_chat_json"],
        result["speaker_face_dir"],
    )
    return result


async def analyze_video(
    video_path: str | Path,
    *,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """异步直接调用，不发送回调。"""
    video = Path(video_path).expanduser().resolve()
    if not video.is_file():
        raise FileNotFoundError(f"视频不存在：{video}")

    return await asyncio.to_thread(
        _run_analysis_sync,
        video,
        dict(options or {}),
    )


def analyze_video_sync(
    video_path: str | Path,
    *,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """普通 Python 程序直接调用。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(analyze_video(video_path, options=options))
    raise RuntimeError(
        "当前线程已有 asyncio 事件循环，请使用 "
        "await analyze_video(video_path, options=options)"
    )


async def _send_http_callback(
    callback_url: str,
    payload: Mapping[str, Any],
    timeout: int = 30,
    callback_token: str = "",
) -> None:
    """可选 HTTP 回调，不依赖 app.callback。"""
    if not callback_url:
        return

    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    def _request() -> None:
        request = urllib.request.Request(
            callback_url,
            data=body,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                **({"X-Internal-Token": callback_token} if callback_token else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=timeout,
            ) as response:
                if response.status >= 400:
                    raise RuntimeError(
                        f"回调失败，HTTP {response.status}"
                    )
        except urllib.error.URLError as exc:
            raise RuntimeError(f"回调请求失败：{exc}") from exc

    await asyncio.to_thread(_request)


async def run_time_analysis(
    job_id: str,
    memory_id: str,
    session_id: str,
    inputs: Mapping[str, Any],
    callback_url: str = "",
    callback: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """兼容任务调用入口。

    - 保留 job_id、memory_id、session_id、inputs、callback_url 参数；
    - callback_url 为空时不发送 HTTP 请求；
    - 可传入 callback 函数模拟外部系统；
    - 无论是否回调，成功时均返回完整 result。
    """
    video_value = inputs.get("video_path")
    if not video_value:
        raise ValueError("inputs 中缺少 video_path")

    LOGGER.info(
        "开始时间记忆分析 job=%s memory=%s session=%s video=%s",
        job_id,
        memory_id,
        session_id,
        video_value,
    )

    try:
        result = await analyze_video(
            str(video_value),
            options=inputs,
        )
        callback_payload = {
            "job_id": job_id,
            "memory_id": memory_id,
            "session_id": session_id,
            "status": "succeeded",
            "result": result,
            "error": None,
        }

        if callback is not None:
            callback_result = callback(callback_payload)
            if asyncio.iscoroutine(callback_result):
                await callback_result

        if callback_url:
            await _send_http_callback(
                callback_url,
                callback_payload,
                callback_token=str(inputs.get("callback_token") or os.getenv("COMPUTE_INTERNAL_TOKEN", "")),
            )

        return result

    except Exception as exc:
        LOGGER.exception("时间记忆分析失败：%s", exc)
        failure_payload = {
            "job_id": job_id,
            "memory_id": memory_id,
            "session_id": session_id,
            "status": "failed",
            "result": {},
            "error": str(exc),
        }

        if callback is not None:
            callback_result = callback(failure_payload)
            if asyncio.iscoroutine(callback_result):
                await callback_result

        if callback_url:
            await _send_http_callback(
                callback_url,
                failure_payload,
                callback_token=str(inputs.get("callback_token") or os.getenv("COMPUTE_INTERNAL_TOKEN", "")),
            )
        raise
