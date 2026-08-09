# LG전자 MS본부 [임베디드 리눅스 커널/시스템 SW 성능 최적화 전문가] 지원 직무경험 정리

> 작성일: 2026-08-09  
> 작성 목적: E: 드라이브 내 자동화 스크립트, AI 활용 도구, 커널/BSP/보안/성능 최적화 자산 기반 채용 공고 요건 매핑 및 실제 경로 정리

---

## 1. 공고 요건 ↔ 보유 직무경험 매핑 요약

### ① 시스템 자동화 스크립트 (Python / Shell / AI 도구)
- **46대 규모 타깃 장비 무인 테스트 팜 제어**
  - Shell/Expect/Bash 병렬 처리로 Eyenix EN675/EN683 카메라 46대의 커널 플래싱, uptime 수집, reboot 제어 및 dmesg 수집 자동화.
  - Python `telnetlib` 및 멀티스레딩 기반 원격 시스템 부하(CPU/Memory/Network) 동시 인가 오케스트레이터 (`run_remote_stress.py`).
- **SCA 정적분석 & 보안 파이프라인 무인화**
  - Makefile 재귀 파싱 소스 역추적기(`extract_sources_for_sca_v3.py`, 990줄): 112개 바이너리, 1,462개 고유 소스파일(166만 LoC) 자동 추적.
  - STQC 금지 C 함수 정규식 검사기(`scan_banned_functions.py`): 40+개 금지함수 스캔 후 SonarQube Issue JSON으로 변환 업로드.
  - SonarQube Web API 기반 HTML 보고서 자동 생성기(`sonar_report.py`, 376줄).

### ② 메모리 / 병목 / 성능 최적화 & 온디바이스 프로파일링
- **터미널 I/O 및 압축해제 오버헤드 벤치마크**
  - raw socket 기반 Telnet 프로토콜 직접 구현 및 `sync` (페이지 캐시 flush) 포함 실측 소요시간 산출 스크립트(`measure.py`, 342줄).
  - verbose I/O 차이에 따른 오버헤드(%) 파일 크기별 CSV 자동 리포팅.
- **Glass-to-Glass 영상 지연시간(Latency) 정량 측정**
  - OpenCV + Tesseract OCR을 활용하여 사분면 ROI OCR 파싱으로 지연시간 자동 측정 (`measure_latency.py`).

### ③ 최신 커널 / 보안 패치 백포팅 / Coccinelle & SBOM Management
- **CodeQL 기반 TOCTOU(CWE-367) 취약점 패치 및 검증**
  - `goahead` 웹서버에서 TOCTOU 4건 탐지 → `stat()+open()`을 `open(O_NOFOLLOW)+fstat()`로 수정 후 재스캔으로 감소 추적 검증.
- **Coccinelle (SmPL) 기반 시맨틱 자동 패치**
  - `safe.cocci` (244줄): C 표준 위험 함수(`strcpy`, `sprintf` 등)를 경계 검사 래퍼 함수로 코드베이스 전반에 일괄 자동 치환.
- **CycloneDX 표준 SBOM 생성 및 타깃 분석**
  - `cdxgen` 기반 OpenSSL 3.5.6(1,701개 컴포넌트) 등 SBOM 생성 및 크로스 타깃 오탐 원인 규명 절차서 작성.

### ④ 임베디드 리눅스 BSP / 디바이스 드라이버 & ARM/SoC 대응
- **ARM64 / RISC-V 타깃 BSP 및 커널/드라이버 운용**
  - Jetson Xavier NX / Orin 플랫폼 Device Tree(Pinmux dtsi) 수정, ADC 동기화 커널 드라이버, IMX327/ES8316 오디오 활성화.
  - devmem 활용 direct MMIO 핀먹스 제어.
- **SoC 벤더 협업 이력 무인 관리**
  - Playwright 기반 `analyze_jira.py` (508줄): Eyenix Jira 기술 지원 포털 이슈 20건, 댓글 32건 자동 파싱 및 ISP 레지스터 협업 이력 관리.

---

## 2. E: 드라이브 실제 경로 매핑표

