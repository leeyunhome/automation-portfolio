#!/bin/bash
# =============================================================================
# analyze_link_events.sh
#
# 다수 장비의 dmesg 를 수집한 뒤, "부팅 이후에 발생한" 이더넷 링크 플랩만
# 골라내어 보고한다.
#
# -----------------------------------------------------------------------------
# 문제 정의
# -----------------------------------------------------------------------------
# 필드에서 간헐적인 네트워크 단절이 보고되었고, 원인 후보 중 하나가
# 이더넷 링크 플랩(link up/down 반복)이었다.
#
# 그런데 dmesg 를 그냥 grep 하면 "모든" 장비에서 link 이벤트가 잡힌다.
# 부팅 과정에서 PHY 가 협상(negotiation)을 마치며 남기는 정상 로그이기 때문이다.
#
#   [    6.985155] IPv6: ADDRCONF(NETDEV_UP): eth0: link is not ready   <- 정상(부팅)
#   [   10.104552] eth-mac 40800000.eth eth0: Link is Up - 100Mbps/Full <- 정상(부팅)
#   [ 4213.882910] eth-mac 40800000.eth eth0: Link is Down              <- 이상(운영 중)
#
# 즉 "이벤트가 있느냐" 가 아니라 "언제 발생했느냐" 가 판정 기준이어야 한다.
#
# -----------------------------------------------------------------------------
# 해결 방법
# -----------------------------------------------------------------------------
# 커널 링 버퍼 타임스탬프(부팅 후 경과 초)를 파싱해 임계값과 비교한다.
# BOOT_THRESHOLD(기본 60초) 이내는 부팅 노이즈로 간주해 버리고,
# 그 이후 발생한 이벤트만 이상 징후로 승격 출력한다.
#
# 사용법
#   ./analyze_link_events.sh [start_octet] [end_octet]
#   BOOT_THRESHOLD=90 ./analyze_link_events.sh 11 56
# =============================================================================

set -u

PREFIX="${DEVICE_SUBNET:-192.168.10}"
LOG_DIR="${LOG_DIR:-./dmesg_logs}"

# 부팅 완료 기준 시간(초). 이 시간 이후의 link 이벤트는 비정상으로 판정한다.
BOOT_THRESHOLD="${BOOT_THRESHOLD:-60}"

START_OCTET="${1:-11}"
END_OCTET="${2:-56}"

mkdir -p "$LOG_DIR"

# -----------------------------------------------------------------------------
# link 이벤트 검사
#   부팅 시 발생하는 link 이벤트는 무시하고,
#   BOOT_THRESHOLD 초 이후에 발생한 이벤트만 감지한다.
# -----------------------------------------------------------------------------
check_link_events() {
    local ip=$1
    local logfile=$2

    if [ ! -f "$logfile" ]; then
        echo "  [$ip] WARNING: 로그 파일을 찾을 수 없습니다 (수집 실패)"
        return
    fi

    # link 관련 이벤트만 추출
    local link_events
    link_events=$(grep -iE "Link is (Up|Down)|link (is not ready|becomes ready)" "$logfile")

    if [ -z "$link_events" ]; then
        # 이벤트가 아예 없는 것도 이상 신호다(드라이버 미로드 등)
        echo "  [$ip] WARNING: dmesg 에서 link 이벤트를 찾을 수 없습니다"
        return
    fi

    local found_post_boot=0
    while IFS= read -r line; do
        # 커널 타임스탬프 정수부 추출: "[   10.026633]" -> "10"
        #   \[\s*      : 여는 대괄호와 뒤따르는 공백
        #   \K         : 여기까지는 매치 결과에서 제외 (lookbehind 대용)
        #   [0-9]+     : 정수부
        #   (?=\.)     : 뒤에 소수점이 오는 경우만 (lookahead)
        local timestamp
        timestamp=$(echo "$line" | grep -oP '\[\s*\K[0-9]+(?=\.)')

        if [ -n "$timestamp" ] && [ "$timestamp" -gt "$BOOT_THRESHOLD" ]; then
            if [ "$found_post_boot" -eq 0 ]; then
                echo ""
                echo "  [$ip] *** 부팅 이후 LINK 이벤트 감지됨! ***"
                found_post_boot=1
            fi
            echo "    $line"
        fi
    done <<< "$link_events"

    if [ "$found_post_boot" -eq 0 ]; then
        echo "  [$ip] OK - 부팅 이후 link 변동 없음"
    fi
}

# -----------------------------------------------------------------------------
# 메인 루프
# -----------------------------------------------------------------------------
echo "=========================================="
echo " Link Down/Up 검사 시작"
echo " 대상       : $PREFIX.$START_OCTET ~ $PREFIX.$END_OCTET"
echo " 부팅 기준  : ${BOOT_THRESHOLD}초"
echo " 로그 경로  : $LOG_DIR"
echo "=========================================="
echo ""

for i in $(seq "$START_OCTET" "$END_OCTET"); do
    ip="$PREFIX.$i"
    logfile="$LOG_DIR/dmesg_${ip}.log"

    echo "ip : $ip"
    ./collect_dmesg.exp "$ip" "$logfile" > /dev/null 2>&1
    check_link_events "$ip" "$logfile"
done

echo ""
echo "=========================================="
echo " 검사 완료 — 로그 원본: $LOG_DIR"
echo "=========================================="
