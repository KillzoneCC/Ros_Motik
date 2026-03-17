#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Вторая нода: подписка на /audio/oscillogram_level (уровень с микрофона от ноды 1), буфер, график осциллограммы,
публикация /audio/oscillogram_level_for_mouth для третьей ноды. Третья нода передаёт уровень анимации рта.
"""
from __future__ import division

import collections
import threading

import rospy
from std_msgs.msg import Float32

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    Image = None
    ImageDraw = None
    PIL_AVAILABLE = False

try:
    from cv_bridge import CvBridge
    from sensor_msgs.msg import Image as SensorImage
    import numpy as np
    CV_BRIDGE_AVAILABLE = True
except (ImportError, SystemError, OSError, Exception):
    CvBridge = None
    SensorImage = None
    np = None
    CV_BRIDGE_AVAILABLE = False


class OscillogramPlotNode:
    def __init__(self):
        rospy.init_node("oscillogram_plot_node", anonymous=False)
        self._buffer_size = int(rospy.get_param("~buffer_size", 300))
        self._plot_width = int(rospy.get_param("~plot_width", 400))
        self._plot_height = int(rospy.get_param("~plot_height", 150))
        self._update_rate = float(rospy.get_param("~update_rate", 5.0))
        self._output_file = rospy.get_param("~output_file", "/tmp/oscillogram_plot.png")
        if isinstance(self._output_file, str):
            self._output_file = self._output_file.strip() or None
        else:
            self._output_file = None
        self._mouth_scale = float(rospy.get_param("~mouth_scale", 2.5))
        self._buffer = collections.deque(maxlen=self._buffer_size)
        self._lock = threading.Lock()
        self._shutdown = False
        rospy.Subscriber("/audio/oscillogram_level", Float32, self._cb_level, queue_size=20)
        self._pub_level_for_mouth = rospy.Publisher("/audio/oscillogram_level_for_mouth", Float32, queue_size=5)
        self._pub_image = None
        self._bridge = None
        if CV_BRIDGE_AVAILABLE and CvBridge is not None and SensorImage is not None:
            self._bridge = CvBridge()
            self._pub_image = rospy.Publisher("/audio/oscillogram_plot_image", SensorImage, queue_size=2)

    def _cb_level(self, msg):
        with self._lock:
            self._buffer.append(max(0.0, min(1.0, msg.data)))

    def _draw_plot(self):
        if Image is None or ImageDraw is None:
            return None
        with self._lock:
            if len(self._buffer) < 2:
                return None
            values = list(self._buffer)
        w, h = self._plot_width, self._plot_height
        img = Image.new("RGB", (w, h), (20, 20, 25))
        draw = ImageDraw.Draw(img)
        n = len(values)
        xs = [int(i * (w - 1) / max(1, n - 1)) for i in range(n)]
        ys = [int((1.0 - v) * (h - 4)) + 2 for v in values]
        points = list(zip(xs, ys))
        draw.line(points, fill=(80, 200, 120), width=2)
        draw.rectangle([0, 0, w - 1, h - 1], outline=(60, 60, 70))
        return img

    def _run_plot_loop(self):
        rate = rospy.Rate(self._update_rate)
        while not self._shutdown and not rospy.is_shutdown():
            with self._lock:
                latest = float(self._buffer[-1]) if self._buffer else 0.0
            level_for_mouth = min(1.0, latest * self._mouth_scale)
            self._pub_level_for_mouth.publish(Float32(data=level_for_mouth))
            if PIL_AVAILABLE:
                img = self._draw_plot()
                if img is not None and self._output_file:
                    try:
                        img.save(self._output_file)
                    except Exception:
                        pass
                if self._pub_image is not None and self._bridge is not None and np is not None and img is not None:
                    try:
                        arr = np.array(img)
                        arr = arr[:, :, ::-1]
                        msg = self._bridge.cv2_to_imgmsg(arr, encoding="bgr8")
                        msg.header.stamp = rospy.Time.now()
                        self._pub_image.publish(msg)
                    except Exception:
                        pass
            rate.sleep()

    def run(self):
        self._shutdown = False
        rospy.loginfo("oscillogram_plot_node: подписка на /audio/oscillogram_level, публикация /audio/oscillogram_level_for_mouth, буфер %d, обновление %.1f Гц", self._buffer_size, self._update_rate)
        th = threading.Thread(target=self._run_plot_loop, daemon=True)
        th.start()
        rospy.spin()
        self._shutdown = True
        th.join(timeout=2.0)


def main():
    try:
        node = OscillogramPlotNode()
        node.run()
    except rospy.ROSInterruptException:
        pass
    except Exception as e:
        rospy.logerr("oscillogram_plot_node: %s", e)
        raise


if __name__ == "__main__":
    main()
