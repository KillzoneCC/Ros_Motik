#!/usr/bin/env python3
# oled_display.py — дисплеи 0x3C (инфо), 0x3D (рот в моде 7).
# Вывод «эмоции по умолчанию» (рот) на дисплей 0x3D отключён в комментариях — дисплей отдаётся motik (топик emotions).
import os
import re
import sys
import time
import psutil
import subprocess
import numpy as np
import Adafruit_SSD1306
from ainex_sdk import voice_play
from PIL import Image, ImageDraw, ImageFont
from ros_robot_controller.ros_robot_controller_sdk import Board

I2C_BUS = 1

def get_pi_model():
    model_path = '/proc/device-tree/model'
    try:
        with open(model_path, 'r') as f:
            model = f.read().strip('\x00').strip()
        model = model.split(' ')[1:3]
        model = f'{model[0]}{model[1]}'
        return model
    except Exception:
        return 'Unknown Pi Model'

def get_total_mem_kb():
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    return int(line.split()[1])
    except Exception as e:
        print(f"Error reading /proc/meminfo: {e}", file=sys.stderr)
    return None

def guess_pi_ram_version():
    total_kb = get_total_mem_kb()
    if total_kb is None:
        return "Unknown"
    total_mb = total_kb // 1024
    if total_mb < 3000:
        return "2G"
    elif total_mb < 6000:
        return "4G"
    elif total_mb < 12000:
        return "8G"
    return "16G"

def split_to_dict(info):
    info_dict = {}
    for i in info:
        if ',' in i:
            j = i.split(',')
            info_dict.update(split_to_dict(j))
        else:
            j = i.split(' ')
            if len(j) >= 2:
                info_dict[j[0]] = ''.join(j[1:])
    return info_dict

def dev_info(ifname):
    info = subprocess.check_output("iw dev {} info".format(ifname), shell=True)
    info = str(info, encoding='utf8').replace('\t', '').replace(':', '').replace(', ', ',').split('\n')
    return split_to_dict(info)

def dev_link(ifname):
    link = subprocess.check_output("iw dev {} link".format(ifname), shell=True)
    link = str(link, encoding='utf8').replace('\t', '').replace(':', '').replace(', ', ',').split('\n')
    return split_to_dict(link)

def dev_state(ifname):
    state = {'mode': 'None', 'ssid': 'None'}
    info = dev_info(ifname)
    mode = 'STA' if info.get('type') != 'AP' else 'AP'
    if mode == 'AP':
        if 'ssid' in info:
            state['ssid'], state['mode'] = info['ssid'], 'AP'
    else:
        link = dev_link(ifname)
        if 'SSID' in link:
            state['ssid'], state['mode'] = link['SSID'], 'STA'
    return state

def i2c_scan(bus_num=1):
    try:
        out = subprocess.check_output(['i2cdetect', '-y', str(bus_num)], stderr=subprocess.DEVNULL, timeout=5).decode('utf-8')
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return []
    found = []
    for line in out.splitlines()[1:]:
        tokens = line.split()
        if not tokens:
            continue
        try:
            row = int(tokens[0].rstrip(':'), 16)
        except ValueError:
            continue
        for col_idx, p in enumerate(tokens[1:17]):
            if p not in ('--', 'UU'):
                try:
                    found.append(row + col_idx)
                except (ValueError, TypeError):
                    pass
    return found


