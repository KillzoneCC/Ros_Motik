#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Публикация в топик эмоций (без дисплея, без ноды отрисовки).
Использование:
  rosrun motik emotions_display_node.py              # публикует default_emotion раз в 1 с
  rosrun motik emotions_display_node.py _emotion:=happy
  rosrun motik emotions_display_node.py _topic:=/emotions_display _emotion:=sad

Отрисовка на OLED выполняется в motik_node (подписка на /emotions).
"""
from __future__ import annotations

import rospy
from std_msgs.msg import String

VALID = (
    "neutral", "happy", "sad", "angry", "surprised", "excited", "sleepy",
    "love", "confused", "scared", "bored", "calm", "disgusted", "tired",
)


def main():
    rospy.init_node("emotions_topic", anonymous=False)
    topic = rospy.get_param("~topic", "emotions")
    emotion_param = (rospy.get_param("~emotion", "neutral") or "neutral").strip().lower()
    emotion = emotion_param if emotion_param in VALID else "neutral"
    rate_hz = rospy.get_param("~rate", 1.0)

    pub = rospy.Publisher(topic, String, queue_size=1, latch=True)
    pub.publish(String(data=emotion))
    rospy.loginfo("emotions_topic: публикуем в %s значение '%s' (rate %.1f Hz)", rospy.resolve_name(topic), emotion, rate_hz)

    if rate_hz <= 0:
        rospy.spin()
        return
    r = rospy.Rate(rate_hz)
    while not rospy.is_shutdown():
        pub.publish(String(data=emotion))
        r.sleep()


if __name__ == "__main__":
    main()
