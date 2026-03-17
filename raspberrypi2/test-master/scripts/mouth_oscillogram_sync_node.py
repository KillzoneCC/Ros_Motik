#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Третья нода: читает уровень от второй ноды (/audio/oscillogram_level_for_mouth) и при воспроизведении — /audio/playback_level.
Сглаживание и публикация /audio/mouth_open_level для анимации рта (нода рта в ainex_bringup). Частота — /mouth_sync_hz или ~rate.
"""
from __future__ import division

import threading
import time

import rospy
from std_msgs.msg import Float32

# Таймаут (сек): если playback_level не приходил дольше — используем уровень с микрофона
PLAYBACK_PRIORITY_TIMEOUT_SEC = 0.35

# Частота по умолчанию (Гц) — калибровка с нодой анимации рта
DEFAULT_MOUTH_SYNC_HZ = 30.0


class MouthOscillogramSyncNode:
    def __init__(self):
        rospy.init_node("mouth_oscillogram_sync_node", anonymous=False)
        # Частота публикации: ~rate или общий /mouth_sync_hz (должна совпадать с нодой рта)
        # fmt: off
        self._smooth = float(rospy.get_param("~smooth", 0.75))  # type: ignore[arg-type]
        self._scale = float(rospy.get_param("~scale", 1.5))  # type: ignore[arg-type]
        self._min_level = float(rospy.get_param("~min_level", 0.02))  # type: ignore[arg-type]
        _rate = rospy.get_param("~rate", rospy.get_param("/mouth_sync_hz", DEFAULT_MOUTH_SYNC_HZ))
        self._publish_rate = float(_rate)  # type: ignore[arg-type]
        # fmt: on
        self._current = 0.0
        self._lock = threading.Lock()
        self._shutdown = False
        self._mic_level = 0.0
        self._playback_level = 0.0
        self._playback_time = 0.0
        rospy.Subscriber("/audio/oscillogram_level_for_mouth",
                         Float32, self._cb_mic_level, queue_size=10)
        rospy.Subscriber("/audio/playback_level", Float32, self._cb_playback_level, queue_size=5)
        self._pub_mouth = rospy.Publisher(
            "/audio/mouth_open_level", Float32, queue_size=5)

    def _cb_mic_level(self, msg):
        raw = float(msg.data) * self._scale
        if raw < self._min_level:
            raw = 0.0
        with self._lock:
            self._mic_level = max(0.0, min(1.0, raw))

    def _cb_playback_level(self, msg):
        raw = float(msg.data) * self._scale
        if raw < self._min_level:
            raw = 0.0
        with self._lock:
            self._playback_level = max(0.0, min(1.0, raw))
            self._playback_time = time.time()

    def _run_publish_loop(self):
        rate = rospy.Rate(self._publish_rate)
        while not self._shutdown and not rospy.is_shutdown():
            now = time.time()
            with self._lock:
                if now - self._playback_time <= PLAYBACK_PRIORITY_TIMEOUT_SEC:
                    target = self._playback_level
                else:
                    target = self._mic_level
                self._current += (target - self._current) * (1.0 - self._smooth)
                self._current = max(0.0, min(1.0, self._current))
                val = self._current
            self._pub_mouth.publish(Float32(data=val))
            rate.sleep()

    def run(self):
        self._shutdown = False
        rospy.loginfo("mouth_oscillogram_sync_node: приоритет /audio/playback_level (с карты), иначе /audio/oscillogram_level_for_mouth (микрофон); публикация /audio/mouth_open_level, scale=%.2f, smooth=%.2f, %.1f Гц",
                      self._scale, self._smooth, self._publish_rate)
        th = threading.Thread(target=self._run_publish_loop, daemon=True)
        th.start()
        rospy.spin()
        self._shutdown = True
        th.join(timeout=2.0)


def main():
    try:
        node = MouthOscillogramSyncNode()
        node.run()
    except rospy.ROSInterruptException:
        pass
    except Exception as e:
        rospy.logerr("mouth_oscillogram_sync_node: %s", e)
        raise


if __name__ == "__main__":
    main()
