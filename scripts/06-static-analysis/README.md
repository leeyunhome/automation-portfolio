# 06 · 정적분석 · 보안 취약점 대응 자동화

레거시 C 코드베이스의 취약점을 자동으로 찾고, 대시보드에 올리고,
대규모로 일괄 수정하기 위한 도구 모음입니다.

## 파일

| 파일 | 역할 | 언어 |
|---|---|---|
| [`scan_banned_functions.py`](scan_banned_functions.py) | 금지 함수 검사 → SonarQube JSON 리포트 | python3 |
| [`convert_cppcheck_to_sonar.py`](convert_cppcheck_to_sonar.py) | cppcheck XML → SonarQube JSON 변환 | python3 |
| [`scan_at_revision.sh`](scan_at_revision.sh) | 특정 날짜 시점으로 되돌려 스캔 후 원복 | bash |
| [`safe_string.cocci`](safe_string.cocci) | 위험 함수를 경계검사 래퍼로 일괄 치환 | Coccinelle (SmPL) |
| [`replay_build_log.py`](replay_build_log.py) | 빌드 로그를 재생해 SAST 분석기로 크로스컴파일 후킹 우회 | python3 |

## 파이프라인

```
hg update -r <과거 리비전>        scan_at_revision.sh
      ↓
cppcheck --enable=all --xml       정적분석
      ↓
convert_cppcheck_to_sonar.py      SonarQube 스키마로 번역
      ↓
scan_banned_functions.py --merge  정책 기반 검사 결과 병합
      ↓
sonar-scanner                     대시보드 업로드
      ↓
hg update tip                     원복 (trap 으로 보장)
```

```bash
export SONAR_HOST_URL=https://sonar.example.com
export SONAR_TOKEN=****

./scan_at_revision.sh 2026-05-26
```

---

# scan_banned_functions.py

## 왜 만들었는가

보안 인증 심사에서 "금지 함수 목록에 대한 사용 현황과 대응 방안" 을 제출해야 했습니다.

- **cppcheck** 는 이런 정책 기반 검사를 하지 않습니다
- **Flawfinder** 는 자체 목록을 쓰기 때문에 심사 기준으로 지정된 목록과 일치시킬 수 없습니다

그래서 `함수명 → CWE → 위험도 → 권장 대체 함수` 를 테이블로 정의하고,
그 테이블을 **단일 진실 공급원(single source of truth)** 으로 삼아
검사 · 통계 · 리포트를 모두 생성하도록 만들었습니다.

```python
BANNED_FUNCTIONS = {
    "gets":    {"cwe": "CWE-120", "risk": "CRITICAL", "alt": "fgets(buf, size, stdin)", "cat": "buffer_overflow"},
    "strcpy":  {"cwe": "CWE-120", "risk": "HIGH",     "alt": "strncpy() or strlcpy()",  "cat": "buffer_overflow"},
    "system":  {"cwe": "CWE-78",  "risk": "CRITICAL", "alt": "exec*() family directly", "cat": "command_injection"},
    "mktemp":  {"cwe": "CWE-377", "risk": "HIGH",     "alt": "mkstemp()",               "cat": "temp_file"},
    ...
}
```

검사 패턴, 위험도 판정, 리포트 메시지, 통계가 전부 여기서 파생됩니다.
목록이 바뀌면 한 곳만 고치면 됩니다.

**커버 범위:** 44개 함수 / 9개 카테고리
(buffer_overflow, memory, input, filesystem, temp_file, command_injection,
allocation, environment, race_condition)

## 오탐을 줄이는 전처리

정규식만으로 소스를 훑으면 실행되지 않는 코드까지 잡힙니다.

| 처리 | 이유 |
|---|---|
| 블록 주석 제거 (상태 머신) | 여러 줄에 걸치므로 `in_block_comment` 상태를 들고 순회 |
| 한 줄 주석 제거 | `// strcpy(a, b)` 는 사용처가 아님 |
| `#include` / `#define` 스킵 | 매크로 **정의**는 사용처가 아님 |
| `\b(name)\s*\(` 패턴 | `my_strcpy_wrapper` 같은 부분 일치 배제, 공백 낀 호출은 포착 |

