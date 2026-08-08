#!/bin/bash
# =============================================================================
# regression_test.sh
#
# C 프로그램(디렉터리에서 .bin 파일을 열거하는 유틸)에 대한 자동 회귀 테스트.
#
# -----------------------------------------------------------------------------
# 구조: setup -> execute -> verify -> teardown
# -----------------------------------------------------------------------------
# 테스트 픽스처를 매번 새로 만들고 끝나면 지운다.
# 이전 실행의 잔재가 결과에 영향을 주지 않도록 하기 위함이다.
#
# -----------------------------------------------------------------------------
# 의도적으로 넣은 엣지 케이스
# -----------------------------------------------------------------------------
#   data1.bin      : 정상 케이스
#   data2.BIN      : 대문자 확장자 — 대소문자 구분 없이 잡아야 한다
#   .hidden.bin    : 숨김 파일 — 숨김이어도 .bin 이면 포함해야 한다
#   document.txt   : 다른 확장자 — 제외되어야 한다
#   archive.zip    : 다른 확장자 — 제외되어야 한다
#   no_extension   : 확장자 없음 — 제외되어야 한다
#   sub_dir/       : 디렉터리 — 파일이 아니므로 제외되어야 한다
#
# 이 조합이 "확장자 매칭", "대소문자", "숨김 파일", "파일 vs 디렉터리"
# 네 가지 분기를 모두 덮는다.
#
# -----------------------------------------------------------------------------
# CI 연동
# -----------------------------------------------------------------------------
#   - 실행 파일 경로를 인자로 받는다 (기본값 ./list_files)
#   - 마지막에 exit $RESULT 로 판정을 종료 코드에 실어 보낸다
#     -> CI 파이프라인이 성공/실패를 그대로 인식한다
#
# 사용법
#   ./regression_test.sh [executable]
# =============================================================================

# 예기치 못한 실패 시 즉시 중단 (단, 비교 구간은 별도 처리)
set -e

# --- Test Setup ---
TEST_DIR="test_dir_for_bin_lister"
EXECUTABLE=${1:-./list_files}
OUTPUT_FILE="test_output.txt"

echo "--- Setting up test environment ---"

# 이전 실행 잔재 제거
rm -rf "$TEST_DIR" "$OUTPUT_FILE"
mkdir "$TEST_DIR"

# 엣지 케이스를 포함한 픽스처 생성
touch "$TEST_DIR/data1.bin"        # 포함되어야 함
touch "$TEST_DIR/data2.BIN"        # 포함되어야 함 (대문자)
touch "$TEST_DIR/document.txt"     # 제외
touch "$TEST_DIR/archive.zip"      # 제외
touch "$TEST_DIR/.hidden.bin"      # 포함되어야 함 (숨김)
touch "$TEST_DIR/no_extension"     # 제외
mkdir  "$TEST_DIR/sub_dir"         # 제외 (디렉터리)

echo "Test directory created with the following contents:"
ls -a "$TEST_DIR"
echo "------------------------------------"


# --- Execution ---
echo "--- Running test ---"

if [ ! -f "$EXECUTABLE" ]; then
    echo "FAIL: Executable '$EXECUTABLE' not found."
    echo "      먼저 컴파일하세요: gcc main.c -o list_files"
    exit 1
fi

"$EXECUTABLE" "$TEST_DIR" > "$OUTPUT_FILE"


# --- Verification ---
echo "--- Verifying results ---"

# 기대 출력. 순서는 무관하므로 양쪽 모두 sort 한 뒤 비교한다.
# (디렉터리 순회 순서는 파일시스템에 따라 달라질 수 있다)
EXPECTED_OUTPUT=$(printf ".hidden.bin (size: 0 bytes)\ndata1.bin (size: 0 bytes)\ndata2.BIN (size: 0 bytes)\n")

SORTED_ACTUAL=$(sort "$OUTPUT_FILE")
SORTED_EXPECTED=$(echo "$EXPECTED_OUTPUT" | sort)

echo "Actual output (sorted):"
echo "$SORTED_ACTUAL"
echo ""
echo "Expected output (sorted):"
echo "$SORTED_EXPECTED"
echo "------------------------------------"

if [ "$SORTED_ACTUAL" == "$SORTED_EXPECTED" ]; then
    echo "PASS: Output matches the expected list of .bin files."
    RESULT=0
else
    echo "FAIL: Output does not match the expected list."
    echo "Difference:"
    # 프로세스 치환으로 임시 파일 없이 diff
    # '|| true' : diff 는 차이가 있으면 non-zero 를 반환하는데,
    #             set -e 때문에 여기서 스크립트가 죽으면 teardown 이 안 된다
    diff <(echo "$SORTED_ACTUAL") <(echo "$SORTED_EXPECTED") || true
    RESULT=1
fi


# --- Teardown ---
echo "--- Cleaning up test environment ---"
rm -rf "$TEST_DIR" "$OUTPUT_FILE"
echo "Cleanup complete."

# 판정 결과를 종료 코드로 전파 (CI 연동)
exit $RESULT
