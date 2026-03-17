#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый синусоидальный сигнал в /audio/level для проверки анимации осциллограммы
на OLED (motik_node в режиме oscillogram_display:=true).

Запуск:
  rosrun sound audio_level_test_sine.py
  rosrun sound audio_level_test_sine.py _rate:=60 _freq:=2.0

Параметры (начальные, можно менять через топики без перезапуска):
  ~rate  — частота публикации (Гц), по умолчанию 60.
  ~freq  — частота синусоиды (Гц), по умолчанию 2.0.

Смена частот вручную (команды):
  rostopic pub /audio_level_test_sine/set_rate std_msgs/Float32 "data: 30.0" --once
  rostopic pub /audio_level_test_sine/set_freq std_msgs/Float32 "data: 1.0" --once
"""
from __future__ import division

import math
import rospy
from std_msgs.msg import Float32

MIN_RATE = 1.0
MAX_RATE = 1500.0
MIN_FREQ = 0.1
MAX_FREQ = 100.0


def main():
    rospy.init_node("audio_level_test_sine", anonymous=False)
    # Начальные значения из параметров; далее меняются по топикам
    state = [
        max(MIN_RATE, min(MAX_RATE, float(rospy.get_param("~rate", 60.0)))),
        max(MIN_FREQ, min(MAX_FREQ, float(rospy.get_param("~freq", 2.0)))),
    ]

    def cb_rate(msg):
        try:
            v = max(MIN_RATE, min(MAX_RATE, float(msg.data)))
            state[0] = v
            rospy.loginfo("audio_level_test_sine: частота публикации установлена %.1f Гц", v)
        except (TypeError, ValueError):
            pass

    def cb_freq(msg):
        try:
            v = max(MIN_FREQ, min(MAX_FREQ, float(msg.data)))
            state[1] = v
            rospy.loginfo("audio_level_test_sine: частота синуса установлена %.1f Гц", v)
        except (TypeError, ValueError):
            pass

    rospy.Subscriber("~set_rate", Float32, cb_rate, queue_size=1)
    rospy.Subscriber("~set_freq", Float32, cb_freq, queue_size=1)

    pub = rospy.Publisher("/audio/level", Float32, queue_size=10)
    start = rospy.get_time()
    rospy.loginfo(
        "audio_level_test_sine: синус в /audio/level, публикация %.1f Гц, синус %.1f Гц. "
        "Менять: ~set_rate, ~set_freq (Float32)",
        state[0], state[1],
    )
    while not rospy.is_shutdown():
        t = rospy.get_time() - start
        rate_hz, sine_hz = state[0], state[1]
        level = 0.5 + 0.45 * math.sin(2.0 * math.pi * sine_hz * t)
        level = max(0.0, min(1.0, level))
        pub.publish(Float32(data=level))
        rospy.sleep(1.0 / rate_hz if rate_hz > 0 else 0.01)


if __name__ == "__main__":
    try:
        main()
    except rospy.ROSInterruptException:
        pass
