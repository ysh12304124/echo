from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


KEY_FRAME_COUNT = 3


def select_key_frame_indexes(frame_count: int) -> list[int]:
    if frame_count <= 0:
        return []
    selected_count = min(frame_count, KEY_FRAME_COUNT)
    if frame_count <= KEY_FRAME_COUNT:
        return list(range(frame_count))
    return [
        round((i + 1) * (frame_count - 1) / (selected_count + 1))
        for i in range(selected_count)
    ]


def estimate_frame_timestamp_ms(
    frame_index: int, frame_count: int, duration_seconds: int
) -> int:
    if frame_count <= 1 or duration_seconds <= 0:
        return 0
    return int((frame_index / (frame_count - 1)) * duration_seconds * 1000)


def parse_json_list(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def frame_media_key(session_id: str, frame_path: str) -> str:
    marker = f"sessions/{session_id}/frames/"
    if marker in frame_path:
        return marker + frame_path.split(marker, 1)[1].split("/", 1)[0]
    return f"sessions/{session_id}/frames/{Path(frame_path).name}"


def ensure_key_frames_column(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(time_memories)")}
    if "key_frames" not in columns:
        conn.execute("ALTER TABLE time_memories ADD COLUMN key_frames TEXT DEFAULT '[]'")


def build_key_frames(
    session_id: str, frame_paths: list[str], duration_seconds: int
) -> list[dict]:
    key_frames = []
    for index in select_key_frame_indexes(len(frame_paths)):
        frame_path = frame_paths[index]
        key_frames.append(
            {
                "media_path": frame_media_key(session_id, frame_path),
                "filename": Path(frame_path).name,
                "frame_index": index,
                "timestamp_ms": estimate_frame_timestamp_ms(
                    index, len(frame_paths), duration_seconds
                ),
            }
        )
    return key_frames


def backfill(db_path: Path, force: bool) -> int:
    conn = sqlite3.connect(db_path)
    try:
        ensure_key_frames_column(conn)
        rows = conn.execute(
            """
            SELECT tm.id, tm.session_id, tm.duration_seconds, tm.key_frames, s.frame_paths
            FROM time_memories tm
            JOIN ingest_sessions s ON s.id = tm.session_id
            WHERE tm.session_id IS NOT NULL
            """
        ).fetchall()

        updated = 0
        for memory_id, session_id, duration_seconds, existing, frame_paths_json in rows:
            if not force and parse_json_list(existing):
                continue
            frame_paths = parse_json_list(frame_paths_json)
            key_frames = build_key_frames(session_id, frame_paths, int(duration_seconds or 0))
            if not key_frames:
                continue
            conn.execute(
                "UPDATE time_memories SET key_frames = ? WHERE id = ?",
                (json.dumps(key_frames, ensure_ascii=False), memory_id),
            )
            updated += 1

        conn.commit()
        return updated
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill selected key frames.")
    parser.add_argument(
        "db_path",
        nargs="?",
        default=str(Path(__file__).resolve().parents[1] / "data" / "echo.db"),
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing key_frames.")
    args = parser.parse_args()

    updated = backfill(Path(args.db_path), args.force)
    print(f"updated={updated}")


if __name__ == "__main__":
    main()
