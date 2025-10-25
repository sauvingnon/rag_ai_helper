import asyncio

async def convert_with_ffmpeg(input_bytes: bytes, fmt="wav") -> bytes:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-i", "pipe:0", "-acodec", "pcm_s16le", "-ar", "16000",
        "-ac", "1", "-f", fmt, "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(input=input_bytes)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {err.decode()}")
    return out
