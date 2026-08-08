#!/bin/bash
# =============================================================================
# reboot_devices.sh
#
# 다수 장비에 reboot 명령을 "동시에" 전송한다.
#
# 왜 병렬이어야 하는가
#   순차 재부팅을 하면 첫 장비와 마지막 장비의 기동 시각이 수 분 벌어진다.
#   uptime 을 비교해 커널 안정성을 판단하는 실험에서 이 시차는 그대로
#   측정 오차가 되므로, 모든 장비를 동일 시점에 리셋해야 비교가 유효하다.
#
# 사용법
#   DEVICE_USER=root DEVICE_PASS=secret ./reboot_devices.sh
# =============================================================================

set -u

PREFIX="${DEVICE_SUBNET:-192.168.10}"
USER_ID="${DEVICE_USER:-root}"
USER_PW="${DEVICE_PASS:-root}"

reboot_device() {
    local ip=$1
    local group=$2

    # reboot 을 보내면 원격 세션이 끊기므로 'expect eof' 로 정상 종료 처리한다.
    # (프롬프트를 다시 기다리면 반드시 타임아웃이 난다)
    expect -c "
        set timeout 5
        spawn telnet $ip
        expect \"login:\"
        send \"$USER_ID\r\"
        expect \"Password:\"
        send \"$USER_PW\r\"
        expect \"#\"
        send \"reboot\r\"
        expect eof
    " > /dev/null 2>&1

    if [ $? -eq 0 ]; then
        echo "[$group] $ip 재부팅 명령 전송 완료"
    else
        echo "[$group] $ip 실패"
    fi
}

# '&' 로 백그라운드 병렬 실행
for i in {11..19}; do reboot_device "$PREFIX.$i" "rev-A"    & done
for i in {20..28}; do reboot_device "$PREFIX.$i" "rev-B"    & done
for i in {29..37}; do reboot_device "$PREFIX.$i" "rev-C"    & done
for i in {38..46}; do reboot_device "$PREFIX.$i" "rev-D"    & done
for i in {47..56}; do reboot_device "$PREFIX.$i" "baseline" & done

# 모든 전송이 끝날 때까지 대기
wait
echo "전체 재부팅 명령 완료"
