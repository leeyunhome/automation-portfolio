# FlexWatch EN683 SCA Project — Context Summary
# 이 파일을 새 대화에서 업로드하면 맥락을 바로 파악할 수 있습니다.
# Last updated: 2026-03-26

## 프로젝트 개요
- FlexWatch EN683 임베디드 카메라 펌웨어의 정적 코드 분석(SCA)
- STQC(인도) 인증을 위한 보안 분석 수행 중
- SCITA가 컨설팅 지원, Vincular가 Coverity 리포트 샘플 제공

## 환경
- 빌드서버: deeplearning@deeplearning-H110-D3 (Ubuntu)
- 소스코드: /home/deeplearning/repos/FlexWatchV42/source/
- SonarQube: http://10.10.237.222:9000 (Community Build v26.3.0)
- SonarQube Token: squ_eeefc57136ffa03bc892d4f26c4aad510ad4b898
- 작업 디렉토리: ~/repos/FlexWatchV42/sca_tools/

## 분석 도구 스택
1. Cppcheck — 버그/메모리 분석 (이미 설치)
2. Flawfinder — CWE 보안 스캔 (pip install flawfinder)
3. scan_banned_functions.py — STQC 금지함수 40+개 검사 (자체 개발)
4. sonar-cxx plugin v2.2.2 — SonarQube C/C++ 언어 지원
5. extract_sources_for_sca_v3.py — 소스코드 목록 추출기 (자체 개발)

## SonarQube 프로젝트 (3개 완료)
| Project | Key | Source | Status |
|---------|-----|--------|--------|
| GoAhead v3.1.3 | goahead-fw | FwSvcV40/goahead-v3.1.3/src/ | ✅ Cppcheck+금지함수 완료, Security E(6) |
| live555 2024.03.08 | live555-fw | live555/live555.2024.03.08/live/ | ⏳ 금지함수 추가 예정 |
| OpenSSL 3.5.4 | openssl-fw | OpenSSL/FW_EN683/openssl-3.5.4/ | ⏳ 금지함수 추가 예정 |

## GoAhead 분석 결과
- 31k LoC (CXX + HTML)
- Cppcheck: 740 issues
- 금지함수: 1,963건 (sprintf:587, strcpy:306, memcpy:301, strcat:254, malloc:189, system:78)
- SonarQube 총 이슈: 2,703건
- Security: E(6), Reliability: C(17), Maintainability: A(2.7k)

## 소스코드 추출 결과 (전체 펌웨어)
- 112 고유 바이너리 (115 항목 중 중복 3개 제외)
- 1,462 고유 소스파일
- 1,662,439 라인 (고유 기준)
- 4,703,820 라인 (바이너리별 중복 포함)

## Coverity 리포트 샘플 분석 (STQC 통과 기준)
- Security Score >= 90 (Coverity 0~100 점수, 샘플은 68로 Fail)
- OWASP Top 10 (2017) Count = 0
- CWE/SANS Top 25 (2019) Count = 0
- Analysis Date: 30일 이내
- Severity Mapping: "Carrier grade" (Very stringent)
  - Very High/High 이슈 0건이어야 Score 90 달성 가능

## 미팅 예정
- 2026-04-07 14:30 KST — SonarSource + SCITA 온라인 미팅
- 핵심 질문: Security Score 90 매핑, OSS 내부 금지함수 수정 범위, Community Edition 인정 여부

## 추가로 돌려야 할 도구 (미완료)
1. Secrets 스캔 — Gitleaks (CWE-798 Hard-coded Credentials)
2. SCA 의존성 분석 — Trivy (OWASP #9 Known Vulnerabilities)
3. SBOM 생성 — CycloneDX + Syft

## 자체 개발 스크립트 (sca_tools/)
| 파일 | 용도 |
|------|------|
| extract_sources_for_sca_v3.py | 바이너리별 소스 추출 + 라인수 카운팅 (~980줄) |
| scan_banned_functions.py | STQC 금지함수 스캔 + SonarQube JSON (~300줄) |
| verify_line_counts.py | 라인수 검증 (~120줄) |
| list_unique_files.py | 개별 파일 목록 (~110줄) |
| scan_folder.py | 폴더 단독 스캔 (~160줄) |
| run_sca_new_project.sh | 자동화 스크립트 |

## 알려진 이슈
- Flawfinder: http.c에 EUC-KR 한글 → iconv 변환 필요
- 네트워크 드라이브(\\10.10.237.222): Filesystem MCP edit_file rename EPERM
- GoAhead v3.1.3이 2014년 버전 → OSS 버전 논의 필요
- sonar-issues.json의 filePath에 src/ 접두어 필요 (GoAhead)
