#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_system_info.py
======================
원격 임베디드 리눅스 장비에 Telnet 으로 접속해 시스템 정보를 일괄 수집하고,
타임스탬프가 붙은 리포트 파일로 저장한다.

용도
----
이슈 리포트를 받았을 때 가장 먼저 확인해야 하는 것들
(커널 버전, CPU/메모리, 디스크, 네트워크, 프로세스 목록)을
사람이 손으로 치지 않고 한 번에 확보한다.

리포트를 파일로 남기는 이유
--------------------------
- 장애 시점의 상태를 스냅샷으로 보존해야 사후 비교가 가능하다.
- 같은 장비를 시간차로 여러 번 떠서 diff 하면 변화 지점이 드러난다.
- 파일명에 호스트와 타임스탬프를 넣어 섞이지 않게 한다.

사용법
------
  DEVICE_HOST=192.168.10.50 DEVICE_USER=root DEVICE_PASS=secret \
    ./collect_system_info.py
"""

import os
import sys
import time
import telnetlib
from datetime import datetime

# --- 접속 설정 (환경변수로 주입) -----------------------------------------
HOST = os.environ.get("DEVICE_HOST", "192.168.10.50")
PORT = int(os.environ.get("DEVICE_PORT", "23"))
USER = os.environ.get("DEVICE_USER", "root")
PASSWORD = os.environ.get("DEVICE_PASS", "")
TIMEOUT = 10

# --- 출력 설정 -----------------------------------------------------------
REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")

# --- 수집 명령 목록 ------------------------------------------------------
# `A || B` 폴백 형태로 구성해, busybox 빌드에 따라 한쪽이 없어도 동작하게 한다.
COMMANDS = [
    ("Hostname",          "hostname"),
    ("Kernel Version",    "uname -a"),
    ("CPU Info",          "cat /proc/cpuinfo"),
    ("Memory Info",       "cat /proc/meminfo"),
    ("Disk Usage",        "df -h"),
    ("Network Info",      "ifconfig || ip addr"),
    ("Uptime",            "uptime"),
    ("Running Processes", "ps aux || ps"),
    ("OS Release",        "cat /etc/os-release 2>/dev/null || cat /etc/issue"),
]

SEPARATOR = "=" * 60


def connect(host, port, user, password, timeout=TIMEOUT):
    """Telnet 접속 후 로그인한다."""
    print(f"[*] Connecting to {host}:{port} ...")
    tn = telnetlib.Telnet(host, port, timeout=timeout)

    tn.read_until(b"login: ", timeout=timeout)
    print("[*] Login prompt received.")
    tn.write(user.encode("ascii") + b"\n")

    tn.read_until(b"Password: ", timeout=timeout)
    tn.write(password.encode("ascii") + b"\n")

    # 로그인 완료 대기 후 환영 배너를 비운다
    time.sleep(2)
    tn.read_very_eager()

    print("[*] Login successful.\n")
    return tn


def run_command(tn, cmd, wait=2):
    """명령을 보내고 출력을 문자열로 반환한다."""
    tn.write(cmd.encode("ascii") + b"\n")
    time.sleep(wait)
    raw = tn.read_very_eager()
    return raw.decode("utf-8", errors="replace")


def collect_info(tn):
    results = {}
    for label, cmd in COMMANDS:
        print(f"  [+] Running: {cmd}")
        results[label] = run_command(tn, cmd)
    return results


def print_report(results, report_file=None):
    """수집 결과를 stdout 과 파일에 동시에 출력한다."""

    def emit(text=""):
        print(text)
        if report_file:
            report_file.write(text + "\n")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    emit("\n" + SEPARATOR)
    emit("  REMOTE SYSTEM INFORMATION REPORT")
    emit(f"  Host      : {HOST}")
    emit(f"  Collected : {timestamp}")
    emit(SEPARATOR)

    for label, output in results.items():
        emit(f"\n{'-' * 60}")
        emit(f"  {label}")
        emit(f"{'-' * 60}")
        for line in output.strip().splitlines():
            emit(f"  {line}")

    emit(f"\n{SEPARATOR}")
    emit("  Report Complete")
    emit(SEPARATOR)


def main():
    try:
        tn = connect(HOST, PORT, USER, PASSWORD)
    except Exception as e:
        print(f"[ERROR] Failed to connect: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        print("[*] Collecting system information ...\n")
        results = collect_info(tn)

        os.makedirs(REPORTS_DIR, exist_ok=True)
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_filename = os.path.join(
            REPORTS_DIR,
            f"sysinfo_{HOST.replace('.', '_')}_{timestamp_str}.txt",
        )

        with open(report_filename, "w", encoding="utf-8") as report_file:
            print_report(results, report_file=report_file)

        print(f"\n[*] Report saved to: {report_filename}")

    except Exception as e:
        print(f"[ERROR] An error occurred during data collection: {e}",
              file=sys.stderr)
    finally:
        tn.close()
        print("[*] Telnet connection closed.")


if __name__ == "__main__":
    main()
