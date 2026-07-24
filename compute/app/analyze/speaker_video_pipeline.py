#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single-file multimodal speaker pipeline.

The module performs FunASR transcription, pyannote diarization, internal face
tracking/mouth-motion analysis, voice-prototype fusion, optional MOSS repair,
and project-facing result export without another Python entrypoint.
"""
from __future__ import annotations

import argparse
import csv
import gc
import importlib
import logging
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import wave
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np


SCRIPT_ROOT = Path(__file__).resolve().parent
DEFAULT_PROJECT_MODELS = SCRIPT_ROOT / "models"
DEFAULT_OUTPUT_ROOT = Path.cwd() / "out"


PUNCTUATION_RE = re.compile(r"[\s，。！？；：、,.!?;:'\"“”‘’（）()\[\]【】《》<>…—_-]+")
SPEAKER_PREFIX_RE = re.compile(r"^\[(?:S\d+|SPEAKER[_ -]?\d+)\]\s*", re.IGNORECASE)
TOKEN_RE = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*|[^\s]")
SENTENCE_END_RE = re.compile(r"[。！？!?；;]+[\"'”’）)】》]*$")
CLAUSE_END_RE = re.compile(r"[，,、：:]+[\"'”’）)】》]*$")


@dataclass(slots=True)
class SpeechSegment:
    start: float
    end: float
    text: str
    speaker: str = "unknown"
    asr_text: str = ""
    moss_text: str | None = None
    moss_speaker: str | None = None
    moss_corrected: bool = False
    moss_speaker_corrected: bool = False
    moss_similarity: float | None = None
    diarization_overlap: float = 0.0
    raw_speaker: str | None = None
    visual_person: str | None = None
    visual_score: float = 0.0
    voice_score: float = 0.0
    fusion_confidence: float = 0.0
    boundary_repaired: bool = False
    source: str = "funasr"


@dataclass(slots=True)
class SpeakerTurn:
    start: float
    end: float
    speaker: str


@dataclass(slots=True)
class MossSegment:
    start: float
    end: float
    text: str
    speaker: str
    chunk_index: int


@dataclass(slots=True)
class RuntimeStats:
    extract_audio_sec: float = 0.0
    funasr_sec: float = 0.0
    pyannote_sec: float = 0.0
    moss_sec: float = 0.0
    visual_sec: float = 0.0
    fusion_sec: float = 0.0
    total_sec: float = 0.0
    video_duration_sec: float = 0.0
    real_time_factor: float = 0.0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PipelineResult:
    video: Path
    output_dir: Path
    output_json: Path
    output_csv: Path
    faces_dir: Path
    avatar_dir: Path
    speaker_count: int
    sentence_count: int
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FaceObservation:
    time_sec: float
    bbox: tuple[int, int, int, int]
    descriptor: np.ndarray
    mouth_motion: float = 0.0
    speaking_score: float = 0.0
    sharpness: float = 0.0
    detection_confidence: float = 1.0


@dataclass(slots=True)
class FaceTrackLite:
    track_id: int
    observations: list[FaceObservation] = field(default_factory=list)
    identity_id: int = -1
    best_face: np.ndarray | None = None
    best_quality: float = -1.0
    last_face_gray: np.ndarray | None = None
    last_mouth_gray: np.ndarray | None = None

    @property
    def start(self) -> float:
        return self.observations[0].time_sec if self.observations else 0.0

    @property
    def end(self) -> float:
        return self.observations[-1].time_sec if self.observations else 0.0

    @property
    def descriptor(self) -> np.ndarray | None:
        if not self.observations:
            return None
        matrix = np.stack([item.descriptor for item in self.observations])
        value = np.median(matrix, axis=0).astype(np.float32)
        norm = float(np.linalg.norm(value))
        return value / norm if norm > 1e-8 else value


@dataclass(slots=True)
class VisualAnalysis:
    tracks: list[FaceTrackLite] = field(default_factory=list)
    identity_tracks: dict[str, list[int]] = field(default_factory=dict)
    identity_count: int = 0
    speaking_identity_count: int = 0
    simultaneous_lower_bound: int = 0
    active_identity_ids: set[int] = field(default_factory=set)
    sample_fps: float = 0.0
    frame_count: int = 0
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def interval_scores(self, start: float, end: float) -> dict[str, float]:
        result: dict[str, list[float]] = defaultdict(list)
        left = max(0.0, start - 0.08)
        right = end + 0.08
        for track in self.tracks:
            if track.identity_id < 0:
                continue
            if self.active_identity_ids and track.identity_id not in self.active_identity_ids:
                continue
            identity = f"可见人物{track.identity_id}"
            for observation in track.observations:
                if left <= observation.time_sec <= right:
                    result[identity].append(observation.speaking_score)
        scores: dict[str, float] = {}
        for identity, values in result.items():
            if values:
                peak = max(values)
                mean = float(np.mean(values))
                scores[identity] = float(min(1.0, 0.65 * peak + 0.35 * mean))
        return scores


def positive_float(value: str) -> float:
    result = float(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def positive_int(value: str) -> int:
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return result


def run_checked(command: Sequence[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if completed.returncode:
        details = "\n".join(part for part in (completed.stdout.strip(), completed.stderr.strip()) if part)
        raise RuntimeError(f"command failed ({completed.returncode}): {command!r}\n{details}")
    return completed


def ffprobe_duration(media: Path) -> float:
    result = run_checked(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media),
        ]
    )
    return max(0.0, float(result.stdout.strip()))


def extract_audio(video: Path, wav: Path) -> None:
    run_checked(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(video),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ]
    )


def clean_text(text: Any) -> str:
    result = str(text or "").strip()
    result = SPEAKER_PREFIX_RE.sub("", result)
    result = re.sub(r"<\|[^|>]+\|>", "", result)
    result = re.sub(r"\s+", " ", result)
    return result.strip()


def clean_sensevoice_text(text: str) -> str:
    """Match Echo time_memory's SenseVoice tag and event cleanup."""
    result = re.sub(r"<\s*\|\s*([^<>|]+?)\s*\|\s*>", r"<|\1|>", text or "")
    try:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        result = rich_transcription_postprocess(result).strip() or result
    except Exception:
        pass
    result = re.sub(r"<\|[^<>]*?\|>", " ", result)
    result = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", " ", result)
    return re.sub(r"\s+", " ", result).strip()


def has_spoken_content(text: str) -> bool:
    return any(character.isalnum() for character in text)


def normalize_text(text: str) -> str:
    return PUNCTUATION_RE.sub("", text).lower()


