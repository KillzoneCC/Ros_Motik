#!/bin/bash
# Подготовка окружения ROS: поиск и загрузка setup.bash
# Используется в start_app_node.service и oled_display.service
# Запуск: source_env.bash roslaunch ainex_bringup bringup.launch

# Поиск ROS (типичные пути)
for ros_setup in /opt/ros/noetic/setup.bash /opt/ros/melodic/setup.bash /opt/ros/foxy/setup.bash; do
    if [ -f "$ros_setup" ]; then
        . "$ros_setup"
        break
    fi
done

# Поиск workspace (devel или install)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for ws in /home/ubuntu/ros_ws /home/pi/ros_ws "$(dirname "$(dirname "$(dirname "$SCRIPT_DIR")")")"; do
    for setup in "$ws/devel/setup.bash" "$ws/install/setup.bash"; do
        if [ -f "$setup" ]; then
            . "$setup"
            break 2
        fi
    done
done

# Выполнить переданные аргументы (например roslaunch ...)
exec "$@"
