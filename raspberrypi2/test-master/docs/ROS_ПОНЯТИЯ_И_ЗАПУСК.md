# Понятия ROS и запуск (пакет test)

## Цепочка нод осциллограммы и анимации рта

| Нода | Топик подписки | Топик публикации |
|------|----------------|------------------|
| 1. audio_oscillogram_capture_node | — | `/audio/oscillogram_level` |
| 2. oscillogram_plot_node | `/audio/oscillogram_level` | `/audio/oscillogram_level_for_mouth` |
| 3. mouth_oscillogram_sync_node | `/audio/oscillogram_level_for_mouth` | `/audio/mouth_open_level` |

Анимация рта: нода `robot_mouth_talk_node` (пакет **ainex_bringup**) подписана на `/audio/mouth_open_level`.

## Запуск по порядку

**Вариант 1 — все три ноды одной командой** (по умолчанию: осциллограмма с того, что играет в системе — PulseAudio монитор, подходит для робота без микрофона):
```bash
cd /home/ubuntu/ros_ws
source /opt/ros/noetic/setup.zsh
source devel/setup.zsh
roslaunch test audio_oscillogram_full.launch
```
С микрофона (ALSA): `roslaunch test audio_oscillogram_full.launch source:=alsa`

**USB-микрофон (конкретика):** осциллограмма считывается первой нодой через ALSA (`arecord`). Устройство задаётся как `plughw:КАРТА,0`.

1. Найти устройство: `arecord -l` — в списке CAPTURE: `card 2` → **plughw:2,0**, `card 3` (Redragon и т.п.) → **plughw:3,0**.
2. Запуск цепочки с USB-микрофона (по умолчанию используется **карта 3** — plughw:3,0):
   ```bash
   roslaunch test audio_oscillogram_full_usb_mic.launch
   ```
   Если микрофон на карте 2: `roslaunch test audio_oscillogram_full_usb_mic.launch device:=plughw:2,0`
3. Дальше без изменений: вторая нода строит осциллограмму и публикует уровень в `/audio/oscillogram_level_for_mouth`, третья нода сглаживает и публикует `/audio/mouth_open_level`, нода рта рисует анимацию по этому топику. Говорите в микрофон — рот двигается в такт.

**Вариант 2 — по одной в разных терминалах:**  
1) `roslaunch test audio_oscillogram_capture.launch`  
2) `roslaunch test oscillogram_plot.launch`  
3) `roslaunch test mouth_oscillogram_sync.launch`

**Анимация рта (отдельный терминал):**
```bash
source /opt/ros/noetic/setup.zsh
source devel/setup.zsh
roslaunch ainex_bringup oled_mouth.launch
```

## Сборка пакета test

```bash
cd /home/ubuntu/ros_ws
source /opt/ros/noetic/setup.zsh
source devel/setup.zsh
catkin build test
source devel/setup.zsh
```

**Робот без отдельного микрофона (только динамик):** по умолчанию первая нода берёт уровень с **монитора вывода PulseAudio** — то, что реально играет в колонки (VLC, браузер, любое приложение в VNC). Чтобы рот синхронизировался со звуком из VNC: (1) запустите PulseAudio (`pulseaudio --start` или через систему), (2) воспроизводите звук через приложения, которые выводят в Pulse (обычно по умолчанию), (3) запустите `roslaunch test audio_oscillogram_full.launch` и ноду рта. Тогда осциллограмма рисуется с потока вывода, третья нода читает её и подстраивает анимацию рта под звук в реальном времени.

Если анимация рта не реагирует на звук: убедитесь, что запущена **третья нода** и нода анимации рта (oled_mouth.launch). При воспроизведении из VNC — что PulseAudio запущен и звук идёт через него (не напрямую в ALSA).

### Устройство вывода звука (воспроизведение)

Нода рта (`robot_mouth_talk_node`) воспроизводит файлы через Pygame и aplay. Чтобы звук шёл на нужную аудиокарту, укажите параметр **output_device**:

```bash
roslaunch ainex_bringup oled_mouth.launch output_device:=plughw:2,0
```

**Как узнать устройство:** `aplay -l` — воспроизведение, `arecord -l` — ввод (микрофон).

### Калибровка частоты (Гц) — третья нода и нода рта

