#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_process_farm.py
======================
IP 대역(CIDR / 범위 / 단일)을 입력받아, 다수의 장비에 SSH로 병렬 접속해
특정 프로세스의 실행 여부를 일괄 점검한다.

-------------------------------------------------------------------------------
왜 만들었는가
-------------------------------------------------------------------------------
장애 조사 중 "핵심 데몬이 죽어 있는 장비가 몇 대나 있는가" 를 확인해야 했다.
장비가 수십 대라 하나씩 SSH 로 들어가 `ps` 를 치는 것은 현실적이지 않았고,
telnet 기반 [01-device-farm](../01-device-farm) 스크립트들과 달리 이 장비군은
SSH 가 열려 있어 paramiko 로 병렬화했다.

[stop_services.sh](stop_services.sh) 가 "데몬을 종료" 하는 스크립트라면,
이 스크립트는 그 반대편 — "데몬이 살아 있는지 확인" 하는 점검 도구다.
종료 전후로 짝을 지어 쓴다: 종료 → 이 스크립트로 전수 확인 → 필요시 재기동.

-------------------------------------------------------------------------------
설계 포인트
-------------------------------------------------------------------------------
1) grep 자기 매칭 회피
   `ps -ef | grep myprocess` 는 grep 프로세스 자신도 결과에 포함시킨다.
   `grep '[m]yprocess'` 트릭을 쓰면 grep 이 찾는 패턴이 정규식 문자 클래스로
   해석되어, grep 명령어 자신의 커맨드라인과는 더 이상 매치되지 않는다.
   (stop_services.sh 에서 쓴 "전체 경로 + grep -v grep" 과 같은 문제를
    다른 방식으로 해결한 것 — SSH 환경에서는 이 트릭이 더 간결하다)

2) IP 입력 형식 세 가지 지원
   CIDR(`/24`), 범위(`start-end`), 단일 IP — 현장에서 장비 목록을 받는
   형태가 매번 다르기 때문에 세 형식을 모두 받아들이게 했다.

3) 병렬 + 상태 3분류
   FOUND / NOT_FOUND / FAILED 로 결과를 명확히 나눈다.
   "확인 안 됨(FAILED)" 을 "정상(NOT_FOUND)" 과 섞으면, 접속 실패로 놓친
   장비가 조용히 "문제 없음" 으로 집계되는 사고가 난다.

4) 자격증명을 코드에 두지 않음
   IP 대역 · 계정 · 비밀번호를 모두 실행 시점에 대화형으로 입력받는다.
   `getpass.getpass()` 로 비밀번호는 화면에 echo 되지 않는다.

사용법
------
  ./check_process_farm.py
  Enter the IP range (e.g., 192.168.1.0/24): 192.168.10.0/24
  Enter SSH username: root
  Enter SSH password: (입력 시 화면에 표시되지 않음)
"""

import getpass
import ipaddress
from concurrent.futures import ThreadPoolExecutor, as_completed

import paramiko

# --- 설정 값 ---
PROCESS_NAME = "media-encoder"   # 점검할 프로세스 이름
MAX_WORKERS = 10                 # 동시 접속 워커 수
TIMEOUT = 10                     # SSH 접속/명령 타임아웃 (초)


def check_process_running(hostname, username, password):
    """단일 장비에 SSH 로 접속해 프로세스 실행 여부를 확인한다.

    Returns:
        tuple: (hostname, status, message)
               status: 'FOUND' | 'NOT_FOUND' | 'FAILED'
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # grep '[m]edia-encoder' 트릭:
    # 첫 글자를 문자 클래스 [x] 로 감싸면 grep 자신의 커맨드라인에 있는
    # 리터럴 문자열 "media-encoder" 와는 매치되지 않는다 (문자 클래스 vs 리터럴).
    # 반면 실제 프로세스명 문자열과는 정상적으로 매치된다.
    command = f"ps -ef | grep '[{PROCESS_NAME[0]}]{PROCESS_NAME[1:]}'"

    try:
        client.connect(hostname=hostname, username=username,
                       password=password, timeout=TIMEOUT)

        _, stdout, _ = client.exec_command(command, timeout=TIMEOUT)
        output = stdout.read().decode("utf-8").strip()

        if output:
            process_line = output.splitlines()[0]
            return (hostname, "FOUND", process_line)
        return (hostname, "NOT_FOUND", f"Process '{PROCESS_NAME}' is not running.")

    except Exception as e:
        # 접속 실패와 "프로세스 없음" 을 절대 같은 상태로 묻지 않는다.
        # FAILED 는 "점검하지 못했다" 는 뜻이지 "정상" 이라는 뜻이 아니다.
        return (hostname, "FAILED", f"Connection or command failed: {e}")
    finally:
        client.close()


def parse_ip_range(ip_range_str):
    """CIDR / 범위 / 단일 IP 세 형식을 모두 받아 IP 리스트로 변환한다."""
    if "/" in ip_range_str:
        network = ipaddress.ip_network(ip_range_str, strict=False)
        return [str(ip) for ip in network.hosts()]

    if "-" in ip_range_str:
        start_ip, end_ip = ip_range_str.split("-")
        start_addr = int(ipaddress.ip_address(start_ip.strip()))
        end_addr = int(ipaddress.ip_address(end_ip.strip()))
        return [str(ipaddress.ip_address(ip)) for ip in range(start_addr, end_addr + 1)]

    return [str(ipaddress.ip_address(ip_range_str.strip()))]


def main():
    print(f"--- Process Checker for '{PROCESS_NAME}' ---")

    ip_range_str = input("Enter the IP range (e.g., 192.168.1.0/24): ")
    ssh_user = input("Enter SSH username: ")
    ssh_password = getpass.getpass("Enter SSH password: ")

    try:
        hosts = parse_ip_range(ip_range_str)
    except ValueError as e:
        print(f"\n[Error] Invalid IP range format: {e}")
        return

    if not hosts:
        print("\n[Info] No hosts to check.")
        return

    print(f"\nChecking for '{PROCESS_NAME}' on {len(hosts)} sets...")

    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_host = {
            executor.submit(check_process_running, host, ssh_user, ssh_password): host
            for host in hosts
        }

        for i, future in enumerate(as_completed(future_to_host), 1):
            try:
                hostname, status, message = future.result()
                results.append((hostname, status, message))

                if status == "FOUND":
                    print(f"  ({i}/{len(hosts)}) [FOUND]     {hostname} | {message}")
                elif status == "NOT_FOUND":
                    print(f"  ({i}/{len(hosts)}) [NOT_FOUND] {hostname}")
                else:
                    print(f"  ({i}/{len(hosts)}) [FAILED]    {hostname} - {message}")

            except Exception as e:
                host = future_to_host[future]
                results.append((host, "FAILED", f"An unexpected error occurred: {e}"))
                print(f"  ({i}/{len(hosts)}) [ERROR]     {host} - {e}")

    found = sum(1 for _, s, _ in results if s == "FOUND")
    not_found = sum(1 for _, s, _ in results if s == "NOT_FOUND")
    failed = sum(1 for _, s, _ in results if s == "FAILED")

    print("\n-----------------------------------------")
    print("Process check complete.")
    print(f"Total sets: {len(hosts)}")
    print(f"  - Found: {found}")
    print(f"  - Not Found: {not_found}")
    print(f"  - Failed to check: {failed}")
    print("-----------------------------------------")


if __name__ == "__main__":
    main()
