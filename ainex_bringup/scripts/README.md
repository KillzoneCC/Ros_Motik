# Скрипты дисплея и рта робота

**Инструкции:**
- [docs/ИНСТРУКЦИЯ_РОТ_И_ЗВУК.md](../docs/ИНСТРУКЦИЯ_РОТ_И_ЗВУК.md) — **полная пошаговая инструкция** для имитации разговора на втором дисплее при наличии звука
- [docs/ЗВУК_И_АНИМАЦИЯ_РОТА.md](../docs/ЗВУК_И_АНИМАЦИЯ_РОТА.md) — ROS-нода, топики, сервисы, интеграция

## Файлы

- **oled_display.py** — при включении: дисплей **0x3D** — рот (мод 7), **0x3C** — инфо (IP, батарея). Сервис `oled_display.service`.
- **robot_mouth_talk_node.py** — ROS-нода: рот с осцилограммой. **Аудио из топика/сервиса** (см. ниже).
- **robot_mouth.py** — тест мимики: мод 6 или 7. Запуск: `python3 robot_mouth.py` или `python3 robot_mouth.py 7`.
- **robot_mouth_talk.py** — звук + имитация речи (мод 7). Звук через файл (AUDIO_FILENAME, ROBOT_MOUTH_AUDIO).
- **oled_mouth_talk.py** — задержка 2 с, затем WAV и рот на OLED 0x3D.
- **oled_i2c_address_help.py** — имитация разговора без звука на 0x3D.
- **check_audio.sh** — проверка звука (aplay, amixer).

## robot_mouth_talk_node — топик и сервис для аудио

Нода всегда готова воспроизводить осцилограмму любого звука. Анимация рта не меняется — звук и путь к файлу берутся из ROS.

### Топики

| Топик | Тип | Описание |
|-------|-----|----------|
| `/oled_mouth/audio_path` | std_msgs/String | Публикуй путь к файлу или имя — нода воспроизведёт и покажет осцилограмму |
| `/oled_mouth/mode` | std_msgs/String | Режим: `idle` (статичный рот), `oscillogram` (по умолчанию) |

### Сервисы

| Сервис | Тип | Описание |
|--------|-----|----------|
| `/oled_mouth/play_audio` | ainex_interfaces/SetString | `data` = путь или имя файла — воспроизвести |

### Запуск

```bash
# Вариант 1: через launch (ROS должен быть запущен)
roslaunch ainex_bringup oled_mouth.launch

# Вариант 2: напрямую
rosrun ainex_bringup robot_mouth_talk_node.py
```

**Важно:** если работает `oled_display.service` (дисплей 0x3D), остановите его: `sudo systemctl stop oled_display.service`

### Примеры

```bash
# Воспроизвести файл через топик
rostopic pub /oled_mouth/audio_path std_msgs/String "data: 'running'" --once
rostopic pub /oled_mouth/audio_path std_msgs/String "data: '/home/ubuntu/ros_ws/src/ainex_bringup/voice/adam-dragon-us_3475244.mp3'" --once

# Воспроизвести через сервис
rosservice call /oled_mouth/play_audio "data: 'running'"

# Сменить режим на статичный рот
rostopic pub /oled_mouth/mode std_msgs/String "data: 'idle'" --once
```

Файлы ищутся в: `ainex_bringup/voice/`, `ainex_sdk/audio/`, `/home/pi/Music/`. Можно передавать имя без расширения (`running`, `warnning`) или полный путь.

## Звук через voice_play (SDK) + ROS

При запущенном `robot_mouth_talk_node` функция `voice_play.play()` из ainex_sdk автоматически использует сервис `/oled_mouth/play_audio` — звук и анимация рта запускаются одновременно через звуковую карту. Примеры: `voice_play.play('running', language='English')`, `voice_play.play('warnning', ...)`.

Если ROS не доступен — используется SoX (play -q). В Docker: `apt install sox`.

## Звук через SDK (Docker)

Положите **kurlyk.wav** (или **kurlyk.mp3**) в **ainex_sdk/audio/** — скрипт подхватит путь через `voice_play` и воспроизведёт через SoX. Или используйте **running.wav** из SDK. В Docker: `apt install sox`.

## Зависимости

```bash
pip3 install pygame luma.oled pillow
# для RMS по громкости: pip3 install numpy soundfile scipy
```