Частота публикации **третьей ноды** и частота обновления **ноды анимации рта** должны совпадать, иначе анимация может не успевать за звуком или дёргаться.

- **Общий параметр:** `/mouth_sync_hz` (по умолчанию 30 Гц). Задаётся в launch-файлах.
- **Третья нода** (test): публикует `/audio/mouth_open_level` с частотой `~rate` или `/mouth_sync_hz`.
- **Нода рта** (ainex_bringup): обновляет дисплей с частотой `~rate` или `/mouth_sync_hz`.

Оба launch-файла уже выставляют одну и ту же частоту (30 Гц). Если меняете частоту — меняйте в обоих местах одинаково:

```bash
# Пример: 30 Гц (по умолчанию)
roslaunch test audio_oscillogram_full.launch
roslaunch ainex_bringup oled_mouth.launch

# Если задаёте свою частоту для ноды рта (тогда и в test/launch/mouth_oscillogram_sync.launch поставьте тот же rate):
roslaunch ainex_bringup oled_mouth.launch mouth_sync_hz:=30
```

---

## Проверка работы того, что мы сделали

Пошаговый чек-лист, чтобы убедиться, что цепочка осциллограммы и анимация рта работают.

### Подготовка (один раз)

```bash
cd /home/ubuntu/ros_ws
source /opt/ros/noetic/setup.zsh && source devel/setup.zsh
```

На роботе **без микрофона** (звук из VNC/VLC): убедитесь, что PulseAudio запущен:
```bash
pulseaudio --start
# или проверка: pactl info
```

---

### 1. Проверка дисплея и анимации (без цепочки)

**Цель:** дисплей включается, рот рисуется, при необходимости — двигается по тестовой синусоиде.

```bash
roslaunch test mouth_animation_test.launch
```

**Ожидаемо:** на OLED статичный рот или плавное открытие/закрытие по синусоиде (тестовый публикатор уровня). Остановка: Ctrl+C. После выхода экран не гаснет (остаётся кадр рта).

**Если экран не светится:** проверьте I2C дисплей (адрес 0x3D), что другой сервис не занял устройство.

---

### 2. Полная цепочка + нода рта

**Терминал 1 — цепочка осциллограммы (по умолчанию: с вывода PulseAudio):**
```bash
roslaunch test audio_oscillogram_full.launch
```

**Терминал 2 — нода рта и дисплея:**
```bash
roslaunch ainex_bringup oled_mouth.launch
```

**Ожидаемо:** в логах первой ноды — «топик /audio/oscillogram_level (источник: PulseAudio монитор…)» или «устройство ALSA …» при `source:=alsa`. Нода рта пишет «топик /oled_mouth/audio_path, /audio/mouth_open_level (sync)…».

---

### 3. Проверка топиков (третий терминал)

```bash
# Список топиков (должны быть аудио-топики)
rostopic list | grep audio

# Частота /audio/mouth_open_level (ожидаемо ~30 Гц)
rostopic hz /audio/mouth_open_level

# Текущие значения уровня (для рта 0..1)
rostopic echo /audio/mouth_open_level
```

**Ожидаемо:** `rostopic hz /audio/mouth_open_level` показывает около 30 Hz. При тишине `data` близко к 0, при звуке — увеличивается.

---

### 4. Проверка реакции на звук

**Вариант A — звук из VNC (VLC, браузер, любой плеер):**  
Воспроизведите любой файл/стрим на роботе. Звук должен идти через **PulseAudio** (стандартный вывод). Рот на дисплее должен открываться/закрываться в такт громкости.

**Вариант B — воспроизведение через ноду рта (уровень с карты, без микрофона):**
```bash
rosservice call /oled_mouth/play_audio "data: '/usr/share/sounds/alsa/Front_Center.wav'"
```
Рот должен двигаться в такт этому файлу (уровень берётся из воспроизводимого потока).

**Вариант C — микрофон (если есть):** запуск с `source:=alsa`, говорить в микрофон — рот в такт.

---

### 5. Краткая сводка: что проверяем

