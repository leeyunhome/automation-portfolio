#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
replay_build_log.py
====================
크로스컴파일 빌드 로그를 파싱해, 그 안의 gcc/g++ 컴파일 명령을
SAST(정적 애플리케이션 보안 테스트) 도구의 소스 분석기로 재실행(replay)한다.

-------------------------------------------------------------------------------
왜 필요한가
-------------------------------------------------------------------------------
상용 SAST 도구(Fortify 등)는 보통 "빌드를 후킹" 하는 방식으로 동작한다.
`sourceanalyzer -b <id> make` 처럼 make 앞에 붙어서, make 가 실제로 실행하는
컴파일러 호출을 가로채 분석에 필요한 정보를 수집한다.

그런데 이 방식은 크로스컴파일 환경에서 자주 실패한다.
- 빌드 시스템이 sourceanalyzer 를 모르는 커스텀 래퍼 스크립트로 컴파일러를
  감싸고 있거나
- 여러 단계의 서브 make 가 겹쳐 후킹이 일부만 걸리거나
- 툴체인 특성상 후킹 프로세스 자체가 크래시하는 경우가 있다

원인을 하나씩 디버깅하는 대신, **이미 성공적으로 완료된 빌드의 로그**를
파싱해서 "그때 실행됐던 컴파일 명령을 그대로 다시 sourceanalyzer 로 실행"
하는 방식으로 우회했다. 빌드는 정상적으로 한 번 끝났으니 로그에는 실제로
사용된 정확한 컴파일러 플래그와 include 경로가 전부 남아 있다.

-------------------------------------------------------------------------------
동작 원리
-------------------------------------------------------------------------------
GNU make 는 `-w`(--print-directory) 옵션이나 서브 make 호출 시 자동으로

    make[2]: Entering directory '/build/src/drivers'
    ...
    riscv64-unknown-linux-gnu-gcc -Wall -I../include -c foo.c -o foo.o
    ...
    make[2]: Leaving directory '/build/src/drivers'

형태의 로그를 남긴다. 이 스크립트는 그 두 마커를 스택으로 추적해
"이 컴파일 명령이 어느 디렉터리에서 실행됐는지" 를 복원하고, 크로스컴파일러
호출 라인을 정규식으로 뽑아 동일한 cwd 에서 sourceanalyzer 로 재실행한다.

    cwd_stack.append(디렉터리)   # Entering
    cwd_stack.pop()              # Leaving
    cwd = cwd_stack[-1]          # 현재 컴파일 명령이 실행된 위치

디렉터리 정보가 없으면 분석기가 상대 include 경로를 못 찾아 헤더를 놓치므로,
이 스택 복원이 없으면 분석 자체가 반쪽짜리가 된다.

-------------------------------------------------------------------------------
한계
-------------------------------------------------------------------------------
- make 가 `-w` 로 디렉터리를 출력하지 않는 빌드 시스템에는 이 방식이 안 통한다.
  그 경우 빌드 스크립트에 `echo "===CWD:$(pwd)==="` 같은 커스텀 마커를
  직접 심어 같은 원리로 추적하는 변형이 필요하다.
- 컴파일이 실패했던 명령은 로그에 없으므로 재현되지 않는다.
  (분석 대상은 "성공한 빌드" 로 한정된다)

사용법
------
  ./replay_build_log.py build.log <BUILD_ID>
  # 예: ./replay_build_log.py build_20260808.log firmware-scan-01

  sourceanalyzer -b <BUILD_ID> -scan -f results.fpr   # 재생 완료 후 리포트 생성
"""

import os
import re
import subprocess
import sys

LOGFILE = sys.argv[1]
BUILD_ID = sys.argv[2]

# 실행 환경에 맞게 조정. 표준 설치 경로를 기본값으로 둔다.
SOURCEANALYZER = os.environ.get(
    "SOURCEANALYZER_BIN",
    os.path.expanduser("~/fortify/bin/sourceanalyzer"),
)

ENTER_RE = re.compile(r"Entering directory '([^']+)'")
LEAVE_RE = re.compile(r"Leaving directory '([^']+)'")

# 크로스컴파일러(예: riscv64-*-gcc) 또는 네이티브 gcc/g++ 의 컴파일 호출만 매치.
# "-c" 가 있는 라인만 잡아 링크 단계(컴파일러가 링커로도 호출되는 경우)를 배제한다.
COMPILE_RE = re.compile(r"^(\S*/(riscv64-[\w-]+-)?(g\+\+|gcc))\s+(.*\s-c\s.*)$")


def main():
    cwd_stack = []
    count = 0
    fail = 0

    with open(LOGFILE, errors="ignore") as f:
        for line in f:
            line = line.rstrip("\n")

            m = ENTER_RE.search(line)
            if m:
                cwd_stack.append(m.group(1))
                continue

            m = LEAVE_RE.search(line)
            if m:
                if cwd_stack:
                    cwd_stack.pop()
                continue

            m = COMPILE_RE.match(line)
            if not m:
                continue

            compiler = "g++" if "g++" in m.group(1) else "gcc"
            rest = m.group(4)
            cwd = cwd_stack[-1] if cwd_stack else os.getcwd()

            cmd = [SOURCEANALYZER, "-b", BUILD_ID, compiler] + rest.split()
            count += 1
            print(f"[{count}] ({cwd}) {compiler} ...")

            r = subprocess.run(cmd, cwd=cwd,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if r.returncode != 0:
                fail += 1
                print(f"    !!! sourceanalyzer exited {r.returncode}")

    print(f"\n완료: 총 {count}개 컴파일 명령 재생, 실패 {fail}건")


if __name__ == "__main__":
    main()
