#!/bin/bash
# =============================================================================
# deploy_kernel.sh
#
# 커널 이미지를 지정한 IP 대역의 장비들에 FTP 로 일괄 전송(플래싱)한다.
#
# 배경
#   대상 장비는 busybox 기반의 최소 루트파일시스템이라 scp/rsync 가 없다.
#   busybox 에 내장된 ftpput 을 사용해 이미지를 밀어 넣는 방식을 택했다.
#
# 사용법
#   ./deploy_kernel.sh <kernel_image> <start_octet> <end_octet>
#   예) ./deploy_kernel.sh kernel-image.gz.rev-B 20 28
# =============================================================================

set -u

PREFIX="${DEVICE_SUBNET:-192.168.10}"
USER_ID="${DEVICE_USER:-root}"
USER_PW="${DEVICE_PASS:-root}"

KERNEL_FILE="${1:-}"
START_OCTET="${2:-}"
END_OCTET="${3:-}"

usage() {
    echo "Usage: $0 <kernel_image> <start_octet> <end_octet>"
    echo "  예) $0 kernel-image.gz.rev-B 20 28"
    exit 1
}

[ -z "$KERNEL_FILE" ] && usage
[ -z "$START_OCTET" ] && usage
[ -z "$END_OCTET" ] && usage

if [ ! -f "$KERNEL_FILE" ]; then
    echo "Error: 커널 이미지 '$KERNEL_FILE' 를 찾을 수 없습니다."
    exit 1
fi

transfer_kernel() {
    local ip=$1
    echo -n "ip : $ip 전송 중... "

    busybox ftpput -u "$USER_ID" -p "$USER_PW" "$ip" "$KERNEL_FILE"

    # 전송 결과를 장비 단위로 즉시 판정 -> 실패 장비를 바로 식별
    if [ $? -eq 0 ]; then
        echo "성공"
    else
        echo "실패"
    fi
}

echo "=== 커널 배포 시작: $KERNEL_FILE -> $PREFIX.$START_OCTET ~ $PREFIX.$END_OCTET ==="

for i in $(seq "$START_OCTET" "$END_OCTET"); do
    transfer_kernel "$PREFIX.$i"
done

echo "=== 배포 완료 ==="
echo "다음 단계: ./reboot_devices.sh 로 재기동 후 ./check_kernel_version.sh 로 검증"