| Что проверяем | Как | Ожидаемый результат |
|---------------|-----|---------------------|
| Дисплей и нода рта | `roslaunch test mouth_animation_test.launch` | Рот на экране, после Ctrl+C экран не гаснет |
| Цепочка из трёх нод | `roslaunch test audio_oscillogram_full.launch` | Ноды стартуют, в логе первой ноды — источник (pulse_monitor или ALSA) |
| Уровень для рта | `rostopic hz /audio/mouth_open_level` | ~30 Гц |
| Синхрон с звуком из VNC | Включить плеер в VNC | Рот двигается в такт (при PulseAudio) |
| Синхрон при play_audio | `rosservice call /oled_mouth/play_audio "data: '...'"` | Рот в такт файлу |

---

### Если что-то не работает

- **Рот не двигается при звуке из VNC:** PulseAudio запущен? Звук идёт через него? Запуск с `source:=pulse_monitor` (по умолчанию в full.launch). Если нет parec: `sudo apt install pulseaudio-utils`, `pulseaudio --start`.
- **Рот не двигается вообще:** цепочка запущена раньше ноды рта? Проверьте `rostopic echo /audio/mouth_open_level` — при работающей цепочке значения меняются.
- **Рот дёргается или «тихо»:** подстройте `mouth_scale` в `oscillogram_plot.launch` и/или `scale` в `mouth_oscillogram_sync.launch` (больше = сильнее открытие).

---

## Проверка работоспособности (подробно)

### Проверка только анимации рта (дисплей)

Чтобы убедиться, что дисплей и нода анимации рта вообще работают (без цепочки осциллограммы), запустите:

```bash
roslaunch test mouth_animation_test.launch
```

Запускается та же нода `robot_mouth_talk_node` из пакета **ainex_bringup** (внутри подключается `oled_mouth.launch`). На дисплее должен появиться статичный рот; без трёх нод топик `/audio/mouth_open_level` пуст, поэтому рот не будет реагировать на звук, но сам экран и нода проверяются. С выводом звука на карту: `roslaunch test mouth_animation_test.launch output_device:=plughw:2,0`.

### Шаг 1 — Цепочка осциллограммы (первый терминал)

```bash
cd /home/ubuntu/ros_ws
source /opt/ros/noetic/setup.zsh && source devel/setup.zsh
roslaunch test audio_oscillogram_full.launch
```

### Шаг 2 — Нода рта и дисплея (второй терминал)

```bash
cd /home/ubuntu/ros_ws
source /opt/ros/noetic/setup.zsh && source devel/setup.zsh
roslaunch ainex_bringup oled_mouth.launch
```

### Шаг 3 — Проверка топиков (третий терминал)

```bash
rostopic echo /audio/mouth_open_level
```

### Шаг 4 — Проверка реакции

Говорите в микрофон — рот на дисплее должен двигаться в такт.

### Остановка

Ctrl+C в каждом терминале. При остановке ноды рта на дисплей выводится финальный кадр (статичный рот), экран не гаснет и не перезагружается.

### Если анимация не реагирует на звук

1. **Запускайте цепочку из трёх нод раньше ноды рта** — сначала `roslaunch test audio_oscillogram_full.launch`, затем `roslaunch ainex_bringup oled_mouth.launch`. Иначе топик `/audio/mouth_open_level` пустой.
2. В логе ноды рта раз в 5 сек должно появляться: «получаем /audio/mouth_open_level» — значит данные доходят.
3. Проверьте: `rostopic hz /audio/mouth_open_level` — должно быть около 30 Гц при работающих трёх нодах.

**Робот без микрофона (только динамик):** по умолчанию `audio_oscillogram_full.launch` использует **PulseAudio монитор** (`source:=pulse_monitor`) — осциллограмма строится по тому, что **реально играет** в системе (VLC, браузер, любое приложение в VNC). Рот синхронизируется со звуком из любого плеера. Если есть отдельный микрофон — запускайте с `source:=alsa` и при необходимости укажите `device:=plughw:X,0`.

**Звук из VLC/плеера:** при `source:=pulse_monitor` цепочка берёт уровень с **монитора вывода** (то, что идёт в колонки). При `source:=alsa` — с микрофона (нужна достаточная громкость рядом). Для анимации строго по файлу через ноду рта: `rosservice call /oled_mouth/play_audio "data: '/путь/к/файлу.mp3'"`.
