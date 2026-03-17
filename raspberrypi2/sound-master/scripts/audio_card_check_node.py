#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import subprocess
import textwrap
from typing import List

import rospy
from std_msgs.msg import String
from sound.srv import CheckAudioCard, CheckAudioCardResponse


def _run_cmd(args: List[str]) -> str:
    try:
        out = subprocess.check_output(args, stderr=subprocess.STDOUT, timeout=5, text=True)
        return out
    except Exception as e:
        return f"ERROR: {e}"


def _grep_device(output: str, device: str) -> bool:
    if not device:
        return True
    return device in output


def main() -> None:
    rospy.init_node("audio_card_check_node", anonymous=False)

    status_pub = rospy.Publisher("/sound/audio_card_status", String, queue_size=1, latch=True)

    playback_cache = _run_cmd(["aplay", "-l"])
    capture_cache = _run_cmd(["arecord", "-l"])

    info_msg = textwrap.dedent(
        f"""audio_card_check_node started.
aplay -l:
{playback_cache}
arecord -l:
{capture_cache}
"""
    )
    status_pub.publish(String(data=info_msg))
    rospy.loginfo("audio_card_check_node: опубликован список устройств в /sound/audio_card_status")

    def handle_check(req: CheckAudioCard.Request) -> CheckAudioCardResponse:
        nonlocal playback_cache, capture_cache

        playback_ok = True
        capture_ok = True
        messages = []

        if req.test_playback:
            if "ERROR:" in playback_cache:
                playback_cache = _run_cmd(["aplay", "-l"])
            playback_ok = _grep_device(playback_cache, req.playback_device)
            if playback_ok:
                messages.append("playback OK")
            else:
                messages.append(f"playback device '{req.playback_device}' not found")

        if req.test_capture:
            if "ERROR:" in capture_cache:
                capture_cache = _run_cmd(["arecord", "-l"])
            capture_ok = _grep_device(capture_cache, req.capture_device)
            if capture_ok:
                messages.append("capture OK")
            else:
                messages.append(f"capture device '{req.capture_device}' not found")

        ok = playback_ok and capture_ok
        msg = "; ".join(messages) if messages else "no tests requested"

        full_status = info_msg + "\nLast check: " + msg
        status_pub.publish(String(data=full_status))

        rospy.loginfo("audio_card_check_node: %s", msg)
        return CheckAudioCardResponse(ok=ok, message=msg)

    srv = rospy.Service("/sound/check_audio_card", CheckAudioCard, handle_check)
    rospy.loginfo("audio_card_check_node: сервис /sound/check_audio_card готов")
    rospy.spin()


if __name__ == "__main__":
    main()

