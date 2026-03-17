#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
audio_card_stream_node
----------------------

Назначение:
- Считывать звук с USB‑аудиокарты в реальном времени и публиковать его в ROS:
    * /audio/raw (std_msgs/UInt8MultiArray) — PCM s16_le mono
    * /sound/dominant_frequency_hz (std_msgs/Float32) — доминантная частота по текущему чанку
    * /oscillogram_frequency_hz (std_msgs/Float32) — рекомендуемая частота для motik осциллограммы

Идея:
- Вместо того, чтобы читать конкретный файл (как /sound/play_sound_with_oscillogram),
  этот узел просто «подслушивает» аудиокарту. Любой звук, который проигрывается
  через настроенное устройство (например, VNC-плеер, который выводит на USB‑карту),
  будет в реальном времени уходить в ROS и использоваться motik для осциллограммы.

Ограничения / нюансы:
- Узел не настраивает ALSA/PulseAudio. Необходимо, чтобы:
    * выбранное устройство действительно принимало тот звук, который вы хотите
      «раздать» в ROS (например, loopback‑девайс, monitor‑device и т.п.);
    * утилита `arecord` была установлена.
"""

from __future__ import division

import subprocess
import threading

import rospy
from std_msgs.msg import Float32, UInt8MultiArray

try:
    import numpy as np
    _NUMPY = True
except ImportError:
    np = None
    _NUMPY = False


def _dominant_frequency_hz(samples, sample_rate):
    """Расчёт доминантной частоты по массиву s16_int."""
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


def _stream_from_arecord(device, rate, chunk_frames, pub_raw, pub_freq, pub_osc_hz):
    """
    Читает сырые S16_LE сэмплы из arecord и публикует их в ROS.

    device: ALSA устройство, например "hw:1,0" или "plughw:1,0"
    rate: частота дискретизации, Гц
    chunk_frames: количество фреймов на один ROS‑сообщение
    """
    # Один фрейм = 1 сэмпл mono s16_le = 2 байта
    bytes_per_frame = 2
    chunk_bytes = chunk_frames * bytes_per_frame

    cmd = [
        "arecord",
        "-D", device,
        "-f", "S16_LE",
        "-c", "1",
        "-r", str(rate),
        "-t", "raw",
    ]

    rospy.loginfo("audio_card_stream_node: запускаю arecord: %s", " ".join(cmd))

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except Exception as e:
        rospy.logerr("audio_card_stream_node: не удалось запустить arecord: %s", e)
        return

    def _log_stderr():
        # Логируем stderr arecord в фоне, чтобы не забить буфер.
        try:
            for line in iter(proc.stderr.readline, b""):
                if not line:
                    break
                rospy.logwarn_throttle(5.0, "arecord: %s", line.decode("utf-8", "ignore").strip())
        except Exception:
            pass

    threading.Thread(target=_log_stderr, daemon=True).start()

    try:
        while not rospy.is_shutdown():
            buf = proc.stdout.read(chunk_bytes)
            if not buf:
                rospy.loginfo("audio_card_stream_node: EOF от arecord, выхожу")
                break

            # Публикуем /audio/raw
            raw_msg = UInt8MultiArray()
            raw_msg.data = list(buf)
            pub_raw.publish(raw_msg)

            # Частотный анализ
            if _NUMPY:
                try:
                    # bytes -> int16
                    samples = np.frombuffer(buf, dtype="<i2").astype(np.int16)
                    hz = _dominant_frequency_hz(samples.tolist(), rate)
                except Exception as e:
                    rospy.logdebug("audio_card_stream_node: freq calc error: %s", e)
                    hz = 0.0
                if hz > 0.0:
                    pub_freq.publish(Float32(data=hz))
                    if pub_osc_hz is not None:
                        pub_osc_hz.publish(Float32(data=hz))
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2.0)
        except Exception:
            pass
        rospy.loginfo("audio_card_stream_node: поток захвата остановлен")


def main():
    rospy.init_node("audio_card_stream_node", anonymous=False)

    # Параметры:
    #   ~device          — ALSA-устройство (например, "hw:1,0" или "plughw:1,0")
    #   ~sample_rate     — частота дискретизации (по умолчанию 16000)
    #   ~chunk_frames    — количество сэмплов в одном сообщении (по умолчанию 1024)
    device = rospy.get_param("~device", "hw:1,0")
    sample_rate = int(rospy.get_param("~sample_rate", 16000))
    chunk_frames = int(rospy.get_param("~chunk_frames", 1024))

    pub_raw = rospy.Publisher("/audio/raw", UInt8MultiArray, queue_size=5)
    pub_freq = rospy.Publisher("/sound/dominant_frequency_hz", Float32, queue_size=5)
    pub_osc_hz = rospy.Publisher("/oscillogram_frequency_hz", Float32, queue_size=2)

    rospy.loginfo(
        "audio_card_stream_node: устройство=%s, sample_rate=%d, chunk_frames=%d",
        device,
        sample_rate,
        chunk_frames,
    )

    # Запускаем поток захвата
    worker = threading.Thread(
        target=_stream_from_arecord,
        args=(device, sample_rate, chunk_frames, pub_raw, pub_freq, pub_osc_hz),
        daemon=True,
    )
    worker.start()

    rospy.loginfo(
        "audio_card_stream_node: публикует /audio/raw, /sound/dominant_frequency_hz, /oscillogram_frequency_hz "
        "на основе звука с аудиокарты"
    )

    rospy.spin()


if __name__ == "__main__":
    try:
        main()
    except rospy.ROSInterruptException:
        pass

