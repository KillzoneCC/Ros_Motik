#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROS-нода: рот с осциллограммой. Аудио приходит из топика или сервиса.

Топики:
  /oled_mouth/audio_path (std_msgs/String) — путь к файлу или имя — воспроизвести и показать осцилограмму
  /oled_mouth/mode      (std_msgs/String) — режим: "idle" (статичный рот), "oscillogram" (по умолчанию при воспроизведении)
  /audio/mouth_open_level (std_msgs/Float32) — уровень открытия рта 0..1 от третьей ноды.
  /audio/playback_level (std_msgs/Float32) — публикуется нодой рта во время воспроизведения: уровень 0..1 из воспроизводимого файла (сигнал на карту); третья нода использует его вместо микрофона.

Сервисы:
  /oled_mouth/play_audio (ainex_interfaces/SetString) — data = путь или имя файла — воспроизвести

Вывод пикселей на дисплей 0x3D отключён в комментариях — дисплей использует motik (топик emotions).

Параметры:
  ~output_device (str) — ALSA-устройство для воспроизведения (Pygame + aplay). По умолчанию "default".
    Как узнать: aplay -l — список устройств воспроизведения; для вывода указывать, например, plughw:CARD,0.
    Ввод (микрофон): arecord -l; в цепочке нод test используется plughw:2,0 для захвата.

Осциллограмма для рта: во время воспроизведения — с аудиокарты (/audio/playback_level), когда не играет — с цепочки нод (/audio/mouth_open_level: динамик или микрофон). Третья нода приоритетно использует playback_level. Рисование пикселей (draw_mouth_mode7) не меняется.
"""
from __future__ import annotations

import atexit
import os
import subprocess
import sys
import threading
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "alsa")
try:
    import pygame
    pygame.init()
except Exception as e:
    print("Ошибка pygame:", e, file=sys.stderr)

import rospy
from std_msgs.msg import String, Float32
from ainex_interfaces.srv import SetString, SetStringResponse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "voice"))
MUSIC_DIR = "/home/pi/Music"

NORMAL_MOUTH_OPEN = 0.08
IMITATE_ONLY_DURATION_SEC = 10.0
W, H = 128, 64
FPS = 60
MOUTH_SMOOTH = 0.76
RMS_SCALE = 32.0
# Таймаут «свежести» уровня из /audio/mouth_open_level (сек); при превышении рисуем статичный рот
MOUTH_SYNC_TIMEOUT_SEC = 0.5
# Частота обновления рта (Гц) — должна совпадать с частотой публикации третьей ноды (/mouth_sync_hz или ~rate)
DEFAULT_MOUTH_UPDATE_HZ = 30.0

try:
    from luma.core.interface.serial import i2c
    from luma.oled.device import ssd1306
    from PIL import Image, ImageDraw
    LUMA_AVAILABLE = True
except ImportError:
    LUMA_AVAILABLE = False

try:
    import numpy as np
    import soundfile as sf
    from scipy import fft
    HAS_RMS = True
except ImportError:
    HAS_RMS = False


def _get_sdk_audio_dir():
    try:
        from ainex_sdk import voice_play
        return voice_play.get_audio_dir()
    except Exception:
        return None


def resolve_audio_path(path_or_name):
    s = (path_or_name or "").strip()
    if not s:
        return None
    p = os.path.expanduser(s)
    if os.path.isfile(p):
        return p
    if not os.path.isabs(p) and "/" not in s and "\\" not in s:
        for base in (VOICE_DIR, _get_sdk_audio_dir() or "", MUSIC_DIR):
            if not base:
                continue
            full = os.path.join(os.path.expanduser(base), s)
            if os.path.isfile(full):
                return full
            for ext in (".mp3", ".wav"):
                f2 = full if s.lower().endswith(ext) else full + ext
                if os.path.isfile(f2):
                    return f2
        try:
            from ainex_sdk import voice_play
            for lang in ("English", "Chinese"):
                vp_path = voice_play.get_path(s, lang)
                if os.path.isfile(vp_path):
                    return vp_path
        except Exception:
            pass
    return None


def _init_mixer(output_device=None):
    """Инициализация Pygame mixer. output_device задаётся через AUDIODEV до первого вызова."""
    if pygame.mixer.get_init():
        return True
    if output_device and output_device != "default":
        os.environ["AUDIODEV"] = output_device
    for channels, buf in [(2, 1024), (1, 512)]:
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=channels, buffer=buf)
            return True
        except pygame.error:
            pass
        time.sleep(0.3)
    try:
        pygame.mixer.init()
        return True
    except pygame.error:
        return False


def _play_via_alsa(path, output_device="default"):
    """Воспроизведение через aplay/mpv/ffplay. output_device — ALSA-устройство (например plughw:2,0)."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return None
    env = os.environ.copy()
    if output_device and output_device != "default":
        env["AUDIODEV"] = output_device
    try:
        if path.lower().endswith(".wav"):
            cmd = ["aplay", "-q"]
            if output_device and output_device != "default":
                cmd.extend(["-D", output_device])
            cmd.append(path)
            return subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env,
            )
        for cmd in (
            ["mpv", "--no-video", "--really-quiet", path],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path],
        ):
            try:
                return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
            except FileNotFoundError:
                continue
    except Exception:
        pass
    return None


