#!/bin/bash
# Проверка, что robot_mouth_talk_node и звук+анимация настроены правильно.
# Запуск: ./check_oled_mouth.sh  (после source devel/setup.bash)

echo "=== Проверка звука и анимации рта ==="
echo ""

# 1. ROS
if ! command -v roscore &>/dev/null; then
    echo "[!] ROS не найден. Выполните: source /opt/ros/noetic/setup.bash"
    exit 1
fi

# 2. ROS master
if ! rostopic list &>/dev/null; then
    echo "[!] ROS master не запущен. Запустите bringup или: roscore"
    echo "    roslaunch ainex_bringup bringup.launch"
    exit 1
fi

# 3. Сервис
if rosservice list 2>/dev/null | grep -q "/oled_mouth/play_audio"; then
    echo "[OK] Сервис /oled_mouth/play_audio доступен"
else
    echo "[!] Сервис /oled_mouth/play_audio НЕ найден"
    echo "    Нода robot_mouth_talk_node не запущена."
    echo "    Проверьте: rosnode list | grep robot_mouth"
    echo "    Запустите: roslaunch ainex_bringup bringup.launch"
    echo "    И остановите oled_display: sudo systemctl stop oled_display.service"
    exit 1
fi

# 4. oled_display
if systemctl is-active --quiet oled_display.service 2>/dev/null; then
    echo "[!] oled_display.service запущен — конфликт с robot_mouth_talk_node!"
    echo "    Остановите: sudo systemctl stop oled_display.service"
else
    echo "[OK] oled_display.service не запущен (нужно для robot_mouth_talk_node)"
fi

echo ""
echo "Тест: rosservice call /oled_mouth/play_audio \"data: 'running'\""
echo "Должны: звук из динамиков + анимация рта на OLED"
echo ""
