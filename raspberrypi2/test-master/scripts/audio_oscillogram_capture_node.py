#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Первая нода: захват уровня звука и публикация в /audio/oscillogram_level.

Режимы (параметр ~source):
  alsa          — с ALSA-устройства ввода (микрофон), например plughw:2,0 (arecord).
  pulse_monitor — с монитора вывода PulseAudio: то, что реально играет в системе (VLC, браузер и т.д.).
                  На роботе без отдельного микрофона используйте pulse_monitor, чтобы рот синхронизировался
                  со звуком из любого приложения (VNC, VLC и т.п.).

Запуск: roslaunch test audio_oscillogram_capture.launch
        roslaunch test audio_oscillogram_capture.launch source:=pulse_monitor
"""
from __future__ import division

import subprocess
import threading

import rospy
from std_msgs.msg import Float32

SAMPLE_BYTES = 2  # 16-bit LE
# Имя источника PulseAudio: монитор стандартного вывода (то, что играет в колонки)
PULSE_MONITOR_SOURCE = "@DEFAULT_SINK@.monitor"


def compute_rms_s16_le(data):
    n = len(data) // SAMPLE_BYTES
    if n == 0:
        return 0.0
    total = 0.0
    for i in range(n):
        j = i * SAMPLE_BYTES
        low = data[j]
        high = data[j + 1]
        s = low + (high << 8)
        if s >= 32768:
            s -= 65536
        total += s * s
    return (total / n) ** 0.5 / 32768.0


def _start_arecord(device, rate, chunk_bytes):
    """Запуск arecord для захвата с ALSA-устройства."""
    return subprocess.Popen(
        [
            "arecord", "-q", "-D", device,
            "-f", "S16_LE", "-r", str(rate), "-c", "1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def _start_parec(rate, chunk_bytes):
    """Запуск parec для захвата с монитора вывода PulseAudio (то, что играет в системе)."""
    return subprocess.Popen(
        [
            "parec", "-r", "-d", PULSE_MONITOR_SOURCE,
            "--raw", "--format=s16le", "--rate=%d" % rate, "--channels=1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


class AudioOscillogramCaptureNode:
    def __init__(self):
        rospy.init_node("audio_oscillogram_capture_node", anonymous=False)
        self.source = str(rospy.get_param("~source", "alsa")).strip().lower()
        self.device = str(rospy.get_param("~device", "plughw:2,0"))
        self.rate = int(rospy.get_param("~rate", 16000))  # type: ignore[arg-type]
        self.chunk_size = int(rospy.get_param(
            "~chunk_size", 1024))  # type: ignore[arg-type]
        self.chunk_bytes = self.chunk_size * SAMPLE_BYTES
        self.pub_level = rospy.Publisher(
            "/audio/oscillogram_level", Float32, queue_size=10)
        self._proc = None
        self._shutdown = False
        self._use_pulse = self.source == "pulse_monitor"
        self._pulse_fail_count = 0

    def _start_capture(self):
        if self._use_pulse:
            try:
                p = _start_parec(self.rate, self.chunk_bytes)
                if p is not None:
                    self._pulse_fail_count = 0
                return p
            except FileNotFoundError:
                self._pulse_fail_count += 1
                rospy.logerr_throttle(
                    10.0,
                    "audio_oscillogram_capture: parec не найден. Установите: sudo apt install pulseaudio-utils. "
                    "Либо запустите PulseAudio (pulseaudio --start), либо используйте source:=alsa для микрофона.")
                return None
            except Exception as e:
                self._pulse_fail_count += 1
                rospy.logerr_throttle(10.0, "audio_oscillogram_capture (parec): %s. Для VNC/звука через колонки нужен запущенный PulseAudio.", e)
                return None
        else:
            try:
                return _start_arecord(self.device, self.rate, self.chunk_bytes)
            except FileNotFoundError:
                rospy.logerr(
                    "audio_oscillogram_capture: arecord не найден. Установите: sudo apt install alsa-utils")
                return None
            except Exception as e:
                rospy.logerr("audio_oscillogram_capture (arecord): %s", e)
                return None

    def _capture_loop(self):
        while not self._shutdown and not rospy.is_shutdown():
            if self._proc is None:
                self._proc = self._start_capture()
                if self._proc is None:
                    rospy.sleep(2.0)
                    continue
            try:
                if self._proc.stdout is None:
                    self._proc = None
                    continue
                data = self._proc.stdout.read(self.chunk_bytes)
                if not data or len(data) < self.chunk_bytes:
                    if self._proc.poll() is not None:
                        self._proc = None
                    continue
                level = compute_rms_s16_le(data)
                if level != level:  # NaN
                    level = 0.0
                level = min(1.0, max(0.0, level))
                msg = Float32(data=level)
                self.pub_level.publish(msg)
            except Exception as e:
                rospy.logdebug("audio_oscillogram_capture read: %s", e)
                if self._proc and self._proc.poll() is not None:
                    self._proc = None
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None

    def run(self):
        self._shutdown = False
        th = threading.Thread(target=self._capture_loop, daemon=True)
        th.start()
        if self._use_pulse:
            rospy.loginfo(
                "audio_oscillogram_capture_node: топик /audio/oscillogram_level (источник: PulseAudio монитор вывода — то, что играет в системе)")
        else:
            rospy.loginfo(
                "audio_oscillogram_capture_node: топик /audio/oscillogram_level (устройство ALSA %s)", self.device)
        rospy.spin()
        self._shutdown = True
        th.join(timeout=2.0)


def main():
    try:
        node = AudioOscillogramCaptureNode()
        node.run()
    except rospy.ROSInterruptException:
        pass
    except Exception as e:
        rospy.logerr("audio_oscillogram_capture_node: %s", e)
        raise


if __name__ == "__main__":
    main()