class OledDisplayNode:
    def __init__(self):
        time.sleep(5)
        self.voltage = 0.0
        self.version = ''
        self.board = Board()
        self.language = os.environ.get('speaker_language', 'English')
        self.robotrc_path = os.path.join('/home/ubuntu/ros_ws', '.robotrc')
        _blank = Image.fromarray(np.zeros((64, 128), dtype=np.uint8)).convert('1')
        self.screen = None
        self.screen_info = None
        # Не используем дисплей 0x3D (рот/эмоция по умолчанию) — вывод пикселей отключён, дисплей для motik (emotions).
        # try:
        #     self.screen = Adafruit_SSD1306.SSD1306_128_64(rst=None, i2c_bus=I2C_BUS, gpio=1, i2c_address=0x3D)
        #     self.screen.begin()
        #     self.screen.image(_blank)
        #     self.screen.display()
        # except Exception:
        #     pass
        try:
            self.screen_info = Adafruit_SSD1306.SSD1306_128_64(rst=None, i2c_bus=I2C_BUS, gpio=1, i2c_address=0x3C)
            self.screen_info.begin()
            self.screen_info.image(_blank)
            self.screen_info.display()
        except Exception:
            pass
        if self.screen is None and self.screen_info is None:
            raise RuntimeError('oled_display: no OLED found on I2C bus %s' % I2C_BUS)
        self.font = ImageFont.load_default()
        self.gram = None
        self.mouth_gram = None
        self.wifi_iface = 'wlan0'
        self.model = '{} {}'.format(get_pi_model(), guess_pi_ram_version())
        while True:
            # Вывод пикселей рта/эмоции на дисплей отключён — дисплей использует motik (emotions).
            # self.draw_mouth_update()
            # try:
            #     self.screen.image(Image.fromarray(self.mouth_gram).convert('1'))
            #     self.screen.display()
            # except Exception:
            #     pass
            if self.screen_info is not None:
                self.sys_states_update()
                try:
                    self.screen_info.image(Image.fromarray(self.gram).convert('1'))
                    self.screen_info.display()
                except Exception:
                    pass
            time.sleep(5)

    def get_version(self):
        try:
            with open(self.robotrc_path, 'r') as f:
                data = f.read()
            self.version = re.findall(r'VERSION.*?\n', data)[0].split('=')[1].replace('\n', '')[1:-1].split('|')[1]
        except Exception:
            self.version = ''

    def voltage_update(self):
        res = os.popen('ps aux | grep ros_robot_controller | grep -v grep | awk \'{print $2}\'').read()
        ros = os.popen('ps aux | grep rosmaster | grep -v grep | awk \'{print $2}\'').read()
        if res and ros:
            try:
                self.voltage = float(os.popen('cat /home/ubuntu/ros_ws/src/ainex_driver/ros_robot_controller/scripts/battery.txt').read()) / 1000.0
            except Exception:
                pass
        else:
            self.board.enable_reception()
            while True:
                voltage = self.board.get_battery()
                if voltage is not None:
                    self.voltage = voltage / 1000.0
                    self.board.enable_reception(False)
                    break
        if self.voltage is not None and self.voltage < 10:
            try:
                self.board.set_buzzer(1900, 0.6, 0.4, 5)
                voice_play.play('warnning', language=self.language)
            except Exception:
                pass

    def sys_states_update(self):
        # Размер берём с того дисплея, что есть (screen или screen_info)
        w = (self.screen or self.screen_info).width
        h = (self.screen or self.screen_info).height
        img = Image.new('1', (w, h))
        draw = ImageDraw.Draw(img)
        try:
            wlan_ip = psutil.net_if_addrs()[self.wifi_iface][0].address
        except Exception:
            wlan_ip = 'N/A'
        wlan_state = dev_state('wlan0')
        self.voltage_update()
        self.get_version()
        mem = psutil.virtual_memory()
        cpu = psutil.cpu_percent()
        disk = psutil.disk_usage('/')
        draw.text((2, 3), wlan_state['mode'] + ' SSID: ' + wlan_state['ssid'], font=self.font, fill=255)
        draw.text((2, 15), "IP: " + wlan_ip, font=self.font, fill=255)
        draw.text((2, 27), "VER: {:<8} {}".format(self.model, self.version), font=self.font, fill=255)
        draw.text((2, 39), "CPU: {}%".format(cpu), font=self.font, fill=255)
        draw.text((64, 39), "MEM: {:0.1f}%".format(mem.used / mem.total * 100.0), font=self.font, fill=255)
        draw.text((2, 51), "DISK: {}%".format(int(disk.percent)), font=self.font, fill=255)
        draw.text((64, 51), "BAT: {:.2f}V".format(self.voltage), font=self.font, fill=255)
        self.gram = np.array(img, dtype=np.uint8) * 255

    # Рисование «эмоции по умолчанию» (рот, три полоски) — не используется, вывод закомментирован в цикле выше; дисплей 0x3D для motik (neutral при включении).
    def draw_mouth_update(self):
        w, h = 128, 64
        img = Image.new('1', (w, h))
        draw = ImageDraw.Draw(img)
        cx, cy = 64, 42
        # Рот увеличен в 3 раза
        bar_height, bar_width = 6, 18
        for i in range(3):
            left = cx - 45 + i * 36
            top = cy - bar_height // 2
            draw.rectangle((left, top, left + bar_width, top + bar_height), fill=255)
        self.mouth_gram = np.array(img, dtype=np.uint8) * 255


if __name__ == "__main__":
    OledDisplayNode()