def millis_or_seconds(value: Any, *, default: float = 0.0) -> float:
    """Best-effort scalar conversion retained for legacy sentence-level fields.

    Word timestamps must not use this scalar heuristic because early millisecond
    values such as 470 or 990 would otherwise be misread as seconds.  Use
    ``_timestamp_pairs`` for a timestamp sequence.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number / 1000.0 if abs(number) >= 10_000.0 else number


def _timestamp_scale(raw_pairs: Sequence[tuple[float, float]], duration: float) -> float:
    """Infer one unit for the complete FunASR timestamp sequence.

    FunASR commonly returns milliseconds.  Inferring each value independently
    caused the observed 470-990 second phantom rows because those early
    millisecond values are numerically below 1000.
    """
    if not raw_pairs:
        return 1.0
    ends = [end for _start, end in raw_pairs]
    widths = [max(0.0, end - start) for start, end in raw_pairs if end > start]
    maximum = max(ends)
    median_width = float(np.median(widths)) if widths else 0.0
    if duration > 0 and maximum > max(duration * 1.5, duration + 5.0):
        return 0.001
    if maximum >= 10_000.0 or median_width >= 20.0:
        return 0.001
    return 1.0


def _timestamp_pairs(
    values: Sequence[Any],
    *,
    duration: float = 0.0,
) -> list[tuple[float, float]]:
    raw_pairs: list[tuple[float, float]] = []
    for value in values or []:
        if not isinstance(value, (list, tuple)) or len(value) < 2:
            continue
        try:
            raw_pairs.append((float(value[0]), float(value[1])))
        except (TypeError, ValueError):
            continue
    scale = _timestamp_scale(raw_pairs, duration)
    pairs: list[tuple[float, float]] = []
    for raw_start, raw_end in raw_pairs:
        start, end = raw_start * scale, raw_end * scale
        if duration > 0:
            start = min(max(0.0, start), duration)
            end = min(max(0.0, end), duration)
        if end > start:
            pairs.append((start, end))
    return pairs


def split_plain_transcript(text: str, timestamps: Sequence[Any], duration: float) -> list[SpeechSegment]:
    """Fallback for FunASR results that do not expose sentence_info."""
    text = clean_text(text)
    if not text:
        return []
    timestamp_pairs = _timestamp_pairs(timestamps, duration=duration)
    pieces = [piece.strip() for piece in re.findall(r".+?[。！？!?；;]|.+$", text) if piece.strip()]
    if not pieces:
        pieces = [text]
    weights = [max(1, len(normalize_text(piece))) for piece in pieces]
    total_weight = sum(weights)
    result: list[SpeechSegment] = []
    cursor = 0
    for index, (piece, weight) in enumerate(zip(pieces, weights)):
        next_cursor = len(timestamp_pairs) if index == len(pieces) - 1 else min(
            len(timestamp_pairs),
            cursor + max(1, round(len(timestamp_pairs) * weight / total_weight)),
        )
        selected = timestamp_pairs[cursor:next_cursor]
        if selected:
            start, end = selected[0][0], selected[-1][1]
        else:
            start = duration * sum(weights[:index]) / total_weight
            end = duration * sum(weights[: index + 1]) / total_weight
        if end > start:
            result.append(SpeechSegment(start=start, end=end, text=piece, asr_text=piece))
        cursor = next_cursor
    return result


def parse_funasr_result(result: Any, duration: float) -> list[SpeechSegment]:
    if isinstance(result, list):
        payload = result[0] if result else {}
    elif isinstance(result, dict):
        payload = result
    else:
        raise ValueError(f"unexpected FunASR result type: {type(result).__name__}")
    if not isinstance(payload, dict):
        raise ValueError("FunASR result does not contain a mapping")

    sentence_info = payload.get("sentence_info") or payload.get("sentences") or []
    segments: list[SpeechSegment] = []
    for item in sentence_info:
        if not isinstance(item, dict):
            continue
        text = clean_text(item.get("text"))
        if not text:
            continue
        start = millis_or_seconds(item.get("start", item.get("start_time", 0.0)))
        end = millis_or_seconds(item.get("end", item.get("end_time", start)))
        if end <= start:
            timestamps = item.get("timestamp") or []
            if timestamps:
                start = millis_or_seconds(timestamps[0][0])
                end = millis_or_seconds(timestamps[-1][1])
        if end > start:
            segments.append(SpeechSegment(start=start, end=end, text=text, asr_text=text))
    if not segments:
        segments = split_plain_transcript(
            clean_text(payload.get("text")),
            payload.get("timestamp") or [],
            duration,
        )
    return sorted(segments, key=lambda item: (item.start, item.end))


def _attach_punctuation(units: Sequence[Any]) -> list[str]:
    """Attach punctuation to the preceding spoken token.

    Paraformer normally returns ``text`` plus character/word timestamps but no
    ``words`` field.  Punctuation generated by CT-Punc has no corresponding
    timestamp, so it must be retained without consuming a timestamp entry.
    """
    tokens: list[str] = []
    leading = ""
    for unit in units:
        value = clean_sensevoice_text(str(unit))
        if not value:
            continue
        if has_spoken_content(value):
            tokens.append(leading + value)
            leading = ""
        elif tokens:
            tokens[-1] += value
        else:
            leading += value
    if leading and tokens:
        tokens[-1] += leading
    return tokens


def _paraformer_tokens(text: str, expected_count: int) -> list[str]:
    """Recover Paraformer timestamp tokens from its text field."""
    text = clean_sensevoice_text(text)
    if not text or expected_count <= 0:
        return []

    candidates = [
        _attach_punctuation(text.split()),
        _attach_punctuation(TOKEN_RE.findall(text)),
    ]
    for candidate in candidates:
        if len(candidate) == expected_count:
            return candidate
    return []


def run_funasr(
    wav: Path,
    *,
    asr_model: Path,
    vad_model: Path,
    punc_model: Path,
    device: str,
    batch_size_s: int,
    duration: float,
) -> list[SpeechSegment]:
    from funasr import AutoModel  # type: ignore

    for path in (asr_model, vad_model, punc_model):
        if not path.is_dir():
            raise FileNotFoundError(f"FunASR model directory does not exist: {path}")

    model = AutoModel(
        model=str(asr_model),
        vad_model=str(vad_model),
        punc_model=str(punc_model),
        output_timestamp=True,
        device=device,
        disable_update=True,
    )
    try:
        result = model.generate(
            input=str(wav),
            batch_size_s=batch_size_s,
            language=os.getenv("TIME_MEMORY_ASR_LANGUAGE", "zh"),
        )
        if not result:
            raise RuntimeError("FunASR returned no transcription result")
        output = result[0]
        if not isinstance(output, dict):
            raise RuntimeError(
                f"FunASR returned an unexpected item type: {type(output).__name__}"
            )

        timestamps = _timestamp_pairs(output.get("timestamp") or [], duration=duration)
        raw_words = list(output.get("words") or output.get("tokens") or [])
        words = _attach_punctuation(raw_words) if raw_words else []

        # SenseVoice exposes ``words``; Paraformer exposes only ``text`` and
        # ``timestamp``.  Recover the latter instead of raising words=0.
        if len(words) != len(timestamps):
            words = _paraformer_tokens(str(output.get("text") or ""), len(timestamps))

        segments: list[SpeechSegment] = []
        if words and len(words) == len(timestamps):
            for word, (start, end) in zip(words, timestamps):
                token_text = clean_sensevoice_text(str(word))
                if not token_text or not has_spoken_content(token_text):
                    continue
                segments.append(
                    SpeechSegment(
                        start=start,
                        end=end,
                        text=token_text,
                        asr_text=token_text,
                    )
                )
        else:
            # A future FunASR model may use a different token representation.
            # Keep the pipeline usable by falling back to sentence-level output.
            segments = parse_funasr_result(result, duration)
            if timestamps and not segments:
                raise RuntimeError(
                    "FunASR text/timestamps could not be aligned: "
                    f"tokens={len(words)} timestamps={len(timestamps)} "
                    f"text_length={len(str(output.get('text') or ''))}"
                )
    finally:
        del model
        gc.collect()
        release_cuda()

    if not segments:
        raise RuntimeError("FunASR returned no usable timestamped text")
    return sorted(segments, key=lambda item: (item.start, item.end))


def iter_annotation(annotation: Any) -> Iterable[SpeakerTurn]:
    if hasattr(annotation, "itertracks"):
        for turn, _track, speaker in annotation.itertracks(yield_label=True):
            yield SpeakerTurn(float(turn.start), float(turn.end), str(speaker))
        return
    for item in annotation:
        if not isinstance(item, tuple):
            continue
        if len(item) == 2:
            turn, speaker = item
        elif len(item) >= 3:
            turn, _track, speaker = item[:3]
        else:
            continue
        yield SpeakerTurn(float(turn.start), float(turn.end), str(speaker))


def _pyannote_local_candidates(model: Path) -> list[Path]:
    """Resolve a user supplied pyannote folder, HF cache folder, or snapshot.

    Windows projects commonly pass ``models/pyannote`` while the actual
    community-1 snapshot is nested below ``snapshots/<hash>``.  This resolver
    accepts all of those layouts and keeps execution fully offline.
    """
    model = model.expanduser().resolve()
    candidates: list[Path] = []
    if model.is_file():
        candidates.append(model)
    if model.is_dir():
        candidates.append(model)
        for name in ("config.yaml", "config.yml", "pipeline.yaml", "pipeline.yml"):
            candidate = model / name
            if candidate.is_file():
                candidates.append(candidate)
        for pattern in (
            "snapshots/*",
            "hub/models--pyannote--speaker-diarization-community-1/snapshots/*",
            "models--pyannote--speaker-diarization-community-1/snapshots/*",
            "**/models--pyannote--speaker-diarization-community-1/snapshots/*",
        ):
            for candidate in sorted(model.glob(pattern), reverse=True):
                if candidate.is_dir():
                    candidates.append(candidate)
                    config = candidate / "config.yaml"
                    if config.is_file():
                        candidates.append(config)
    # Also search next to the requested path and in the project model root.
    for base in dict.fromkeys([model.parent, DEFAULT_PROJECT_MODELS, SCRIPT_ROOT]):
        if not base.exists():
            continue
        for candidate in sorted(
            base.glob("**/models--pyannote--speaker-diarization-community-1/snapshots/*"),
            reverse=True,
        ):
            if candidate.is_dir():
                candidates.append(candidate)
                config = candidate / "config.yaml"
                if config.is_file():
                    candidates.append(config)
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower() if os.name == "nt" else str(candidate)
        if key not in seen and candidate.exists():
            seen.add(key)
            unique.append(candidate)
    return unique


def run_pyannote(
    wav: Path,
    *,
    model: Path,
    token: str | None,
    device: str,
    min_speakers: int | None,
    max_speakers: int | None,
    logger: logging.Logger | None = None,
) -> list[SpeakerTurn]:
    import torch  # type: ignore
    from pyannote.audio import Pipeline  # type: ignore

    requested_device = str(device).strip().lower()
    if requested_device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError(
            f"--diarization-device={device} was requested, but PyTorch CUDA is unavailable. "
            "Install a CUDA PyTorch build or use --diarization-device cpu."
        )

    local_candidates = _pyannote_local_candidates(model)
    sources: list[str] = [str(item) for item in local_candidates]
    if token:
        sources.append("pyannote/speaker-diarization-community-1")
    if not sources:
        raise RuntimeError(
            "No local pyannote community-1 model was found. "
            f"Received --pyannote-model={model}. Expected a snapshot containing config.yaml, "
            "for example models/pyannote/config.yaml or "
            "models/pyannote/models--pyannote--speaker-diarization-community-1/snapshots/<hash>/config.yaml. "
            "Alternatively set HF_TOKEN after accepting the model conditions."
        )

    pipeline = None
    failures: list[str] = []
    for source in sources:
        try:
            try:
                pipeline = Pipeline.from_pretrained(source, token=token)
            except TypeError:
                pipeline = Pipeline.from_pretrained(source, use_auth_token=token)
            if pipeline is not None:
                if logger:
                    logger.info("pyannote model source: %s", source)
                break
        except Exception as exc:
            failures.append(f"{source}: {type(exc).__name__}: {exc}")
            pipeline = None
    if pipeline is None:
        raise RuntimeError(
            "Unable to load pyannote community-1 from any local candidate. "
            + " | ".join(failures[:6])
        )

    torch_device = torch.device(device)
    pipeline.to(torch_device)
    if logger:
        gpu_name = None
        if torch_device.type == "cuda":
            gpu_name = torch.cuda.get_device_name(torch_device.index or 0)
        logger.info("pyannote device: %s%s", torch_device, f" ({gpu_name})" if gpu_name else "")

    kwargs: dict[str, int] = {}
    if min_speakers is not None:
        kwargs["min_speakers"] = min_speakers
    if max_speakers is not None:
        kwargs["max_speakers"] = max_speakers
    try:
        with wave.open(str(wav), "rb") as source:
            sample_rate = source.getframerate()
            channels = source.getnchannels()
            samples = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16)
        waveform = torch.from_numpy(samples.copy()).float().div_(32768.0)
        waveform = waveform.reshape(-1, channels).transpose(0, 1).contiguous()
        output = pipeline({"waveform": waveform, "sample_rate": sample_rate}, **kwargs)
        annotation = getattr(output, "exclusive_speaker_diarization", None)
        if annotation is None:
            annotation = getattr(output, "speaker_diarization", output)
        turns = sorted(iter_annotation(annotation), key=lambda item: (item.start, item.end))
    finally:
        del pipeline
        gc.collect()
        release_cuda()
    if not turns:
        raise RuntimeError("pyannote returned no speaker turns")
    return turns


def release_cuda() -> None:
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> float:
    return max(0.0, min(end_a, end_b) - max(start_a, start_b))


def speaker_for_interval(start: float, end: float, turns: Sequence[SpeakerTurn]) -> tuple[str, float]:
    scores: dict[str, float] = {}
    for turn in turns:
        amount = overlap(start, end, turn.start, turn.end)
        if amount > 0:
            scores[turn.speaker] = scores.get(turn.speaker, 0.0) + amount
    duration = max(1e-6, end - start)
    if scores:
        speaker, amount = max(scores.items(), key=lambda item: item[1])
        return speaker, amount / duration
    center = (start + end) / 2
    nearest = min(turns, key=lambda turn: abs((turn.start + turn.end) / 2 - center))
    return nearest.speaker, 0.0


def render_tokens(tokens: Sequence[str]) -> str:
    output = ""
    previous_ascii = False
    for token in tokens:
        ascii_word = bool(re.fullmatch(r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", token))
        if output and ascii_word and previous_ascii:
            output += " "
        output += token
        previous_ascii = ascii_word
    return output.strip()


def split_by_speaker_turns(segment: SpeechSegment, turns: Sequence[SpeakerTurn]) -> list[SpeechSegment]:
    clipped: list[tuple[float, float, str]] = []
    for turn in turns:
        start, end = max(segment.start, turn.start), min(segment.end, turn.end)
        if end - start >= 0.12:
            if clipped and clipped[-1][2] == turn.speaker and start - clipped[-1][1] <= 0.15:
                clipped[-1] = (clipped[-1][0], end, turn.speaker)
            else:
                clipped.append((start, end, turn.speaker))
    speaker_totals: dict[str, float] = {}
    for start, end, speaker in clipped:
        speaker_totals[speaker] = speaker_totals.get(speaker, 0.0) + end - start
    if len(speaker_totals) <= 1 or segment.end - segment.start < 1.2:
        speaker, share = speaker_for_interval(segment.start, segment.end, turns)
        segment.speaker = speaker
        segment.diarization_overlap = share
        return [segment]
    total = sum(speaker_totals.values())
    if max(speaker_totals.values()) / max(total, 1e-6) >= 0.85:
        speaker, share = speaker_for_interval(segment.start, segment.end, turns)
        segment.speaker = speaker
        segment.diarization_overlap = share
        return [segment]

    tokens = TOKEN_RE.findall(segment.text)
    if len(tokens) < len(clipped):
        speaker, share = speaker_for_interval(segment.start, segment.end, turns)
        segment.speaker = speaker
        segment.diarization_overlap = share
        return [segment]
    durations = [end - start for start, end, _speaker in clipped]
    result: list[SpeechSegment] = []
    cursor = 0
    remaining_duration = sum(durations)
    for index, ((start, end, speaker), turn_duration) in enumerate(zip(clipped, durations)):
        remaining_tokens = len(tokens) - cursor
        if index == len(clipped) - 1:
            count = remaining_tokens
        else:
            count = max(1, round(remaining_tokens * turn_duration / max(remaining_duration, 1e-6)))
            count = min(count, remaining_tokens - (len(clipped) - index - 1))
        text = render_tokens(tokens[cursor : cursor + count])
        cursor += count
        remaining_duration -= turn_duration
        if text:
            result.append(
                SpeechSegment(
                    start=start,
                    end=end,
                    text=text,
                    speaker=speaker,
                    asr_text=text,
                    diarization_overlap=min(1.0, turn_duration / max(end - start, 1e-6)),
                )
            )
    return result



def _cosine_similarity(left: np.ndarray | None, right: np.ndarray | None) -> float:
    if left is None or right is None or left.size == 0 or right.size == 0:
        return 0.0
    denominator = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denominator <= 1e-9:
        return 0.0
    return float(np.clip(np.dot(left, right) / denominator, -1.0, 1.0))


def _bbox_iou(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> float:
    lx, ly, lw, lh = left
    rx, ry, rw, rh = right
    x1, y1 = max(lx, rx), max(ly, ry)
    x2, y2 = min(lx + lw, rx + rw), min(ly + lh, ry + rh)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = lw * lh + rw * rh - intersection
    return float(intersection / union) if union > 0 else 0.0


def _face_descriptor(face: np.ndarray) -> np.ndarray:
    import cv2  # type: ignore

    resized = cv2.resize(face, (64, 64), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    center = gray[5:59, 7:57]
    low = cv2.resize(center, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32).reshape(-1)
    low = (low - float(low.mean())) / max(float(low.std()), 1e-6)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).reshape(-1).astype(np.float32)
    hist /= max(float(np.linalg.norm(hist)), 1e-6)
    descriptor = np.concatenate([low, hist]).astype(np.float32)
    descriptor /= max(float(np.linalg.norm(descriptor)), 1e-6)
    return descriptor


def _face_motion(previous_face: np.ndarray | None, current_face: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    import cv2  # type: ignore

    current = cv2.resize(current_face, (64, 64), interpolation=cv2.INTER_AREA)
    current_gray = cv2.cvtColor(current, cv2.COLOR_BGR2GRAY)
    current_mouth = current_gray[34:62, 10:54]
    if previous_face is None:
        return 0.0, current_gray, current_mouth
    previous = cv2.resize(previous_face, (64, 64), interpolation=cv2.INTER_AREA)
    previous_gray = cv2.cvtColor(previous, cv2.COLOR_BGR2GRAY)
    previous_mouth = previous_gray[34:62, 10:54]
    mouth_change = float(cv2.absdiff(current_mouth, previous_mouth).mean()) / 255.0
    head_change = float(cv2.absdiff(current_gray[5:34, 9:55], previous_gray[5:34, 9:55]).mean()) / 255.0
    local_motion = max(0.0, mouth_change - 0.65 * head_change)
    return local_motion, current_gray, current_mouth


def _track_overlap_seconds(left: FaceTrackLite, right: FaceTrackLite) -> float:
    return max(0.0, min(left.end, right.end) - max(left.start, right.start))



class _FaceDetectorBackend:
    """Uniform face detector interface with GPU-first fallback selection."""

    def __init__(self, name: str, detector: Any, detect_fn: Any, cleanup_fn: Any | None = None):
        self.name = name
        self.detector = detector
        self._detect_fn = detect_fn
        self._cleanup_fn = cleanup_fn

    def detect(self, frame: np.ndarray, min_face_size: int) -> list[tuple[int, int, int, int, float]]:
        return self._detect_fn(frame, min_face_size)

    def close(self) -> None:
        if self._cleanup_fn is not None:
            try:
                self._cleanup_fn()
            except Exception:
                pass
        self.detector = None
        gc.collect()
        release_cuda()


def _ascii_cache_directory() -> Path:
    """Return a writable ASCII-only cache directory for native OpenCV loaders."""
    candidates: list[Path] = []
    configured = os.getenv("SPEAKER_FUSION_ASCII_CACHE")
    if configured:
        candidates.append(Path(configured))
    if os.name == "nt":
        system_root = Path(os.environ.get("SystemRoot", r"C:\\Windows"))
        system_drive = Path(os.environ.get("SystemDrive", "C:"))
        candidates.extend([
            system_root / "Temp" / "speaker_fusion_cv",
            system_drive / "speaker_fusion_cv_cache",
        ])
    candidates.append(Path(tempfile.gettempdir()) / "speaker_fusion_cv")

    for candidate in candidates:
        try:
            if any(ord(character) > 127 for character in str(candidate)):
                continue
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_test"
            probe.write_text("ok", encoding="ascii")
            probe.unlink(missing_ok=True)
            return candidate
        except Exception:
            continue
    raise RuntimeError(
        "No writable ASCII-only cache directory is available. Set "
        "SPEAKER_FUSION_ASCII_CACHE to an English-only writable path, e.g. C:\\speaker_fusion_cache."
    )


def _resolve_haar_cascade_path(explicit_path: Path | None = None) -> Path:
    """Copy OpenCV's cascade to an ASCII path so Windows native code can load it."""
    import cv2  # type: ignore

    candidates: list[Path] = []
    if explicit_path is not None:
        candidates.append(explicit_path.expanduser().resolve())
    cv_data = getattr(cv2, "data", None)
    if cv_data is not None and getattr(cv_data, "haarcascades", None):
        candidates.append(Path(cv_data.haarcascades) / "haarcascade_frontalface_default.xml")
    candidates.extend([
        SCRIPT_ROOT / "models" / "haarcascade_frontalface_default.xml",
        SCRIPT_ROOT / "haarcascade_frontalface_default.xml",
    ])
    source = next((item for item in candidates if item.is_file()), None)
    if source is None:
        raise FileNotFoundError(
            "haarcascade_frontalface_default.xml was not found. Install opencv-python or pass --face-cascade."
        )
    if not any(ord(character) > 127 for character in str(source)):
        return source
    cache = _ascii_cache_directory()
    target = cache / "haarcascade_frontalface_default.xml"
    if not target.is_file() or target.stat().st_size != source.stat().st_size:
        shutil.copy2(source, target)
    return target


