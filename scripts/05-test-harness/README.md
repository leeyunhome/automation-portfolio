# 05 · 테스트 하네스

CI 에 연동 가능한 회귀 테스트와, 테스트 입력 세트를 만드는 스크립트입니다.

## 파일

| 파일 | 역할 | 언어 |
|---|---|---|
| [`regression_test.sh`](regression_test.sh) | C 유틸리티 자동 회귀 테스트 | bash |
| [`sample_random_files.sh`](sample_random_files.sh) | 무작위 테스트 입력 세트 생성 | bash |

---

# regression_test.sh

디렉터리에서 `.bin` 파일을 열거하는 C 유틸리티에 대한 자동 회귀 테스트입니다.

```bash
./regression_test.sh              # 기본 실행 파일 (./list_files)
./regression_test.sh ./build/lister   # 경로 지정
echo $?                           # 0 = PASS, 1 = FAIL
```

## 구조 — setup → execute → verify → teardown

픽스처를 매번 새로 만들고 끝나면 지웁니다.
**이전 실행의 잔재가 결과에 영향을 주지 않도록** 하기 위함입니다.

```
setup     테스트 디렉터리 생성 + 엣지 케이스 파일 배치
execute   실행 파일에 넘겨 출력을 파일로 캡처
verify    정렬 후 기대값과 비교, 다르면 diff 출력
teardown  픽스처 제거
exit      판정 결과를 종료 코드로 전파
```

## 의도적으로 설계한 엣지 케이스

| 픽스처 | 기대 | 검증하는 분기 |
|---|---|---|
| `data1.bin` | 포함 | 정상 경로 |
| `data2.BIN` | 포함 | 확장자 **대소문자** |
| `.hidden.bin` | 포함 | **숨김 파일** 처리 |
| `document.txt` | 제외 | 확장자 필터 |
| `archive.zip` | 제외 | 확장자 필터 |
| `no_extension` | 제외 | **확장자 없음** |
| `sub_dir/` | 제외 | **파일 vs 디렉터리** |

이 조합이 "확장자 매칭 · 대소문자 · 숨김 파일 · 파일/디렉터리 구분"
네 가지 분기를 모두 덮습니다.

특히 `.hidden.bin` 은 판단이 필요한 케이스였습니다 —
숨김 파일이지만 `.bin` 이므로 **포함되어야 한다**는 것이 이 유틸리티의 사양입니다.
사양을 테스트로 고정해 두면 나중에 누가 `ls` 기반으로 리팩터링해도 바로 잡힙니다.

## 순서 비의존 비교

```bash
SORTED_ACTUAL=$(sort "$OUTPUT_FILE")
SORTED_EXPECTED=$(echo "$EXPECTED_OUTPUT" | sort)
```

디렉터리 순회 순서는 파일시스템과 커널 버전에 따라 달라집니다.
양쪽을 정렬한 뒤 비교해야 **환경이 바뀌어도 테스트가 깨지지 않습니다.**

## `set -e` 와 diff 의 충돌

```bash
diff <(echo "$SORTED_ACTUAL") <(echo "$SORTED_EXPECTED") || true
#                                                          ^^^^^^^
```

`diff` 는 차이가 있으면 non-zero 를 반환합니다.
`set -e` 가 켜져 있으므로 `|| true` 가 없으면 **실패 케이스에서 스크립트가
그 자리에서 죽어 teardown 이 실행되지 않습니다.**
픽스처가 남아 다음 실행을 오염시킵니다.

## CI 연동

```bash
EXECUTABLE=${1:-./list_files}   # 경로 파라미터화
...
exit $RESULT                    # 판정을 종료 코드로 전파
```

CI 파이프라인이 성공/실패를 그대로 인식합니다.
실행 파일이 없으면 컴파일 안내와 함께 FAIL 처리합니다.

---

# sample_random_files.sh

소스 디렉터리에서 이미지를 무작위 N개 뽑아 아카이브로 묶습니다.
장비에 올릴 테스트 입력 세트를 **매번 다르게** 만들기 위한 용도입니다.

```bash
./sample_random_files.sh ./images sample.tar.gz 150
./sample_random_files.sh ./images sample.zip
```

## 핵심 — NULL 구분자 파이프라인

파일명에 공백이나 개행이 들어 있으면, 개행 기준 파이프라인은
**파일 하나를 여러 개로 쪼갭니다.** 실제 데이터셋 파일명에 공백이 흔해서 겪은 문제입니다.

```
find ... -print0    │  결과를 NULL(\0) 로 구분해 출력
shuf -z             │  NULL 구분 입력 → NULL 구분 출력
xargs -0            │  NULL 구분 입력을 인자로 변환
tar --null -T -     │  NULL 구분 파일 목록을 stdin 에서 읽음
```

**한 곳이라도 개행 기준이면 체인 전체가 깨집니다.**
그래서 파이프라인 전 구간을 NULL 로 통일했습니다.

```bash
FIND_CMD="find '$SOURCE_DIR' -type f \( -iname '*.jpg' -o -iname '*.jpeg' \) -print0"

sh -c "$FIND_CMD" | shuf -z -n "$NUM_FILES" | tar -czvf "$OUTPUT_FILE" --null -T -
```

`-iname` 으로 대소문자 무관 매칭(`JPG`, `jpg`, `Jpeg`)도 함께 처리합니다.

## 지원하지 않는 포맷은 명확히 실패시킨다

```bash
*)
    echo "Error: Unsupported archive format '$OUTPUT_FILE'."
    echo "Supported: .zip, .tar.gz, .tgz, .tar.bz2, .tbz2, .tar.xz, .txz, .tar"
    exit 2
    ;;
```

조용히 넘어가면 "아카이브가 만들어졌겠지" 하고 다음 단계로 갔다가
나중에 발견하게 됩니다. 지원 목록과 함께 `exit 2` 로 즉시 중단합니다.

---

## 의존성

- `bash`, `coreutils` (`sort`, `shuf`, `diff`)
- `tar`, `zip` (사용하는 포맷에 따라)
- `shuf -z` 는 GNU coreutils 8.22 이상 필요
