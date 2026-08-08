# 03 · 성능 정량화

정성적 성능 보고("느리다")를 측정 가능한 숫자로 바꾸는 스크립트들입니다.

## 파일

| 파일 | 역할 | 언어 |
|---|---|---|
| [`measure_extract_overhead.py`](measure_extract_overhead.py) | 압축 해제 오버헤드 벤치마크 (원격) | python3 (표준 라이브러리만) |
| [`measure_latency_ocr.py`](measure_latency_ocr.py) | Glass-to-Glass 지연 OCR 측정 | python3 + opencv + tesseract |

---

# 3-1. 압축 해제 오버헤드 벤치마크

## 무엇을 측정했는가

장비에서 `tar -zxf`(silent) 와 `tar -zxvf`(verbose) 의 해제 시간을
**파일 크기별로** 비교하고 오버헤드를 % 로 산출합니다.

## 왜 측정했는가

"장비 기동 시 모델 로딩이 느리다" 는 정성적 보고를 숫자로 만들어야 했습니다.
기동 스크립트가 `tar` 를 verbose 로 호출하고 있었는데,
느린 시리얼 콘솔에 파일명을 한 줄씩 찍는 비용이 유의미한지 확인이 필요했습니다.

## 결과

| 크기 | silent + sync | verbose + sync | 오버헤드 |
|---|---:|---:|---:|
| 6.3 KB | 0.0994s | 0.1222s | **+22.92%** |
| 6.3 KB | 0.0653s | 0.0683s | +4.48% |
| 6.3 KB | 0.0567s | 0.0565s | -0.36% |
| 5.4 MB | 7.8925s | 6.4021s | -18.88% |
| 30.0 MB | 27.2925s | 27.1777s | -0.42% |

원본 데이터: [`../../samples/tar_benchmark_result.csv`](../../samples/tar_benchmark_result.csv)

**해석:** 작은 파일에서는 터미널 출력 비용이 전체 시간의 상당 부분을 차지하지만,
큰 파일에서는 압축 해제와 I/O 대기가 지배적이라 그 비용이 노이즈에 묻힙니다.

즉 **"verbose 를 끄면 빨라진다" 는 일반화는 틀렸고**,
다수의 작은 아카이브를 순차 해제하는 기동 경로에서만 유효한 최적화입니다.
측정하지 않았다면 잘못된 결론을 내렸을 지점입니다.

---

## 측정 정확도를 위해 한 것

### 1. `sync` 포함 측정

```python
f"tar -zxf '{file_name}' && sync"
```

`sync` 없이 재면 **페이지 캐시에만 쓰고 반환되는 시간**을 재게 됩니다.
실제 스토리지 쓰기가 끝나기 전에 tar 가 리턴하므로,
그 숫자로 최적화를 판단하면 틀립니다.

측정에 무엇을 포함할지 정하는 순간 결론이 갈리는 지점입니다.

### 2. 매 측정 전 동일 시작 조건 복원

직전 측정이 남긴 파일이 있으면 tar 가 덮어쓰기를 하며 시간이 달라집니다.

```python
cleanup_new_files(sock, existing_files)   # 조건 복원
time_silent = measure_extraction(sock, cmd_silent, "Silent Mode")

cleanup_new_files(sock, existing_files)   # 조건 복원
time_verbose = measure_extraction(sock, cmd_verbose, "Verbose Mode")
```

### 3. 타임아웃 시 `-1` 반환

```python
except socket.timeout:
    return -1
```

실패값을 결과에 섞지 않아 평균이 오염되지 않게 합니다.
`0` 을 반환하면 "매우 빠름" 으로 집계되어 통계가 망가집니다.

---

## 안전장치 — 집합 차분 기반 클린업

**운영 중인 장비에서 도는 스크립트**이므로 원본 파일을 지우는 사고는 절대 없어야 합니다.
"조심해서 짜기" 로는 부족하고, 구조적으로 불가능하게 만들어야 합니다.

```python
def cleanup_new_files(sock, existing_files):
    current_files = list_dir_entries(sock)

    # 집합 차분 — 이것이 안전장치의 핵심
    new_files = current_files - existing_files

    for filename in sorted(new_files):
        # 이중 안전장치: 원본 아카이브는 어떤 경우에도 건드리지 않는다
        if filename.endswith(".tar.gz"):
            continue
        send_command(sock, f"rm -rf './{filename}'", timeout=30)
```

- 측정 시작 전 디렉터리 스냅샷을 기준선으로 확보
- 클린업 대상은 `현재 - 기준선` 으로 **새로 생긴 것만**
- 원본 확장자는 명시적으로 skip (이중 방어)

---

## 왜 telnetlib 대신 raw socket 인가

verbose 모드는 수천 줄을 순식간에 쏟아냅니다.
`telnetlib.read_until()` 은 기대 바이트열을 기다리는데, 대량 출력 중에는

