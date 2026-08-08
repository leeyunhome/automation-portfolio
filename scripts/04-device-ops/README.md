# 04 · 장비 운영 유틸리티

장애 조사와 테스트 준비에 반복적으로 필요한 작업들을 자동화한 스크립트입니다.

## 파일

| 파일 | 실행 위치 | 역할 | 언어 |
|---|---|---|---|
| [`collect_system_info.py`](collect_system_info.py) | 제어 호스트 | 원격 시스템 정보 일괄 수집 · 리포트 저장 | python3 |
| [`stop_services.sh`](stop_services.sh) | **장비 위** | 애플리케이션 데몬 안전 종료 | POSIX sh |

---

# collect_system_info.py

## 용도

이슈 리포트를 받았을 때 가장 먼저 확인해야 하는 항목들을 한 번에 확보합니다.

```
hostname / uname -a / /proc/cpuinfo / /proc/meminfo
df -h / ifconfig / uptime / ps aux / /etc/os-release
```

```bash
DEVICE_HOST=192.168.10.50 DEVICE_USER=root DEVICE_PASS=**** \
  ./collect_system_info.py
```

## 왜 파일로 남기는가

stdout 으로만 보면 그 순간 지나가 버립니다. 파일로 남기면:

- **장애 시점의 상태를 스냅샷으로 보존** → 사후 비교가 가능
- 같은 장비를 시간차로 여러 번 떠서 `diff` 하면 **변화 지점이 드러남**
- 파일명에 호스트와 타임스탬프를 넣어 여러 장비 결과가 섞이지 않음

```python
f"sysinfo_{HOST.replace('.', '_')}_{timestamp_str}.txt"
# → sysinfo_192_168_10_50_20260808_143022.txt
```

`emit()` 헬퍼로 stdout 과 파일에 동시에 출력해, 실행 중에도 결과를 보면서
파일에도 남깁니다.

## 이식성 — 폴백 명령

```python
("Network Info",     "ifconfig || ip addr"),
("Running Processes","ps aux || ps"),
("OS Release",       "cat /etc/os-release 2>/dev/null || cat /etc/issue"),
```

busybox 빌드 구성에 따라 어떤 명령이 포함되어 있는지 다릅니다.
`A || B` 형태로 구성해 한쪽이 없어도 수집이 이어집니다.

---

# stop_services.sh

테스트 전 리소스를 확보하거나 특정 프로세스만 격리 검증할 때
애플리케이션 데몬을 종료합니다. **장비 위에서 직접 실행**됩니다.

단순해 보이지만 두 가지 함정을 밟고 나서야 완성된 스크립트입니다.

## 함정 1 — 스크립트가 자기 자신을 죽인다

```sh
ps -ef | grep myapp | awk '{print $1}'
```

이 명령은 세 가지를 매치시킵니다.

1. 실제 `myapp` 프로세스 ← 원하는 것
2. `grep myapp` 프로세스 자신
3. **이 스크립트 자신** (커맨드라인에 "myapp" 문자열이 들어있으므로)

3번의 PID 를 kill 하면 스크립트가 자살합니다.

**해결:** 프로세스를 **전체 경로**로 지정합니다.

```sh
PROCESS_PATHS="/opt/app/bin/media-encoder /opt/app/bin/vision-init"

pid=$(ps -ef | grep "$process_path" | grep -v grep | awk '{print $1}')
#                    ^^^^^^^^^^^^^^   ^^^^^^^^^^^
#                    전체 경로 매칭    grep 자신 제외
```

부분 문자열이 아니라 실행 파일 경로로 매칭하므로 오탐이 사라집니다.

## 함정 2 — busybox 의 ps 는 컬럼이 다르다

일반적인 procps 의 `ps -ef` 출력:

```
UID   PID  PPID  C STIME TTY   TIME     CMD
root  1234  1     0 09:15 ?    00:00:01 /opt/app/bin/media-encoder
      ^^^^ PID 는 두 번째 컬럼 → awk '{print $2}'
```

대상 장비의 busybox `ps -ef` 출력:

```
PID   USER     COMMAND
1234  root     /opt/app/bin/media-encoder
^^^^ PID 가 첫 번째 컬럼 → awk '{print $1}'
```

**해결:** 실제 장비에서 출력을 확인하고 필드 번호를 맞췄습니다.

```sh
awk '{print $1}'    # busybox 환경
# awk '{print $2}'  # procps 환경이라면 이것
```

> 이런 환경 차이는 **코드를 읽어서는 알 수 없습니다.**
> 실제 타깃에서 출력을 확인해야만 드러나므로,
> 발견할 때마다 이유와 함께 주석에 남겨 두는 것이 중요합니다.

## POSIX sh 로 작성한 이유

대상 장비에 `bash` 가 없습니다. busybox 의 `ash` 에서 동작하도록
bash 확장 문법(`[[ ]]`, 배열, `local`)을 쓰지 않았습니다.

---

## 의존성

| 스크립트 | 필요 도구 |
|---|---|
| `collect_system_info.py` | `python3` (표준 라이브러리만) |
| `stop_services.sh` | POSIX `sh`, `ps`, `grep`, `awk` (busybox 로 충분) |

> **참고:** `telnetlib` 는 Python 3.13 에서 제거되었습니다.
> 3.13 이상에서는 [`../03-performance/measure_extract_overhead.py`](../03-performance/measure_extract_overhead.py) 의
> raw socket 구현을 참고해 대체할 수 있습니다.
