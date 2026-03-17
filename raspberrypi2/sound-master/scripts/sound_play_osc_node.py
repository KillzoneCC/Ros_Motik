#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Второй сервис: проверка длительности звука и воспроизведение с подключением к осциллограмме.

Сервисы:
  /sound/sound_duration (SoundDuration)     — по file_path вернуть duration_sec, ok, message.
  /sound/play_sound_with_oscillogram (PlaySoundWithOscillogram) — воспроизвести файл, слать сырой
    звук в /audio/raw и доминантную частоту в /sound/dominant_frequency_hz (Float32); осциллограмма
    motik может использовать эти данные.

Топики при воспроизведении:
  /audio/raw (std_msgs/UInt8MultiArray) — PCM s16_le моно, для motik oscillogram.
  /sound/dominant_frequency_hz (std_msgs/Float32) — доминантная частота (Гц) по текущему чанку.
"""
from __future__ import division

import os
import struct
import threading

import rospy
from std_msgs.msg import Float32, UInt8MultiArray

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    np = None
    _NUMPY = False

try:
    import soundfile as sf
    _SOUNDFILE = True
except ImportError:
    sf = None
    _SOUNDFILE = False

from sound.srv import SoundDuration, SoundDurationResponse, PlaySoundWithOscillogram, PlaySoundWithOscillogramResponse

CHUNK_SAMPLES = 1024
SAMPLE_RATE_DEFAULT = 16000


def _get_duration_soundfile(path):
    if not _SOUNDFILE or not path or not os.path.isfile(path):
        return None
    try:
        info = sf.info(path)
        return info.duration
    except Exception:
        return None


def _get_duration_wav(path):
    if not path or not path.lower().endswith(".wav") or not os.path.isfile(path):
        return None
    try:
        import wave
        with wave.open(path, "rb") as w:
            n = w.getnframes()
            r = w.getframerate()
            return n / float(r) if r else 0.0
    except Exception:
        return None


def get_duration(file_path):
    path = os.path.expanduser((file_path or "").strip())
    if not path or not os.path.isfile(path):
        return None, "file not found"
    dur = _get_duration_soundfile(path)
    if dur is not None:
        return dur, None
    dur = _get_duration_wav(path)
    if dur is not None:
        return dur, None
    return None, "unsupported format or read error"


def _dominant_frequency_hz(samples, sample_rate):
    if not _NUMPY or samples is None or len(samples) < 64 or sample_rate <= 0:
        return 0.0
    n = len(samples)
    n_fft = 1
    while n_fft < n:
        n_fft *= 2
    n_fft = min(n_fft, 4096)
    x = np.array(samples[:n_fft], dtype=np.float64) / 32768.0
    fft = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
    mag = np.abs(fft)
    if np.sum(mag) == 0:
        return 0.0
    peak_idx = int(np.argmax(mag))
    return float(freqs[peak_idx])


def _play_with_oscillogram(path, loop, pub_raw, pub_freq, pub_osc_hz, sample_rate_out):
    path = os.path.expanduser((path or "").strip())
    if not path or not os.path.isfile(path):
        rospy.logwarn("sound_play_osc: file not found %s", path)
        return
    if not _SOUNDFILE and not path.lower().endswith(".wav"):
        rospy.logwarn("sound_play_osc: need soundfile for non-WAV; install: pip3 install soundfile")
        return
    try:
        if _SOUNDFILE:
            data, sr = sf.read(path, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            # resample to sample_rate_out if needed
            if sr != sample_rate_out and _NUMPY and sample_rate_out > 0:
                from numpy import interp
                n_out = int(len(data) * sample_rate_out / sr)
                x_old = np.linspace(0, 1, len(data))
                x_new = np.linspace(0, 1, n_out)
                data = np.interp(x_new, x_old, data).astype(np.float32)
                sr = sample_rate_out
        else:
            import wave
            with wave.open(path, "rb") as w:
                sr = w.getframerate()
                n = w.getnframes()
                buf = w.readframes(n)
            # s16 -> float
            data = np.frombuffer(buf, dtype=np.int16) / 32768.0
            if sr != sample_rate_out and sample_rate_out > 0 and _NUMPY:
                n_out = int(len(data) * sample_rate_out / sr)
                data = np.interp(
                    np.linspace(0, len(data) - 1, n_out),
                    np.arange(len(data)),
                    data,
                ).astype(np.float32)
                sr = sample_rate_out
    except Exception as e:
        rospy.logwarn("sound_play_osc: read error %s", e)
        return
    rospy.loginfo("sound_play_osc: playing %s (%.2f s), publishing /audio/raw, /sound/dominant_frequency_hz, /oscillogram_frequency_hz", path, len(data) / float(sr))
    while True:
        pos = 0
        while pos < len(data) and not rospy.is_shutdown():
            chunk_float = data[pos:pos + CHUNK_SAMPLES]
            pos += len(chunk_float)
            if len(chunk_float) == 0:
                break
            # PCM s16_le for /audio/raw
            chunk_int = (chunk_float * 32767).clip(-32768, 32767).astype(np.int16)
            raw_msg = UInt8MultiArray()
            raw_msg.data = list(chunk_int.tobytes())
            pub_raw.publish(raw_msg)
            # dominant frequency
            if _NUMPY and len(chunk_float) >= 64:
                samples_int = chunk_int.tolist()
                hz = _dominant_frequency_hz(samples_int, sr)
                pub_freq.publish(Float32(data=hz))
                if pub_osc_hz is not None and hz > 0:
                    pub_osc_hz.publish(Float32(data=hz))
            rospy.sleep(len(chunk_float) / float(sr))
        if not loop or rospy.is_shutdown():
            break
    rospy.loginfo("sound_play_osc: playback finished")


def main():
    rospy.init_node("sound_play_osc_node", anonymous=False)
    sample_rate = int(rospy.get_param("~sample_rate", SAMPLE_RATE_DEFAULT))
    pub_raw = rospy.Publisher("/audio/raw", UInt8MultiArray, queue_size=5)
    pub_freq = rospy.Publisher("/sound/dominant_frequency_hz", Float32, queue_size=5)
    pub_osc_hz = rospy.Publisher("/oscillogram_frequency_hz", Float32, queue_size=2)
    play_thread = [None]
    play_lock = threading.Lock()

    def handle_duration(req):
        dur, err = get_duration(req.file_path)
        if err:
            return SoundDurationResponse(duration_sec=0.0, ok=False, message=err)
        return SoundDurationResponse(duration_sec=dur, ok=True, message="ok")

    def handle_play(req):
        with play_lock:
            if play_thread[0] is not None and play_thread[0].is_alive():
                return PlaySoundWithOscillogramResponse(ok=False, message="playback already in progress")
        def run():
            _play_with_oscillogram(req.file_path, req.loop, pub_raw, pub_freq, pub_osc_hz, sample_rate)
            with play_lock:
                play_thread[0] = None
        t = threading.Thread(target=run, daemon=True)
        play_thread[0] = t
        t.start()
        return PlaySoundWithOscillogramResponse(ok=True, message="playback started")

    rospy.Service("/sound/sound_duration", SoundDuration, handle_duration)
    rospy.Service("/sound/play_sound_with_oscillogram", PlaySoundWithOscillogram, handle_play)
    rospy.loginfo(
        "sound_play_osc_node: /sound/sound_duration, /sound/play_sound_with_oscillogram; "
        "during playback: /audio/raw, /sound/dominant_frequency_hz, /oscillogram_frequency_hz"
    )
    rospy.spin()


if __name__ == "__main__":
    try:
        main()
    except rospy.ROSInterruptException:
        pass
