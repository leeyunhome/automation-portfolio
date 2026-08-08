#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_remote_stress.py
====================
다수의 임베디드 리눅스 장비에 CPU / Memory / Network 부하를 동시에 인가하고,
일괄 해제하는 원격 스트레스 테스트 오케스트레이터.

목적
----
장비가 "한가할 때는 멀쩡한데 부하가 걸리면 죽는다" 는 유형의 결함을
재현하기 위한 도구. 한 대만 괴롭혀서는 재현되지 않는 문제가 있어,
동일 네트워크의 여러 장비에 동시에 부하를 인가할 필요가 있었다.

부하 인가 방식
-------------
대상은 busybox 기반 최소 환경이라 stress-ng 같은 표준 도구가 없다.
장비에 이미 존재하는 것만으로 부하를 만든다.

  CPU : dd if=/dev/urandom of=/dev/null  (urandom 이라 순수 연산 부하)
  MEM : tmpfs 를 램디스크로 마운트하고 dd 로 채움
  NET : iperf 서버 기동
  STOP: killall 로 일괄 정리

설계 포인트
----------
1) 자기 종료형 명령
   `dd ... & PID=$!; sleep N; kill $PID` 형태로 보내, 스크립트가 죽어도
   장비에 부하가 영구히 남지 않도록 한다. (원격 테스트에서 중요)
2) 스레드 병렬 + 스태거링
   장비당 스레드를 띄우되 0.1초 간격을 둬 동시 접속 폭주를 완화한다.
3) 부분 실패 허용
   장비별 try/except 로 감싸, 한 대가 죽어도 나머지 테스트는 계속된다.
4) 제외 옵션
   이미 장애가 난 장비를 -e 로 빼고 돌릴 수 있다.

사용법
------
  # 20대에 60초간 CPU 부하
  ./run_remote_stress.py root secret cpu -d 60

  # 210, 219 를 제외하고 메모리 부하
  ./run_remote_stress.py root secret mem -d 120 -e 210 219

  # 전체 정지
  ./run_remote_stress.py root secret stop
"""

import argparse
import telnetlib
import threading
import time

# --- 설정 ---------------------------------------------------------------
IP_BASE = "192.168.20"
IP_RANGE_START = 201
IP_RANGE_END = 220

TELNET_PORT = 23
CONNECT_TIMEOUT = 10


def run_command_on_device(ip, username, password, command, port=TELNET_PORT,
                          timeout=CONNECT_TIMEOUT):
    """지정된 IP 장비에 Telnet 접속하여 명령어를 실행한다.

    with 문으로 소켓을 확실히 닫고, 예외는 삼켜서 문자열로 반환한다.
    한 대의 실패가 전체 테스트를 중단시키면 안 되기 때문이다.
    """
    try:
        with telnetlib.Telnet(ip, port, timeout) as tn:
            tn.read_until(b"login: ", timeout=5)
            tn.write(username.encode("ascii") + b"\n")

            tn.read_until(b"Password: ", timeout=5)
            tn.write(password.encode("ascii") + b"\n")

            tn.read_until(b"# ", timeout=5)

            print(f"[OK] [{ip}] 명령어 실행: {command}")
            tn.write(command.encode("ascii") + b"\n")

            # 명령을 백그라운드로 던졌으므로 즉시 세션을 닫아도 된다.
            tn.write(b"exit\n")

        return f"[{ip}] 명령어 전송 성공"

    except Exception as e:
        return f"[FAIL] [{ip}] 오류 발생: {e}"


def build_command(load_type, duration):
    """부하 종류에 따른 원격 셸 명령을 합성한다.

    모든 명령은 '자기 종료형' 으로 구성해, 제어 스크립트가 중단되어도
    장비에 부하가 남지 않도록 한다.
    """
    if load_type == "cpu":
        # urandom 읽기로 CPU 를 태운다. sleep 후 자기 자신이 kill.
        return (f"dd if=/dev/urandom of=/dev/null & "
                f"PID=$!; sleep {duration}; kill $PID")

    if load_type == "mem":
        # tmpfs 램디스크를 만들어 실제 물리 메모리를 점유시킨다.
        return (f"mkdir -p /tmp/ram; "
                f"mount -t tmpfs -o size=50M tmpfs /tmp/ram; "
                f"dd if=/dev/zero of=/tmp/ram/dummy bs=1M count=50; "
                f"sleep {duration}; umount /tmp/ram")

    if load_type == "net":
        return f"iperf -s -t {duration} &"

    if load_type == "stop":
        return "killall dd iperf"

    raise ValueError(f"알 수 없는 부하 종류: {load_type}")


def main():
    parser = argparse.ArgumentParser(
        description="여러 임베디드 장비에 Telnet 으로 접속하여 부하 테스트를 실행합니다.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("username", help="Telnet 사용자 이름 (예: root)")
    parser.add_argument("password", help="Telnet 패스워드")
    parser.add_argument("load_type", choices=["cpu", "mem", "net", "stop"],
                        help="부하 종류")
    parser.add_argument("-d", "--duration", type=int, default=60,
                        help="부하 지속 시간(초). 기본값: 60")
    parser.add_argument("-e", "--exclude", type=int, nargs="*", default=[],
                        help="제외할 IP 의 마지막 옥텟 (예: -e 210 219)")

    args = parser.parse_args()

    # 제외 목록을 반영해 대상 IP 리스트 생성
    ip_list = [
        f"{IP_BASE}.{i}"
        for i in range(IP_RANGE_START, IP_RANGE_END + 1)
        if i not in args.exclude
    ]

    command = build_command(args.load_type, args.duration)

    print(f"--- {args.load_type.upper()} 부하 테스트 시작 "
          f"(대상: {len(ip_list)}대, 제외: {args.exclude}) ---")

    threads = []
    for ip in ip_list:
        thread = threading.Thread(
            target=run_command_on_device,
            args=(ip, args.username, args.password, command),
        )
        threads.append(thread)
        thread.start()
        # 스태거링: 동시 접속 폭주로 장비/스위치가 흔들리는 것을 완화
        time.sleep(0.1)

    # 모든 워커 수렴 대기
    for thread in threads:
        thread.join()

    print("\n--- 모든 작업 완료 ---")


if __name__ == "__main__":
    main()
