#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Нода захвата звука: с микрофона (ALSA) или непосредственно с выхода на динамики (Analog Stereo Output) через PulseAudio.
Публикует уровень 0..1 в /audio/level для отрисовки осциллограммы в motik_node.

Параметры:
  ~source: "pulse_monitor" — захват с выхода на динамики (Analog Stereo, по умолчанию), "alsa" — микрофон.
  ~pulse_source: имя источника PulseAudio (если задано — используется он; иначе авто-поиск Analog Stereo monitor).
  ~device: устройство ALSA при source:=alsa (например plughw:2,0).
  ~rate: частота дискретизации (по умолчанию 16000).
"""
from __future__ import division

import subprocess
import threading

import rospy
from std_msgs.msg import Float32

SAMPLE_BYTES = 2
PULSE_MONITOR_SOURCE = "@DEFAULT_SINK@.monitor"


def _find_analog_stereo_monitor():
    """Ищет источник PulseAudio — монитор выхода Analog Stereo (непосредственно с выхода на динамики)."""
    try:
        out = subprocess.check_output(
            ["pactl", "list", "sources", "short"],
            stderr=subprocess.DEVNULL,
            timeout=5,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        name = parts[1]
        if name.endswith(".monitor") and "analog" in name.lower():
            return name
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        name = parts[1]
        if name.endswith(".monitor"):
            return name
    return None


def compute_rms_s16_le(data):
    n = len(data) // SAMPLE_BYTES
    if n == 0:
        return 0.0
    total = 0.0
    for i in range(n):
        j = i * SAMPLE_BYTES
        s = data[j] + (data[j + 1] << 8)
        if s >= 32768:
            s -= 65536
        total += s * s
    return (total / n) ** 0.5 / 32768.0


def _start_arecord(device, rate, chunk_bytes):
    return subprocess.Popen(
        ["arecord", "-q", "-D", device, "-f", "S16_LE", "-r", str(rate), "-c", "1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def _start_parec(rate, chunk_bytes, source=None):
    src = source or PULSE_MONITOR_SOURCE
    return subprocess.Popen(
        ["parec", "-r", "-d", src, "--raw", "--format=s16le", "--rate=%d" % rate, "--channels=1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def main():
    rospy.init_node("sound_node", anonymous=False)
    source = str(rospy.get_param("~source", "pulse_monitor")).strip().lower()
    device = str(rospy.get_param("~device", "plughw:2,0"))
    rate = int(rospy.get_param("~rate", 16000))
    chunk_size = int(rospy.get_param("~chunk_size", 1024))
    chunk_bytes = chunk_size * SAMPLE_BYTES

    pub_level = rospy.Publisher("/audio/level", Float32, queue_size=10)
    use_pulse = source == "pulse_monitor"
    pulse_src_param = rospy.get_param("~pulse_source", "").strip()
    if use_pulse and not pulse_src_param:
        pulse_src_param = _find_analog_stereo_monitor() or PULSE_MONITOR_SOURCE
    elif use_pulse:
        pulse_src_param = pulse_src_param or PULSE_MONITOR_SOURCE
    proc = [None]  # mutable
    shutdown = [False]

    def capture_loop():
        while not shutdown[0] and not rospy.is_shutdown():
            if proc[0] is None:
                try:
                    if use_pulse:
                        proc[0] = _start_parec(rate, chunk_bytes, pulse_src_param)
                    else:
                        proc[0] = _start_arecord(device, rate, chunk_bytes)
                except FileNotFoundError:
                    if use_pulse:
                        rospy.logerr_throttle(10.0, "sound_node: parec не найден. Установите pulseaudio-utils или используйте source:=alsa")
                    else:
                        rospy.logerr("sound_node: arecord не найден. Установите alsa-utils")
                    rospy.sleep(2.0)
                    continue
                except Exception as e:
                    rospy.logerr_throttle(10.0, "sound_node: %s", e)
                    rospy.sleep(2.0)
                    continue
            try:
                if proc[0].stdout is None:
                    proc[0] = None
                    continue
                data = proc[0].stdout.read(chunk_bytes)
                if not data or len(data) < chunk_bytes:
                    if proc[0].poll() is not None:
                        proc[0] = None
                    continue
                level = compute_rms_s16_le(data)
                level = max(0.0, min(1.0, level)) if level == level else 0.0
                pub_level.publish(Float32(data=level))
            except Exception as e:
                rospy.logdebug("sound_node read: %s", e)
                if proc[0] and proc[0].poll() is not None:
                    proc[0] = None
        if proc[0] and proc[0].poll() is None:
            try:
                proc[0].terminate()
            except Exception:
                pass
            proc[0] = None

    th = threading.Thread(target=capture_loop, daemon=True)
    th.start()
    if use_pulse:
        rospy.loginfo("sound_node: захват с выхода на динамики (Analog Stereo / PulseAudio), источник: %s, топик /audio/level",
                      pulse_src_param)
    else:
        rospy.loginfo("sound_node: захват с микрофона (ALSA %s), топик /audio/level", device)
    rospy.spin()
    shutdown[0] = True
    th.join(timeout=2.0)


if __name__ == "__main__":
    try:
        main()
    except rospy.ROSInterruptException:
        pass
    except Exception as e:
        rospy.logerr("sound_node: %s", e)
        raise