```python
def _build_pattern():
    names = "|".join(re.escape(f) for f in BANNED_FUNCTIONS)
    return re.compile(rf"\b({names})\s*\(")
```

## SonarQube 와의 연동

자체 포맷을 만들지 않고 SonarQube 가 이미 이해하는
**Generic Issue Import 스키마**로 출력합니다.
대시보드 · 추이 그래프 · 담당자 지정 기능을 그대로 얻을 수 있습니다.

```python
"message": (f"[{f['cwe']}] Banned function '{f['function']}()' used. "
            f"Replace with: {f['alternative']}")
```

메시지에 CWE 와 대체 함수를 함께 넣어, 대시보드에서 바로 조치 방법을 알 수 있게 했습니다.

## 재실행 안전성 (idempotent)

```python
existing["issues"] = [
    i for i in existing.get("issues", [])
    if i.get("engineId") != "banned-function-scanner"
]
existing["issues"].extend(new_json["issues"])
```

`--merge` 할 때 **자기 자신이 만든 이슈를 먼저 제거**하고 새로 넣습니다.
그렇지 않으면 재스캔할 때마다 같은 이슈가 누적되어 통계가 망가집니다.
몇 번을 돌려도 결과가 같습니다.

---

# convert_cppcheck_to_sonar.py

## 왜 필요한가

SonarQube 커뮤니티 에디션은 C/C++ 을 기본 분석하지 않습니다.
대신 외부 분석기 결과를 표준 스키마로 받아들이는 경로를 제공하므로,
cppcheck 결과를 번역하면 SonarQube 의 기능을 그대로 쓸 수 있습니다.

## severity / type 이원 매핑

cppcheck 의 severity 하나를 SonarQube 의 **두 축**으로 나눕니다.

| cppcheck | SonarQube severity | SonarQube type |
|---|---|---|
| `error` | CRITICAL | **BUG** |
| `warning` | MAJOR | **BUG** |
| `style` | MINOR | CODE_SMELL |
| `performance` | MINOR | CODE_SMELL |
| `portability` | MINOR | CODE_SMELL |
| `information` | INFO | CODE_SMELL |

"고쳐야 하는 결함(BUG)" 과 "정리하면 좋은 코드(CODE_SMELL)" 가
대시보드에서 섞이지 않아야 우선순위를 매길 수 있습니다.

## 노이즈 필터링

```python
NOISE_RULES = {"missingIncludeSystem"}
```

크로스 컴파일 환경에서는 시스템 헤더 경로를 cppcheck 가 알 수 없어
이 경고가 **수천 건** 쏟아집니다. 실제 결함이 아니므로 변환 단계에서 버립니다.
**이걸 걸러야 나머지 신호가 보입니다.**

## 경로 정규화

```bash
--base-path ./src
```

SonarQube 는 `sonar.sources` 기준 상대 경로를 기대하는데
cppcheck 는 실행 위치에 따라 절대/상대 경로를 섞어 냅니다.
경로가 어긋나면 이슈가 "파일 없음" 으로 붙어 **대시보드에 아예 나타나지 않습니다.**

---

# scan_at_revision.sh

## 왜 만들었는가

**"이 취약점이 언제 코드에 들어왔는가"** 를 알아야 할 때가 있습니다.
현재 시점만 스캔해서는 알 수 없고, 과거 리비전을 하나씩 수동으로 체크아웃해
분석하는 것은 반복 작업입니다.

날짜를 인자로 받아
`그 날짜 이전의 최신 리비전 탐색 → 체크아웃 → 전체 SCA → 원복` 을 한 번에 수행합니다.
날짜를 바꿔 가며 여러 번 돌리면 **이슈 건수의 변화 지점(= 유입 시점)** 이 드러납니다.

> 커널 CVE 백포팅에서 "패치 전/후를 같은 기준으로 비교" 하는 것과 같은 구조입니다.

## 리비전 탐색

```bash
hg log -r "max(ancestors(tip) and date('< $NEXT_DAY'))" --template "{rev}\n"
```

