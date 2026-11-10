import io
from pathlib import Path
import subprocess
import tempfile
import unittest
import wave
import imageio_ffmpeg
from engine.audio_import import normalize_recording
from engine.call_context import wav_segments


def source_wav(rate=48000,channels=2):
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as w:
        w.setnchannels(channels);w.setsampwidth(2);w.setframerate(rate)
        w.writeframes((b'\xe8\x03'+b'\xd0\x07' if channels==2 else b'\xe8\x03')*rate)
    return buffer.getvalue()


class AudioImportTests(unittest.TestCase):
    def test_48khz_stereo_is_resampled_without_losing_channel_mapping(self):
        converted=normalize_recording(source_wav())
        with wave.open(io.BytesIO(converted)) as w:
            self.assertEqual((w.getframerate(),w.getsampwidth(),w.getnchannels()),(16000,2,2))
            self.assertAlmostEqual(w.getnframes()/w.getframerate(),1,places=2)
        clips=wav_segments(converted,'agent_left')
        self.assertEqual([c['speaker'] for c in clips],['agent','customer'])

    def test_mp4_audio_track_and_mp3_decode_to_accepted_wav(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'source.wav';source.write_bytes(source_wav(channels=1))
            for extension,codec in [('mp4','aac'),('mp3','libmp3lame')]:
                target=Path(d)/('recording.'+extension)
                subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-loglevel','error','-i',str(source),'-c:a',codec,str(target)],check=True)
                converted=normalize_recording(target.read_bytes())
                self.assertEqual(len(wav_segments(converted)),1)
                with wave.open(io.BytesIO(converted)) as w:
                    self.assertEqual(w.getnchannels(),1)
                    self.assertEqual(w.getframerate(),16000)

    def test_valid_pcm_is_reused_and_invalid_media_is_rejected(self):
        original=source_wav(rate=16000,channels=1)
        self.assertEqual(normalize_recording(original),original)
        with self.assertRaisesRegex(ValueError,'decode an audio track'):
            normalize_recording(b'This is not an audio file')
