#!/usr/bin/env python3
"""Fetch a video's transcript, or frames from it, for an agent to read.

usage: video.py URL [--out DIR]
       video.py URL --out DIR (--frames N | --at TIME[,TIME...])

The first form writes DIR/transcript.md: metadata, description, chapters, and the
timestamped transcript from the platform's own subtitles. The second downloads a
low-resolution copy and writes DIR/frame_<time>.jpg at evenly spaced or given times.
Works on any site yt-dlp supports, such as YouTube and Bilibili. Needs yt-dlp; frames
also need ffmpeg.

Exit codes: 0 success, 2 error, 3 the video has no subtitles to read.
"""
import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

NOT_SUBTITLES = {"danmaku", "live_chat", "comments"}
FORMAT_PREFERENCE = ["json3", "vtt", "srt"]
PARAGRAPH_SECONDS = 60
SPARSE_CHARS_PER_MINUTE = 100
CJK = re.compile(r"[぀-ヿ㐀-鿿가-힯]")
TAG = re.compile(r"<[^>]+>")


def fail(message, code=2):
    print(message, file=sys.stderr)
    sys.exit(code)


def ytdlp(*args):
    result = subprocess.run(["yt-dlp", "--no-playlist", "--no-warnings", *args], capture_output=True, text=True)
    if result.returncode != 0:
        fail(f"yt-dlp failed: {result.stderr.strip()}")
    return result.stdout


def load_info(url, out):
    info_path = out / "info.json"
    if not info_path.exists():
        info_path.write_text(ytdlp("--dump-single-json", url))
    return info_path, json.loads(info_path.read_text())


def matches(lang, wanted):
    return wanted and (lang == wanted or lang.startswith(wanted + "-"))


def pick_track(info):
    """Return (kind, lang, ext): manual subtitles in the spoken language first, then auto captions of the original audio."""
    spoken = info.get("language")
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k not in NOT_SUBTITLES}
    auto = info.get("automatic_captions") or {}
    candidates = (
        [("manual", k) for k in manual if matches(k, spoken)]
        + [("auto", k) for k in auto if k.endswith("-orig")]
        + [("auto", k) for k in auto if k == spoken]
        + [("manual", k) for k in manual]
    )
    if not candidates:
        return None
    kind, lang = candidates[0]
    available = [f["ext"] for f in (manual if kind == "manual" else auto)[lang]]
    ext = next((e for e in FORMAT_PREFERENCE if e in available), None)
    if ext is None:
        fail(f"no readable format for {lang} subtitles, only {available}")
    return kind, lang, ext


def parse_timestamp(text):
    parts = [float(p.replace(",", ".")) for p in text.split(":")]
    seconds = 0.0
    for p in parts:
        seconds = seconds * 60 + p
    return seconds


def parse_json3(text):
    cues = []
    for event in json.loads(text).get("events", []):
        line = "".join(s.get("utf8", "") for s in event.get("segs") or []).replace("\n", " ").strip()
        if line:
            cues.append((event.get("tStartMs", 0) / 1000, line))
    return cues


def parse_cues(text):
    """Parse VTT or SRT, dropping lines that repeat the previous one, as rolling auto captions do."""
    cues = []
    previous = None
    for block in re.split(r"\n\s*\n", text.replace("\r", "")):
        lines = block.strip().split("\n")
        timing = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if timing is None:
            continue
        start = parse_timestamp(lines[timing].split("-->")[0].strip())
        for raw in lines[timing + 1 :]:
            line = TAG.sub("", raw).strip()
            if line and line != previous:
                cues.append((start, line))
                previous = line
    return cues


def clock(seconds):
    seconds = int(seconds)
    h, m, s = seconds // 3600, seconds // 60 % 60, seconds % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def render_transcript(cues, chapters):
    joiner = "" if CJK.search("".join(c for _, c in cues[:50])) else " "
    starts = sorted((c["start_time"], c["title"]) for c in chapters)
    out, paragraph, paragraph_start = [], [], None

    def flush():
        if paragraph:
            out.append(f"[{clock(paragraph_start)}] " + joiner.join(paragraph))
            paragraph.clear()

    for start, line in cues:
        while starts and start >= starts[0][0]:
            flush()
            out.append(f"### {starts.pop(0)[1]}")
        if paragraph and start - paragraph_start >= PARAGRAPH_SECONDS:
            flush()
        if not paragraph:
            paragraph_start = start
        paragraph.append(line)
    flush()
    return "\n\n".join(out)