| 절 | 의미 |
|---|---|
| `ancestors(tip)` | 현재 브랜치의 조상으로 한정 — 다른 헤드의 커밋 배제 |
| `date('< X')` | X 이전에 커밋된 것 |
| `max(...)` | 그중 가장 최신 |

**"그 날짜에 실제로 빌드되던 코드"** 를 정확히 집어냅니다.
단순히 날짜로 필터링하면 다른 브랜치의 커밋이 섞여 재현이 안 됩니다.

## 복구 보장 — trap

작업 트리를 **과거로 되돌린 상태로 스크립트가 끝나면 안 됩니다.**

```bash
restore_tip() {
    local rc=$?
    cd "$REPO_DIR"
    hg update tip >> "$LOG_FILE" 2>&1 || true
    exit $rc
}
trap restore_tip EXIT INT TERM
```

정상 종료 · 실패 · Ctrl-C 어느 경로로 나가든 복구가 실행됩니다.

> 원본에서는 각 단계마다 수동으로 복구 코드를 넣었는데
> (`[ $? -ne 0 ] && hg update ... && exit 1`),
> 경로가 늘어날수록 빠뜨리기 쉬워 `trap` 방식으로 정리했습니다.

## cppcheck 억제 룰

```bash
--suppress=missingInclude    # 크로스 컴파일에서 시스템 헤더를 못 찾아 대량 발생
--suppress=unusedFunction    # 라이브러리성 코드에서는 정상 (외부에서 호출)
```

`--enable=all` 로 전부 켜되, 이 두 가지는 구조적으로 발생하는 노이즈라 억제합니다.

---

# replay_build_log.py

## 왜 필요한가

상용 SAST 도구는 보통 **"빌드를 후킹"** 하는 방식으로 동작합니다.
`sourceanalyzer -b <id> make` 처럼 make 앞에 붙어서, make 가 실제로 실행하는
컴파일러 호출을 가로채 분석에 필요한 정보를 수집합니다.

그런데 이 방식은 크로스컴파일 환경에서 자주 실패합니다.

- 빌드 시스템이 커스텀 래퍼 스크립트로 컴파일러를 감싸고 있거나
- 여러 단계의 서브 make 가 겹쳐 후킹이 일부만 걸리거나
- 툴체인 특성상 후킹 프로세스 자체가 크래시하는 경우가 있습니다

원인을 하나씩 디버깅하는 대신, **이미 성공적으로 완료된 빌드의 로그**를
파싱해서 "그때 실행됐던 컴파일 명령을 그대로 다시 sourceanalyzer 로 실행"
하는 방식으로 우회했습니다. 빌드는 정상적으로 한 번 끝났으니 로그에는
실제로 사용된 정확한 플래그와 include 경로가 전부 남아 있습니다.

## 동작 원리 — 디렉터리 스택 복원

GNU make 는 서브 make 호출 시 자동으로 다음과 같은 로그를 남깁니다.

```
make[2]: Entering directory '/build/src/drivers'
...
riscv64-unknown-linux-gnu-gcc -Wall -I../include -c foo.c -o foo.o
...
make[2]: Leaving directory '/build/src/drivers'
```

`-I../include` 같은 **상대 경로**는 컴파일이 실행된 디렉터리를 알아야
올바르게 해석됩니다. 이 스크립트는 `Entering`/`Leaving` 두 마커를
스택으로 추적해 각 컴파일 명령이 어느 디렉터리에서 실행됐는지 복원합니다.

```python
if enter_match:
    cwd_stack.append(directory)
if leave_match:
    cwd_stack.pop()

cwd = cwd_stack[-1] if cwd_stack else os.getcwd()
# 이 cwd 에서 sourceanalyzer 를 실행해야 상대 include 경로가 풀린다
```

이 복원이 없으면 분석기가 헤더를 못 찾아 분석 자체가 반쪽짜리가 됩니다.

## 한계

- make 가 디렉터리를 출력하지 않는 빌드 시스템에는 이 방식이 안 통합니다.
  그 경우 빌드 스크립트에 `echo "===CWD:$(pwd)==="` 같은 커스텀 마커를
  직접 심어 같은 원리로 추적하는 변형이 필요합니다.
