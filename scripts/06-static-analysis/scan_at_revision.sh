#!/bin/bash
# =============================================================================
# scan_at_revision.sh
#
# 지정한 "날짜 시점" 의 소스로 되돌려 정적분석을 수행하고, 끝나면 원복한다.
#
# -----------------------------------------------------------------------------
# 왜 만들었는가
# -----------------------------------------------------------------------------
# "이 취약점이 언제 코드에 들어왔는가" 를 알아야 할 때가 있다.
# 현재 시점만 스캔해서는 알 수 없고, 과거 리비전을 하나씩 수동으로 체크아웃해
# 분석하는 것은 반복 작업이다.
#
# 이 스크립트는 날짜를 인자로 받아
#   그 날짜 이전의 최신 커밋 탐색 -> 체크아웃 -> 전체 SCA -> 원복
# 을 한 번에 수행한다. 날짜를 바꿔 가며 여러 번 돌리면
# 이슈 건수의 변화 지점(= 유입 시점)이 드러난다.
#
# 커널 CVE 백포팅에서 "패치 전/후를 같은 기준으로 비교" 하는 것과 같은 구조다.
#
# -----------------------------------------------------------------------------
# 안전장치
# -----------------------------------------------------------------------------
# 작업 트리를 과거로 되돌리므로, 어떤 경로로 끝나든 반드시 원래 브랜치로 복구해야 한다.
#   - 시작 시 현재 브랜치/커밋을 기록
#   - trap EXIT 으로 정상 종료 / 실패 / 중단(Ctrl-C) 모두에서 복구 실행
#
# 원본에서는 각 단계마다 수동으로 복구 코드를 넣었는데,
# 경로가 늘어날수록 빠뜨리기 쉬워 trap 방식으로 정리했다.
#
# 사용법
#   ./scan_at_revision.sh 2026-05-26
#
# 필요 환경변수
#   SONAR_HOST_URL, SONAR_TOKEN   (자격증명은 코드에 두지 않는다)
# =============================================================================

set -euo pipefail

# ── 인자 ──────────────────────────────────────────────────
TARGET_DATE="${1:-}"
if [ -z "$TARGET_DATE" ]; then
    echo "Usage: $0 <YYYY-MM-DD>"
    echo "  예) $0 2026-05-26"
    exit 1
fi

# ── 설정 (환경변수로 주입) ────────────────────────────────
REPO_DIR="${REPO_DIR:-$(pwd)}"
TARGET_DIR="${TARGET_DIR:-$REPO_DIR/src}"
SONAR_URL="${SONAR_HOST_URL:?SONAR_HOST_URL 환경변수를 설정하세요}"
SONAR_TOKEN="${SONAR_TOKEN:?SONAR_TOKEN 환경변수를 설정하세요}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONVERT_PY="$SCRIPT_DIR/convert_cppcheck_to_sonar.py"
SCAN_PY="$SCRIPT_DIR/scan_banned_functions.py"

LOG_DIR="${LOG_DIR:-$SCRIPT_DIR/logs}"
FOLDER_NAME=$(basename "$TARGET_DIR")
DATETIME=$(date +"%Y%m%d_%H%M")
DATE_CLEAN=$(echo "$TARGET_DATE" | tr -d '-')
PROJECT_KEY="${FOLDER_NAME}-at-${DATE_CLEAN}"
PROJECT_NAME="${FOLDER_NAME} at ${TARGET_DATE}"
LOG_FILE="${LOG_DIR}/sca_${FOLDER_NAME}_at${DATE_CLEAN}_${DATETIME}.log"

mkdir -p "$LOG_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

# ── 복구 보장 ─────────────────────────────────────────────
# 작업 트리를 과거로 되돌린 상태로 스크립트가 끝나면 안 된다.
# 정상 종료 / 실패 / Ctrl-C 어느 경로로 나가든 원래 브랜치로 복구한다.
restore_branch() {
    local rc=$?
    log "[복구] 원래 브랜치로 복구 중..."
    cd "$REPO_DIR"
    git checkout "$CURRENT_REF" >> "$LOG_FILE" 2>&1 || true
    log "복구 완료 (현재: $(git rev-parse --short HEAD 2>/dev/null || echo unknown))"
    exit $rc
}