def _resolve_lrasd_root(explicit_root: Path | None) -> Path | None:
    candidates: list[Path] = []
    if explicit_root is not None:
        candidates.append(explicit_root.expanduser().resolve())
    candidates.extend([
        SCRIPT_ROOT / "LR-ASD",
        SCRIPT_ROOT.parent / "LR-ASD",
        SCRIPT_ROOT / "vendor" / "LR-ASD",
        SCRIPT_ROOT.parent / "vendor" / "LR-ASD",
        Path.cwd() / "LR-ASD",
    ])
    # Search nested project layouts once so users do not need to pass a long path.
    for base in dict.fromkeys([SCRIPT_ROOT, SCRIPT_ROOT.parent, Path.cwd()]):
        if not base.exists():
            continue
        try:
            for weight in base.glob("**/model/faceDetector/s3fd/sfd_face.pth"):
                candidates.append(weight.parents[3])
        except OSError:
            pass
    seen: set[str] = set()
    for root in candidates:
        key = str(root).lower() if os.name == "nt" else str(root)
        if key in seen:
            continue
        seen.add(key)
        if (root / "model" / "faceDetector" / "s3fd" / "__init__.py").is_file() and (
            root / "model" / "faceDetector" / "s3fd" / "sfd_face.pth"
        ).is_file():
            return root
    return None


def _create_face_detector(
    *,
    backend: str,
    device: str,
    cascade_path: Path | None,
    lrasd_root: Path | None,
    confidence: float,
    facedet_scale: float,
    logger: logging.Logger | None,
    allow_cpu_fallback: bool = False,
) -> _FaceDetectorBackend:
    """Create a GPU detector; CPU fallback is opt-in for reproducible accuracy."""
    import cv2  # type: ignore

    requested = backend.lower().strip()
    failures: list[str] = []

    # 1) LR-ASD S3FD: highest-quality GPU option already used by LR-ASD projects.
    if requested in {"auto", "s3fd"}:
        root = _resolve_lrasd_root(lrasd_root)
        if root is None:
            failures.append("S3FD: LR-ASD model directory not found")
        else:
            try:
                import torch  # type: ignore

                if not device.lower().startswith("cuda") or not torch.cuda.is_available():
                    raise RuntimeError("CUDA is unavailable or --visual-device is not cuda:N")
                root_text = str(root)
                sys.path.insert(0, root_text)
                try:
                    module = importlib.import_module("model.faceDetector.s3fd")
                    s3fd_class = getattr(module, "S3FD")
                    detector = s3fd_class(device=device)
                finally:
                    try:
                        sys.path.remove(root_text)
                    except ValueError:
                        pass

                def detect_s3fd(frame: np.ndarray, min_face_size: int) -> list[tuple[int, int, int, int, float]]:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    raw = detector.detect_faces(rgb, conf_th=float(confidence), scales=[float(facedet_scale)])
                    height, width = frame.shape[:2]
                    result: list[tuple[int, int, int, int, float]] = []
                    for box in np.asarray(raw).reshape(-1, 5) if np.asarray(raw).size else []:
                        x1, y1, x2, y2, score = [float(value) for value in box]
                        x1, y1 = max(0, int(round(x1))), max(0, int(round(y1)))
                        x2, y2 = min(width, int(round(x2))), min(height, int(round(y2)))
                        if x2 - x1 >= min_face_size and y2 - y1 >= min_face_size:
                            result.append((x1, y1, x2 - x1, y2 - y1, score))
                    return result

                if logger:
                    logger.info("face detector backend: s3fd-gpu (%s)", device)
                return _FaceDetectorBackend("s3fd-gpu", detector, detect_s3fd)
            except Exception as exc:
                failures.append(f"S3FD: {type(exc).__name__}: {exc}")
                if requested == "s3fd":
                    raise RuntimeError("Failed to initialize requested S3FD detector: " + failures[-1]) from exc

    # 2) OpenCV CUDA Haar. This is available only in a CUDA-enabled OpenCV build.
    if requested in {"auto", "opencv-cuda-haar"}:
        try:
            cuda_count = int(cv2.cuda.getCudaEnabledDeviceCount()) if hasattr(cv2, "cuda") else 0
            if cuda_count <= 0:
                raise RuntimeError("OpenCV was built without CUDA support")
            ascii_cascade = _resolve_haar_cascade_path(cascade_path)
            factory = getattr(cv2.cuda, "CascadeClassifier_create", None)
            if factory is None:
                classifier_type = getattr(cv2.cuda, "CascadeClassifier", None)
                factory = getattr(classifier_type, "create", None) if classifier_type is not None else None
            if factory is None:
                raise RuntimeError("cv2.cuda CascadeClassifier API is unavailable")
            detector = factory(str(ascii_cascade))
            if hasattr(detector, "setScaleFactor"):
                detector.setScaleFactor(1.08)
            if hasattr(detector, "setMinNeighbors"):
                detector.setMinNeighbors(5)

            def detect_cuda_haar(frame: np.ndarray, min_face_size: int) -> list[tuple[int, int, int, int, float]]:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                gpu_gray = cv2.cuda_GpuMat()
                gpu_gray.upload(gray)
                if hasattr(detector, "setMinObjectSize"):
                    detector.setMinObjectSize((int(min_face_size), int(min_face_size)))
                raw = detector.detectMultiScale(gpu_gray)
                converted = detector.convert(raw) if hasattr(detector, "convert") else raw
                array = np.asarray(converted).reshape(-1, 4) if np.asarray(converted).size else np.empty((0, 4))
                return [(int(x), int(y), int(w), int(h), 1.0) for x, y, w, h in array]

            if logger:
                logger.info("face detector backend: opencv-cuda-haar (GPU %s)", device)
            return _FaceDetectorBackend("opencv-cuda-haar", detector, detect_cuda_haar)
        except Exception as exc:
            failures.append(f"OpenCV CUDA Haar: {type(exc).__name__}: {exc}")
            if requested == "opencv-cuda-haar":
                raise RuntimeError("Failed to initialize requested OpenCV CUDA detector: " + failures[-1]) from exc

    # 3) CPU Haar fallback.  When a CUDA device was requested, do not silently
    # degrade to Haar unless the user explicitly allows it.  Silent fallback was
    # the cause of dozens of fragmented identities in long videos.
    if requested == "auto" and device.lower().startswith("cuda") and not allow_cpu_fallback:
        raise RuntimeError(
            "GPU visual detection was requested but neither S3FD nor OpenCV CUDA could be initialized. "
            "Place LR-ASD under ./LR-ASD or pass --lrasd-root <path>, and verify "
            "LR-ASD/model/faceDetector/s3fd/sfd_face.pth. Backend failures: "
            + " | ".join(failures)
        )
    if requested not in {"auto", "opencv-haar"}:
        raise ValueError(f"unsupported face detector backend: {backend}")
    ascii_cascade = _resolve_haar_cascade_path(cascade_path)
    detector = cv2.CascadeClassifier(str(ascii_cascade))
    if detector.empty():
        raise RuntimeError(
            f"OpenCV face detector could not be loaded from ASCII cache: {ascii_cascade}; "
            f"previous backend failures: {' | '.join(failures)}"
        )

    def detect_cpu_haar(frame: np.ndarray, min_face_size: int) -> list[tuple[int, int, int, int, float]]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        boxes = detector.detectMultiScale(
            gray,
            scaleFactor=1.08,
            minNeighbors=5,
            minSize=(int(min_face_size), int(min_face_size)),
        )
        return [(int(x), int(y), int(w), int(h), 1.0) for x, y, w, h in boxes]

    if logger:
        if failures:
            logger.warning("GPU face detector unavailable; falling back to CPU Haar: %s", " | ".join(failures))
        logger.info("face detector backend: opencv-haar-cpu; cascade=%s", ascii_cascade)
    return _FaceDetectorBackend("opencv-haar-cpu", detector, detect_cpu_haar)


