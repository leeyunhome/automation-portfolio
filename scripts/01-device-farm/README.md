# 01 · 장비 팜 병렬 제어 및 커널 로그 분석

다수의 임베디드 리눅스 장비를 제어 호스트 한 대에서 무인 제어하고,
커널 리비전별 장기 안정성을 비교하기 위한 스크립트 모음입니다.

## 파일

| 파일 | 역할 | 언어 |
|---|---|---|
| [`deploy_kernel.sh`](deploy_kernel.sh) | 커널 이미지 FTP 일괄 플래싱 | bash |
| [`reboot_devices.sh`](reboot_devices.sh) | 46대 동시 재부팅 | bash + expect |
| [`check_kernel_version.sh`](check_kernel_version.sh) | 탑재 커널 빌드 번호 전수 검증 | bash + expect |
| [`check_uptime_parallel.sh`](check_uptime_parallel.sh) | uptime 병렬 수집 · 그룹별 집계 | bash + expect |
| [`collect_dmesg.exp`](collect_dmesg.exp) | dmesg 전량 수집 | expect |
| [`analyze_link_events.sh`](analyze_link_events.sh) | 부팅 이후 링크 플랩 자동 탐지 | bash |

## 실행 순서

이 5개 스크립트는 하나의 회귀 사이클을 이룹니다.

```
deploy_kernel.sh          커널 플래싱
      ↓
reboot_devices.sh         46대 동시 리셋
      ↓
check_kernel_version.sh   의도한 커널이 올라갔는지 검증
      ↓
check_uptime_parallel.sh  리비전별 무재부팅 시간 집계 (주기적 반복)
      ↓
analyze_link_events.sh    dmesg 수집 후 이상 탐지
      ↓
  다음 리비전으로 반복
```

```bash
export DEVICE_SUBNET=192.168.10
export DEVICE_USER=root
export DEVICE_PASS=****

./deploy_kernel.sh kernel-image.gz.rev-B 20 28
./reboot_devices.sh
./check_kernel_version.sh
./check_uptime_parallel.sh
BOOT_THRESHOLD=60 ./analyze_link_events.sh 11 56
```

---

## 실험 설계 — IP 대역 = 커널 리비전

커널 안정성을 비교하려면 **동일 조건에서 커널만 달라야** 합니다.
IP 대역을 리비전 그룹에 배정하는 규칙 하나로 이를 코드에 고정했습니다.

| 대역 | 그룹 | 대수 |
|---|---|---|
| `.11 – .19` | rev-A | 9 |
| `.20 – .28` | rev-B | 9 |
| `.29 – .37` | rev-C | 9 |
| `.38 – .46` | rev-D | 9 |
| `.47 – .56` | baseline | 10 |

네 개 스크립트가 모두 같은 매핑을 쓰기 때문에, 배포·검증·집계가 자연스럽게 정합합니다.

---

## 왜 병렬 실행인가

장비 한 대당 telnet 접속 · 로그인 · 명령 · 종료에 8~10초가 걸립니다.
46대를 순차로 돌면 6~8분. 그동안 첫 장비와 마지막 장비의 **관측 시점이 벌어지고,
그 시차가 그대로 uptime 비교의 오차**가 됩니다.

재부팅도 마찬가지입니다. 순차 재부팅하면 기동 시각이 수 분 벌어져
"어느 커널이 더 오래 버티는가" 비교 자체가 성립하지 않습니다.

```bash
# 모든 워커를 백그라운드로 던지고
for i in {11..19}; do check_uptime "$PREFIX.$i" "rev-A" & done
for i in {20..28}; do check_uptime "$PREFIX.$i" "rev-B" & done
# ...

wait                    # 배리어 — 전원 수렴 대기
sort "$RESULT_FILE"     # 그룹별 정렬 출력
```

**결과: 6~8분 → 11초.** 실행시간이 "가장 느린 장비 1대" 수준으로 수렴합니다.

### 락 없이 결과를 모으는 방법

46개 워커가 동시에 같은 파일에 쓰지만 뮤텍스가 없습니다.

```bash
printf "%-10s  %-20s  %s\n" "[$group]" "$ip" "$result" >> "$RESULT_FILE"
```

