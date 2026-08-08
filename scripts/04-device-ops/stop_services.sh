#!/bin/sh
# =============================================================================
# stop_services.sh
#
# 장비 위에서 실행되어, 지정한 애플리케이션 데몬들을 안전하게 종료한다.
# (테스트 전 리소스를 확보하거나, 특정 프로세스만 격리 검증할 때 사용)
#
# -----------------------------------------------------------------------------
# 두 가지 함정을 피하기 위한 설계
# -----------------------------------------------------------------------------
# 1) 스크립트 자기 자신이 grep 에 걸리는 문제
#    `ps -ef | grep myapp` 은 grep 프로세스 자신과, 이 스크립트의
#    커맨드라인까지 매치시킨다. 그 PID 를 kill 하면 스크립트가 자살한다.
#
#    해결: 프로세스를 '전체 경로'로 지정해 grep 한다.
#          부분 문자열이 아니라 실행 파일 경로로 매칭하므로 오탐이 사라진다.
#          (추가로 grep -v grep 으로 grep 자신도 제외)
#
# 2) busybox 의 ps 출력 포맷이 데스크톱 리눅스와 다른 문제
#    일반적인 procps 의 `ps -ef` 는 두 번째 컬럼이 PID 지만,
#    대상 장비의 busybox ps 는 첫 번째 컬럼이 PID 다.
#    실제 장비에서 출력을 확인하고 awk 필드 번호를 맞췄다.
#
#    해결: awk '{print $1}'   (procps 환경이라면 $2 여야 한다)
#
# POSIX sh 로 작성 — 대상 장비에 bash 가 없다.
# =============================================================================

# 종료할 프로세스를 '전체 경로'로 관리한다 (위 1번 함정 회피)
PROCESS_PATHS="/opt/app/bin/media-encoder /opt/app/bin/vision-init"

echo "=== 프로세스 종료를 시작합니다 (Full Path 모드) ==="

for process_path in $PROCESS_PATHS
do
    # 전체 경로로 매칭 + grep 자신 제외
    # awk $1 : busybox ps 는 PID 가 첫 번째 컬럼 (위 2번 함정 회피)
    pid=$(ps -ef | grep "$process_path" | grep -v grep | awk '{print $1}')

    if [ -n "$pid" ]; then
        echo "-> '$process_path' (PID: $pid) 프로세스를 종료합니다."
        kill $pid
    else
        # 경로에서 파일명만 뽑아 간결하게 표시
        process_name=$(basename "$process_path")
        echo "-> '$process_name' 프로세스가 실행 중이지 않습니다."
    fi
done

echo "=== 모든 작업이 완료되었습니다 ==="
