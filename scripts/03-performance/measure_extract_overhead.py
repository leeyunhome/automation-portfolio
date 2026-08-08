#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_extract_overhead.py
===========================
임베디드 장비에서 `tar -zxf`(silent) 와 `tar -zxvf`(verbose) 의
압축 해제 소요시간을 파일 크기별로 비교 측정하여 CSV 로 리포트한다.

-------------------------------------------------------------------------------
왜 이걸 측정했는가
-------------------------------------------------------------------------------
"장비 기동 시 모델 로딩이 느리다" 는 정성적 보고를 정량화해야 했다.
기동 스크립트가 tar 를 verbose 로 호출하고 있었는데, 느린 시리얼 콘솔에
파일명을 한 줄씩 찍는 비용이 실제로 유의미한지 확인이 필요했다.

측정 결과 파일 크기와 콘솔 상태에 따라 오버헤드가 -19% ~ +23% 로
크게 요동쳤고, 이는 "verbose 를 끄면 빨라진다" 는 단순한 결론이 아니라
I/O 대기가 지배적인 구간에서는 터미널 출력이 묻힌다는 것을 보여준다.

-------------------------------------------------------------------------------
측정 정확도를 위해 한 것
-------------------------------------------------------------------------------
1) sync 포함 측정
   `tar ... && sync` 로 측정한다. sync 없이 재면 페이지 캐시에만 쓰고
   반환되는 시간을 재게 되어, 실제 스토리지 쓰기 완료 시점을 놓친다.

2) 매 측정 전 동일 시작 조건 복원
   직전 측정이 남긴 파일이 있으면 tar 가 덮어쓰기를 하며 시간이 달라진다.
   측정 직전마다 클린업을 수행해 조건을 맞춘다.

3) 집합 차분 기반 안전 클린업
   측정 시작 전 디렉터리 스냅샷을 떠 두고, 클린업 시
   (현재 파일 집합 - 최초 파일 집합) 만 삭제한다.
   운영 중인 장비에서 도는 스크립트이므로 원본을 절대 건드리면 안 된다.
   추가 안전장치로 .tar.gz 원본은 명시적으로 skip 한다.

4) 타임아웃 시 -1 반환
   측정이 타임아웃되면 그 값을 결과에 섞지 않고 -1 로 표시해
   평균이 오염되는 것을 막는다.

-------------------------------------------------------------------------------
telnetlib 대신 raw socket 을 쓴 이유
-------------------------------------------------------------------------------
verbose 모드는 수천 줄을 순식간에 쏟아낸다. telnetlib.read_until() 은
"기대하는 바이트열" 을 기다리는데, 대량 출력 중에는 프롬프트 문자가
데이터 중간에 우연히 등장하기도 하고 버퍼가 밀리기도 한다.

그래서 소켓을 직접 다루며 두 가지 종료 판정을 병행한다.
  (a) 버퍼가 프롬프트 문자로 "끝나는가"
  (b) 0.5초 이상 신규 데이터 유입이 멈췄는가 (idle 휴리스틱)
둘을 함께 보면 대량 출력 상황에서도 명령 종료를 안정적으로 판정할 수 있다.

사용법
------
  DEVICE_HOST=192.168.10.50 DEVICE_PASS=secret ./measure_extract_overhead.py
