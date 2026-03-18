#!/bin/bash
# Проверка звука на роботе (Raspberry Pi / Linux).
# Запуск: ./check_audio.sh   или   bash check_audio.sh

echo "=== Устройства воспроизведения (aplay -l) ==="
aplay -l 2>/dev/null || echo "aplay не найден или нет устройств. Установите: sudo apt install alsa-utils"

echo ""
echo "=== Текущая громкость (amixer) ==="
amixer 2>/dev/null | head -20 || echo "amixer не найден"

echo ""
echo "=== Совет: включить звук ==="
echo "  1. Убедитесь, что динамик/наушники подключены к правильному выходу (jack или HDMI)."
echo "  2. Выберите устройство по умолчанию:"
echo "       sudo raspi-config → System Options → Audio → нужный выход"
echo "  3. Или вручную (пример для jack):"
echo "       amixer set Master 100%"
echo "       amixer set PCM 100%"
echo "  4. Для USB-звуковой карты: после подключения проверьте aplay -l и задайте устройство в ~/.asoundrc при необходимости."
echo "  5. Проверка: aplay /usr/share/sounds/alsa/Front_Center.wav"
echo ""
echo "  Если звука нет, проверьте:"
echo "    - в raspi-config, что аудио не отключено;"
echo "    - драйвер: lsmod | grep snd;"
echo "    - для Pi 4/5: в config.txt нет dtparam=audio=off."
echo ""
