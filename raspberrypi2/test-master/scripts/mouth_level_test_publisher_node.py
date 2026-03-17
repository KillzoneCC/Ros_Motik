#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый публикатор: шлёт уровень 0..1 в /audio/mouth_open_level по синусоиде.
Нужен только для проверки анимации рта на дисплее без микрофона и цепочки нод.
Запуск: через mouth_animation_test.launch (вместе с нодой рта из ainex_bringup).
"""
from __future__ import division

import math
import rospy
from std_msgs.msg import Float32

DEFAULT_HZ = 30.0


def main():
    rospy.init_node("mouth_level_test_publisher_node", anonymous=False)
    rate_hz = float(rospy.get_param("~rate", rospy.get_param("/mouth_sync_hz", DEFAULT_HZ)))
    pub = rospy.Publisher("/audio/mouth_open_level", Float32, queue_size=5)
    rate = rospy.Rate(rate_hz)
    start = rospy.get_time()
    rospy.loginfo("mouth_level_test_publisher: публикую уровень в /audio/mouth_open_level (синусоида), %.1f Гц", rate_hz)
    while not rospy.is_shutdown():
        t = rospy.get_time() - start
        # Синусоида 0.05..0.95 — рот плавно открывается и закрывается
        level = 0.5 + 0.45 * math.sin(t * 2.0)
        level = max(0.0, min(1.0, level))
        pub.publish(Float32(data=level))
        rate.sleep()


if __name__ == "__main__":
    try:
        main()
    except rospy.ROSInterruptException:
        pass