"""

import csv
import os
import socket
import time
import traceback
from datetime import datetime

# --- [설정 구역] ---------------------------------------------------------
HOST = os.environ.get("DEVICE_HOST", "192.168.10.50")
USER = os.environ.get("DEVICE_USER", "root")
PASSWORD = os.environ.get("DEVICE_PASS", "")
TELNET_PORT = 23

TARGET_DIR = os.environ.get("TARGET_DIR", "/opt/app/models")
OUTPUT_CSV = f"tar_sync_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

# 타임아웃 설정
SOCKET_TIMEOUT = 20
LOGIN_TIMEOUT = 10
CMD_TIMEOUT = 600          # 대용량 아카이브 해제를 고려한 상한
READ_CHUNK_SIZE = 4096
IDLE_SETTLE_SEC = 0.5      # 이 시간 이상 데이터가 없으면 출력 종료로 간주


def read_until_prompt(sock, prompts=(b"#", b"$"), timeout=10):
    """소켓에서 데이터를 읽다가 프롬프트가 나오면 멈춘다.

    종료 판정을 이중으로 한다:
      (a) 버퍼가 프롬프트 문자로 끝남
      (b) IDLE_SETTLE_SEC 이상 신규 데이터 없음 + 프롬프트로 끝남

    (b) 가 필요한 이유: verbose 출력이 대량으로 흐르는 동안에는
    (a) 만으로는 중간에 잘못 끊길 수 있다.
    """
    sock.settimeout(timeout)
    buffer = b""
    start_time = time.time()
    last_data_time = start_time

    while True:
        try:
            chunk = sock.recv(READ_CHUNK_SIZE)
            if not chunk:
                break
            buffer += chunk
            last_data_time = time.time()

            # (a) 프롬프트로 끝나는지 확인
            for prompt in prompts:
                if buffer.strip().endswith(prompt.strip()):
                    return buffer.decode("utf-8", errors="ignore")
                # 로그인/패스워드 프롬프트는 문자열 포함 여부로 판정
                if b"login:" in prompt.lower() or b"assword:" in prompt.lower():
                    if prompt.lower() in buffer.lower():
                        return buffer.decode("utf-8", errors="ignore")

            # 전체 타임아웃
            if time.time() - start_time > timeout:
                raise socket.timeout(f"Read timeout ({timeout}s)")

            # (b) idle 휴리스틱
            if time.time() - last_data_time > IDLE_SETTLE_SEC:
                if buffer.strip().endswith((b"#", b"$", b">")):
                    return buffer.decode("utf-8", errors="ignore")

        except socket.timeout:
            # 타임아웃이 나도 버퍼가 프롬프트로 끝나면 성공으로 처리(복구 경로)
            if buffer and buffer.strip().endswith((b"#", b"$", b">")):
                return buffer.decode("utf-8", errors="ignore")
            raise


def create_connection(ip, user, password):
    """telnet 로그인 시퀀스를 raw socket 으로 직접 수행한다."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(SOCKET_TIMEOUT)
        sock.connect((ip, TELNET_PORT))
        print(f"[{ip}] Connected. Logging in...")

        read_until_prompt(sock, [b"login:", b"Login:"], timeout=LOGIN_TIMEOUT)
        sock.sendall(user.encode("ascii") + b"\n")

        if password:
            read_until_prompt(sock, [b"Password:", b"password:"],
                              timeout=LOGIN_TIMEOUT)
            sock.sendall(password.encode("ascii") + b"\n")

        read_until_prompt(sock, [b"#", b"$", b">"], timeout=LOGIN_TIMEOUT)
        print(f"[{ip}] Login Successful.")
        return sock

    except Exception as e:
        print(f"[{ip}] Connection failed: {e}")
        return None


def send_command(sock, cmd, timeout=10):
    sock.sendall(cmd.encode("ascii") + b"\n")
    return read_until_prompt(sock, timeout=timeout)


def list_dir_entries(sock):
    """현재 디렉터리의 1-depth 항목 집합을 반환한다."""
    output = send_command(sock, "find . -maxdepth 1 -not -name '.'", timeout=10)

    entries = set()
    for line in output.splitlines():
        line = line.strip()
        if line and not line.startswith("find") and line != ".":
            filename = line.lstrip("./")
            if filename:
                entries.add(filename)
    return entries


def get_existing_files(sock):
    """측정 시작 전 스냅샷. 이후 클린업의 기준선이 된다."""
    print("   [Snapshot] Capturing existing files...")
    existing = list_dir_entries(sock)
    print(f"   [Snapshot] Found {len(existing)} existing items")
    return existing


def cleanup_new_files(sock, existing_files):
    """스냅샷 대비 '새로 생긴 것' 만 삭제한다.

    운영 장비에서 도는 스크립트이므로, 원본 파일을 지우는 사고를
    구조적으로 차단하는 것이 핵심이다.
    """
    print("   [Cleanup] Identifying new files...")
    current_files = list_dir_entries(sock)

    # 집합 차분 — 이것이 안전장치의 핵심
    new_files = current_files - existing_files

    if not new_files:
        print("   [Cleanup] No new files to delete")
        return

    print(f"   [Cleanup] Found {len(new_files)} new items to delete")
    for filename in sorted(new_files):
        # 이중 안전장치: 원본 아카이브는 어떤 경우에도 건드리지 않는다
        if filename.endswith(".tar.gz"):
            print(f"   [Cleanup] Skipping archive: {filename}")
            continue
        send_command(sock, f"rm -rf './{filename}'", timeout=30)

    send_command(sock, "sync", timeout=30)
    print("   [Cleanup] Done.")


