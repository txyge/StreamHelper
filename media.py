"""Приём локальных записей и экспорт точного интервала через FFmpeg."""
import json
import math
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

from streams import Problem, rows, session

FORMATS = {"video/mp4": "mov", "video/webm": "matroska"}
MAX_UPLOAD = 1024**3


def executable(name):
    command = os.environ.get(f"STREAMHELPER_{name.upper()}", name)
    resolved = shutil.which(command)
    if not resolved:
        raise Problem(f"Не найден {name}. Проверьте зависимости в README.", 503)
    return resolved


def run(name, options, timeout):
    try:
        process = subprocess.run(
            [executable(name), *options], capture_output=True, timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Problem(f"Не удалось выполнить {name}. Проверьте файл и настройки.") from exc
    if process.returncode:
        raise Problem("FFmpeg не смог обработать запись. Проверьте формат и целостность файла.")
    return process.stdout


def input_options(mime):
    return ["-protocol_whitelist", "file", "-f", FORMATS[mime]]


def probe(path, mime):
    raw = run("ffprobe", [
        "-v", "error", *input_options(mime), "-select_streams", "v:0",
        "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(path)
    ], 25)
    info = json.loads(raw)
    try:
        duration = float(info["format"]["duration"])
        if not info.get("streams") or not math.isfinite(duration) or duration <= 0:
            raise ValueError
        return duration
    except (KeyError, ValueError, TypeError) as exc:
        raise Problem("У записи должен быть видеопоток с известной длительностью.") from exc


def file_path(store, kind, key):
    directory = store.directory / kind
    directory.mkdir(exist_ok=True)
    return directory / key


def upload(store, sid, source, length, mime):
    if mime not in FORMATS:
        raise Problem("Выберите запись MP4 или WebM.", 415)
    with store.connect() as db:
        session(db, sid)
    key = uuid4().hex
    target = file_path(store, "recordings", key)
    try:
        with target.open("xb") as output:
            remaining = length
            while remaining:
                chunk = source.read(min(remaining, 1024 * 1024))
                if not chunk:
                    raise Problem("Загрузка записи прервана.")
                output.write(chunk)
                remaining -= len(chunk)
        duration = probe(target, mime)
        with store.connect(write=True) as db:
            db.execute("INSERT INTO recordings VALUES (?, ?, ?, ?)", (key, sid, mime, duration))
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"id": key, "duration": duration}


def export(store, sid, data):
    key = data.get("recording")
    if not isinstance(key, str) or not key or len(key) > 32:
        raise Problem("Сначала загрузите запись.")
    with store.connect() as db:
        session(db, sid)
        source = db.execute("SELECT * FROM recordings WHERE id=? AND session_id=?",
                            (key, sid)).fetchone()
    if not source:
        raise Problem("Запись не найдена в этом эфире.")
    number = data.get("position")
    if type(number) not in (int, float) or not 0 < number <= source["duration"] + 0.1:
        raise Problem("Пустой или недопустимый отрезок. Перейдите к нужной позиции записи.")
    end = min(float(number), source["duration"])
    start = max(0, end - 30)
    key = uuid4().hex
    target = file_path(store, "clips", key + ".mp4")
    try:
        run("ffmpeg", [
            "-nostdin", "-v", "error", "-ss", f"{start:.9f}",
            *input_options(source["mime"]), "-i", str(file_path(store, "recordings", source["id"])),
            "-t", f"{end-start:.9f}", "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264",
            "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-movflags", "+faststart", str(target)
        ], 180)
        probe(target, "video/mp4")
        with store.connect(write=True) as db:
            db.execute("INSERT INTO clips VALUES (?, ?, ?, ?)", (key, sid, start, end))
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"id": key, "start": start, "end": end}


def detail(db, sid):
    return {
        "clips": rows(db, "SELECT * FROM clips WHERE session_id=? ORDER BY rowid DESC", sid),
        "recordings": rows(db, "SELECT id, duration FROM recordings WHERE session_id=? ORDER BY rowid DESC", sid),
    }
