# 02 · 원격 부하 테스트

다수의 임베디드 장비에 CPU / Memory / Network 부하를 동시에 인가하고
일괄 해제하는 오케스트레이터입니다.

## 파일

| 파일 | 역할 | 언어 |
|---|---|---|
| [`run_remote_stress.py`](run_remote_stress.py) | CPU/MEM/NET 원격 부하 인가 · 해제 | python3 (표준 라이브러리만) |

## 사용법

```bash
# 20대에 60초간 CPU 부하
./run_remote_stress.py root secret cpu -d 60

# 210, 219 를 제외하고 120초간 메모리 부하
./run_remote_stress.py root secret mem -d 120 -e 210 219

# 네트워크 부하
./run_remote_stress.py root secret net -d 90

# 전체 정지
./run_remote_stress.py root secret stop
```

---

## 왜 만들었는가

"한가할 때는 멀쩡한데 부하가 걸리면 죽는다" 유형의 결함을 재현하기 위한 도구입니다.
한 대만 괴롭혀서는 재현되지 않아, 동일 네트워크의 여러 장비에
**동시에** 부하를 인가할 필요가 있었습니다.

---

## 있는 것만으로 부하를 만든다

대상 장비는 busybox 기반 최소 루트파일시스템이라 `stress-ng` 같은 표준 도구가 없습니다.
크로스 컴파일해서 올릴 수도 있지만, 테스트 도구를 넣는 것 자체가 변수를 추가하는 일입니다.
**장비에 이미 있는 것만** 조합해 각 자원별 부하를 구성했습니다.

| 자원 | 인가 방식 | 선택 이유 |
|---|---|---|
| CPU | `dd if=/dev/urandom of=/dev/null` | `/dev/zero` 가 아닌 `urandom` — 커널 PRNG 연산으로 실제 CPU 를 태운다. zero 는 메모리 복사에 그친다 |
| Memory | `mount -t tmpfs -o size=50M` + `dd` | tmpfs 는 물리 메모리를 점유한다. 파일 쓰기처럼 보이지만 실제로는 RAM 압박 |
| Network | `iperf -s -t N &` | 장비에 이미 포함된 도구 |
| 정지 | `killall dd iperf` | 일괄 정리 |

---

## 설계 결정

### 1. 자기 종료형 명령

원격 부하 테스트의 최악은 **제어 스크립트가 죽어서 장비에 부하가 영구히 남는 것**입니다.
20대에 CPU 100% 를 걸어 둔 채 스크립트가 죽으면 수동으로 하나씩 접속해 정리해야 합니다.

모든 명령을 장비가 스스로 해제하는 형태로 보냅니다.

```python
return (f"dd if=/dev/urandom of=/dev/null & "
        f"PID=$!; sleep {duration}; kill $PID")
#        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
#        원격 셸이 자기 자신의 부하를 시간 후 종료
```

메모리도 마찬가지로 `sleep N; umount /tmp/ram` 이 명령에 포함됩니다.

### 2. 스레드 병렬 + 스태거링

```python
thread.start()
time.sleep(0.1)   # 스태거링
```

20대에 동시에 telnet 을 열면 장비나 스위치가 흔들릴 수 있습니다.
0.1초 간격을 두면 부하 인가 시점은 실질적으로 동일하게 유지하면서
접속 폭주만 완화됩니다.

### 3. 부분 실패 허용

각 워커를 `try/except` 로 감싸고 예외를 문자열로 반환합니다.

```python
try:
    with telnetlib.Telnet(ip, port, timeout) as tn:
        ...
except Exception as e:
    return f"[FAIL] [{ip}] 오류 발생: {e}"
```

한 대가 죽어도 나머지 19대의 테스트는 계속됩니다.
부하 테스트에서는 **일부 장비가 죽는 것이 오히려 관측 대상**이므로,
그것이 전체 실행을 중단시켜서는 안 됩니다.

### 4. 제외 옵션

```python
parser.add_argument("-e", "--exclude", type=int, nargs="*", default=[])
```

이미 장애가 난 장비, 다른 테스트에 물려 있는 장비를 빼고 돌릴 수 있습니다.
`nargs="*"` 로 여러 개를 한 번에 지정합니다.

---

## 의존성

- `python3` (표준 라이브러리만 — `telnetlib`, `threading`, `argparse`)
- 타깃 장비: `busybox` (dd, mount, killall), `iperf` (네트워크 부하 시)

> **참고:** `telnetlib` 는 Python 3.13 에서 제거되었습니다.
> 3.13 이상에서는 [`03-performance/measure_extract_overhead.py`](../03-performance/measure_extract_overhead.py) 의
> raw socket 구현을 참고해 대체할 수 있습니다.