- 컴파일이 실패했던 명령은 로그에 없으므로 재현되지 않습니다
  (분석 대상은 "성공한 빌드"로 한정됩니다).

```bash
./replay_build_log.py build.log firmware-scan-01
sourceanalyzer -b firmware-scan-01 -scan -f results.fpr   # 재생 완료 후 리포트 생성
```

---

# safe_string.cocci

레거시 C 코드베이스 전체의 위험한 표준 함수 호출을
경계 검사가 들어간 래퍼로 **일괄 치환**하는 Coccinelle 시맨틱 패치입니다.

```bash
# 미리보기 (원본 수정 없음)
spatch --sp-file safe_string.cocci --dir ./src > safe_string.patch

# 실제 적용
spatch --sp-file safe_string.cocci --dir ./src --in-place
```

## 왜 sed 가 아니라 Coccinelle 인가

텍스트 치환으로는 다음을 구분할 수 없습니다.

- 주석이나 문자열 리터럴 안의 `"strcpy"`
- `my_strcpy_wrapper()` 같은 부분 일치
- 매크로 정의부와 실제 호출부
- 인자 안에 괄호나 콤마가 중첩된 경우

Coccinelle 은 **C 파서 위에서 동작**하므로 "함수 호출" 이라는 구문 구조를 인식합니다.
그리고 결정적으로, 치환 결과에 **원래 인자에서 파생된 표현식**을 넣을 수 있습니다.

## 치환 설계

```c
strcpy(dst, src)
  → safe_strcpy(NULL, NULL, sizeof(dst), strlen(src), dst, src)
                             ~~~~~~~~~~~~~~~~~~~~~~~~
                             호출 지점에서 자동 생성되는 경계 정보
```

래퍼는 목적지 버퍼 크기와 소스 길이를 받아 런타임에 검증합니다.
그 크기 정보를 `sizeof(DST)` / `strlen(SRC)` 로 **자동 생성하는 것이 이 패치의 핵심**입니다.
사람이 수천 곳을 손으로 고치면 반드시 실수가 납니다.

앞의 `NULL` 두 개는 래퍼가 받는 (파일명, 함수명) 슬롯으로,
`__FILE__`, `__func__` 로 채우면 위반 발생 시 위치 추적이 가능합니다.

**커버 범위:** `snprintf` `sprintf` `strcpy` `strncpy` `strlcpy`
`strcat` `strncat` `memcpy` `memcmp` `malloc` `strcmp`

## 주의 — `sizeof(DST)` 의 함정

`DST` 가 **배열**이면 `sizeof` 는 버퍼 크기를 주지만,
**포인터**면 포인터 크기(4/8 바이트)를 줍니다.

따라서 이 패치는 "배열 버퍼로 선언된 목적지" 에 대해서만 안전하며,
적용 후 포인터 인자 호출부는 별도로 검토해야 합니다.

> **자동화가 사람의 판단을 완전히 대체하지는 않습니다.**
> 다만 검토 대상을 수천 곳에서 수십 곳으로 줄여 줍니다.

---

## 의존성

| 도구 | 용도 |
|---|---|
| `python3` | 스캐너 · 변환기 (표준 라이브러리만) |
| `cppcheck` | 정적분석 |
| `sonar-scanner` | SonarQube 업로드 |
| `hg` (Mercurial) | 리비전 체크아웃 |
| `spatch` (Coccinelle) | 시맨틱 패치 적용 |
| `flawfinder` | 선택 — `--with-flawfinder` 사용 시 |
| SAST 소스 분석기 (`sourceanalyzer` 등) | `replay_build_log.py` 사용 시 |

```bash
sudo apt install cppcheck coccinelle mercurial
pip install flawfinder
```

## 보안 주의

자격증명은 **반드시 환경변수로 주입**하세요.
원본 스크립트에는 SonarQube 토큰이 하드코딩되어 있었고,
이를 공개용으로 정리하며 `${SONAR_TOKEN:?}` 형태로 변경했습니다.

```bash
export SONAR_HOST_URL=https://sonar.example.com
export SONAR_TOKEN=****
```

`:?` 는 변수가 없으면 즉시 실패시켜, 빈 토큰으로 스캔이 조용히 실패하는 것을 막습니다.
