#!/bin/bash
# =============================================================================
# check_uptime_parallel.sh
#
# 다수의 임베디드 리눅스 장비에서 uptime 을 "동시에" 수집하여
# 커널 리비전 그룹별로 정렬 출력한다.
#
# 목적
#   커널 리비전별 장기 안정성(무재부팅 시간)을 비교하기 위한 소킹 테스트 집계.
#   장비를 순차 접속하면 (장비 수 x telnet 왕복시간) 만큼 걸리므로,
#   워커를 백그라운드로 모두 띄우고 wait 으로 수렴시켜 실행시간을
#   "가장 느린 장비 1대" 수준으로 단축한다.
#
# 설계 포인트
#   1) 워커별 expect 스크립트를 heredoc 으로 동적 생성 -> 인용부호 지옥 회피
#   2) script(1) 로 PTY 를 확보 -> telnet 이 파이프에서도 정상 동작
#   3) 공유 결과 파일에 정렬 가능한 고정폭 포맷으로 append -> 완료 후 sort
#
# 사용법
#   DEVICE_USER=root DEVICE_PASS=secret ./check_uptime_parallel.sh
# =============================================================================

set -u

PREFIX="${DEVICE_SUBNET:-192.168.10}"
USER_ID="${DEVICE_USER:-root}"
USER_PW="${DEVICE_PASS:-changeme}"

RESULT_FILE="$(mktemp /tmp/uptime_results.XXXXXX)"
trap 'rm -f "$RESULT_FILE"' EXIT

# -----------------------------------------------------------------------------
# 워커: 장비 1대에 접속해 uptime 을 읽고 공유 결과 파일에 append
# -----------------------------------------------------------------------------
check_uptime() {
    local ip=$1
    local group=$2
    local expfile="/tmp/expect_${ip}.exp"
    local outfile="/tmp/output_${ip}.txt"

    # expect 스크립트를 장비별로 동적 생성
    cat > "$expfile" << EOF
log_user 1
set timeout 10
spawn telnet $ip
expect "login:"
send "$USER_ID\r"
expect "Password:"
send "$USER_PW\r"
expect "~#"
send "uptime\r"
expect "~#"
send "exit\r"
expect eof
EOF

    # script(1) 로 PTY 를 붙여 실행 (telnet 은 TTY 가 없으면 동작이 달라짐)
    script -q -c "expect $expfile" "$outfile" 2>/dev/null

    # telnet 출력의 CR 제거 후 uptime 라인만 추출
    #   - tr -d '\r'      : 원격 CRLF 정규화
    #   - grep -E 'up +[0-9]' : 배너/프롬프트 노이즈 배제
    local result
    result=$(tr -d '\r' < "$outfile" | grep -E 'up +[0-9]' | head -1 | xargs)
    rm -f "$expfile" "$outfile"

    # 고정폭 포맷으로 append -> 이후 sort 로 그룹 정렬이 가능해짐
    if [ -n "$result" ]; then
        printf "%-10s  %-20s  %s\n" "[$group]" "$ip" "$result" >> "$RESULT_FILE"
    else
        printf "%-10s  %-20s  %s\n" "[$group]" "$ip" "접속 실패 / 무응답" >> "$RESULT_FILE"
    fi
}

# -----------------------------------------------------------------------------
# IP 대역 = 커널 리비전 그룹 매핑
#   동일 조건에서 커널만 바꿔 비교하기 위해, 대역별로 리비전을 배정한다.
# -----------------------------------------------------------------------------
for i in {11..19}; do check_uptime "$PREFIX.$i" "rev-A"    & done
for i in {20..28}; do check_uptime "$PREFIX.$i" "rev-B"    & done
for i in {29..37}; do check_uptime "$PREFIX.$i" "rev-C"    & done
for i in {38..46}; do check_uptime "$PREFIX.$i" "rev-D"    & done
for i in {47..56}; do check_uptime "$PREFIX.$i" "baseline" & done

# 모든 워커 수렴 대기 (배리어)
wait

echo "====== 전체 업타임 확인 결과 ======"
printf "%-10s  %-20s  %s\n" "그룹" "IP" "업타임"
echo "------------------------------------------------------------"
sort "$RESULT_FILE"
echo "============================ 완료 ============================"
