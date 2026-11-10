"""Decode uploaded media locally into PCM WAV; original files remain unchanged."""
import io
from pathlib import Path
import subprocess
import tempfile
import wave

MAX_BYTES=60*1024*1024


def normalize_recording(content):
    if not content or len(content)>MAX_BYTES:
        raise ValueError("Upload a recording under 60 MB")
    try:
        with wave.open(io.BytesIO(content),'rb') as audio:
            if audio.getnchannels() in (1,2) and audio.getsampwidth()==2 and 8000<=audio.getframerate()<=44100:
                if not 0<audio.getnframes()/audio.getframerate()<=600:
                    raise ValueError("Use a recording up to 10 minutes long")
                return content
    except (wave.Error,EOFError):
        pass
    import imageio_ffmpeg
    with tempfile.TemporaryDirectory(prefix='hmh-audio-') as directory:
        source=Path(directory)/'upload.media'
        target=Path(directory)/'converted.wav'
        source.write_bytes(content)
        command=[imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error',
            '-protocol_whitelist','file,pipe','-i',str(source),'-map','0:a:0','-vn',
            '-t','601','-ar','16000','-acodec','pcm_s16le','-fs','40000000','-f','wav',str(target)]
        try:
            result=subprocess.run(command,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=60)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Audio conversion timed out. Try a shorter recording.") from exc
        if result.returncode or not target.exists():
            raise ValueError("Could not decode an audio track. Use an unlocked MP4, M4A, MP3, WAV, OGG, WebM or FLAC file.")
        converted=target.read_bytes()
    with wave.open(io.BytesIO(converted),'rb') as audio:
        if audio.getnchannels() not in (1,2):
            raise ValueError("Use a mono or stereo recording; surround audio is not supported")
        if not 0<audio.getnframes()/audio.getframerate()<=600:
            raise ValueError("Use a recording up to 10 minutes long")
    return converted