def analyze_video_faces(
    video: Path,
    faces_dir: Path,
    *,
    sample_fps: float = 8.0,
    min_face_size: int = 48,
    max_track_gap: float = 0.65,
    identity_similarity: float = 0.86,
    detector_backend: str = "auto",
    detector_device: str = "cuda:0",
    face_cascade: Path | None = None,
    lrasd_root: Path | None = None,
    face_confidence: float = 0.82,
    facedet_scale: float = 0.25,
    logger: logging.Logger | None = None,
    allow_cpu_fallback: bool = False,
    target_speaker_count: int | None = None,
) -> VisualAnalysis:
    """Dependency-light face tracking and mouth-motion analysis.

    This is deliberately independent of the audio result.  Face tracks provide
    a visible-person upper bound and high-confidence mouth-motion anchors.  The
    The detector is GPU-first: LR-ASD S3FD, then OpenCV CUDA Haar, then a
    Unicode-safe CPU Haar fallback. No external Python entrypoint is launched.
    """
    import cv2  # type: ignore

    faces_dir.mkdir(parents=True, exist_ok=True)
    for stale in faces_dir.glob("*"):
        if stale.is_file():
            stale.unlink()
        elif stale.is_dir():
            shutil.rmtree(stale)

    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"cannot open video for visual analysis: {video}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 25.0)
    total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    stride = max(1, int(round(fps / max(sample_fps, 0.5))))
    detector = _create_face_detector(
        backend=detector_backend,
        device=detector_device,
        cascade_path=face_cascade,
        lrasd_root=lrasd_root,
        confidence=face_confidence,
        facedet_scale=facedet_scale,
        logger=logger,
        allow_cpu_fallback=allow_cpu_fallback,
    )
    if logger:
        logger.info("visual detector selected: %s; device=%s", detector.name, detector_device)

    tracks: list[FaceTrackLite] = []
    frame_index = 0
    sampled_frames = 0
    while True:
        ok, frame = capture.read()
        if not ok or frame is None:
            break
        if frame_index % stride != 0:
            frame_index += 1
            continue
        sampled_frames += 1
        timestamp = frame_index / fps
        boxes = detector.detect(frame, min_face_size)
        detections: list[dict[str, Any]] = []
        height, width = frame.shape[:2]
        for x, y, w, h, detection_confidence in boxes:
            margin_x, margin_y = int(w * 0.08), int(h * 0.08)
            x1, y1 = max(0, x - margin_x), max(0, y - margin_y)
            x2, y2 = min(width, x + w + margin_x), min(height, y + h + margin_y)
            crop = frame[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            descriptor = _face_descriptor(crop)
            sharpness = float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
            detections.append({
                "bbox": (int(x1), int(y1), int(x2 - x1), int(y2 - y1)),
                "crop": crop.copy(),
                "descriptor": descriptor,
                "sharpness": sharpness,
                "detection_confidence": float(detection_confidence),
            })

        active = [
            track for track in tracks
            if track.observations and timestamp - track.end <= max_track_gap
        ]
        pairs: list[tuple[float, int, int]] = []
        for track_index, track in enumerate(active):
            last = track.observations[-1]
            for detection_index, detection in enumerate(detections):
                iou = _bbox_iou(last.bbox, detection["bbox"])
                appearance = (_cosine_similarity(last.descriptor, detection["descriptor"]) + 1.0) / 2.0
                lx, ly, lw, lh = last.bbox
                rx, ry, rw, rh = detection["bbox"]
                distance = math.hypot((lx + lw / 2) - (rx + rw / 2), (ly + lh / 2) - (ry + rh / 2))
                scale = max(1.0, math.hypot(width, height))
                proximity = max(0.0, 1.0 - distance / (0.35 * scale))
                score = 0.45 * iou + 0.35 * appearance + 0.20 * proximity
                if score >= 0.38:
                    pairs.append((score, track_index, detection_index))
        pairs.sort(reverse=True)
        used_tracks: set[int] = set()
        used_detections: set[int] = set()
        matches: dict[int, int] = {}
        for _score, track_index, detection_index in pairs:
            if track_index in used_tracks or detection_index in used_detections:
                continue
            used_tracks.add(track_index)
            used_detections.add(detection_index)
            matches[detection_index] = track_index

        for detection_index, detection in enumerate(detections):
            if detection_index in matches:
                track = active[matches[detection_index]]
            else:
                track = FaceTrackLite(track_id=len(tracks))
                tracks.append(track)
            previous_crop = track.best_face if track.observations else None
            motion, face_gray, mouth_gray = _face_motion(previous_crop, detection["crop"])
            observation = FaceObservation(
                time_sec=timestamp,
                bbox=detection["bbox"],
                descriptor=detection["descriptor"],
                mouth_motion=motion,
                sharpness=detection["sharpness"],
                detection_confidence=float(detection["detection_confidence"]),
            )
            track.observations.append(observation)
            track.last_face_gray = face_gray
            track.last_mouth_gray = mouth_gray
            quality = detection["sharpness"] * math.sqrt(max(1, detection["bbox"][2] * detection["bbox"][3]))
            if quality > track.best_quality:
                track.best_quality = quality
                track.best_face = detection["crop"].copy()
        frame_index += 1
    capture.release()
    detector.close()

    raw_track_count = len(tracks)
    minimum_observations = max(3, int(round(sample_fps * 0.40)))
    filtered_tracks: list[FaceTrackLite] = []
    for track in tracks:
        if len(track.observations) < minimum_observations:
            continue
        confidences = [item.detection_confidence for item in track.observations]
        box_sizes = [min(item.bbox[2], item.bbox[3]) for item in track.observations]
        if confidences and float(np.median(confidences)) < max(0.55, face_confidence * 0.72):
            continue
        if box_sizes and float(np.median(box_sizes)) < float(min_face_size):
            continue
        filtered_tracks.append(track)
    tracks = filtered_tracks
    for new_id, track in enumerate(tracks):
        track.track_id = new_id

    parent = list(range(len(tracks)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    candidates: list[tuple[float, int, int]] = []
    for left in range(len(tracks)):
        for right in range(left + 1, len(tracks)):
            # Two tracks visible at the same time can never be the same person.
            if _track_overlap_seconds(tracks[left], tracks[right]) > 0.12:
                continue
            similarity = (_cosine_similarity(tracks[left].descriptor, tracks[right].descriptor) + 1.0) / 2.0
            if similarity >= identity_similarity:
                candidates.append((similarity, left, right))
    for _similarity, left, right in sorted(candidates, reverse=True):
        union(left, right)

    roots: dict[int, int] = {}
    for index, track in enumerate(tracks):
        root = find(index)
        if root not in roots:
            roots[root] = len(roots)
        track.identity_id = roots[root]

    identity_tracks: dict[str, list[int]] = defaultdict(list)
    for track in tracks:
        identity_tracks[f"可见人物{track.identity_id}"].append(track.track_id)

    # Normalize mouth motion per visible identity.  This avoids declaring a
    # listener as speaking merely because the camera itself is moving.
    speaking_identities: set[int] = set()
    for identity_name, track_ids in identity_tracks.items():
        observations = [
            observation
            for track_id in track_ids
            for observation in tracks[track_id].observations
        ]
        motions = np.asarray([item.mouth_motion for item in observations], dtype=np.float32)
        baseline = float(np.median(motions)) if len(motions) else 0.0
        high = float(np.quantile(motions, 0.90)) if len(motions) >= 3 else baseline
        scale = max(0.006, high - baseline)
        positive_count = 0
        for item in observations:
            item.speaking_score = float(np.clip((item.mouth_motion - baseline) / scale, 0.0, 1.0))
            positive_count += int(item.speaking_score >= 0.55)
        if positive_count >= max(2, int(round(sample_fps * 0.20))):
            speaking_identities.add(int(identity_name.replace("可见人物", "")))

    # In fixed-speaker mode, keep only the strongest visual speaker identities
    # for audio/visual fusion.  Other visible faces remain diagnostic detections
    # but cannot create dozens of false speaker candidates.
    identity_strength: dict[int, float] = {}
    for identity_name, track_ids in identity_tracks.items():
        identity_id = int(identity_name.replace("可见人物", ""))
        observations = [
            observation
            for track_id in track_ids
            for observation in tracks[track_id].observations
        ]
        positives = sum(item.speaking_score >= 0.45 for item in observations)
        strength = float(sum(item.speaking_score for item in observations) + 0.03 * len(observations) + positives)
        identity_strength[identity_id] = strength
    ranked_identity_ids = [
        identity_id
        for identity_id, _value in sorted(identity_strength.items(), key=lambda item: item[1], reverse=True)
    ]
    if target_speaker_count is not None and target_speaker_count > 0:
        active_identity_ids = set(ranked_identity_ids[:target_speaker_count])
    else:
        active_identity_ids = set(ranked_identity_ids)
    speaking_identities.intersection_update(active_identity_ids)

    # Maximum simultaneous stable tracks is a strict visible-person lower bound.
    times = sorted({item.time_sec for track in tracks for item in track.observations})
    simultaneous_lower_bound = 0
    tolerance = 0.55 / max(sample_fps, 0.5)
    for timestamp in times:
        count = 0
        for track in tracks:
            if any(abs(item.time_sec - timestamp) <= tolerance for item in track.observations):
                count += 1
        simultaneous_lower_bound = max(simultaneous_lower_bound, count)

    for identity_name, track_ids in identity_tracks.items():
        identity_id = int(identity_name.replace("可见人物", ""))
        if active_identity_ids and identity_id not in active_identity_ids:
            continue
        candidates_for_avatar = [tracks[index] for index in track_ids if tracks[index].best_face is not None]
        if not candidates_for_avatar:
            continue
        best = max(candidates_for_avatar, key=lambda item: item.best_quality)
        target = faces_dir / f"{identity_name}.jpg"
        ok, encoded = cv2.imencode(".jpg", best.best_face, [cv2.IMWRITE_JPEG_QUALITY, 94])
        if ok:
            encoded.tofile(str(target))

    diagnostics = {
        "backend": detector.name + "+internal_face_tracks+mouth_motion",
        "detector_device": detector_device,
        "sample_fps": sample_fps,
        "source_fps": fps,
        "sampled_frames": sampled_frames,
        "total_frames": total_frames,
        "detected_track_count_before_filter": raw_track_count,
        "raw_track_count": len(tracks),
        "raw_identity_count": len(identity_tracks),
        "identity_count": len(active_identity_ids),
        "active_identity_ids": sorted(active_identity_ids),
        "speaking_identity_count": len(speaking_identities),
        "simultaneous_lower_bound": simultaneous_lower_bound,
        "identity_tracks": dict(identity_tracks),
    }
    (faces_dir / "manifest.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return VisualAnalysis(
        tracks=tracks,
        identity_tracks=dict(identity_tracks),
        identity_count=len(active_identity_ids),
        speaking_identity_count=len(speaking_identities),
        simultaneous_lower_bound=min(simultaneous_lower_bound, target_speaker_count) if target_speaker_count else simultaneous_lower_bound,
        active_identity_ids=active_identity_ids,
        sample_fps=sample_fps,
        frame_count=sampled_frames,
        diagnostics=diagnostics,
    )


def _speaker_overlap_scores(start: float, end: float, turns: Sequence[SpeakerTurn]) -> dict[str, float]:
    duration = max(1e-6, end - start)
    scores: dict[str, float] = defaultdict(float)
    for turn in turns:
        amount = overlap(start, end, turn.start, turn.end)
        if amount > 0:
            scores[turn.speaker] += amount / duration
    if not scores and turns:
        center = (start + end) / 2.0
        nearest = min(turns, key=lambda item: abs((item.start + item.end) / 2.0 - center))
        scores[nearest.speaker] = 0.25
    return {speaker: float(min(1.0, score)) for speaker, score in scores.items()}


def _load_wav_float(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as source:
        rate = source.getframerate()
        channels = source.getnchannels()
        samples = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16).astype(np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples / 32768.0, rate


def _acoustic_feature(audio: np.ndarray, rate: int, start: float, end: float) -> np.ndarray | None:
    left = max(0, int(round(start * rate)))
    right = min(len(audio), int(round(end * rate)))
    if right - left < int(rate * 0.06):
        center = (left + right) // 2
        half = int(rate * 0.08)
        left, right = max(0, center - half), min(len(audio), center + half)
    samples = audio[left:right]
    if len(samples) < 32:
        return None
    samples = samples - float(np.mean(samples))
    frame_length = max(128, int(round(rate * 0.025)))
    hop = max(64, int(round(rate * 0.010)))
    if len(samples) < frame_length:
        samples = np.pad(samples, (0, frame_length - len(samples)))
    frames = []
    for offset in range(0, max(1, len(samples) - frame_length + 1), hop):
        frame = samples[offset:offset + frame_length]
        if len(frame) < frame_length:
            frame = np.pad(frame, (0, frame_length - len(frame)))
        frames.append(frame * np.hanning(frame_length))
    matrix = np.stack(frames)
    spectrum = np.abs(np.fft.rfft(matrix, n=512)) ** 2
    mean_spectrum = np.log1p(np.mean(spectrum, axis=0))
    bands = np.asarray([float(np.mean(chunk)) for chunk in np.array_split(mean_spectrum[1:], 24)], dtype=np.float32)
    rms = float(np.sqrt(np.mean(samples * samples) + 1e-12))
    zcr = float(np.mean(np.abs(np.diff(np.signbit(samples)).astype(np.float32))))
    frequencies = np.fft.rfftfreq(512, 1.0 / rate)
    power = np.mean(spectrum, axis=0)
    total = float(np.sum(power) + 1e-12)
    centroid = float(np.sum(frequencies * power) / total) / (rate / 2.0)
    bandwidth = float(np.sqrt(np.sum(((frequencies / (rate / 2.0) - centroid) ** 2) * power) / total))
    feature = np.concatenate([bands, np.asarray([math.log1p(rms * 100.0), zcr, centroid, bandwidth], dtype=np.float32)])
    feature = feature - float(feature.mean())
    feature /= max(float(np.linalg.norm(feature)), 1e-6)
    return feature.astype(np.float32)


def _build_voice_prototypes(audio: np.ndarray, rate: int, turns: Sequence[SpeakerTurn]) -> dict[str, np.ndarray]:
    values: dict[str, list[np.ndarray]] = defaultdict(list)
    for turn in turns:
        start, end = turn.start, turn.end
        if end - start < 0.35:
            continue
        cursor = start
        while cursor < end:
            chunk_end = min(end, cursor + 2.5)
            feature = _acoustic_feature(audio, rate, cursor, chunk_end)
            if feature is not None:
                values[turn.speaker].append(feature)
            cursor = chunk_end
    prototypes: dict[str, np.ndarray] = {}
    for speaker, features in values.items():
        prototype = np.median(np.stack(features), axis=0).astype(np.float32)
        prototype /= max(float(np.linalg.norm(prototype)), 1e-6)
        prototypes[speaker] = prototype
    return prototypes


def _visual_voice_mapping(
    words: Sequence[SpeechSegment],
    turns: Sequence[SpeakerTurn],
    visual: VisualAnalysis | None,
) -> tuple[dict[str, str], dict[str, Any]]:
    if visual is None or visual.identity_count == 0:
        return {}, {"votes": {}, "mapping": {}}
    votes: dict[tuple[str, str], float] = defaultdict(float)
    for word in words:
        visual_scores = visual.interval_scores(word.start, word.end)
        if not visual_scores:
            continue
        ranked_visual = sorted(visual_scores.items(), key=lambda item: item[1], reverse=True)
        top_identity, top_visual = ranked_visual[0]
        runner_up = ranked_visual[1][1] if len(ranked_visual) > 1 else 0.0
        if top_visual < 0.55 or top_visual - runner_up < 0.15:
            continue
        audio_scores = _speaker_overlap_scores(word.start, word.end, turns)
        if not audio_scores:
            continue
        speaker, audio_score = max(audio_scores.items(), key=lambda item: item[1])
        if audio_score < 0.45:
            continue
        votes[(speaker, top_identity)] += max(0.05, word.end - word.start) * top_visual * audio_score

    mapping: dict[str, str] = {}
    used_identities: set[str] = set()
    for (speaker, identity), value in sorted(votes.items(), key=lambda item: item[1], reverse=True):
        if speaker in mapping or identity in used_identities:
            continue
        speaker_total = sum(score for (candidate, _identity), score in votes.items() if candidate == speaker)
        if speaker_total <= 0 or value / speaker_total < 0.52:
            continue
        mapping[speaker] = identity
        used_identities.add(identity)
    return mapping, {
        "votes": {f"{speaker}->{identity}": round(value, 6) for (speaker, identity), value in votes.items()},
        "mapping": mapping,
    }


def fuse_word_speakers(
    words: Sequence[SpeechSegment],
    turns: Sequence[SpeakerTurn],
    wav: Path,
    visual: VisualAnalysis | None,
    *,
    switch_penalty: float = 0.30,
) -> tuple[list[SpeechSegment], dict[str, Any]]:
    """Assign speaker labels with a Viterbi-style multimodal sequence model."""
    result = list(sorted(words, key=lambda item: (item.start, item.end)))
    speakers = sorted({turn.speaker for turn in turns})
    if not result or not speakers:
        return result, {"mapping": {}, "word_count": len(result)}

    audio, rate = _load_wav_float(wav)
    prototypes = _build_voice_prototypes(audio, rate, turns)
    mapping, mapping_diagnostics = _visual_voice_mapping(result, turns, visual)
    mapped_identities = set(mapping.values())

    emissions: list[dict[str, float]] = []
    evidence_rows: list[dict[str, Any]] = []
    for word in result:
        diarization_scores = _speaker_overlap_scores(word.start, word.end, turns)
        feature = _acoustic_feature(audio, rate, word.start, word.end)
        voice_scores = {
            speaker: max(0.0, (_cosine_similarity(feature, prototypes.get(speaker)) + 1.0) / 2.0)
            for speaker in speakers
        }
        visual_scores = visual.interval_scores(word.start, word.end) if visual is not None else {}
        top_visible = max(visual_scores.values()) if visual_scores else 0.0
        row: dict[str, float] = {}
        for speaker in speakers:
            pyannote_score = diarization_scores.get(speaker, 0.0)
            voice_score = voice_scores.get(speaker, 0.5)
            identity = mapping.get(speaker)
            if identity is not None:
                visual_score = visual_scores.get(identity, 0.0)
            elif top_visible < 0.35 and speaker not in mapping:
                # No visible mouth is active: support an off-screen/wearer voice.
                visual_score = 0.58
            elif identity is None and not mapping:
                visual_score = 0.50
            else:
                visual_score = 0.05
            row[speaker] = 0.48 * pyannote_score + 0.22 * voice_score + 0.25 * visual_score + 0.05
        emissions.append(row)
        evidence_rows.append({
            "start": round(word.start, 3),
            "end": round(word.end, 3),
            "text": word.text,
            "diarization": {key: round(value, 4) for key, value in diarization_scores.items()},
            "voice": {key: round(value, 4) for key, value in voice_scores.items()},
            "visual": {key: round(value, 4) for key, value in visual_scores.items()},
        })

    dp: list[dict[str, float]] = []
    back: list[dict[str, str | None]] = []
    dp.append(dict(emissions[0]))
    back.append({speaker: None for speaker in speakers})
    for index in range(1, len(result)):
        gap = max(0.0, result[index].start - result[index - 1].end)
        current_dp: dict[str, float] = {}
        current_back: dict[str, str | None] = {}
        current_audio = _speaker_overlap_scores(result[index].start, result[index].end, turns)
        previous_audio = _speaker_overlap_scores(result[index - 1].start, result[index - 1].end, turns)
        current_top = max(current_audio, key=current_audio.get) if current_audio else None
        previous_top = max(previous_audio, key=previous_audio.get) if previous_audio else None
        for speaker in speakers:
            best_score = -1e18
            best_previous: str | None = None
            for previous_speaker in speakers:
                penalty = 0.0
                if previous_speaker != speaker:
                    penalty = switch_penalty
                    if gap >= 0.35:
                        penalty = min(penalty, 0.12)
                    elif current_top == speaker and previous_top == previous_speaker:
                        if current_audio.get(speaker, 0.0) >= 0.78:
                            penalty = min(penalty, 0.08)
                candidate = dp[index - 1][previous_speaker] + emissions[index][speaker] - penalty
                if candidate > best_score:
                    best_score = candidate
                    best_previous = previous_speaker
            current_dp[speaker] = best_score
            current_back[speaker] = best_previous
        dp.append(current_dp)
        back.append(current_back)

    path = [max(dp[-1], key=dp[-1].get)]
    for index in range(len(result) - 1, 0, -1):
        previous = back[index][path[-1]]
        path.append(previous if previous is not None else path[-1])
    path.reverse()

    for index, (word, speaker) in enumerate(zip(result, path)):
        ranked = sorted(emissions[index].items(), key=lambda item: item[1], reverse=True)
        best = emissions[index][speaker]
        runner_up = max((value for candidate, value in ranked if candidate != speaker), default=0.0)
        diarization_scores = _speaker_overlap_scores(word.start, word.end, turns)
        feature = _acoustic_feature(audio, rate, word.start, word.end)
        voice_score = max(0.0, (_cosine_similarity(feature, prototypes.get(speaker)) + 1.0) / 2.0)
        visual_scores = visual.interval_scores(word.start, word.end) if visual is not None else {}
        word.raw_speaker = max(diarization_scores, key=diarization_scores.get) if diarization_scores else speaker
        word.speaker = speaker
        word.diarization_overlap = diarization_scores.get(speaker, 0.0)
        word.voice_score = voice_score
        word.visual_person = mapping.get(speaker)
        word.visual_score = visual_scores.get(word.visual_person, 0.0) if word.visual_person else 0.0
        margin = max(0.0, best - runner_up)
        word.fusion_confidence = float(np.clip(0.45 + 0.75 * margin, 0.0, 1.0))
        word.source = "funasr+pyannote+voice_prototype+visual_track_viterbi"

    diagnostics = {
        "candidate_speakers": speakers,
        "voice_prototype_count": len(prototypes),
        "audio_to_visual": mapping,
        "mapping_evidence": mapping_diagnostics,
        "word_evidence": evidence_rows,
        "switch_penalty": switch_penalty,
    }
    return result, diagnostics


def _speaker_runs(words: Sequence[SpeechSegment]) -> list[tuple[int, int]]:
    if not words:
        return []
    runs: list[tuple[int, int]] = []
    start = 0
    for index in range(1, len(words)):
        if words[index].speaker != words[index - 1].speaker:
            runs.append((start, index))
            start = index
    runs.append((start, len(words)))
    return runs


def smooth_word_speaker_assignments(
    words: Sequence[SpeechSegment],
    *,
    min_switch_seconds: float = 0.45,
    short_token_max_seconds: float = 0.32,
    boundary_merge_gap: float = 0.18,
) -> list[SpeechSegment]:
    """Suppress pyannote boundary jitter without deleting real short replies.

    The repair is deliberately conservative.  It fixes isolated A-B-A runs and
    single-character lexical tails attached to a neighbouring word.  Standalone
    fillers such as "嗯" and "啊" are not forcibly reassigned.
    """
    result = list(words)
    if len(result) < 2:
        return result

    filler_tokens = {"嗯", "啊", "呃", "哦", "诶", "哎", "唉"}
    suffix_tokens = {"的", "了", "吗", "呢", "吧", "呀", "么", "儿", "啡", "间", "上", "下"}

    # First repair lexical tail characters even when they share a run with the
    # following sentence.  This catches "咖/啡" and "牌子/的" splits.
    for index, item in enumerate(result):
        duration = max(0.0, item.end - item.start)
        token = normalize_text(item.text)
        if (
            duration <= short_token_max_seconds
            and len(token) == 1
            and token not in filler_tokens
        ):
            previous = result[index - 1] if index > 0 else None
            following = result[index + 1] if index + 1 < len(result) else None
            previous_gap = (
                max(0.0, item.start - previous.end)
                if previous is not None else float("inf")
            )
            following_gap = (
                max(0.0, following.start - item.end)
                if following is not None else float("inf")
            )
            target: str | None = None
            if (
                token in suffix_tokens
                and previous is not None
                and previous_gap <= boundary_merge_gap
                and not SENTENCE_END_RE.search(previous.text)
            ):
                target = previous.speaker
            elif (
                following is not None
                and following_gap <= boundary_merge_gap
                and previous_gap > boundary_merge_gap
            ):
                target = following.speaker
            if target is not None and target != item.speaker:
                item.speaker = target
                item.source += "+lexical_boundary_repair"

    changed = True
    passes = 0
    while changed and passes < 4:
        changed = False
        passes += 1
        runs = _speaker_runs(result)
        for run_index, (left, right) in enumerate(runs):
            run = result[left:right]
            duration = max(0.0, run[-1].end - run[0].start)
            normalized = "".join(normalize_text(item.text) for item in run)
            char_count = len(normalized)
            weighted_duration = sum(max(1e-6, item.end - item.start) for item in run)
            average_overlap = sum(
                item.diarization_overlap * max(1e-6, item.end - item.start)
                for item in run
            ) / weighted_duration
            average_fusion = sum(
                item.fusion_confidence * max(1e-6, item.end - item.start)
                for item in run
            ) / weighted_duration

            previous_run = runs[run_index - 1] if run_index > 0 else None
            next_run = runs[run_index + 1] if run_index + 1 < len(runs) else None

            # A-B-A: the middle speaker lasts only a boundary-sized interval.
            if previous_run and next_run:
                previous_speaker = result[previous_run[0]].speaker
                next_speaker = result[next_run[0]].speaker
                if (
                    previous_speaker == next_speaker
                    and previous_speaker != run[0].speaker
                    and (
                        (duration <= min_switch_seconds and average_overlap < 0.72 and average_fusion < 0.74)
                        or (char_count <= 1 and average_overlap < 0.82 and average_fusion < 0.82)
                    )
                ):
                    for item in run:
                        item.speaker = previous_speaker
                        item.source += "+speaker_jitter_repair"
                    changed = True
                    break

            # Repair a single lexical character split at a word boundary.
            if len(run) == 1 and duration <= short_token_max_seconds and char_count <= 1:
                item = run[0]
                token = normalize_text(item.text)
                if token and token not in filler_tokens:
                    previous = result[left - 1] if left > 0 else None
                    following = result[right] if right < len(result) else None
                    previous_gap = (
                        max(0.0, item.start - previous.end)
                        if previous is not None else float("inf")
                    )
                    following_gap = (
                        max(0.0, following.start - item.end)
                        if following is not None else float("inf")
                    )
                    target: str | None = None
                    if (
                        previous is not None
                        and previous_gap <= boundary_merge_gap
                        and token in suffix_tokens
                        and not SENTENCE_END_RE.search(previous.text)
                    ):
                        target = previous.speaker
                    elif following is not None and following_gap <= boundary_merge_gap:
                        target = following.speaker
                    elif (
                        previous is not None
                        and previous_gap <= boundary_merge_gap
                        and not SENTENCE_END_RE.search(previous.text)
                    ):
                        target = previous.speaker
                    if target is not None and target != item.speaker:
                        item.speaker = target
                        item.source += "+short_token_boundary_repair"
                        changed = True
                        break
    return result


def _build_sentence_segments(
    assigned: Sequence[SpeechSegment],
    *,
    sentence_gap_seconds: float,
    sentence_max_seconds: float,
    sentence_hard_max_seconds: float,
    sentence_max_chars: int,
) -> list[SpeechSegment]:
    merged: list[SpeechSegment] = []
    current: SpeechSegment | None = None
    confidence_weighted_sum = 0.0
    confidence_duration_sum = 0.0
    fusion_weighted_sum = 0.0
    voice_weighted_sum = 0.0
    visual_weighted_sum = 0.0
    visual_votes: Counter[str] = Counter()
    raw_votes: Counter[str] = Counter()

    def flush_current() -> None:
        nonlocal current, confidence_weighted_sum, confidence_duration_sum
        nonlocal fusion_weighted_sum, voice_weighted_sum, visual_weighted_sum
        nonlocal visual_votes, raw_votes
        if current is not None and has_spoken_content(current.text):
            duration = max(confidence_duration_sum, 1e-6)
            current.diarization_overlap = min(1.0, confidence_weighted_sum / duration)
            current.fusion_confidence = min(1.0, fusion_weighted_sum / duration)
            current.voice_score = min(1.0, voice_weighted_sum / duration)
            current.visual_score = min(1.0, visual_weighted_sum / duration)
            current.visual_person = visual_votes.most_common(1)[0][0] if visual_votes else None
            current.raw_speaker = raw_votes.most_common(1)[0][0] if raw_votes else current.speaker
            current.text = current.text.strip()
            current.asr_text = current.text
            merged.append(current)
        current = None
        confidence_weighted_sum = 0.0
        confidence_duration_sum = 0.0
        fusion_weighted_sum = 0.0
        voice_weighted_sum = 0.0
        visual_weighted_sum = 0.0
        visual_votes = Counter()
        raw_votes = Counter()

    for index, word in enumerate(assigned):
        next_word = assigned[index + 1] if index + 1 < len(assigned) else None
        word_duration = max(1e-6, word.end - word.start)
        if current is not None:
            gap = max(0.0, word.start - current.end)
            projected_duration = word.end - current.start
            projected_chars = len(normalize_text(current.text + word.text))
            split_before = (
                word.speaker != current.speaker
                or gap > sentence_gap_seconds
                or projected_duration > sentence_hard_max_seconds
                or projected_chars > sentence_max_chars * 2
            )
            if split_before:
                flush_current()

        if current is None:
            current = SpeechSegment(
                start=word.start,
                end=word.end,
                text=word.text,
                speaker=word.speaker,
                asr_text=word.text,
                diarization_overlap=word.diarization_overlap,
                raw_speaker=word.raw_speaker,
                visual_person=word.visual_person,
                visual_score=word.visual_score,
                voice_score=word.voice_score,
                fusion_confidence=word.fusion_confidence,
                boundary_repaired=word.boundary_repaired,
                source=word.source,
            )
        else:
            add_space = (
                bool(current.text)
                and current.text[-1].isascii()
                and current.text[-1].isalnum()
                and bool(word.text)
                and word.text[0].isascii()
                and word.text[0].isalnum()
            )
            current.end = max(current.end, word.end)
            current.text += (" " if add_space else "") + word.text
            current.asr_text = current.text
            current.boundary_repaired = current.boundary_repaired or word.boundary_repaired

        confidence_weighted_sum += word.diarization_overlap * word_duration
        fusion_weighted_sum += word.fusion_confidence * word_duration
        voice_weighted_sum += word.voice_score * word_duration
        visual_weighted_sum += word.visual_score * word_duration
        confidence_duration_sum += word_duration
        if word.visual_person:
            visual_votes[word.visual_person] += word_duration
        if word.raw_speaker:
            raw_votes[word.raw_speaker] += word_duration

        assert current is not None
        current_duration = current.end - current.start
        current_chars = len(normalize_text(current.text))
        next_gap = max(0.0, next_word.start - current.end) if next_word is not None else float("inf")
        next_speaker_change = next_word is None or next_word.speaker != current.speaker
        ended_sentence = bool(SENTENCE_END_RE.search(current.text))
        ended_clause = bool(CLAUSE_END_RE.search(current.text))
        reached_soft_limit = current_duration >= sentence_max_seconds or current_chars >= sentence_max_chars
        split_after = (
            ended_sentence
            or next_speaker_change
            or next_gap > sentence_gap_seconds
            or (
                reached_soft_limit
                and (ended_clause or next_gap >= 0.15 or current_chars >= sentence_max_chars)
            )
            or current_duration >= sentence_hard_max_seconds
        )
        if split_after:
            flush_current()
    flush_current()
    return merged


def align_diarization(
    segments: Sequence[SpeechSegment],
    turns: Sequence[SpeakerTurn],
    *,
    sentence_gap_seconds: float = 0.65,
    sentence_max_seconds: float = 6.0,
    sentence_hard_max_seconds: float = 9.0,
    sentence_max_chars: int = 48,
    speaker_switch_min_seconds: float = 0.45,
    short_token_max_seconds: float = 0.32,
    boundary_merge_gap: float = 0.18,
    wav: Path | None = None,
    visual: VisualAnalysis | None = None,
    fusion_switch_penalty: float = 0.30,
) -> tuple[list[SpeechSegment], dict[str, Any]]:
    """Multimodal word assignment followed by sentence reconstruction."""
    if not turns:
        raise ValueError("speaker turns must not be empty")
    assigned = [item for item in sorted(segments, key=lambda item: (item.start, item.end)) if has_spoken_content(item.text)]
    fusion_diagnostics: dict[str, Any] = {"mode": "pyannote_only"}
    if wav is not None:
        assigned, fusion_diagnostics = fuse_word_speakers(
            assigned,
            turns,
            wav,
            visual,
            switch_penalty=fusion_switch_penalty,
        )
        fusion_diagnostics["mode"] = "pyannote+voice_prototype+visual_track+viterbi"
    else:
        for word in assigned:
            word.speaker, word.diarization_overlap = speaker_for_interval(word.start, word.end, turns)
            word.raw_speaker = word.speaker
            word.fusion_confidence = word.diarization_overlap

    before = [item.speaker for item in assigned]
    assigned = smooth_word_speaker_assignments(
        assigned,
        min_switch_seconds=speaker_switch_min_seconds,
        short_token_max_seconds=short_token_max_seconds,
        boundary_merge_gap=boundary_merge_gap,
    )
    for item, old_speaker in zip(assigned, before):
        if item.speaker != old_speaker:
            item.boundary_repaired = True
    merged = _build_sentence_segments(
        assigned,
        sentence_gap_seconds=sentence_gap_seconds,
        sentence_max_seconds=sentence_max_seconds,
        sentence_hard_max_seconds=sentence_hard_max_seconds,
        sentence_max_chars=sentence_max_chars,
    )
    fusion_diagnostics["word_count"] = len(assigned)
    fusion_diagnostics["sentence_count"] = len(merged)
    fusion_diagnostics["boundary_repairs"] = sum(1 for item in assigned if item.boundary_repaired)
    return merged, fusion_diagnostics


def encode_multipart(fields: dict[str, str], file_path: Path) -> tuple[bytes, str]:
    boundary = f"----speaker-fusion-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode("utf-8")
        )
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(file_path.read_bytes())
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), boundary


def call_moss(
    wav: Path,
    *,
    endpoint: str,
    timeout: int,
    prompt: str,
    chunk_seconds: float,
) -> list[MossSegment]:
    body, boundary = encode_multipart(
        {
            "response_format": "verbose_json",
            "language": "zh",
            "prompt": prompt,
            "max_new_tokens": "4096",
        },
        wav,
    )
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"MOSS correction request failed: HTTP {exc.code}: {details}") from exc
    result: list[MossSegment] = []
    for item in payload.get("segments", []):
        raw_text = str(item.get("text", "")).strip()
        prefix = re.match(r"^\[([^\]]+)\]\s*", raw_text)
        speaker = str(item.get("speaker") or (prefix.group(1) if prefix else "unknown")).strip()
        text = clean_text(raw_text)
        start = float(item.get("start", 0.0))
        end = float(item.get("end", start))
        if text and end > start:
            result.append(
                MossSegment(
                    start,
                    end,
                    text,
                    speaker,
                    int(max(0.0, start) // chunk_seconds),
                )
            )
    return result


def temporal_iou(a: SpeechSegment, b: MossSegment) -> float:
    intersect = overlap(a.start, a.end, b.start, b.end)
    union = max(a.end, b.end) - min(a.start, b.start)
    return intersect / max(union, 1e-6)


def apply_moss_corrections(
    segments: Sequence[SpeechSegment],
    moss_segments: Sequence[MossSegment],
    *,
    min_similarity: float,
    min_iou: float,
    speaker_min_mapping_share: float,
    speaker_max_pyannote_confidence: float,
) -> tuple[int, int, dict[str, str]]:
    if not moss_segments:
        return 0, 0, {}
    speaker_votes: dict[tuple[int, str], dict[str, float]] = {}
    for moss in moss_segments:
        key = (moss.chunk_index, moss.speaker)
        votes = speaker_votes.setdefault(key, {})
        for segment in segments:
            amount = overlap(segment.start, segment.end, moss.start, moss.end)
            if amount > 0:
                votes[segment.speaker] = votes.get(segment.speaker, 0.0) + amount

    moss_to_pyannote: dict[tuple[int, str], tuple[str, float]] = {}
    printable_mapping: dict[str, str] = {}
    for key, votes in speaker_votes.items():
        ranked = sorted(votes.items(), key=lambda item: item[1], reverse=True)
        total = sum(votes.values())
        if not ranked or total < 0.5:
            continue
        share = ranked[0][1] / total
        runner_up_share = ranked[1][1] / total if len(ranked) > 1 else 0.0
        if share >= speaker_min_mapping_share and share - runner_up_share >= 0.15:
            moss_to_pyannote[key] = (ranked[0][0], share)
            printable_mapping[f"chunk{key[0]}:{key[1]}"] = ranked[0][0]
    best_moss_for_asr: dict[int, int] = {}
    for asr_index, segment in enumerate(segments):
        best_moss_for_asr[asr_index] = max(
            range(len(moss_segments)),
            key=lambda index: temporal_iou(segment, moss_segments[index]),
        )
    best_asr_for_moss: dict[int, int] = {}
    for moss_index, moss in enumerate(moss_segments):
        best_asr_for_moss[moss_index] = max(
            range(len(segments)),
            key=lambda index: temporal_iou(segments[index], moss),
        )

    text_changed = 0
    speaker_changed = 0
    for asr_index, moss_index in best_moss_for_asr.items():
        if best_asr_for_moss.get(moss_index) != asr_index:
            continue
        segment, moss = segments[asr_index], moss_segments[moss_index]
        iou = temporal_iou(segment, moss)
        mapped_speaker = moss_to_pyannote.get((moss.chunk_index, moss.speaker))
        segment.moss_speaker = (
            f"chunk{moss.chunk_index}:{moss.speaker}"
            + (f"->{mapped_speaker[0]}" if mapped_speaker else "")
        )
        if (
            mapped_speaker
            and mapped_speaker[0] != segment.speaker
            and mapped_speaker[1] >= speaker_min_mapping_share
            and max(segment.diarization_overlap, segment.fusion_confidence) <= speaker_max_pyannote_confidence
            and iou >= min_iou
        ):
            segment.speaker = mapped_speaker[0]
            segment.moss_speaker_corrected = True
            segment.source = "funasr+pyannote+moss_speaker_correction"
            speaker_changed += 1
        left, right = normalize_text(segment.text), normalize_text(moss.text)
        if not left or not right:
            continue
        similarity = SequenceMatcher(None, left, right).ratio()
        segment.moss_text = moss.text
        segment.moss_similarity = similarity
        length_ratio = len(right) / max(len(left), 1)
        if (
            iou >= min_iou
            and similarity >= min_similarity
            and 0.55 <= length_ratio <= 1.8
            and moss.text != segment.text
        ):
            segment.text = moss.text
            segment.moss_corrected = True
            segment.source = (
                "funasr+pyannote+moss_speaker_and_text_correction"
                if segment.moss_speaker_corrected
                else "funasr+pyannote+moss_text_correction"
            )
            text_changed += 1
    return text_changed, speaker_changed, printable_mapping


def relabel_speakers(segments: Sequence[SpeechSegment]) -> dict[str, str]:
    order: list[str] = []
    for segment in segments:
        if segment.speaker not in order:
            order.append(segment.speaker)
    mapping = {speaker: f"说话人{index}" for index, speaker in enumerate(order)}
    for segment in segments:
        segment.speaker = mapping[segment.speaker]
    return mapping


def build_speaker_summary(segments: Sequence[SpeechSegment]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for segment in segments:
        item = summary.setdefault(
            segment.speaker,
            {
                "utterance_count": 0,
                "speech_duration_sec": 0.0,
                "first_start_sec": segment.start,
                "last_end_sec": segment.end,
                "confidence_weighted_sum": 0.0,
            },
        )
        duration = max(0.0, segment.end - segment.start)
        item["utterance_count"] += 1
        item["speech_duration_sec"] += duration
        item["first_start_sec"] = min(item["first_start_sec"], segment.start)
        item["last_end_sec"] = max(item["last_end_sec"], segment.end)
        item["confidence_weighted_sum"] += segment.diarization_overlap * duration

    for item in summary.values():
        duration = max(float(item["speech_duration_sec"]), 1e-6)
        item["average_diarization_confidence"] = round(
            float(item.pop("confidence_weighted_sum")) / duration,
            4,
        )
        item["speech_duration_sec"] = round(float(item["speech_duration_sec"]), 3)
        item["first_start_sec"] = round(float(item["first_start_sec"]), 3)
        item["last_end_sec"] = round(float(item["last_end_sec"]), 3)
    return summary


def write_visual_csv(path: Path, video: Path, segments: Sequence[SpeechSegment]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "sentence_id",
                "video",
                "start",
                "end",
                "duration",
                "speaker",
                "raw_speaker",
                "visible_person",
                "diarization_confidence",
                "voice_score",
                "visual_score",
                "fusion_confidence",
                "boundary_repaired",
                "text",
            ],
        )
        writer.writeheader()
        for index, segment in enumerate(segments, 1):
            writer.writerow(
                {
                    "id": index,
                    "sentence_id": f"S{index:05d}",
                    "video": video.name,
                    "start": f"{segment.start:.3f}",
                    "end": f"{segment.end:.3f}",
                    "duration": f"{max(0.0, segment.end - segment.start):.3f}",
                    "speaker": segment.speaker,
                    "raw_speaker": segment.raw_speaker or "",
                    "visible_person": segment.visual_person or "",
                    "diarization_confidence": f"{segment.diarization_overlap:.4f}",
                    "voice_score": f"{segment.voice_score:.4f}",
                    "visual_score": f"{segment.visual_score:.4f}",
                    "fusion_confidence": f"{segment.fusion_confidence:.4f}",
                    "boundary_repaired": int(segment.boundary_repaired),
                    "text": segment.text,
                }
            )


def safe_replace_file(staged_file: Path, final_file: Path) -> None:
    final_file.parent.mkdir(parents=True, exist_ok=True)
    incoming = final_file.parent / f".{final_file.name}.{uuid.uuid4().hex}.tmp"
    shutil.copy2(staged_file, incoming)
    os.replace(incoming, final_file)


def safe_replace_output(staged_json: Path, final_json: Path) -> Path:
    staged_avatars = staged_json.parent / f"{staged_json.stem}_avatars"
    final_avatars = final_json.parent / f"{final_json.stem}_avatars"
    final_json.parent.mkdir(parents=True, exist_ok=True)
    incoming_json = final_json.parent / f".{final_json.name}.{uuid.uuid4().hex}.tmp"
    incoming_avatars = final_json.parent / f".{final_avatars.name}.{uuid.uuid4().hex}.tmp"
    shutil.copy2(staged_json, incoming_json)
    if staged_avatars.is_dir():
        shutil.copytree(staged_avatars, incoming_avatars)
    if final_avatars.exists():
        resolved = final_avatars.resolve()
        if resolved.parent != final_json.parent.resolve() or resolved.name != f"{final_json.stem}_avatars":
            raise RuntimeError(f"refusing to replace unexpected avatar path: {resolved}")
        shutil.rmtree(resolved)
    os.replace(incoming_json, final_json)
    if incoming_avatars.exists():
        os.replace(incoming_avatars, final_avatars)
    return final_avatars


def safe_output_name(value: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._\-\u4e00-\u9fff]+", "_", value).strip("._-")
    return cleaned or "video"


def export_faces(avatar_dir: Path, faces_dir: Path) -> list[Path]:
    """Copy visual speaker portraits to the stable project-facing folder."""
    faces_dir.parent.mkdir(parents=True, exist_ok=True)
    if faces_dir.exists():
        shutil.rmtree(faces_dir)
    faces_dir.mkdir(parents=True, exist_ok=True)

    exported: list[Path] = []
    if avatar_dir.is_dir():
        candidates = sorted(
            path
            for path in avatar_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        )
        for index, source in enumerate(candidates):
            filename = f"{index:03d}_{safe_output_name(source.stem)}{source.suffix.lower()}"
            target = faces_dir / filename
            shutil.copy2(source, target)
            exported.append(target)

    manifest = {
        "source_avatar_dir": str(avatar_dir),
        "faces_dir": str(faces_dir),
        "face_count": len(exported),
        "files": [path.name for path in exported],
    }
    (faces_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return exported


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Internal FunASR + pyannote + face-track/mouth-motion + voice-prototype speaker fusion"
    )
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="default output root; creates OUT_ROOT/VIDEO_STEM/",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        help="defaults to OUT_ROOT/VIDEO_STEM/result.json",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="defaults to OUT_ROOT/VIDEO_STEM/transcript.csv",
    )
    parser.add_argument(
        "--faces-dir",
        type=Path,
        help="stable face folder; defaults to OUT_ROOT/VIDEO_STEM/faces",
    )
    parser.add_argument("--diagnostics-json", type=Path)
    parser.add_argument("--output-log", type=Path)
    parser.add_argument("--models-root", type=Path, default=DEFAULT_PROJECT_MODELS)
    parser.add_argument("--asr-model", type=Path)
    parser.add_argument("--vad-model", type=Path)
    parser.add_argument("--punc-model", type=Path)
    parser.add_argument("--pyannote-model", type=Path)
    parser.add_argument("--asr-device", default="cuda:0")
    parser.add_argument("--diarization-device", default="cuda:0")
    parser.add_argument("--visual-device", default="cuda:0")
    parser.add_argument(
        "--face-detector",
        choices=("auto", "s3fd", "opencv-cuda-haar", "opencv-haar"),
        default="auto",
        help="GPU-first face detector; auto tries S3FD, OpenCV CUDA, then Unicode-safe CPU Haar",
    )
    parser.add_argument("--face-cascade", type=Path, help="optional Haar XML path")
    parser.add_argument("--lrasd-root", type=Path, help="optional LR-ASD root used for GPU S3FD")
    parser.add_argument("--face-confidence", type=float, default=0.82)
    parser.add_argument(
        "--allow-cpu-visual-fallback",
        action="store_true",
        help="allow CPU Haar only when GPU S3FD/OpenCV CUDA is unavailable",
    )
    parser.add_argument("--facedet-scale", type=positive_float, default=0.25)
    parser.add_argument("--batch-size-s", type=int, default=60)
    parser.add_argument(
        "--num-speakers",
        type=positive_int,
        help="exact known speaker count; sets pyannote min_speakers=max_speakers",
    )
    parser.add_argument("--min-speakers", type=positive_int)
    parser.add_argument("--max-speakers", type=positive_int)
    parser.add_argument(
        "--speaker-count-mode",
        choices=("fixed", "audio", "visual-fusion"),
        default="visual-fusion",
        help="visual-fusion derives pyannote bounds from stable visible identities plus off-screen allowance",
    )
    parser.add_argument("--max-offscreen-speakers", type=int, default=1)
    parser.add_argument("--visual-sample-fps", type=positive_float, default=8.0)
    parser.add_argument("--visual-min-face-size", type=positive_int, default=48)
    parser.add_argument("--visual-identity-similarity", type=float, default=0.86)
    parser.add_argument("--fusion-switch-penalty", type=float, default=0.30)
    parser.add_argument(
        "--sentence-gap-seconds",
        type=float,
        default=0.65,
        help="split a sentence when same-speaker silence exceeds this value",
    )
    parser.add_argument(
        "--sentence-max-seconds",
        type=positive_float,
        default=6.0,
        help="soft maximum duration for one sentence row",
    )
    parser.add_argument(
        "--sentence-hard-max-seconds",
        type=positive_float,
        default=9.0,
        help="hard maximum duration for one sentence row",
    )
    parser.add_argument(
        "--sentence-max-chars",
        type=int,
        default=48,
        help="soft maximum normalized character count for one sentence row",
    )
    parser.add_argument(
        "--speaker-switch-min-seconds",
        type=float,
        default=0.45,
        help="repair isolated speaker changes shorter than this duration",
    )
    parser.add_argument(
        "--short-token-max-seconds",
        type=float,
        default=0.32,
        help="maximum duration of a one-character boundary fragment",
    )
    parser.add_argument(
        "--boundary-merge-gap",
        type=float,
        default=0.18,
        help="maximum gap used when attaching a split character to a neighbour",
    )
    parser.add_argument("--skip-moss", action="store_true")
    parser.add_argument(
        "--moss-endpoint",
        default="http://127.0.0.1:18082/v1/audio/transcriptions",
    )
    parser.add_argument("--moss-timeout", type=int, default=1800)
    parser.add_argument("--moss-min-similarity", type=float, default=0.52)
    parser.add_argument("--moss-min-iou", type=float, default=0.30)
    parser.add_argument(
        "--moss-chunk-seconds",
        type=positive_float,
        default=240.0,
        help="must match MOSS_CHUNK_SECONDS; speaker IDs are mapped separately per chunk",
    )
    parser.add_argument("--moss-speaker-min-mapping-share", type=float, default=0.68)
    parser.add_argument("--moss-speaker-max-pyannote-confidence", type=float, default=0.82)
    parser.add_argument(
        "--moss-prompt",
        default=(
            "请逐字转写普通话对话，保留准确标点、数字、专有名词和说话时间。"
            "不要总结，不要补写听不清的内容。"
        ),
    )
    parser.add_argument("--skip-visual", action="store_true")
    return parser


def _first_existing_path(candidates: Sequence[Path]) -> Path:
    for candidate in candidates:
        expanded = candidate.expanduser()
        if expanded.exists():
            return expanded.resolve()
    return candidates[0].expanduser().resolve()


def _find_snapshot(root: Path, pattern: str) -> Path | None:
    if not root.exists():
        return None
    matches = sorted(root.glob(pattern))
    return matches[-1].resolve() if matches else None


def resolve_model_paths(args: argparse.Namespace) -> None:
    root = args.models_root.expanduser().resolve()
    server_root = Path("/home/realmagic/models/speaker-fusion")

    asr_candidates = [
        root / "asr",
        root / "modelscope/models/iic--speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch/snapshots/master",
        server_root / "modelscope/models/iic--speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch/snapshots/master",
    ]
    vad_candidates = [
        root / "vad",
        root / "modelscope/models/iic--speech_fsmn_vad_zh-cn-16k-common-pytorch/snapshots/master",
        server_root / "modelscope/models/iic--speech_fsmn_vad_zh-cn-16k-common-pytorch/snapshots/master",
    ]
    punc_candidates = [
        root / "punc",
        root / "modelscope/models/iic--punc_ct-transformer_zh-cn-common-vocab272727-pytorch/snapshots/master",
        server_root / "modelscope/models/iic--punc_ct-transformer_zh-cn-common-vocab272727-pytorch/snapshots/master",
    ]

    discovered_pyannote = _find_snapshot(
        root,
        "**/models--pyannote--speaker-diarization-community-1/snapshots/*",
    )
    pyannote_candidates = [
        root / "pyannote",
        root / "speaker-diarization-community-1",
    ]
    if discovered_pyannote is not None:
        pyannote_candidates.insert(0, discovered_pyannote)
    pyannote_candidates.append(
        server_root
        / "huggingface/hub/models--pyannote--speaker-diarization-community-1/snapshots/3533c8cf8e369892e6b79ff1bf80f7b0286a54ee"
    )

    args.asr_model = (
        args.asr_model.expanduser().resolve()
        if args.asr_model is not None
        else _first_existing_path(asr_candidates)
    )
    args.vad_model = (
        args.vad_model.expanduser().resolve()
        if args.vad_model is not None
        else _first_existing_path(vad_candidates)
    )
    args.punc_model = (
        args.punc_model.expanduser().resolve()
        if args.punc_model is not None
        else _first_existing_path(punc_candidates)
    )
    args.pyannote_model = (
        args.pyannote_model.expanduser().resolve()
        if args.pyannote_model is not None
        else _first_existing_path(pyannote_candidates)
    )




def _write_pipeline_json(
    path: Path,
    *,
    video: Path,
    segments: Sequence[SpeechSegment],
    stats: RuntimeStats,
    faces_dir: Path,
    visual: VisualAnalysis | None,
    fusion_diagnostics: dict[str, Any],
    count_bounds: dict[str, Any],
    moss_text_corrections: int,
    moss_speaker_corrections: int,
    moss_speaker_mapping: dict[str, str],
) -> None:
    payload = {
        "video": str(video),
        "speaker_count": len({item.speaker for item in segments}),
        "sentence_count": len(segments),
        "speaker_summary": build_speaker_summary(segments),
        "faces_dir": str(faces_dir),
        "messages": [
            {
                "start_sec": item.start,
                "end_sec": item.end,
                "speaker": item.speaker,
                "raw_speaker": item.raw_speaker,
                "visible_person": item.visual_person,
                "text": item.text,
                "diarization_confidence": round(item.diarization_overlap, 4),
                "voice_score": round(item.voice_score, 4),
                "visual_score": round(item.visual_score, 4),
                "fusion_confidence": round(item.fusion_confidence, 4),
                "boundary_repaired": item.boundary_repaired,
                "source": item.source,
                "audio": asdict(item),
            }
            for item in segments
        ],
        "visual": visual.diagnostics if visual is not None else {"backend": "disabled"},
        "fusion": fusion_diagnostics,
        "speaker_count_bounds": count_bounds,
        "pipeline": {
            "audio_transcription": "FunASR timestamped tokens",
            "speaker_diarization": "pyannote community-1",
            "visible_people": "GPU-first S3FD/OpenCV detector + internal face tracks + mouth motion",
            "voice_identity": "per-pyannote acoustic spectral prototypes",
            "word_assignment": "multimodal Viterbi with switch penalty",
            "moss_policy": "optional; low-confidence text/speaker repair only",
            "moss_text_corrections": moss_text_corrections,
            "moss_speaker_corrections": moss_speaker_corrections,
            "moss_chunk_speaker_mapping": moss_speaker_mapping,
            "runtime": asdict(stats),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _copy_faces_to_avatar_dir(faces_dir: Path, avatar_dir: Path) -> None:
    if avatar_dir.exists():
        shutil.rmtree(avatar_dir)
    avatar_dir.mkdir(parents=True, exist_ok=True)
    for source in faces_dir.glob("*.jpg"):
        shutil.copy2(source, avatar_dir / source.name)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.video = args.video.expanduser().resolve()
    output_root = args.output_root.expanduser().resolve()
    output_dir = output_root / safe_output_name(args.video.stem)
    output_dir.mkdir(parents=True, exist_ok=True)
    args.output_json = args.output_json.expanduser().resolve() if args.output_json else output_dir / "result.json"
    args.output_csv = args.output_csv.expanduser().resolve() if args.output_csv else output_dir / "transcript.csv"
    args.faces_dir = args.faces_dir.expanduser().resolve() if args.faces_dir else output_dir / "faces"
    args.diagnostics_json = args.diagnostics_json.expanduser().resolve() if args.diagnostics_json else output_dir / "diagnostics.json"
    args.output_log = args.output_log.expanduser().resolve() if args.output_log else output_dir / "pipeline.log"
    args.face_cascade = args.face_cascade.expanduser().resolve() if args.face_cascade else None
    args.lrasd_root = args.lrasd_root.expanduser().resolve() if args.lrasd_root else None
    resolve_model_paths(args)
    if not args.video.is_file():
        raise FileNotFoundError(f"video does not exist: {args.video}")
    for executable in ("ffmpeg", "ffprobe"):
        if shutil.which(executable) is None:
            raise FileNotFoundError(f"required executable is not on PATH: {executable}")

    args.output_log.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("speaker_video_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    file_handler = logging.FileHandler(args.output_log, encoding="utf-8", mode="w")
    stream_handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler.setFormatter(formatter)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    started = time.perf_counter()
    stats = RuntimeStats(video_duration_sec=ffprobe_duration(args.video))
    visual: VisualAnalysis | None = None
    fusion_diagnostics: dict[str, Any] = {}
    count_bounds: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="speaker_fusion_run_") as temp_name:
        temp_dir = Path(temp_name)
        wav = temp_dir / "audio_16k_mono.wav"
        step = time.perf_counter()
        extract_audio(args.video, wav)
        stats.extract_audio_sec = time.perf_counter() - step
        logger.info("audio extracted: %.3fs", stats.extract_audio_sec)

        if not args.skip_visual:
            step = time.perf_counter()
            visual = analyze_video_faces(
                args.video,
                args.faces_dir,
                sample_fps=args.visual_sample_fps,
                min_face_size=args.visual_min_face_size,
                identity_similarity=args.visual_identity_similarity,
                detector_backend=args.face_detector,
                detector_device=args.visual_device,
                face_cascade=args.face_cascade,
                lrasd_root=args.lrasd_root,
                face_confidence=args.face_confidence,
                facedet_scale=args.facedet_scale,
                logger=logger,
                allow_cpu_fallback=args.allow_cpu_visual_fallback,
                target_speaker_count=args.num_speakers,
            )
            stats.visual_sec = time.perf_counter() - step
            logger.info(
                "visual identities=%d speaking=%d simultaneous_lower_bound=%d tracks=%d",
                visual.identity_count,
                visual.speaking_identity_count,
                visual.simultaneous_lower_bound,
                len(visual.tracks),
            )
        else:
            args.faces_dir.mkdir(parents=True, exist_ok=True)
            (args.faces_dir / "manifest.json").write_text(
                json.dumps({"backend": "disabled", "face_count": 0}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        effective_min = args.min_speakers
        effective_max = args.max_speakers
        if args.num_speakers is not None:
            effective_min = effective_max = args.num_speakers
            count_mode = "fixed"
        else:
            count_mode = args.speaker_count_mode
            if count_mode == "visual-fusion" and visual is not None and visual.identity_count > 0:
                visible_min = max(visual.simultaneous_lower_bound, visual.speaking_identity_count, 1)
                visible_max = max(visible_min, visual.identity_count + max(0, args.max_offscreen_speakers))
                effective_min = max(effective_min or 1, visible_min)
                effective_max = min(effective_max, visible_max) if effective_max is not None else visible_max
                effective_max = max(effective_min, effective_max)
        count_bounds = {
            "mode": count_mode,
            "requested_num_speakers": args.num_speakers,
            "effective_min_speakers": effective_min,
            "effective_max_speakers": effective_max,
            "visible_identity_count": visual.identity_count if visual else 0,
            "visible_speaking_count": visual.speaking_identity_count if visual else 0,
            "max_offscreen_speakers": args.max_offscreen_speakers,
        }
        logger.info("speaker count bounds: %s", count_bounds)

        step = time.perf_counter()
        asr_segments = run_funasr(
            wav,
            asr_model=args.asr_model,
            vad_model=args.vad_model,
            punc_model=args.punc_model,
            device=args.asr_device,
            batch_size_s=args.batch_size_s,
            duration=stats.video_duration_sec,
        )
        stats.funasr_sec = time.perf_counter() - step
        logger.info("FunASR tokens=%d elapsed=%.3fs", len(asr_segments), stats.funasr_sec)

        step = time.perf_counter()
        turns = run_pyannote(
            wav,
            model=args.pyannote_model,
            token=os.environ.get("HF_TOKEN"),
            device=args.diarization_device,
            min_speakers=effective_min,
            max_speakers=effective_max,
            logger=logger,
        )
        segments, fusion_diagnostics = align_diarization(
            asr_segments,
            turns,
            sentence_gap_seconds=args.sentence_gap_seconds,
            sentence_max_seconds=args.sentence_max_seconds,
            sentence_hard_max_seconds=args.sentence_hard_max_seconds,
            sentence_max_chars=args.sentence_max_chars,
            speaker_switch_min_seconds=args.speaker_switch_min_seconds,
            short_token_max_seconds=args.short_token_max_seconds,
            boundary_merge_gap=args.boundary_merge_gap,
            wav=wav,
            visual=visual,
            fusion_switch_penalty=args.fusion_switch_penalty,
        )
        speaker_mapping = relabel_speakers(segments)
        fusion_diagnostics["relabel_mapping"] = speaker_mapping
        stats.pyannote_sec = time.perf_counter() - step
        stats.fusion_sec = stats.pyannote_sec
        logger.info("fused sentences=%d speakers=%d elapsed=%.3fs", len(segments), len(set(item.speaker for item in segments)), stats.pyannote_sec)

        moss_text_corrections = 0
        moss_speaker_corrections = 0
        moss_speaker_mapping: dict[str, str] = {}
        if not args.skip_moss:
            step = time.perf_counter()
            moss_segments = call_moss(
                wav,
                endpoint=args.moss_endpoint,
                timeout=args.moss_timeout,
                prompt=args.moss_prompt,
                chunk_seconds=args.moss_chunk_seconds,
            )
            moss_text_corrections, moss_speaker_corrections, moss_speaker_mapping = apply_moss_corrections(
                segments,
                moss_segments,
                min_similarity=args.moss_min_similarity,
                min_iou=args.moss_min_iou,
                speaker_min_mapping_share=args.moss_speaker_min_mapping_share,
                speaker_max_pyannote_confidence=args.moss_speaker_max_pyannote_confidence,
            )
            stats.moss_sec = time.perf_counter() - step
            logger.info("MOSS low-confidence repairs text=%d speaker=%d", moss_text_corrections, moss_speaker_corrections)

        stats.total_sec = time.perf_counter() - started
        stats.real_time_factor = stats.total_sec / max(stats.video_duration_sec, 1e-6)
        write_visual_csv(args.output_csv, args.video, segments)
        _write_pipeline_json(
            args.output_json,
            video=args.video,
            segments=segments,
            stats=stats,
            faces_dir=args.faces_dir,
            visual=visual,
            fusion_diagnostics=fusion_diagnostics,
            count_bounds=count_bounds,
            moss_text_corrections=moss_text_corrections,
            moss_speaker_corrections=moss_speaker_corrections,
            moss_speaker_mapping=moss_speaker_mapping,
        )
        diagnostics = {
            "video": str(args.video),
            "count_bounds": count_bounds,
            "visual": visual.diagnostics if visual else {"backend": "disabled"},
            "fusion": fusion_diagnostics,
            "runtime": asdict(stats),
        }
        args.diagnostics_json.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
        avatar_dir = output_dir / "result_avatars"
        _copy_faces_to_avatar_dir(args.faces_dir, avatar_dir)

    result_payload = {
        "output_dir": str(output_dir),
        "output_json": str(args.output_json),
        "output_csv": str(args.output_csv),
        "diagnostics_json": str(args.diagnostics_json),
        "output_log": str(args.output_log),
        "faces_dir": str(args.faces_dir),
        "avatar_dir": str(avatar_dir),
        "sentence_count": len(segments),
        "speaker_count": len(set(item.speaker for item in segments)),
        "speaker_summary": build_speaker_summary(segments),
        "runtime": asdict(stats),
    }
    logger.info("completed: %s", result_payload)
    print(json.dumps(result_payload, ensure_ascii=False, indent=2))
    return 0


def process_video_result(
    video_path: str | Path,
    *,
    output_root: str | Path | None = None,
    num_speakers: int | None = None,
    use_moss: bool = False,
    asr_device: str = "cuda:0",
    diarization_device: str = "cuda:0",
    visual_device: str = "cuda:0",
    face_detector: str = "auto",
    lrasd_root: str | Path | None = None,
) -> PipelineResult:
    """Project-facing API returning all generated paths and counts."""
    video = Path(video_path).expanduser().resolve()
    root = Path(output_root).expanduser().resolve() if output_root else (Path.cwd() / "out").resolve()
    argv = [
        "--video", str(video),
        "--output-root", str(root),
        "--asr-device", asr_device,
        "--diarization-device", diarization_device,
        "--visual-device", visual_device,
        "--face-detector", face_detector,
    ]
    if lrasd_root is not None:
        argv.extend(["--lrasd-root", str(Path(lrasd_root).expanduser().resolve())])
    if num_speakers is not None:
        argv.extend(["--num-speakers", str(num_speakers)])
    if not use_moss:
        argv.append("--skip-moss")
    return_code = main(argv)
    if return_code != 0:
        raise RuntimeError(f"speaker pipeline failed with exit code {return_code}")
    output_dir = root / safe_output_name(video.stem)
    payload = json.loads((output_dir / "result.json").read_text(encoding="utf-8"))
    return PipelineResult(
        video=video,
        output_dir=output_dir,
        output_json=output_dir / "result.json",
        output_csv=output_dir / "transcript.csv",
        faces_dir=output_dir / "faces",
        avatar_dir=output_dir / "result_avatars",
        speaker_count=int(payload.get("speaker_count", 0)),
        sentence_count=int(payload.get("sentence_count", 0)),
        warnings=list((payload.get("pipeline") or {}).get("runtime", {}).get("warnings", [])),
    )


def process_video(video_path: str | Path) -> Path:
    """Call from another Python program and receive ``out/<video>/faces``."""
    return process_video_result(video_path).faces_dir


if __name__ == "__main__":
    raise SystemExit(main())