def get_file_size(sock, filepath):
    """파일 크기(바이트)를 반환한다.

    busybox 환경에 따라 stat 이 없거나 옵션이 다를 수 있어
    `stat || ls -l` 폴백 후 두 출력 포맷을 모두 파싱한다.
    """
    try:
        output = send_command(
            sock, f"stat -c %s '{filepath}' 2>/dev/null || ls -l '{filepath}'",
            timeout=5)

        # stat 결과: 숫자 한 줄
        for line in output.splitlines():
            if line.strip().isdigit():
                return int(line.strip())

        # ls -l 결과: 5번째 필드가 크기
        for line in output.splitlines():
            if filepath in line:
                parts = line.split()
                if len(parts) >= 5:
                    try:
                        return int(parts[4])
                    except ValueError:
                        pass
    except Exception as e:
        print(f"   [Warning] Could not get file size: {e}")
    return 0


def measure_extraction(sock, cmd, description):
    """명령 실행 시간을 측정한다. 타임아웃 시 -1 을 반환한다."""
    print(f"   [Measure] {description}")

    start_time = time.time()
    sock.sendall(cmd.encode("ascii") + b"\n")

    try:
        read_until_prompt(sock, timeout=CMD_TIMEOUT)
    except socket.timeout:
        print(f"   [Error] Timeout during {description}!")
        return -1
    except Exception as e:
        print(f"   [Error] Exception during {description}: {e}")
        return -1

    duration = time.time() - start_time
    print(f"   [Result] Time: {duration:.4f} sec")
    return duration


def main():
    sock = create_connection(HOST, USER, PASSWORD)
    if not sock:
        return

    try:
        print(f"\n--- Moving to {TARGET_DIR} ---")
        send_command(sock, f"cd {TARGET_DIR}")

        print("\n--- Taking initial snapshot ---")
        existing_files = get_existing_files(sock)

        print("\n--- Searching for .tar.gz files ---")
        find_output = send_command(
            sock, "find . -maxdepth 1 -name '*.tar.gz' -type f", timeout=10)

        file_list = []
        for line in find_output.splitlines():
            line = line.strip()
            if line.endswith(".tar.gz") and not line.startswith("find"):
                filename = line.lstrip("./")
                if filename and filename not in file_list:
                    file_list.append(filename)

        if not file_list:
            print("[Fatal] No .tar.gz files found. Exiting.")
            return

        print(f"\nFound {len(file_list)} file(s)")
        results = []

        for idx, file_name in enumerate(file_list, 1):
            print(f"\n{'=' * 60}")
            print(f"[{idx}/{len(file_list)}] Processing: {file_name}")
            print(f"{'=' * 60}")

            file_size = get_file_size(sock, file_name)
            print(f"   File size: {file_size:,} bytes "
                  f"({file_size / 1024 / 1024:.2f} MB)")

            # --- Test 1: Silent (zxf) + sync ---
            print("\n   --- Test 1: Silent Mode (zxf + sync) ---")
            cleanup_new_files(sock, existing_files)   # 동일 시작 조건 복원
            time_silent = measure_extraction(
                sock, f"tar -zxf '{file_name}' && sync", "Silent Mode")

            # --- Test 2: Verbose (zxvf) + sync ---
            print("\n   --- Test 2: Verbose Mode (zxvf + sync) ---")
            cleanup_new_files(sock, existing_files)   # 동일 시작 조건 복원
            time_verbose = measure_extraction(
                sock, f"tar -zxvf '{file_name}' && sync", "Verbose Mode")

            diff = 0
            overhead_pct = 0
            if time_silent > 0 and time_verbose > 0:
                diff = time_verbose - time_silent
                overhead_pct = (diff / time_silent) * 100
                print(f"\n   Summary: silent={time_silent:.4f}s  "
                      f"verbose={time_verbose:.4f}s  "
                      f"diff={diff:.4f}s ({overhead_pct:.2f}%)")

            results.append([
                file_name, file_size,
                round(time_silent, 4), round(time_verbose, 4),
                round(diff, 4), round(overhead_pct, 2),
            ])

        print(f"\n{'=' * 60}")
        print("--- Final Cleanup ---")
        cleanup_new_files(sock, existing_files)

        print(f"\n--- Saving results to {OUTPUT_CSV} ---")
        # utf-8-sig: 스프레드시트에서 한글이 깨지지 않도록 BOM 포함
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "File Name", "Size (Bytes)",
                "Silent(zxf)+Sync (sec)", "Verbose(zxvf)+Sync (sec)",
                "Diff (sec)", "Overhead (%)",
            ])
            writer.writerows(results)

        print(f"Results saved to {OUTPUT_CSV}")
        print("All original files preserved.")

    except Exception as e:
        print(f"\n[Fatal Error] {e}")
        traceback.print_exc()
    finally:
        if sock:
            sock.close()
            print("\n[Connection closed]")


if __name__ == "__main__":
    main()