def transcript(url, out):
    info_path, info = load_info(url, out)
    track = pick_track(info)
    if track is None:
        fail(
            f"No subtitles are available for this video ({info.get('extractor_key')}), "
            "so its content cannot be read. Some sites, like Bilibili, show subtitles only to logged-in users.",
            code=3,
        )
    kind, lang, ext = track
    flag = "--write-subs" if kind == "manual" else "--write-auto-subs"
    ytdlp(
        "--load-info-json", str(info_path), "--skip-download", flag,
        "--sub-langs", lang, "--sub-format", ext, "-o", str(out / "subs.%(ext)s"),
    )
    sub_file = out / f"subs.{lang}.{ext}"
    if not sub_file.exists():
        fail(f"yt-dlp reported success but wrote no {sub_file.name}")
    raw = sub_file.read_text(encoding="utf-8")
    cues = parse_json3(raw) if ext == "json3" else parse_cues(raw)

    chapters = info.get("chapters") or []
    duration = info.get("duration") or 0
    header = [
        f"# {info.get('title')}",
        "",
        f"- URL: {info.get('webpage_url') or url}",
        f"- Channel: {info.get('channel') or info.get('uploader')}",
        f"- Uploaded: {info.get('upload_date')}",
        f"- Duration: {clock(duration)}",
        f"- Transcript: {'uploader subtitles' if kind == 'manual' else 'auto-generated captions'}, {lang}",
        "",
        "## Description",
        "",
        (info.get("description") or "").strip() or "(none)",
    ]
    if chapters:
        header += ["", "## Chapters", ""] + [f"- [{clock(c['start_time'])}] {c['title']}" for c in chapters]
    body = render_transcript(cues, chapters)
    (out / "transcript.md").write_text("\n".join(header) + "\n\n## Transcript\n\n" + body + "\n", encoding="utf-8")

    chars = sum(len(c) for _, c in cues)
    print(f"{out / 'transcript.md'}: {len(cues)} cues, {chars} characters, {clock(duration)} long")
    if duration and chars / (duration / 60) < SPARSE_CHARS_PER_MINUTE:
        print("The transcript is sparse for the video's length, so the video is probably mostly music or visuals.")


def frames(url, out, count, at):
    if not shutil.which("ffmpeg"):
        fail("ffmpeg is not installed; it is needed to extract frames")
    _, info = load_info(url, out)
    duration = info.get("duration") or 0
    if at:
        times = [parse_timestamp(t.strip()) for t in at.split(",")]
    else:
        times = [duration * (i + 0.5) / count for i in range(count)]
    video = next(out.glob("video.*"), None)
    if video is None:
        # Media URLs in a saved info.json expire, so extract again rather than reuse it.
        ytdlp(
            url,
            "-f", "bv*[height<=720][ext=mp4]/bv*[height<=720]/b[height<=720]/wv*/w",
            "-o", str(out / "video.%(ext)s"),
        )
        video = next(out.glob("video.*"))
    for t in times:
        target = out / f"frame_{clock(t).replace(':', '-')}.jpg"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", str(t), "-i", str(video),
             "-frames:v", "1", "-q:v", "3", str(target)],
            check=True,
        )
        print(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url")
    parser.add_argument("--out", type=pathlib.Path, help="output directory, reused across calls for the same video")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--frames", type=int, help="extract this many evenly spaced frames")
    group.add_argument("--at", help="extract frames at these comma-separated times, such as 1:30,12:05")
    args = parser.parse_args()

    if not shutil.which("yt-dlp"):
        fail("yt-dlp is not installed. Install it with `brew install yt-dlp` or `pipx install yt-dlp`.")
    out = args.out or pathlib.Path(tempfile.mkdtemp(prefix="video-"))
    out.mkdir(parents=True, exist_ok=True)
    if args.frames or args.at:
        frames(args.url, out, args.frames, args.at)
    else:
        transcript(args.url, out)


if __name__ == "__main__":
    main()
