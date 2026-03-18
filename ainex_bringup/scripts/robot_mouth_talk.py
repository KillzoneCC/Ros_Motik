# -*- coding: utf-8 -*-
"""Звук + имитация речи ртом (мод 7). Пока играет звук — рот имитирует речь; по окончании — стандартный рот."""
import math
import os
import subprocess
import sys
import time

# -----------------------------------------------------------------------------
# Звуковой файл: укажите имя ниже. Скрипт ищет его (по порядку):
#  1) Папка voice в пакете ainex_bringup (ainex_bringup/voice/)  ← основная папка
#  2) Папка SDK: ainex_sdk/audio/
#  3) Папка на роботе: /home/pi/Music/
# Или задайте полный путь в ROBOT_MOUTH_AUDIO.
# -----------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VOICE_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, "..", "voice"))
# Имя файла (положите его в папку voice/):
AUDIO_FILENAME = "adam-dragon-us_3475244.mp3"
# Папки для поиска (робот Pi или Ubuntu)
MUSIC_DIRS = ["/home/pi/Music", "/home/ubuntu/Music"]

# Стандартный рот без действий после окончания звука (как в sound_and_mouth_talk)
NORMAL_MOUTH_OPEN = 0.08
# Если звук не удалось запустить — имитация рта столько секунд, затем стандартный рот
IMITATE_ONLY_DURATION_SEC = 10.0

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "alsa")
try:
    import pygame
    pygame.init()
except Exception as e:
    print("Ошибка pygame:", e, file=sys.stderr)

def _get_sdk_audio_dir():
    """Путь к папке audio в ainex_sdk (ainex_driver/ainex_sdk/audio/)."""
    try:
        from ainex_sdk import voice_play
        return voice_play.get_audio_dir()
    except Exception:
        return None


def _resolve_audio_path():
    # 1) Явный путь из переменной окружения
    env_path = os.environ.get("ROBOT_MOUTH_AUDIO", "").strip()
    if env_path:
        p = os.path.expanduser(env_path)
        if os.path.isfile(p):
            return p
    # 2) Папка voice в ainex_bringup (ainex_bringup/voice/AUDIO_FILENAME)
    path_from_voice = os.path.join(VOICE_DIR, AUDIO_FILENAME)
    if os.path.isfile(path_from_voice):
        return path_from_voice
    # 3) Файл в папке SDK: ainex_sdk/audio/AUDIO_FILENAME
    sdk_dir = _get_sdk_audio_dir()
    if sdk_dir:
        path_in_sdk = os.path.join(sdk_dir, AUDIO_FILENAME)
        if os.path.isfile(path_in_sdk):
            return path_in_sdk
    # 4) Файл в /home/pi/Music или /home/ubuntu/Music
    for music_dir in MUSIC_DIRS:
        path_from_music = os.path.join(os.path.expanduser(music_dir), AUDIO_FILENAME)
        if os.path.isfile(path_from_music):
            return path_from_music
    # Не найден — для сообщения об ошибке
    if sdk_dir:
        return os.path.join(sdk_dir, AUDIO_FILENAME)
    return path_from_voice

def _init_mixer():
    if pygame.mixer.get_init():
        return True
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
    except pygame.error as e:
        print("Ошибка звука:", e, file=sys.stderr)
        return False


