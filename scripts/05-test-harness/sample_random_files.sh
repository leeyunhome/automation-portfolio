#!/bin/bash
# =============================================================================
# sample_random_files.sh
#
# 소스 디렉터리에서 이미지 파일을 무작위로 N개 뽑아 아카이브로 묶는다.
# (장비에 올릴 테스트 입력 세트를 매번 다르게 만들기 위한 용도)
#
# -----------------------------------------------------------------------------
# 핵심: NULL 구분자 파이프라인
# -----------------------------------------------------------------------------
# 파일명에 공백이나 따옴표, 개행이 들어 있으면 개행 기준 파이프라인은
# 파일 하나를 여러 개로 쪼개거나 엉뚱한 경로를 만든다.
# 실제로 데이터셋 파일명에 공백이 흔해서 겪은 문제다.
#
# 그래서 파이프라인 전 구간을 NULL(\0) 구분자로 통일했다.
#
#   find -print0   : 결과를 NULL 로 구분해 출력
#   shuf -z        : NULL 구분 입력을 받아 NULL 구분으로 출력
#   xargs -0       : NULL 구분 입력을 인자로 변환
#   tar --null -T -: NULL 구분 파일 목록을 표준입력에서 읽음
#
# 한 곳이라도 개행 기준이면 체인 전체가 깨지므로 모두 맞춰야 한다.
#
# 사용법
#   ./sample_random_files.sh <source_dir> <output_archive> [num_files]
#   예) ./sample_random_files.sh ./images sample.tar.gz 150
# =============================================================================

usage() {
    echo "Usage: $0 <source_directory> <output_archive_name> [num_files]"
    echo
    echo "Arguments:"
    echo "  <source_directory>    : 이미지 파일이 있는 원본 폴더"
    echo "  <output_archive_name> : 생성할 압축 파일명 (예: sample.zip, images.tar.gz)"
    echo "  [num_files]           : 무작위 추출 개수 (기본값: 100)"
    echo
    echo "Example:"
    echo "  $0 ./images my_random_pics.zip 150"
    echo "  $0 ./images my_images.tar.gz"
}

if [ "$#" -lt 2 ]; then
    usage
    exit 1
fi

SOURCE_DIR="$1"
OUTPUT_FILE="$2"
NUM_FILES=${3:-100}

if [ ! -d "$SOURCE_DIR" ]; then
    echo "Error: Source directory '$SOURCE_DIR' does not exist."
    exit 1
fi

echo "Source:     $SOURCE_DIR"
echo "Output:     $OUTPUT_FILE"
echo "Count:      $NUM_FILES"
echo "-----------------------------------"

# -iname 으로 대소문자 무관 매칭 (JPG, jpg, Jpeg 등)
# -print0 으로 NULL 구분 출력 — 파이프라인의 시작점
FIND_CMD="find '$SOURCE_DIR' -type f \( -iname '*.jpg' -o -iname '*.jpeg' \) -print0"

case "$OUTPUT_FILE" in
    *.zip)
        echo "Creating .zip archive..."
        sh -c "$FIND_CMD" | shuf -z -n "$NUM_FILES" | xargs -0 zip "$OUTPUT_FILE"
        ;;

    *.tar.gz | *.tgz)
        echo "Creating .tar.gz archive..."
        sh -c "$FIND_CMD" | shuf -z -n "$NUM_FILES" | tar -czvf "$OUTPUT_FILE" --null -T -
        ;;

    *.tar.bz2 | *.tbz2)
        echo "Creating .tar.bz2 archive..."
        sh -c "$FIND_CMD" | shuf -z -n "$NUM_FILES" | tar -cjvf "$OUTPUT_FILE" --null -T -
        ;;

    *.tar.xz | *.txz)
        echo "Creating .tar.xz archive..."
        sh -c "$FIND_CMD" | shuf -z -n "$NUM_FILES" | tar -cJvf "$OUTPUT_FILE" --null -T -
        ;;

    *.tar)
        echo "Creating .tar archive (no compression)..."
        sh -c "$FIND_CMD" | shuf -z -n "$NUM_FILES" | tar -cvf "$OUTPUT_FILE" --null -T -
        ;;

    *)
        # 지원하지 않는 포맷은 조용히 넘어가지 않고 명확히 실패시킨다
        echo "Error: Unsupported archive format '$OUTPUT_FILE'."
        echo "Supported: .zip, .tar.gz, .tgz, .tar.bz2, .tbz2, .tar.xz, .txz, .tar"
        exit 2
        ;;
esac

echo "-----------------------------------"
if [ $? -eq 0 ]; then
    echo "Success: '$OUTPUT_FILE' created with $NUM_FILES random images."
else
    echo "Error: Failed to create archive."
fi