def load_wav_for_rms(path):
    if not HAS_RMS or not path or not os.path.isfile(path):
        return None, 0, 0.0
    try:
        data, sr = sf.read(path)
        if data.ndim > 1:
            data = data.mean(axis=1)
        return data.astype("float32"), sr, len(data) / float(sr)
    except Exception:
        return None, 0, 0.0


def is_speech(chunk, sr):
    if len(chunk) == 0:
        return False
    zcr = np.mean(np.abs(np.diff(np.sign(chunk)))) / 2
    if zcr < 0.05:
        return False
    freqs = fft.fftfreq(len(chunk), 1 / sr)[: len(chunk) // 2]
    magnitude = np.abs(fft.fft(chunk))[: len(chunk) // 2]
    if np.sum(magnitude) == 0:
        return False
    centroid = np.sum(magnitude * freqs) / np.sum(magnitude)
    return 800 <= centroid <= 6000


def get_rms_from_samples(wav_samples, wav_sr, pos_ms, window_ms=40):
    """RMS громкости в окне для анимации рта. Используется сырой RMS, чтобы рот реагировал на любой звук (речь, музыка)."""
    if wav_samples is None or wav_sr <= 0:
        return 0.0
    center = int(pos_ms / 1000.0 * wav_sr)
    half = int(window_ms / 2000.0 * wav_sr)
    start = max(0, center - half)
    end = min(len(wav_samples), center + half)
    if end <= start:
        return 0.0
    chunk = wav_samples[start:end]
    rms = float(np.sqrt(np.mean(chunk ** 2)))
    # Раньше возвращали 0 при не-речи — рот не двигался на музыке. Теперь всегда сырой RMS.
    return rms


def draw_mouth_mode7(mouth_open):
    import random
    img = Image.new("1", (W, H), 0)
    draw = ImageDraw.Draw(img)
    cx, cy = 64, 42
    h = max(6, int(42 * mouth_open) if mouth_open > 0.02 else 0)
    for i in range(3):
        th = max(6, h + (random.randint(-9, 9) if mouth_open > 0.1 else 0))
        left, top = cx - 45 + i * 36, cy - th // 2
        draw.rectangle((left, top, left + 18, top + th), fill=255)
    return img


def draw_idle_mouth():
    img = Image.new("1", (W, H), 0)
    draw = ImageDraw.Draw(img)
    cx, cy = 64, 42
    bar_height, bar_width = 6, 18
    for i in range(3):
        left = cx - 45 + i * 36
        top = cy - bar_height // 2
        draw.rectangle((left, top, left + bar_width, top + bar_height), fill=255)
    return img


class RobotMouthTalkNode:
    def __init__(self):
        rospy.init_node("robot_mouth_talk_node", anonymous=False)
        self.device = None
        self.play_queue = []
        self.lock = threading.Lock()
        self.mode = rospy.get_param("~mode", "oscillogram")
        # Устройство вывода звука (ALSA). Как узнать: aplay -l — воспроизведение, arecord -l — ввод
        self._output_device = (rospy.get_param("~output_device", "default") or "default").strip()
        if self._output_device != "default":
            os.environ["AUDIODEV"] = self._output_device
        # Уровень от третьей ноды (/audio/mouth_open_level) — осциллограмма или микрофон
        self._mouth_sync_level = 0.0
        self._mouth_sync_time = 0.0
        self._mouth_sync_lock = threading.Lock()
        self._sync_timeout = float(rospy.get_param("~mouth_sync_timeout_sec", MOUTH_SYNC_TIMEOUT_SEC))
        # Частота обновления дисплея (Гц): ~rate или общий /mouth_sync_hz — должна совпадать с третьей нодой
        self._mouth_update_hz = float(rospy.get_param("~rate", rospy.get_param("/mouth_sync_hz", DEFAULT_MOUTH_UPDATE_HZ)))
        self._init_display()

        rospy.Subscriber("/oled_mouth/audio_path", String, self._cb_audio_path, queue_size=1)
        rospy.Subscriber("/oled_mouth/mode", String, self._cb_mode, queue_size=1)
        rospy.Subscriber("/audio/mouth_open_level", Float32, self._cb_mouth_open_level, queue_size=5)
        self._pub_playback_level = rospy.Publisher("/audio/playback_level", Float32, queue_size=5)
        self.srv = rospy.Service("/oled_mouth/play_audio", SetString, self._srv_play_audio)

        rospy.on_shutdown(self._shutdown_display)  # при остановке ноды — финальный кадр, экран не гаснет
        atexit.register(self._shutdown_display)   # дублируем на случай выхода без rospy (kill, исключение)
        rospy.loginfo("robot_mouth_talk_node: топик /oled_mouth/audio_path, /audio/mouth_open_level (sync), сервис /oled_mouth/play_audio, вывод звука: %s, обновление: %.1f Гц", self._output_device, self._mouth_update_hz)

    def _init_display(self):
        # Вывод на дисплей отключён — дисплей 0x3D использует motik (emotions). Нода работает без вывода пикселей.
        self.device = None
        # if not LUMA_AVAILABLE:
        #     rospy.logerr("Установите: pip3 install luma.oled pillow")
        #     raise RuntimeError("luma.oled not available")
        # try:
        #     serial = i2c(port=1, address=0x3D)
        #     self.device = ssd1306(serial, width=W, height=H)
        #     try:
        #         self.device.display(draw_idle_mouth())
        #     except Exception as e:
        #         rospy.logwarn("Первый кадр на дисплей: %s", e)
        # except Exception as e:
        #     rospy.logerr("Дисплей I2C 0x3D: %s", e)
        #     raise

    def _cb_audio_path(self, msg):
        path = (msg.data or "").strip()
        if path:
            with self.lock:
                self.play_queue.append(path)

    def _cb_mode(self, msg):
        m = (msg.data or "").strip().lower()
        if m in ("idle", "oscillogram"):
            self.mode = m

    def _cb_mouth_open_level(self, msg):
        """Уровень открытия рта от цепочки нод (третья нода): осциллограмма с динамика/микрофона."""
        val = max(0.0, min(1.0, float(msg.data)))
        with self._mouth_sync_lock:
            self._mouth_sync_level = val
            self._mouth_sync_time = time.time()
        rospy.loginfo_throttle(5.0, "robot_mouth_talk_node: получаем /audio/mouth_open_level (осциллограмма)")

    def _get_sync_mouth_level(self):
        """Возвращает (level, valid). valid=False если топик давно не обновлялся."""
        with self._mouth_sync_lock:
            level = self._mouth_sync_level
            t = self._mouth_sync_time
        return level, (time.time() - t) <= self._sync_timeout

    def _srv_play_audio(self, req):
        path = (req.data or "").strip()
        if path:
            with self.lock:
                self.play_queue.append(path)
        return SetStringResponse(success=True, message="queued" if path else "empty")

    def _display(self, img):
        # Вывод пикселей на дисплей отключён — дисплей для motik (emotions).
        if self.device is None:
            return
        # try:
        #     self.device.display(img)
        # except Exception as e:
        #     rospy.logdebug("display: %s", e)

    def _shutdown_display(self):
        """При остановке ноды рисуем финальный кадр — экран не гаснет и не уходит в случайное состояние."""
        if self.device is not None:
            try:
                self._display(draw_idle_mouth())
                time.sleep(0.15)  # даём I2C передаче завершиться до выхода процесса
                self._display(draw_idle_mouth())
            except Exception as e:
                rospy.logdebug("shutdown_display: %s", e)

    def _play_and_animate(self, audio_path):
        resolved = resolve_audio_path(audio_path)
        if not resolved:
            rospy.logwarn("Аудио не найдено: %s", audio_path)
            return
        wav_samples, wav_sr, duration_sec = load_wav_for_rms(resolved)

        play_proc = None
        audio_ok = False
        use_subprocess = False

        if _init_mixer(self._output_device):
            try:
                pygame.mixer.music.load(resolved)
                pygame.mixer.music.play()
                audio_ok = True
            except pygame.error as e:
                rospy.logwarn("pygame: %s", e)

        if not audio_ok:
            play_proc = _play_via_alsa(resolved, self._output_device)
            if play_proc and play_proc.poll() is None:
                use_subprocess, audio_ok = True, True

        if not audio_ok:
            rospy.logwarn("Звук не запущен. Имитация %s с.", IMITATE_ONLY_DURATION_SEC)

        mouth_open = 0.0
        start_time = time.time()
        duration_ms = int(duration_sec * 1000) if duration_sec > 0 else 0
        min_anim_sec = 0.3

        while rospy.is_shutdown() is False:
            elapsed = time.time() - start_time
            if use_subprocess and play_proc:
                elapsed_ms = int(elapsed * 1000)
                is_playing = play_proc.poll() is None and (duration_ms == 0 or elapsed_ms < duration_ms)
            else:
                is_playing = pygame.mixer.music.get_busy() if pygame.mixer.get_init() else False

            # Уровень рта: при воспроизведении публикуем уровень из файла (сигнал на карту), третья нода отдаёт его в mouth_open_level
            if is_playing and wav_samples is not None and wav_sr > 0:
                pos_ms = int(elapsed * 1000)
                level = min(1.0, get_rms_from_samples(wav_samples, wav_sr, pos_ms) * RMS_SCALE)
                self._pub_playback_level.publish(Float32(data=level))
            # Рот рисуем по уровню от третьей ноды (playback_level при воспроизведении, иначе осциллограмма)
            level, valid = self._get_sync_mouth_level()
            if valid:
                target = level
            else:
                target = NORMAL_MOUTH_OPEN if is_playing else 0.0
            target = max(0.0, min(1.0, target))

            mouth_open += (target - mouth_open) * (1.0 - MOUTH_SMOOTH)
            mouth_open = max(0.0, min(1.0, mouth_open))
            self._display(draw_mouth_mode7(mouth_open))
            time.sleep(1.0 / FPS)

            if use_subprocess and play_proc:
                if elapsed >= min_anim_sec and (play_proc.poll() is not None or (duration_ms > 0 and int(elapsed * 1000) >= duration_ms)):
                    break
            elif not is_playing and audio_ok and elapsed > max(1.0, min_anim_sec):
                break
            elif not audio_ok and elapsed >= IMITATE_ONLY_DURATION_SEC:
                break

        if use_subprocess and play_proc and play_proc.poll() is None:
            play_proc.terminate()
        if pygame.mixer.get_init() and audio_ok and not use_subprocess:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass

    def run(self):
        self._display(draw_idle_mouth())
        # В rospy нет spin_once(); колбэки обрабатываем в отдельном потоке
        spin_thread = threading.Thread(target=rospy.spin, daemon=True)
        spin_thread.start()
        rate = rospy.Rate(self._mouth_update_hz)
        while not rospy.is_shutdown():
            path = None
            with self.lock:
                if self.play_queue:
                    path = self.play_queue.pop(0)
            if path:
                self._play_and_animate(path)
                self._display(draw_idle_mouth())
            else:
                if self.mode == "idle":
                    self._display(draw_idle_mouth())
                else:
                    # Режим oscillogram: рот по уровню от третьей ноды (осциллограмма с динамика/микрофона)
                    level, valid = self._get_sync_mouth_level()
                    if valid:
                        self._display(draw_mouth_mode7(level))
                    else:
                        rospy.loginfo_throttle(5.0, "robot_mouth_talk_node: нет данных с /audio/mouth_open_level — запустите сначала три ноды (roslaunch test audio_oscillogram_full.launch)")
                        self._display(draw_mouth_mode7(NORMAL_MOUTH_OPEN))
            rate.sleep()


def main():
    try:
        node = RobotMouthTalkNode()
        node.run()
    except rospy.ROSInterruptException:
        pass
    except Exception as e:
        rospy.logerr("robot_mouth_talk_node: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
