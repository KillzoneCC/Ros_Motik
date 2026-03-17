#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
motik_node: топики /emotions и /emotions_display (текущая эмоция), вывод эмоций на OLED (I2C 0x3D).
При включённом ~oscillogram_display — осциллограмма звука на том же дисплее.

Осциллограмма:
  По умолчанию уровень из /audio/level (std_msgs/Float32).
  Если задана ~oscillogram_frequency_hz (например 440) — уровень считается по полосе вокруг этой частоты
  из сырого звука /audio/raw (std_msgs/UInt8MultiArray, s16_le моно). Нужны numpy и источник /audio/raw.
  ~oscillogram_frequency_band_hz — полуширина полосы (по умолчанию 50 Гц).
  ~audio_sample_rate — частота дискретизации (по умолчанию 16000).
  ~audio_raw_topic — топик сырого PCM (по умолчанию /audio/raw).

Управление эмоциями: топик /emotions (std_msgs/String).
Ключевые слова: neutral, happy, sad, angry, surprised, excited, sleepy, love, confused, scared, bored, calm, disgusted, tired.
"""
from __future__ import annotations

import atexit
import collections
import time

import rospy
from std_msgs.msg import String, Float32, UInt8MultiArray

W, H = 128, 64
I2C_PORT = 1
I2C_ADDRESS = 0x3D

try:
    import numpy as np
    _NUMPY_AVAILABLE = True
except ImportError:
    np = None
    _NUMPY_AVAILABLE = False

try:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    from PIL import Image, ImageDraw
    _LUMA_AVAILABLE = True
except ImportError:
    _LUMA_AVAILABLE = False
    i2c = None
    ssd1306 = None
    Image = None
    ImageDraw = None

SAMPLE_BYTES = 2  # s16_le


VALID_EMOTIONS = (
    "neutral", "happy", "sad", "angry", "surprised", "excited", "sleepy",
    "love", "confused", "scared", "bored", "calm", "disgusted", "tired",
)


def _draw_emotion(emotion: str):
    """Рисует кадр эмоции 128x64 (ч/б). Рот по центру дисплея."""
    img = Image.new("1", (W, H), 0)
    draw = ImageDraw.Draw(img)
    emotion = (emotion or "neutral").strip().lower()
    cx, cy = W // 2, H // 2
    mouth_scale = 2.2
    r = int(14 * mouth_scale)
    line_w = max(1, int(3 * mouth_scale))

    if emotion == "happy":
        draw.arc((cx - r, cy - r, cx + r, cy + r),
                 0, 180, fill=255, width=line_w)
    elif emotion == "sad":
        draw.arc((cx - r, cy - r, cx + r, cy + r),
                 180, 360, fill=255, width=line_w)
    elif emotion == "angry":
        draw.line((cx - r, cy, cx + r, cy), fill=255, width=line_w)
    elif emotion == "surprised":
        draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                     outline=255, width=line_w)
    elif emotion == "excited":
        draw.arc((cx - r, cy - r, cx + r, cy + r),
                 0, 180, fill=255, width=line_w)
    elif emotion in ("sleepy", "tired"):
        rs = max(4, r // 2)
        draw.line((cx - rs, cy, cx + rs, cy), fill=255, width=line_w)
    elif emotion == "love":
        draw.arc((cx - r, cy - r - 2, cx + r, cy + r - 2),
                 0, 180, fill=255, width=line_w)
    elif emotion == "confused":
        n = 9
        pts = [(cx - r + (2 * r * i) // (n - 1), cy + (6 if i % 2 else -6))
               for i in range(n)]
        for i in range(len(pts) - 1):
            draw.line([pts[i], pts[i + 1]], fill=255, width=line_w)
    elif emotion == "scared":
        draw.ellipse((cx - r, cy - r, cx + r, cy + r),
                     outline=255, width=line_w)
    elif emotion == "bored":
        rs = max(6, r // 2)
        draw.line((cx - rs, cy, cx + rs, cy), fill=255, width=line_w)
    elif emotion == "calm":
        draw.arc((cx - r, cy - r, cx + r, cy + r),
                 30, 150, fill=255, width=line_w)
    elif emotion == "disgusted":
        draw.arc((cx - r, cy - r, cx + r, cy + r),
                 180, 360, fill=255, width=line_w)
    else:
        draw.line((cx - r, cy, cx + r, cy), fill=255, width=line_w)
    return img


def _s16le_to_samples(data: bytes):
    """Декодирует байты s16_le в список int (моно)."""
    n = len(data) // SAMPLE_BYTES
    out = []
    for i in range(n):
        j = i * SAMPLE_BYTES
        s = data[j] + (data[j + 1] << 8)
        if s >= 32768:
            s -= 65536
        out.append(s)
    return out


def _bandpass_waveform(samples, sample_rate: float, target_hz: float, band_hz: float):
    """Полосовой фильтр через FFT: оставляет только target_hz ± band_hz, возвращает вещественный сигнал."""
    if not _NUMPY_AVAILABLE or len(samples) < 64:
        return samples if _NUMPY_AVAILABLE and hasattr(samples, "__len__") else []
    n_fft = 1
    n = len(samples)
    while n_fft < n:
        n_fft *= 2
    n_fft = min(n_fft, 4096)
    x = np.array(samples[:n_fft], dtype=np.float64) / 32768.0
    X = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
    mask = (freqs >= max(0, target_hz - band_hz)
            ) & (freqs <= target_hz + band_hz)
    X_filtered = X * mask
    out = np.fft.irfft(X_filtered, n=n_fft)
    return out.tolist()


def _level_at_frequency_hz(samples, sample_rate: float, target_hz: float, band_hz: float = 50.0) -> float:
    """
    Уровень (0..1) в полосе вокруг target_hz через FFT.
    band_hz — полуширина полосы (берём target_hz ± band_hz).
    """
    if not _NUMPY_AVAILABLE or not samples or sample_rate <= 0 or target_hz <= 0:
        return 0.0
    n = len(samples)
    if n < 64:
        return 0.0
    # степень двойки для FFT
    n_fft = 1
    while n_fft < n:
        n_fft *= 2
    n_fft = min(n_fft, 4096)
    x = np.array(samples[:n_fft], dtype=np.float64) / 32768.0
    fft = np.fft.rfft(x)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sample_rate)
    mag = np.abs(fft)
    low = max(0.0, target_hz - band_hz)
    high = target_hz + band_hz
    mask = (freqs >= low) & (freqs <= high)
    if not np.any(mask):
        return 0.0
    level = float(np.mean(mag[mask]))
    # нормализация: типичный максимум при полной шкале ~ n_fft/2
    norm = (n_fft / 2.0) * 0.5
    level = min(1.0, level / norm) if norm > 0 else 0.0
    return max(0.0, level)


def _draw_oscillogram(level: float):
    """Рисует осциллограмму: одна полоса по центру (для режима только /audio/level)."""
    img = Image.new("1", (W, H), 0)
    draw = ImageDraw.Draw(img)
    cx, cy = W // 2, H // 2
    bar_half_height = max(2, int(cy * max(0.0, min(1.0, level))))
    bar_width = 8
    left = cx - bar_width // 2
    top = cy - bar_half_height
    right = cx + bar_width // 2
    bottom = cy + bar_half_height
    draw.rectangle((left, top, right, bottom), fill=255)
    return img


def _draw_oscillogram_waveform(y_values: list, center: bool = True):
    """
    Рисует осциллограмму — линия по точкам.
    y_values: список из W значений. Если center=True — значения в -1..1 (0 по центру);
    иначе 0..1 (уровень). Экран: x 0..W-1, y 0..H-1 (y вниз).
    """
    img = Image.new("1", (W, H), 0)
    draw = ImageDraw.Draw(img)
    cy = H // 2
    n = min(len(y_values), W)
    if n < 2:
        return img
    pts = []
    for i in range(n):
        y = y_values[i]
        if center:
            # -1..1 -> пиксель: 0 вверху, H-1 внизу; центр cy
            y_px = cy + int(y * (cy - 1))
        else:
            # 0..1 -> уровень: 0 внизу, 1 вверху
            y_px = H - 1 - int(y * (H - 1))
        y_px = max(0, min(H - 1, y_px))
        pts.append((i, y_px))
    for j in range(len(pts) - 1):
        draw.line([pts[j], pts[j + 1]], fill=255, width=1)
    return img


def main():
    rospy.init_node("motik_node")

    emotions_pub = rospy.Publisher(
        "emotions", String, queue_size=1, latch=True)
    emotions_display_pub = rospy.Publisher(
        "emotions_display", String, queue_size=1, latch=True)
    oscillogram_display_pub = rospy.Publisher(
        "oscillogram_display", Float32, queue_size=5)

    current_emotion = rospy.get_param("~default_emotion", "neutral")
    emotion_msg = String(data=current_emotion)
    emotions_pub.publish(emotion_msg)
    emotions_display_pub.publish(emotion_msg)

    oscillogram_display = rospy.get_param("~oscillogram_display", False)
    # Целевая частота для осциллограммы можно задавать параметром
    # ~oscillogram_frequency_hz и/или в рантайме через топик
    # /oscillogram_frequency_hz (std_msgs/Float32).
    oscillogram_frequency_hz = float(
        rospy.get_param("~oscillogram_frequency_hz", 0.0))
    oscillogram_frequency_band_hz = float(
        rospy.get_param("~oscillogram_frequency_band_hz", 50.0))
    # Усиление осциллограммы (масштаб уровня 0..1) для тихих сигналов.
    oscillogram_gain = float(rospy.get_param("~oscillogram_gain", 3.0))
    audio_sample_rate = float(rospy.get_param("~audio_sample_rate", 16000.0))
    audio_raw_topic = rospy.get_param("~audio_raw_topic", "/audio/raw")
    animate = rospy.get_param("~animate", False)
    animation_interval_sec = rospy.get_param("~animation_interval_sec", 2.0)
    device = None
    last_level = 0.0
    # True = рисуем эмоции, False = осциллограмма или нет дисплея
    display_emotions_mode = False
    use_frequency_oscillogram = oscillogram_frequency_hz > 0 and _NUMPY_AVAILABLE
    # Буферы для осциллограммы-волны: сэмплы (raw) или уровни (level)
    oscillogram_waveform_buffer_size = int(
        rospy.get_param("~oscillogram_waveform_buffer_size", 2048))
    samples_buffer = collections.deque(
        maxlen=oscillogram_waveform_buffer_size)  # float -1..1
    # 128 уровней 0..1 для режима /audio/level
    levels_buffer = collections.deque(maxlen=W)

    if _LUMA_AVAILABLE:
        try:
            serial = i2c(port=I2C_PORT, address=I2C_ADDRESS)
            device = ssd1306(serial, width=W, height=H)
            if oscillogram_display:
                device.display(_draw_oscillogram_waveform(
                    [0.0] * W, center=(use_frequency_oscillogram or True)))
                if use_frequency_oscillogram:
                    rospy.loginfo("motik_node: осциллограмма по частоте %.0f Гц на дисплее I2C 0x%02X, топик %s",
                                  oscillogram_frequency_hz, I2C_ADDRESS, audio_raw_topic)
                else:
                    rospy.loginfo(
                        "motik_node: осциллограмма на дисплее I2C 0x%02X, топик /audio/level", I2C_ADDRESS)
            else:
                display_emotions_mode = True
                device.display(_draw_emotion(current_emotion))
                rospy.loginfo("motik_node: эмоции на дисплее I2C 0x%02X, топик %s",
                              I2C_ADDRESS, rospy.resolve_name("emotions"))
        except Exception as e:
            rospy.logwarn("motik_node: дисплей недоступен: %s", e)
            device = None
    elif oscillogram_display:
        rospy.logwarn("motik_node: pip3 install luma.oled pillow для дисплея")

    def on_audio_level(msg):
        nonlocal last_level
        # Усиление уровня для режима /audio/level
        lvl = max(0.0, min(1.0, float(msg.data)))
        lvl *= oscillogram_gain
        last_level = max(0.0, min(1.0, lvl))
        levels_buffer.append(last_level)
        try:
            oscillogram_display_pub.publish(Float32(data=last_level))
        except Exception as e:
            rospy.logdebug("motik_node oscillogram_display publish: %s", e)
        if device is not None and not display_emotions_mode:
            try:
                # Осциллограмма как линия уровней во времени (128 точек)
                pts = list(levels_buffer)
                if len(pts) < W:
                    pts = [0.0] * (W - len(pts)) + pts
                device.display(_draw_oscillogram_waveform(
                    pts[-W:], center=False))
            except Exception as e:
                rospy.logdebug("motik_node display: %s", e)

    def on_audio_raw(msg):
        nonlocal last_level
        if not msg.data:
            return
        try:
            samples_int = _s16le_to_samples(bytes(msg.data))
            samples_float = [s / 32768.0 for s in samples_int]
            samples_buffer.extend(samples_float)
        except Exception as e:
            rospy.logdebug("motik_node raw decode: %s", e)
            return
        # Уровень по частоте для топика
        if use_frequency_oscillogram:
            try:
                last_level = _level_at_frequency_hz(
                    samples_int, audio_sample_rate,
                    oscillogram_frequency_hz, oscillogram_frequency_band_hz,
                )
                # Усиление уровня для частотного режима
                last_level *= oscillogram_gain
                last_level = max(0.0, min(1.0, last_level))
            except Exception as e:
                rospy.logdebug("motik_node level_at_frequency: %s", e)
            try:
                oscillogram_display_pub.publish(Float32(data=last_level))
            except Exception as e:
                pass
        # Волна для дисплея: 128 точек
        if device is None or display_emotions_mode:
            return
        try:
            buf = list(samples_buffer)
            if len(buf) < 2:
                return
            if use_frequency_oscillogram and _NUMPY_AVAILABLE and len(buf) >= 64:
                # Полосовой фильтр по заданной частоте — волна меняется под эту частоту
                filtered = _bandpass_waveform(
                    [int(x * 32768) for x in buf[-2048:]],
                    audio_sample_rate,
                    oscillogram_frequency_hz,
                    oscillogram_frequency_band_hz,
                )
                if not filtered:
                    return
                # 128 точек из отфильтрованного сигнала (даунсэмпл)
                step = max(1, len(filtered) // W)
                y_values = [filtered[-W * step + i * step] for i in range(W)]
            else:
                # Весь сигнал — сырая волна
                step = max(1, len(buf) // W)
                y_values = [buf[-W * step + i * step] for i in range(W)]
            device.display(_draw_oscillogram_waveform(y_values, center=True))
        except Exception as e:
            rospy.logdebug("motik_node waveform display: %s", e)

    def on_emotion(msg):
        nonlocal current_emotion
        raw = (msg.data or "neutral").strip().lower() or "neutral"
        current_emotion = raw if raw in VALID_EMOTIONS else "neutral"
        if device is not None and display_emotions_mode:
            try:
                device.display(_draw_emotion(current_emotion))
            except Exception as e:
                rospy.logdebug("motik_node display: %s", e)

    rospy.Subscriber("emotions", String, on_emotion, queue_size=1)

    def on_osc_frequency(msg):
        """Позволяет менять частоту осциллограммы в рантайме.

        Топик: /oscillogram_frequency_hz (std_msgs/Float32)
        data <= 0  -> режим уровня по /audio/level
        data > 0   -> уровень в полосе вокруг заданной частоты (нужен numpy и /audio/raw)
        """
        nonlocal oscillogram_frequency_hz, use_frequency_oscillogram
        try:
            val = float(getattr(msg, "data", 0.0))
        except Exception:
            val = 0.0
        if val <= 0.0:
            oscillogram_frequency_hz = 0.0
            use_frequency_oscillogram = False
            rospy.loginfo("motik_node: выключен режим частотной осциллограммы, используется /audio/level")
        else:
            oscillogram_frequency_hz = val
            if not _NUMPY_AVAILABLE:
                use_frequency_oscillogram = False
                rospy.logwarn(
                    "motik_node: numpy недоступен, осциллограмма по частоте %.1f Гц не будет работать, используется /audio/level",
                    oscillogram_frequency_hz,
                )
            else:
                use_frequency_oscillogram = True
                rospy.loginfo(
                    "motik_node: осциллограмма по частоте %.1f Гц (полоса ±%.1f Гц), источник %s",
                    oscillogram_frequency_hz,
                    oscillogram_frequency_band_hz,
                    audio_raw_topic,
                )

    # Управление частотой "анимации частотки" — можно крутить частоту по топику
    rospy.Subscriber("oscillogram_frequency_hz", Float32, on_osc_frequency, queue_size=1)

    animation_index = [0]

    def animation_tick(_event):
        if rospy.is_shutdown() or not device or not display_emotions_mode:
            return
        emotion = VALID_EMOTIONS[animation_index[0]]
        animation_index[0] = (animation_index[0] + 1) % len(VALID_EMOTIONS)
        try:
            device.display(_draw_emotion(emotion))
        except Exception as e:
            rospy.logdebug("motik_node animation: %s", e)

    if device is not None and display_emotions_mode and animate:
        rospy.Timer(rospy.Duration(animation_interval_sec), animation_tick)
        rospy.loginfo(
            "motik_node: авто-анимация эмоций, интервал %.1f с", animation_interval_sec)

    if oscillogram_display and device is not None:
        if use_frequency_oscillogram:
            rospy.Subscriber(audio_raw_topic, UInt8MultiArray,
                             on_audio_raw, queue_size=5)
        else:
            rospy.Subscriber("/audio/level", Float32,
                             on_audio_level, queue_size=5)
    if oscillogram_display and oscillogram_frequency_hz > 0 and not _NUMPY_AVAILABLE:
        rospy.logwarn(
            "motik_node: для осциллограммы по частоте установите numpy (pip3 install numpy). Используется /audio/level.")

    if device is not None:
        def shutdown_display():
            try:
                if display_emotions_mode:
                    device.display(_draw_emotion("neutral"))
                else:
                    device.display(_draw_oscillogram_waveform(
                        [0.0] * W, center=True))
                time.sleep(0.15)
            except Exception:
                pass
        rospy.on_shutdown(shutdown_display)
        atexit.register(shutdown_display)

    rospy.loginfo(
        "motik node started, emotions topic: %s, emotions_display topic: %s, oscillogram_display topic: %s",
        emotions_pub.resolved_name,
        emotions_display_pub.resolved_name,
        oscillogram_display_pub.resolved_name,
    )
    rospy.spin()


if __name__ == "__main__":
    main()