- 프롬프트 문자(`#`)가 데이터 중간에 우연히 등장하고
- 버퍼가 밀려 종료 판정이 어긋납니다

소켓을 직접 다루며 **종료 판정을 이중으로** 했습니다.

```python
# (a) 버퍼가 프롬프트 문자로 끝나는가
for prompt in prompts:
    if buffer.strip().endswith(prompt.strip()):
        return buffer.decode("utf-8", errors="ignore")

# (b) 0.5초 이상 신규 데이터 유입이 멈췄는가 (idle 휴리스틱)
if time.time() - last_data_time > IDLE_SETTLE_SEC:
    if buffer.strip().endswith((b"#", b"$", b">")):
        return buffer.decode("utf-8", errors="ignore")
```

추가로 `socket.timeout` 이 발생해도 버퍼가 프롬프트로 끝나면
성공으로 처리하는 복구 경로를 뒀습니다.

## busybox 환경 차이 대응

```python
send_command(sock, f"stat -c %s '{filepath}' 2>/dev/null || ls -l '{filepath}'")
```

busybox 빌드 구성에 따라 `stat` 이 없거나 `-c` 옵션을 지원하지 않습니다.
폴백을 두고 **두 출력 포맷을 모두 파싱**합니다
(stat 은 숫자 한 줄, `ls -l` 은 5번째 필드).

---

# 3-2. Glass-to-Glass 지연 측정

## 측정 원리

밀리초 스톱워치를 두 장비가 동시에 촬영하고,
원본 스톱워치와 두 장비의 출력 화면을 한 모니터에 나란히 배치합니다.
이 상태를 스크린샷으로 캡처하면 **한 장의 이미지 안에 세 시각이 함께 찍힙니다.**

```
┌─────────────────┬─────────────────┐
│  reference      │  device_a       │
│  00:12:04.187   │  00:12:04.041   │
├─────────────────┼─────────────────┤
│  (미사용)        │  device_b       │
│                 │  00:12:03.902   │
└─────────────────┴─────────────────┘

latency_a = 724.041 - 724.187 = -0.146 s  → 약 146 ms
latency_b = 723.902 - 724.187 = -0.285 s  → 약 285 ms
```

원본과 각 장비 화면의 시각 차이가 곧 그 장비의 파이프라인 지연
(촬영 → 인코딩 → 전송 → 디코딩 → 표시)입니다.

사람이 스크린샷 수백 장의 숫자를 눈으로 읽고 빼는 것은 비현실적이라
ROI 분할 + OCR + 파싱 + 차분을 자동화했습니다.

---

## OCR 자동화에서 가장 위험한 것

**ROI 가 어긋났는데 그럴듯한 숫자가 나오는 상황**입니다.
결과가 조용히 틀리면 알아챌 방법이 없습니다.

```python
cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
cv2.putText(debug_img, f"{name}: {clean_text} ({val}s)", ...)
...
cv2.imwrite("debug_roi.png", debug_img)
```

첫 이미지에 ROI 사각형과 인식 결과를 그려 파일로 저장합니다.
**사람이 1초 만에 영역 설정을 검증**할 수 있습니다.

## 그 밖의 설계 결정

| 결정 | 이유 |
|---|---|
| ROI 를 비율(0.0–1.0)로 지정 | 해상도가 다른 캡처 세션이 섞여도 동일 설정으로 동작 |
| `--psm 7` (single text line) | 숫자 한 줄만 있는 영역이라 페이지 세그멘테이션을 끄면 인식률이 오른다 |
| 과한 이진화를 하지 않음 | 화면 캡처는 대비가 이미 좋고, 이진화는 오히려 얇은 획을 지운다 |
| 관용적 파싱 + `None` 반환 | OCR 은 `:` 와 `.` 를 혼동한다. 실패 시 `None` 을 반환해 통계에서 자동 제외 |

```python
# 숫자와 구분자만 남기고 필드 개수에 따라 유연하게 해석
clean_text = re.sub(r"[^0-9:.]", "", text)
parts = clean_text.split(":")

if len(parts) == 3:   # HH:MM:SS.ms
    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
if len(parts) == 2:   # MM:SS.ms
    return float(parts[0]) * 60 + float(parts[1])
if len(parts) == 1:   # SS.ms
    return float(parts[0])
return None           # 해석 불가 → 통계에서 제외
```

---

## 의존성

| 스크립트 | 필요 도구 |
|---|---|
| `measure_extract_overhead.py` | `python3` (표준 라이브러리만) |
| `measure_latency_ocr.py` | `python3`, `opencv-python`, `pytesseract`, `pandas`, 시스템 `tesseract-ocr` |

```bash
pip install opencv-python pytesseract pandas
sudo apt install tesseract-ocr
```
