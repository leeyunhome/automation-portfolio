#!/bin/bash
# =============================================================================
# check_kernel_version.sh
#
# 다수 장비의 커널 빌드 번호(uname -v)를 수집하여,
# IP 대역에 배정된 커널 리비전 그룹과 실제 탑재 버전이 일치하는지 검증한다.
#
# 목적
#   커널 플래싱(deploy_kernel.sh) 이후 "의도한 커널이 실제로 올라갔는가" 를
#   전수 확인한다. 소킹 테스트 결과의 신뢰성은 이 검증에 달려 있다.
#   - 플래싱 실패한 장비가 섞이면 A/B 비교 자체가 무의미해진다.
#
# 사용법
#   DEVICE_USER=root DEVICE_PASS=secret ./check_kernel_version.sh
# =============================================================================

set -u

PREFIX="${DEVICE_SUBNET:-192.168.10}"
USER_ID="${DEVICE_USER:-root}"
USER_PW="${DEVICE_PASS:-changeme}"

check_build() {
    local ip=$1
    local group=$2
    echo -n "[$group] ip : $ip ... "

    # expect -c 인라인 방식: 파일 생성 없이 대화형 세션 자동화
    # set timeout 5 : 죽은 장비에서 무한 대기하지 않도록 상한선
    local result
    result=$(expect -c "
        set timeout 5
        spawn telnet $ip
        expect \"login:\"
        send \"$USER_ID\r\"
        expect \"Password:\"
        send \"$USER_PW\r\"
        expect \"#\"
        send \"uname -v\r\"
        expect \"#\"
        send \"exit\r\"
    " 2>/dev/null | grep -E '#[0-9]+ SMP')
    # grep 패턴 '#<빌드번호> SMP' 로 커널 빌드 라인만 정확히 추출
    # (배너/에코된 명령어가 섞여도 오탐하지 않음)

    if [ -n "$result" ]; then
        echo "$result"
    else
        echo "접속 실패 또는 응답 없음"
    fi
}

# IP 대역 = 커널 리비전 그룹 (check_uptime_parallel.sh 와 동일한 매핑)
for i in {11..19}; do check_build "$PREFIX.$i" "rev-A";    done
for i in {20..28}; do check_build "$PREFIX.$i" "rev-B";    done
for i in {29..37}; do check_build "$PREFIX.$i" "rev-C";    done
for i in {38..46}; do check_build "$PREFIX.$i" "rev-D";    done
for i in {47..56}; do check_build "$PREFIX.$i" "baseline"; done