def _play_via_alsa(path):
    """Запасное воспроизведение без Pulse: aplay (WAV) или mpv/ffplay (MP3)."""
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        return None
    try:
        if path.lower().endswith(".wav"):
            return subprocess.Popen(
                ["aplay", "-q", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        for cmd in (["mpv", "--no-video", "--really-quiet", path], ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]):
            try:
                return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                continue
    except Exception:
        pass
    return None

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
    HAS_RMS = True
except ImportError:
    HAS_RMS = False

W, H = 128, 64
FPS = 60
MOUTH_SMOOTH = 0.76
RMS_SCALE = 32.0
AUDIO_PATH = _resolve_audio_path()

wav_samples = None
wav_sr = 44100
duration_sec = 0.0


def _load_audio_for_rms(path):
    """Загрузка аудио для RMS. WAV — soundfile. MP3 — pydub (если установлен) или soundfile."""
    if not HAS_RMS or not path or not os.path.isfile(path):
        return None, 44100, 0.0
    ext = path.lower().split(".")[-1] if "." in path else ""
    # MP3: soundfile/libsndfile обычно не поддерживает. Пробуем pydub.
    if ext == "mp3":
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_mp3(path)
            samples = np.array(audio.get_array_of_samples(), dtype=np.float32) / 32768.0
            if audio.channels > 1:
                samples = samples.reshape(-1, audio.channels).mean(axis=1)
            return samples, audio.frame_rate, len(samples) / float(audio.frame_rate)
        except Exception:
            pass
    try:
        data, sr = sf.read(path)
        if data.ndim > 1:
            data = data.mean(axis=1)
        return data.astype(np.float32), sr, len(data) / float(sr)
    except Exception:
        return None, 44100, 0.0


if os.path.isfile(AUDIO_PATH):
    wav_samples, wav_sr, duration_sec = _load_audio_for_rms(AUDIO_PATH)

def get_rms(pos_ms, window_ms=40):
    """RMS громкости в окне. Рот реагирует на любой звук (речь, музыка)."""
    if wav_samples is None or wav_sr <= 0:
        return 0.0
    center = int(pos_ms / 1000.0 * wav_sr)
    half = int(window_ms / 2000.0 * wav_sr)
    start = max(0, center - half)
    end = min(len(wav_samples), center + half)
    if end <= start:
        return 0.0
    chunk = wav_samples[start:end]
    return float(np.sqrt(np.mean(chunk ** 2)))

def draw_mouth_mode7(mouth_open):
    import random
    img = Image.new("1", (W, H), 0)
    draw = ImageDraw.Draw(img)
    cx, cy = 64, 42
    # Рот увеличен в 3 раза
    h = max(6, int(42 * mouth_open) if mouth_open > 0.02 else 0)
    for i in range(3):
        th = max(6, h + (random.randint(-9, 9) if mouth_open > 0.1 else 0))
        left, top = cx - 45 + i * 36, cy - th // 2
        draw.rectangle((left, top, left + 18, top + th), fill=255)
    return img


def _draw_oled_display_mouth(device):
    """Рот как в oled_display.draw_mouth_update() — стандартный рот робота (три полоски, увеличены в 3 раза)."""
    img = Image.new("1", (W, H), 0)
    draw = ImageDraw.Draw(img)
    cx, cy = 64, 42
    bar_height, bar_width = 6, 18
    for i in range(3):
        left = cx - 45 + i * 36
        top = cy - bar_height // 2
        draw.rectangle((left, top, left + bar_width, top + bar_height), fill=255)
    device.display(img)


def _draw_default_mouth(device):
    """Рот по умолчанию, как в sound_and_mouth_talk: draw_mouth_frame(NORMAL_MOUTH_OPENNESS) — обычный рот без действий."""
    device.display(draw_mouth_mode7(NORMAL_MOUTH_OPEN))


def run():
    if not LUMA_AVAILABLE:
        print("Установите: pip3 install luma.oled pillow")
        sys.exit(1)
    if not os.path.isfile(AUDIO_PATH):
        print("Файл не найден:", AUDIO_PATH)
        print("Положите", AUDIO_FILENAME, "в папку voice:", VOICE_DIR)
        sdk_dir = _get_sdk_audio_dir()
        if sdk_dir:
            print("Или в папку SDK:", sdk_dir)
        print("Или в", ", ".join(os.path.join(d, AUDIO_FILENAME) for d in MUSIC_DIRS))
        print("Или задайте ROBOT_MOUTH_AUDIO=/полный/путь/к/файлу.mp3")
        sys.exit(1)
    try:
        serial = i2c(port=1, address=0x3D)
        device = ssd1306(serial, width=W, height=H)
    except Exception as e:
        print("Дисплей I2C 0x3D:", e)
        sys.exit(1)

    # При запуске сразу показываем рот по умолчанию (как в sound_and_mouth_talk)
    _draw_default_mouth(device)
    time.sleep(0.5)

    try:
        _run_playback_and_hold_mouth(device)
    except KeyboardInterrupt:
        pass
    finally:
        # Как в sound_and_mouth_talk: после завершения (нормального или Ctrl+C) выводим рот по умолчанию — не очищаем экран, остаётся обычный рот
        try:
            _draw_default_mouth(device)
            time.sleep(0.1)
            _draw_default_mouth(device)
        except Exception:
            pass


def _run_playback_and_hold_mouth(device):
    """Воспроизведение, имитация рта, затем удержание рта до Ctrl+C."""
    play_proc = None
    audio_ok = False
    use_sdk_play = False
    # 1) Пробуем pygame
    if _init_mixer():
        try:
            pygame.mixer.music.load(AUDIO_PATH)
            pygame.mixer.music.play()
            audio_ok = True
        except pygame.error as e:
            print("Ошибка воспроизведения (pygame):", e, file=sys.stderr)

    # 2) Запас: aplay (WAV) или mpv/ffplay (MP3) — без Pulse
    if not audio_ok:
        play_proc = _play_via_alsa(AUDIO_PATH)
        if play_proc is not None:
            time.sleep(0.2)
            if play_proc.poll() is None:
                use_sdk_play, audio_ok = True, True
            else:
                play_proc = None

    if not audio_ok:
        print("Звук не запущен (Pulse/ALSA). Рот будет имитировать речь {:.0f} с.".format(IMITATE_ONLY_DURATION_SEC), file=sys.stderr)

    mouth_open = 0.0
    start_time = time.time()
    duration_ms = int(duration_sec * 1000) if duration_sec > 0 else 0
    min_anim_sec = 0.3  # минимум времени анимации, чтобы рот успел появиться

    while True:
        elapsed = time.time() - start_time
        if use_sdk_play and play_proc is not None:
            elapsed_ms = int(elapsed * 1000)
            is_playing = play_proc.poll() is None and (duration_ms == 0 or elapsed_ms < duration_ms)
            pos_ms = elapsed_ms
        else:
            pos_ms = pygame.mixer.music.get_pos() if pygame.mixer.get_init() else 0
            pos_ms = max(0, pos_ms)
            is_playing = pygame.mixer.music.get_busy() if pygame.mixer.get_init() else False

        # Имитация разговора: открытие/закрытие рта по громкости или синусоиде
        if is_playing:
            if HAS_RMS and wav_samples is not None:
                target = min(1.0, get_rms(pos_ms) * RMS_SCALE)
            else:
                target = max(0, min(1, 0.3 + 0.5 * (0.5 + 0.5 * math.sin(pos_ms / 1000.0 * 15))))
        else:
            target = (0.3 + 0.5 * (0.5 + 0.5 * math.sin(elapsed * 8))) if not audio_ok else 0.0
            target = max(0.0, min(1.0, target))

        mouth_open += (target - mouth_open) * (1.0 - MOUTH_SMOOTH)
        mouth_open = max(0.0, min(1.0, mouth_open))
        device.display(draw_mouth_mode7(mouth_open))
        time.sleep(1.0 / FPS)

        if use_sdk_play and play_proc is not None:
            if elapsed >= min_anim_sec and (play_proc.poll() is not None or (duration_ms > 0 and int(elapsed * 1000) >= duration_ms)):
                break
        elif not is_playing and audio_ok and elapsed > max(1.0, min_anim_sec):
            break
        elif not audio_ok and elapsed >= IMITATE_ONLY_DURATION_SEC:
            break

    # Звук закончился — останавливаем воспроизведение, выводим рот по умолчанию (как в sound_and_mouth_talk) и держим до Ctrl+C
    if use_sdk_play and play_proc is not None and play_proc.poll() is None:
        play_proc.terminate()
    if pygame.mixer.get_init() and audio_ok and not use_sdk_play:
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

    _draw_default_mouth(device)
    print("Воспроизведение завершено. Рот остаётся на экране. Завершите скрипт (Ctrl+C) для выхода.")

    try:
        while True:
            time.sleep(2)
            _draw_default_mouth(device)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    print("Звук:", AUDIO_PATH)
    print("Мод 7, дисплей 0x3D")
    run()