- 한 줄 append 는 사실상 원자적입니다 (PIPE_BUF 이내)
- **순서는 어차피 `sort` 로 결정**되므로 쓰기 순서를 보장할 필요가 없습니다
- 고정폭 포맷(`%-10s %-20s`)이라 정렬 키가 자연스럽게 그룹명이 됩니다

---

## telnet 자동화의 함정

### 1. PTY 가 필요하다

telnet 은 TTY 가 없으면 동작이 달라집니다. 파이프로 연결하면 프롬프트가 오지 않거나
출력 버퍼링이 바뀝니다.

```bash
script -q -c "expect $expfile" "$outfile"
#      ^^^ 의사 터미널(PTY)을 확보한 채 실행
```

### 2. CR 이 섞여 들어온다

원격 출력은 CRLF 라 그대로 비교하면 어긋납니다.

```bash
tr -d '\r' < "$outfile" | grep -E 'up +[0-9]' | head -1 | xargs
#            └ 정규화        └ 배너/프롬프트 노이즈 배제
```

### 3. reboot 후에는 프롬프트를 기다리면 안 된다

세션이 끊기므로 `expect eof` 로 정상 종료를 기다려야 합니다.
프롬프트를 기다리면 반드시 타임아웃이 납니다.

```tcl
send "reboot\r"
expect eof        # NOT expect "#"
```

### 4. 죽은 장비에서 무한 대기하지 않기

`set timeout 5` 로 상한선을 두고, 무응답은 "접속 실패" 로 명시적으로 기록합니다.
결과에서 빠지는 것과 실패로 기록되는 것은 완전히 다릅니다 —
전자는 조용히 사라지지만 후자는 조사 대상이 됩니다.

---

## 커널 로그 이상 탐지

### 문제

간헐적 네트워크 단절을 조사하며 dmesg 를 `grep "Link is"` 로 훑었더니
**정상 장비를 포함해 46대 전부가 걸렸습니다.**

```
[    6.985155] IPv6: ADDRCONF(NETDEV_UP): eth0: link is not ready
[   10.104552] eth-mac 40800000.eth eth0: Link is Up - 100Mbps/Full
```

부팅 과정에서 PHY 가 링크를 협상하며 남기는 **정상 로그**입니다.

### 해결

판정 기준을 "이벤트가 있느냐" 가 아니라 **"언제 발생했느냐"** 로 바꿨습니다.
커널 링 버퍼 타임스탬프를 파싱해 임계값과 비교합니다.

```bash
timestamp=$(echo "$line" | grep -oP '\[\s*\K[0-9]+(?=\.)')
#                                   │      │  │       └ 뒤에 소수점이 오는 경우만 (lookahead)
#                                   │      │  └───────── 정수부
#                                   │      └──────────── 여기까지는 매치 결과에서 제외
#                                   └─────────────────── 여는 대괄호 + 공백

if [ "$timestamp" -gt "$BOOT_THRESHOLD" ]; then
    # 부팅 이후 발생 → 이상 징후로 승격
fi
```

`\K` 를 쓰면 후처리(`cut`, `sed`) 없이 한 번에 숫자만 얻을 수 있습니다.

### 세 가지 결과를 구분한다

| 판정 | 의미 |
|---|---|
| `OK` | 부팅 이후 link 변동 없음 |
| `*** 부팅 이후 LINK 이벤트 감지됨! ***` | 임계값 이후 이벤트 발생 (해당 로그 라인 함께 출력) |
| `WARNING` | 로그 수집 실패, 또는 link 이벤트가 **아예 없음** |

마지막 항목이 중요합니다. 이벤트가 하나도 없는 것도 이상 신호입니다
(드라이버 미로드 등). "정상" 으로 묻히면 안 됩니다.

### 결과

단순 grep 으로는 46대 전부가 "이벤트 있음" 이었지만,
타임스탬프 필터링 후 **실제 이상 장비 2대**만 남았습니다.

전체 출력 예시: [`../../samples/link_events_output.txt`](../../samples/link_events_output.txt)

---

## 의존성

- `bash`, `expect`, `telnet`
- `script(1)` — PTY 확보용 (util-linux)
- `grep -P` — PCRE 지원 필요 (GNU grep)
- 타깃 장비: `busybox` (ftpput 사용)