log "======================================================"
log " 날짜 지정 정적분석"
log " 기준 날짜  : $TARGET_DATE"
log " Project Key: $PROJECT_KEY"
log "======================================================"

cd "$REPO_DIR"
# 브랜치명이 있으면 브랜치로, 없으면(detached HEAD) 커밋 해시로 기록해야
# 복구 시점에 정확히 원래 위치로 돌아갈 수 있다.
CURRENT_REF=$(git symbolic-ref --short -q HEAD || git rev-parse HEAD)
log "현재 위치: $CURRENT_REF"

trap restore_branch EXIT INT TERM

# ── Step 0. 해당 날짜 이전 최신 커밋으로 체크아웃 ──────────
log "[Step 0] $TARGET_DATE 시점으로 체크아웃"

# git log 해설:
#   --before="X"    X 이전에 커밋된 것
#   -1               그중 가장 최신 (log 는 최신순으로 나열되므로 첫 줄)
#   HEAD             현재 브랜치의 조상들로 한정 (다른 브랜치의 커밋 배제)
# -> "그 날짜에 실제로 빌드되던 코드" 를 정확히 집어낸다
NEXT_DAY=$(date -d "$TARGET_DATE + 1 day" +%Y-%m-%d)
TARGET_REV=$(git log -1 --before="$NEXT_DAY" --format="%H" HEAD 2>/dev/null || true)

if [ -z "$TARGET_REV" ]; then
    log "ERROR: $TARGET_DATE 이전 커밋을 찾을 수 없습니다."
    exit 1
fi

log "체크아웃 커밋: $TARGET_REV"
git checkout "$TARGET_REV" >> "$LOG_FILE" 2>&1
log "체크아웃 완료"

# ── Step 1. cppcheck ──────────────────────────────────────
log "[Step 1] cppcheck 실행"
cd "$TARGET_DIR"

# --enable=all 로 전부 켜되, 노이즈성 룰은 여기서 억제한다.
#   missingInclude : 크로스 컴파일 환경에서 시스템 헤더를 못 찾아 대량 발생
#   unusedFunction : 라이브러리성 코드에서는 정상 (외부에서 호출)
cppcheck --enable=all --std=c11 --xml --xml-version=2 \
    --suppress=missingInclude \
    --suppress=unusedFunction \
    -I . . \
    2> cppcheck-report.xml

ERROR_COUNT=$(grep -c '<error ' cppcheck-report.xml || echo "0")
log "cppcheck 완료 — ${ERROR_COUNT}건"

# ── Step 2. SonarQube 포맷 변환 ───────────────────────────
log "[Step 2] cppcheck -> sonar-issues.json 변환"
python3 "$CONVERT_PY" cppcheck-report.xml -o sonar-issues.json --base-path . \
    >> "$LOG_FILE" 2>&1
log "변환 완료"

# ── Step 3. 금지 함수 스캔 + 병합 ─────────────────────────
log "[Step 3] 금지 함수 스캔 + 병합"
python3 "$SCAN_PY" . -o sonar-issues.json --merge \
    --csv banned-functions-report.csv >> "$LOG_FILE" 2>&1
log "금지 함수 스캔 완료"

# ── Step 4. 업로드 ────────────────────────────────────────
log "[Step 4] sonar-scanner 실행"
sonar-scanner \
    -Dsonar.projectKey="$PROJECT_KEY" \
    -Dsonar.projectName="$PROJECT_NAME" \
    -Dsonar.sources=. \
    -Dsonar.host.url="$SONAR_URL" \
    -Dsonar.token="$SONAR_TOKEN" \
    -Dsonar.externalIssuesReportPaths=sonar-issues.json \
    -Dsonar.sourceEncoding=UTF-8 \
    -Dsonar.cxx.file.suffixes=.c,.cpp,.cc,.cxx,.h,.hpp \
    >> "$LOG_FILE" 2>&1

log "======================================================"
log " 완료"
log " 기준 날짜 : $TARGET_DATE (커밋: $TARGET_REV)"
log " 대시보드  : ${SONAR_URL}/dashboard?id=${PROJECT_KEY}"
log " 로그      : $LOG_FILE"
log "======================================================"

# trap 이 여기서 원래 브랜치로 복구를 수행한다
