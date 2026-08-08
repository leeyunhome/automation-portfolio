# 임베디드 리눅스 테스트 자동화 포트폴리오

다수의 임베디드 리눅스 장비를 대상으로 **커널 배포 · 안정성 검증 · 부하 인가 · 커널 로그 이상 탐지 · 성능 정량화**를
무인으로 수행하기 위해 작성한 Shell / Python 자동화 스크립트 모음입니다.

**[→ GitHub Pages 에서 전체 설명 보기](https://leeyunhome.github.io/automation-portfolio/)**

---

## 배경

임베디드 장비의 펌웨어 안정성은 "한 대를 오래 켜 두고 지켜보는" 방식으로는 검증되지 않습니다.
간헐적 결함은 표본이 충분해야 드러나고, 커널을 바꿔 가며 비교하려면 동일 조건에서 여러 대를 동시에 돌려야 합니다.

그런데 대상 장비는 busybox 기반 최소 루트파일시스템이라
`ssh` 도 `stress-ng` 도 `perf` 도 없고, 접속 수단은 telnet 뿐이었습니다.
가진 것만으로 검증 인프라를 만들어야 했고, 그 결과물이 이 저장소입니다.

| 항목 | 규모 |
|---|---|
| 동시 제어 장비 수 | 46대 |
| 전수 점검 소요 시간 | 11초 (순차 실행 대비 약 40배) |
| 커널 리비전 A/B 그룹 | 5개 (그룹당 9~10대) |
| 공개 스크립트 | 18개 |

---

## 구성

각 폴더에는 **해당 스크립트들의 설계 의도와 판단 근거를 설명하는 `README.md`** 가 함께 있습니다.

```
scripts/
├── 01-device-farm/          장비 팜 병렬 제어 + 커널 로그 분석
│   ├── README.md                    ← 병렬화 설계, telnet 함정, 타임스탬프 필터링
│   ├── deploy_kernel.sh             커널 이미지 FTP 일괄 플래싱
│   ├── reboot_devices.sh            46대 동시 재부팅
│   ├── check_kernel_version.sh      탑재 커널 빌드 번호 전수 검증
│   ├── check_uptime_parallel.sh     uptime 병렬 수집 · 그룹별 집계
│   ├── collect_dmesg.exp            dmesg 전량 수집 (expect)
│   └── analyze_link_events.sh       부팅 이후 링크 플랩 자동 탐지
├── 02-stress-test/
│   ├── README.md                    ← 부하 인가 방식 선택 근거, 자기 종료형 명령
│   └── run_remote_stress.py         CPU/MEM/NET 원격 부하 인가 오케스트레이터
├── 03-performance/
│   ├── README.md                    ← sync 포함 측정, 집합 차분 클린업, OCR 검증
│   ├── measure_extract_overhead.py  압축 해제 오버헤드 벤치마크
│   └── measure_latency_ocr.py       Glass-to-Glass 지연 OCR 측정
├── 04-device-ops/
│   ├── README.md                    ← busybox 환경 차이 대응 사례
│   ├── collect_system_info.py       원격 시스템 정보 일괄 수집
│   ├── check_process_farm.py        SSH 병렬 접속 프로세스 상태 전수 점검
│   └── stop_services.sh             애플리케이션 데몬 안전 종료
├── 05-test-harness/
│   ├── README.md                    ← 엣지 케이스 설계, CI 연동
│   ├── regression_test.sh           C 유틸리티 회귀 테스트
│   └── sample_random_files.sh       무작위 테스트 입력 세트 생성
└── 06-static-analysis/      정적분석 · 보안 취약점 대응
    ├── README.md                    ← 정책 기반 검사, 리비전 시점 추적, 시맨틱 패치
    ├── scan_banned_functions.py     금지 함수 검사 → SonarQube 리포트
    ├── convert_cppcheck_to_sonar.py cppcheck XML → SonarQube JSON 변환
    ├── scan_at_revision.sh          특정 날짜 시점으로 되돌려 스캔 후 원복
    └── replay_build_log.py          빌드 로그 재생으로 SAST 크로스컴파일 후킹 우회

samples/     실제 실행 출력 예시
assets/img/  구조도 · 다이어그램 (SVG)
```

---

## 대표 사례

### 1. 46대 병렬 제어 — 실행시간을 "가장 느린 1대" 수준으로

장비 한 대당 telnet 왕복에 8~10초. 46대를 순차로 돌면 6~8분이 걸리고,
그동안 첫 장비와 마지막 장비의 관측 시점이 벌어져 **그 시차가 그대로 uptime 비교의 오차**가 됩니다.

46개 워커를 모두 백그라운드로 띄우고 `wait` 으로 수렴시켜 11초로 단축했습니다.
락 없이 결과를 모으기 위해, 각 워커가 **한 줄짜리 고정폭 레코드**를 append 하고 수렴 후 `sort` 로 정렬합니다.

```bash
printf "%-10s  %-20s  %s\n" "[$group]" "$ip" "$result" >> "$RESULT_FILE"

for i in {11..19}; do check_uptime "$PREFIX.$i" "rev-A" & done
# ...
wait
sort "$RESULT_FILE"
```

### 2. 커널 로그 이상 탐지 — 46대 → 2대로 좁히기

간헐적 네트워크 단절을 조사하며 dmesg 를 `grep "Link is"` 로 훑었더니
**정상 장비를 포함해 46대 전부가 걸렸습니다.** 부팅 시 PHY 협상 로그가 모든 장비에 있기 때문입니다.

판정 기준이 "이벤트가 있느냐"가 아니라 **"언제 발생했느냐"** 여야 했습니다.
커널 링 버퍼 타임스탬프를 파싱해 부팅 후 60초를 경계로 노이즈를 걸러냅니다.

```bash
timestamp=$(echo "$line" | grep -oP '\[\s*\K[0-9]+(?=\.)')
#                                   \[\s*  여는 대괄호 + 공백
#                                   \K     여기까지는 매치 결과에서 제외
#                                   [0-9]+ 정수부
#                                   (?=\.) 뒤에 소수점이 오는 경우만
```

필터링 후 실제 이상 장비 2대만 남았고, 조사 대상이 좁혀지자 원인 분석이 가능해졌습니다.

### 3. 성능 측정 — `sync` 를 붙이느냐로 결론이 갈린다

"기동 시 모델 로딩이 느리다"는 정성적 보고를 정량화했습니다.
`tar -zxf` 와 `tar -zxvf` 의 해제 시간을 파일 크기별로 비교했습니다.

측정 정확도를 위해:
- **`sync` 포함 측정** — 없이 재면 페이지 캐시에만 쓰고 반환되는 시간을 재게 되어 실제 스토리지 쓰기 완료 시점을 놓칩니다
- **매 측정 전 동일 시작 조건 복원** — 직전 측정의 잔재가 있으면 tar 가 덮어쓰기를 하며 시간이 달라집니다
- **집합 차분 기반 안전 클린업** — 운영 장비에서 도는 스크립트이므로 `current - existing` 으로 새로 생긴 것만 삭제

| 크기 | silent + sync | verbose + sync | 오버헤드 |
|---|---:|---:|---:|
| 6.3 KB | 0.0994s | 0.1222s | **+22.92%** |
| 6.3 KB | 0.0653s | 0.0683s | +4.48% |
| 5.4 MB | 7.8925s | 6.4021s | -18.88% |
| 30.0 MB | 27.2925s | 27.1777s | -0.42% |

작은 파일에서는 터미널 출력 비용이 유의미하지만, 큰 파일에서는 I/O 대기가 지배적이라 묻힙니다.
즉 **"verbose 를 끄면 빨라진다"는 일반화는 틀렸고**, 다수의 작은 아카이브를 순차 해제하는
기동 경로에서만 유효한 최적화입니다. 측정하지 않았다면 잘못된 결론을 내렸을 지점입니다.

### 4. 취약점 유입 시점 추적

"이 취약점이 언제 들어왔는가" 를 알기 위해, 날짜를 인자로 받아
`그 날짜 이전의 최신 리비전 탐색 → 체크아웃 → 전체 정적분석 → 원복` 을 자동화했습니다.

```bash
hg log -r "max(ancestors(tip) and date('< $NEXT_DAY'))" --template "{rev}\n"
#          ancestors(tip)  현재 브랜치의 조상으로 한정 (다른 헤드 배제)
#          date('< X')     X 이전에 커밋된 것
#          max(...)        그중 가장 최신
```

날짜를 바꿔 가며 돌리면 이슈 건수의 변화 지점이 드러납니다.
작업 트리를 과거로 되돌리므로, `trap ... EXIT INT TERM` 으로
**정상 종료 · 실패 · Ctrl-C 어느 경로로 나가든** tip 복구를 보장합니다.

---

## 실행

모든 스크립트는 자격증명을 환경변수로 주입받습니다.

```bash
export DEVICE_SUBNET=192.168.10
export DEVICE_USER=root
export DEVICE_PASS=****

cd scripts/01-device-farm
./check_uptime_parallel.sh              # 병렬 uptime 집계
./check_kernel_version.sh               # 커널 버전 전수 검증

BOOT_THRESHOLD=60 ./analyze_link_events.sh 11 56   # 링크 플랩 탐지
```

```bash
cd scripts/02-stress-test
./run_remote_stress.py root secret cpu -d 60           # 60초 CPU 부하
./run_remote_stress.py root secret mem -d 120 -e 210   # 210 제외, 메모리 부하
./run_remote_stress.py root secret stop                # 전체 정지
```

### 의존성

| 스크립트 | 필요 도구 |
|---|---|
| `01-device-farm/*` | `bash`, `expect`, `telnet`, `busybox`(ftpput), `grep -P` (PCRE) |
| `02-stress-test`, `04-device-ops` | `python3` (표준 라이브러리만) |
| `03-performance/measure_extract_overhead.py` | `python3` (표준 라이브러리만) |
| `03-performance/measure_latency_ocr.py` | `python3`, `opencv-python`, `pytesseract`, `pandas`, `tesseract-ocr` |
| `05-test-harness/*` | `bash`, `coreutils`(shuf -z), `tar`, `zip` |
| `06-static-analysis/*` | `python3`, `cppcheck`, `sonar-scanner`, `hg`, SAST 소스 분석기(`replay_build_log.py` 사용 시) |

---

## 참고

공개를 위해 장비 주소·경로·자격증명 등 식별 정보는 일반화했으며, 동작 로직과 설계 의도는 그대로 유지했습니다.

---

## 라이선스

MIT
