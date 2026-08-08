#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_cppcheck_to_sonar.py
============================
cppcheck XML(v2) 리포트를 SonarQube Generic Issue Import JSON 으로 변환한다.

-------------------------------------------------------------------------------
왜 필요한가
-------------------------------------------------------------------------------
SonarQube 커뮤니티 에디션은 C/C++ 을 기본 분석하지 않는다.
대신 외부 분석기의 결과를 표준 스키마(Generic Issue Import)로 받아들이는
경로를 제공하므로, cppcheck 결과를 그 스키마로 번역하면
SonarQube 의 대시보드 · 추이 그래프 · 담당자 지정 기능을 그대로 쓸 수 있다.

참고: https://docs.sonarsource.com/sonarqube/latest/analyzing-source-code/
      importing-external-issues/generic-issue-import-format/

-------------------------------------------------------------------------------
변환에서 신경 쓴 것
-------------------------------------------------------------------------------
1) severity / type 이원 매핑
   cppcheck 의 severity 하나를 SonarQube 의 severity 와 type 두 축으로 나눈다.
   error/warning 은 BUG, style/performance/portability 는 CODE_SMELL 로 분류해
   "고쳐야 하는 결함" 과 "정리하면 좋은 코드" 가 대시보드에서 섞이지 않게 한다.

2) missingIncludeSystem 필터링
   크로스 컴파일 환경에서는 시스템 헤더 경로를 cppcheck 가 알 수 없어
   이 경고가 수천 건 쏟아진다. 실제 결함이 아니므로 변환 단계에서 버린다.
   -> 이걸 걸러야 나머지 신호가 보인다.

3) --base-path 로 경로 정규화
   SonarQube 는 sonar.sources 기준 상대 경로를 기대하는데
   cppcheck 는 실행 위치에 따라 절대/상대 경로를 섞어 낸다.
   경로가 어긋나면 이슈가 "파일 없음" 으로 붙어 대시보드에 나타나지 않는다.

사용법
------
  ./convert_cppcheck_to_sonar.py cppcheck-report.xml -o sonar-issues.json
  ./convert_cppcheck_to_sonar.py cppcheck-report.xml -o sonar-issues.json --base-path ./src
"""

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

# cppcheck severity -> SonarQube severity
SEVERITY_MAP = {
    "error":       "CRITICAL",
    "warning":     "MAJOR",
    "style":       "MINOR",
    "performance": "MINOR",
    "portability": "MINOR",
    "information": "INFO",
}

# cppcheck severity -> SonarQube issue type
# 같은 severity 를 두 축으로 나누는 것이 핵심.
# "결함(BUG)" 과 "코드 냄새(CODE_SMELL)" 를 구분해야 우선순위를 매길 수 있다.
TYPE_MAP = {
    "error":       "BUG",
    "warning":     "BUG",
    "style":       "CODE_SMELL",
    "performance": "CODE_SMELL",
    "portability": "CODE_SMELL",
    "information": "CODE_SMELL",
}

# 크로스 컴파일 환경에서 대량 발생하는 노이즈 (실제 결함 아님)
NOISE_RULES = {"missingIncludeSystem"}


def parse_cppcheck_xml(xml_path):
    """cppcheck XML v2 를 파싱해 이슈 리스트를 반환한다.

    구조: <results><errors><error ...><location .../></error></errors></results>
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    errors = root.find("errors")
    if errors is None:
        print("Warning: <errors> 태그를 찾을 수 없습니다. XML 형식을 확인하세요.",
              file=sys.stderr)
        return []

    issues = []
    for error in errors.findall("error"):
        error_id = error.get("id", "unknown")

        if error_id in NOISE_RULES:
            continue

        # location 이 없는 이슈(전역 정보성)는 파일에 붙일 수 없으므로 제외
        locations = error.findall("location")
        if not locations:
            continue

        primary_loc = locations[0]
        file_path = primary_loc.get("file", "")
        line = primary_loc.get("line", "0")

        if not file_path or line == "0":
            continue

        msg = error.get("msg", "")
        issues.append({
            "id": error_id,
            "severity": error.get("severity", "information"),
            "message": msg,
            "verbose": error.get("verbose", msg),
            "file": file_path,
            "line": int(line),
        })

    return issues


def convert_to_sonar_format(issues, base_path=None):
    """SonarQube Generic Issue Import JSON 으로 변환한다."""
    sonar_issues = []

    abs_base = os.path.abspath(base_path) if base_path else None

    for issue in issues:
        file_path = issue["file"]

        # 경로 정규화 — 어긋나면 이슈가 대시보드에 붙지 않는다
        if abs_base:
            abs_file = os.path.abspath(file_path)
            if abs_file.startswith(abs_base):
                file_path = os.path.relpath(abs_file, abs_base)
            else:
                file_path = os.path.relpath(file_path, abs_base)

        sonar_issues.append({
            "engineId": "cppcheck",
            "ruleId": issue["id"],
            "severity": SEVERITY_MAP.get(issue["severity"], "INFO"),
            "type": TYPE_MAP.get(issue["severity"], "CODE_SMELL"),
            "primaryLocation": {
                "message": issue["message"],
                "filePath": file_path,
                "textRange": {"startLine": issue["line"]},
            },
        })

    return {"issues": sonar_issues}


def main():
    parser = argparse.ArgumentParser(
        description="cppcheck XML -> SonarQube Generic Issue Import JSON 변환기")
    parser.add_argument("input", help="cppcheck XML 리포트 경로")
    parser.add_argument("-o", "--output", default="sonar-issues.json",
                        help="출력 JSON 경로 (기본: sonar-issues.json)")
    parser.add_argument("--base-path", default=None,
                        help="소스 루트 경로 (sonar.sources 기준 상대경로 변환)")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: 파일을 찾을 수 없습니다: {args.input}", file=sys.stderr)
        sys.exit(1)

    print(f"[1/3] cppcheck XML 파싱 중: {args.input}")
    issues = parse_cppcheck_xml(args.input)
    print(f"       -> {len(issues)}개 이슈 (노이즈 룰 제외 후)")

    print("[2/3] SonarQube 형식으로 변환 중...")
    sonar_data = convert_to_sonar_format(issues, args.base_path)

    severity_counts, type_counts = {}, {}
    for issue in sonar_data["issues"]:
        severity_counts[issue["severity"]] = severity_counts.get(issue["severity"], 0) + 1
        type_counts[issue["type"]] = type_counts.get(issue["type"], 0) + 1

    print(f"       심각도별: {dict(sorted(severity_counts.items()))}")
    print(f"       유형별:   {dict(sorted(type_counts.items()))}")

    print(f"[3/3] JSON 저장 중: {args.output}")
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(sonar_data, f, indent=2, ensure_ascii=False)

    print(f"\n완료! {len(sonar_data['issues'])}개 이슈가 변환되었습니다.")
    print("\nsonar-scanner 실행 시 다음 옵션을 추가하세요:")
    print(f"  -Dsonar.externalIssuesReportPaths={args.output}")


if __name__ == "__main__":
    main()