| 구 분 | 상세 설명 및 산출물 | 실제 경로 (E: 드라이브) |
| :--- | :--- | :--- |
| **종합 요약서** | 기존 지원 준비 정리 문서 | [`file:///e:/coding/01_자동화스크립트_경험정리.md`](file:///e:/coding/01_%EC%9E%90%EB%8F%99%ED%99%94%EC%8A%A4%ED%81%AC%EB%A6%BD%ED%8A%B8_%EA%B2%BD%ED%97%98%EC%A0%95%EB%A6%AC.md) |
| **STQC SCA 컨텍스트** | STQC 인증 정적분석 프로젝트 현황 | [`file:///e:/static_code_analysis/SCA_Project_Context_Summary.md`](file:///e:/static_code_analysis/SCA_Project_Context_Summary.md) |
| **테스트 팜 자동화** | 46대 장비 병렬 제어 및 dmesg 수집 | [`file:///e:/coding/yh_utility/change_kernel.sh`](file:///e:/coding/yh_utility/change_kernel.sh)<br>[`file:///e:/coding/yh_utility/checkuptime_telnet.sh`](file:///e:/coding/yh_utility/checkuptime_telnet.sh)<br>[`file:///e:/coding/yh_utility/settingenviron.sh`](file:///e:/coding/yh_utility/settingenviron.sh) |
| **원격 스트레스 테스트** | CPU/MEM/NET 동시 부하 오케스트레이터 | [`file:///e:/coding/yh_utility/EN675_SYSTEM_LOAD_TEST/run_remote_stress.py`](file:///e:/coding/yh_utility/EN675_SYSTEM_LOAD_TEST/run_remote_stress.py) |
| **성능 오버헤드 벤치마크** | raw socket 기반 tar I/O 오버헤드 측정 (342줄) | [`file:///e:/coding/yh_utility/measure_untar_aimodel_speed/measure.py`](file:///e:/coding/yh_utility/measure_untar_aimodel_speed/measure.py) |
| **Glass-to-Glass Latency** | OpenCV + OCR 지연시간 측정 스크립트 | [`file:///e:/coding/latency_test/measure_latency.py`](file:///e:/coding/latency_test/measure_latency.py) |
| **CodeQL TOCTOU 분석** | TOCTOU 탐지, 수정 및 재검증 이력 | [`file:///e:/coding/scita_code_ql/CLAUDE.md`](file:///e:/coding/scita_code_ql/CLAUDE.md) |
| **Coccinelle 패치** | 위험함수 일괄 경계검사 래퍼 치환 (244줄) | [`file:///e:/coding/repos/FlexWatchV42/safe.cocci`](file:///e:/coding/repos/FlexWatchV42/safe.cocci) |
| **SCA 자동화 스크립트** | 소스 역추적기, 금지함수 검사기, Sonar 리포터 | [`file:///e:/coding/repos/FlexWatchV42/sca_tools/extract_sources_for_sca_v3.py`](file:///e:/coding/repos/FlexWatchV42/sca_tools/extract_sources_for_sca_v3.py)<br>[`file:///e:/coding/repos/FlexWatchV42/sca_tools/scan_banned_functions.py`](file:///e:/coding/repos/FlexWatchV42/sca_tools/scan_banned_functions.py)<br>[`file:///e:/coding/sonarqube_temp/sonar_report.py`](file:///e:/coding/sonarqube_temp/sonar_report.py) |
| **SBOM 관리 절차서** | cdxgen 기반 CycloneDX SBOM 생성 표준 | [`file:///e:/coding/.claude/skills/cdxgen-sbom/SKILL.md`](file:///e:/coding/.claude/skills/cdxgen-sbom/SKILL.md) |
| **Jira 협업 분석기** | Playwright 기반 Jira 포털 이슈 파싱 (508줄) | [`file:///e:/coding/yh_utility/analyze_jira_eyenix/analyze_jira.py`](file:///e:/coding/yh_utility/analyze_jira_eyenix/analyze_jira.py)<br>[`file:///e:/coding/yh_utility/analyze_jira_eyenix/troubleshooting_log.md`](file:///e:/coding/yh_utility/analyze_jira_eyenix/troubleshooting_log.md) |
| **Jetson ARM BSP/Pinmux** | Jetson Xavier NX Pinmux & DTB 설정 | [`file:///e:/Jetson_AI_Bridge/`](file:///e:/Jetson_AI_Bridge/)<br>[`file:///e:/tegra19x-jetson_xavier_nx_module-pinmux.dtsi`](file:///e:/tegra19x-jetson_xavier_nx_module-pinmux.dtsi) |

---

## 3. 대표 스크립트 코드 스니펫 및 개요

### [1] raw Socket 기반 Telnet I/O 성능 벤치마크 (`measure.py`)
```python
# e:\coding\yh_utility\measure_untar_aimodel_speed\measure.py (일부)
def read_until_prompt(sock, timeout=CMD_TIMEOUT):
    # idle 휴리스틱과 raw socket 파싱으로 verbose 출력 내 프롬프트 끝 판정
    ...
def test_tar_performance(sock, tar_file, extract_dir, verbose=False):
    cmd = f"time tar -{'zxvf' if verbose else 'zxf'} {tar_file} -C {extract_dir} && sync\n"
    # sync 포함 실제 디스크 flush 및 쓰기 완료 시간 정량 측정
```

### [2] CodeQL TOCTOU 취약점 패치 검증 스크립트/절차 (`scita_code_ql\CLAUDE.md`)
```bash
# CodeQL 스캔 & SARIF 생성
codeql database analyze codeql/cpp-queries:Security/CWE/CWE-367 --format=sarif-latest --output=toctou_result.sarif
# stat() -> open() 구문을 open(O_NOFOLLOW) -> fstat() 방식으로 변경 후 재검증
```

### [3] Coccinelle 시맨틱 일괄 패치 (`safe.cocci`)
```cocci
// e:\coding\repos\FlexWatchV42\safe.cocci (일부)
@@
expression DST, SRC;
@@
- sprintf(DST, SRC, ...)
+ safe_sprintf(sizeof(DST), SRC, ...)
```

---

## 4. 자소서 및 경력기술서 작성용 핵심 문구

- **자동화 검증 파이프라인**: "BusyBox/Linux 타깃 IP 카메라 46대를 동시 제어하는 무인 테스트 팜을 구축하고, 커널 타임스탬프 파싱 기반으로 부팅 노이즈와 실제 이더넷 Link Flap 결함을 구분하는 자동 감지 체계를 정립했습니다."
- **성능 최적화 및 정량화**: "터미널 Verbose I/O가 시스템 압축 해제 및 모델 로드 속도에 미치는 오버헤드를 raw socket 및 `sync` 파이프라인으로 측정하여 % 단위 정량 벤치마크 리포트를 자동화했습니다."
- **CVE 패치 & 시맨틱 패치**: "CodeQL 분석으로 펌웨어 웹서버 내 TOCTOU 취약점을 규명 및 패치 후 감소를 검증하였으며, Coccinelle 244줄 시맨틱 패치를 통해 대규모 C 코드베이스의 위험 함수를 경계 검사 래퍼로 일괄 자동 치환했습니다."
