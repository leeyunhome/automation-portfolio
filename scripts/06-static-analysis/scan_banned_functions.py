#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scan_banned_functions.py
========================
C/C++ 소스에서 사용이 금지된 위험 함수를 검사하고,
SonarQube 의 Generic Issue Import 형식(JSON)으로 리포트를 생성한다.

-------------------------------------------------------------------------------
왜 만들었는가
-------------------------------------------------------------------------------
보안 인증 심사에서 "금지 함수 목록에 대한 사용 현황과 대응 방안" 을 제출해야 했다.
cppcheck 는 이런 정책 기반 검사를 하지 않고, Flawfinder 는 자체 목록을 쓰기 때문에
심사 기준으로 지정된 목록과 정확히 일치시킬 수 없었다.

그래서 "함수명 -> CWE -> 위험도 -> 권장 대체 함수" 를 테이블로 정의하고,
그 테이블을 단일 진실 공급원(single source of truth)으로 삼아
검사 · 통계 · 리포트를 모두 생성하도록 만들었다.

-------------------------------------------------------------------------------
설계 포인트
-------------------------------------------------------------------------------
1) 오탐을 줄이는 전처리
   정규식만으로 소스를 훑으면 주석이나 매크로 정의에 등장하는 함수명까지 잡힌다.
   - 블록 주석 / 한 줄 주석을 상태 머신으로 제거
   - #include, #define 라인은 스킵
   - `\b(name)\s*\(` 패턴으로 "호출 형태" 만 매치 (변수명 부분일치 배제)

2) SonarQube 와의 연동
   자체 포맷을 만들지 않고 SonarQube 가 이미 이해하는
   Generic Issue Import 스키마로 출력한다.
   -> 대시보드/추이/담당자 지정 같은 기능을 그대로 얻을 수 있다.

3) --merge 재실행 안전성
   재스캔 시 기존 JSON 에 이슈가 중복 누적되면 통계가 망가진다.
   merge 할 때 engineId 가 자기 자신인 이슈를 먼저 제거하고 새로 넣는다.
   -> 몇 번을 돌려도 결과가 같다(idempotent).

4) Flawfinder 병행(선택)
   --with-flawfinder 로 외부 도구 결과를 같은 JSON 에 합칠 수 있다.
   설치되어 있지 않으면 경고만 남기고 계속 진행한다.

사용법
------
  ./scan_banned_functions.py ./src/
  ./scan_banned_functions.py ./src/ ../common/ -o banned-issues.json
  ./scan_banned_functions.py ./src/ -o sonar-issues.json --merge
  ./scan_banned_functions.py ./src/ --with-flawfinder -o sonar-issues.json --merge --csv report.csv
"""

import argparse
import csv
import json
import os
import re
import subprocess
from collections import defaultdict

# =============================================================================
# 금지 함수 테이블 — 이 딕셔너리가 단일 진실 공급원이다.
#   검사 패턴, 위험도 판정, 리포트 메시지, 통계가 모두 여기서 파생된다.
# =============================================================================
BANNED_FUNCTIONS = {
    # 문자열 — 버퍼 오버플로우
    "gets":      {"cwe": "CWE-120", "risk": "CRITICAL", "alt": "fgets(buf, size, stdin)",           "cat": "buffer_overflow"},
    "strcpy":    {"cwe": "CWE-120", "risk": "HIGH",     "alt": "strncpy() or strlcpy()",            "cat": "buffer_overflow"},
    "strcat":    {"cwe": "CWE-120", "risk": "HIGH",     "alt": "strncat() or strlcat()",            "cat": "buffer_overflow"},
    "sprintf":   {"cwe": "CWE-120", "risk": "HIGH",     "alt": "snprintf()",                        "cat": "buffer_overflow"},
    "vsprintf":  {"cwe": "CWE-120", "risk": "HIGH",     "alt": "vsnprintf()",                       "cat": "buffer_overflow"},
    "streadd":   {"cwe": "CWE-120", "risk": "MEDIUM",   "alt": "bounds-checked version",            "cat": "buffer_overflow"},
    "strecpy":   {"cwe": "CWE-120", "risk": "MEDIUM",   "alt": "bounds-checked version",            "cat": "buffer_overflow"},
    "strtrns":   {"cwe": "CWE-120", "risk": "MEDIUM",   "alt": "bounds-checked version",            "cat": "buffer_overflow"},

    # 문자열 — 부분적 위험 (안전해 보이지만 조건부로 위험)
    "strncpy":   {"cwe": "CWE-120", "risk": "MEDIUM",   "alt": "strlcpy() (null-term guarantee)",   "cat": "buffer_overflow"},
    "strncat":   {"cwe": "CWE-120", "risk": "MEDIUM",   "alt": "strlcat()",                         "cat": "buffer_overflow"},
    "strncmp":   {"cwe": "CWE-126", "risk": "LOW",      "alt": "check length carefully",            "cat": "buffer_overflow"},
    "strtok":    {"cwe": "CWE-362", "risk": "MEDIUM",   "alt": "strtok_r()",                        "cat": "race_condition"},

    # 메모리
    "memcpy":    {"cwe": "CWE-120", "risk": "MEDIUM",   "alt": "memcpy_s() or bounds check",        "cat": "memory"},
    "memmove":   {"cwe": "CWE-120", "risk": "MEDIUM",   "alt": "memmove_s()",                       "cat": "memory"},
    "memcmp":    {"cwe": "CWE-126", "risk": "LOW",      "alt": "verify sizes first",                "cat": "memory"},
    "bcopy":     {"cwe": "CWE-120", "risk": "MEDIUM",   "alt": "memcpy() or memmove()",             "cat": "memory"},
    "bzero":     {"cwe": "CWE-120", "risk": "LOW",      "alt": "memset()",                          "cat": "memory"},

    # 입력
    "scanf":     {"cwe": "CWE-120", "risk": "HIGH",     "alt": "fgets() + sscanf() with width",     "cat": "input"},
    "fscanf":    {"cwe": "CWE-120", "risk": "HIGH",     "alt": "fgets() + parsing",                 "cat": "input"},
    "sscanf":    {"cwe": "CWE-120", "risk": "MEDIUM",   "alt": "sscanf with %Ns width",             "cat": "input"},
    "vscanf":    {"cwe": "CWE-120", "risk": "HIGH",     "alt": "fgets() + parsing",                 "cat": "input"},
    "vsscanf":   {"cwe": "CWE-120", "risk": "MEDIUM",   "alt": "fgets() + parsing",                 "cat": "input"},
    "vfscanf":   {"cwe": "CWE-120", "risk": "HIGH",     "alt": "fgets() + parsing",                 "cat": "input"},

    # 파일시스템
    "realpath":  {"cwe": "CWE-22",  "risk": "MEDIUM",   "alt": "realpath() with PATH_MAX buf",      "cat": "filesystem"},
    "getopt":    {"cwe": "CWE-120", "risk": "LOW",      "alt": "getopt_long()",                     "cat": "filesystem"},
    "getpass":   {"cwe": "CWE-120", "risk": "HIGH",     "alt": "custom secure input",               "cat": "filesystem"},

    # 임시 파일 — TOCTOU 경합
    "mktemp":    {"cwe": "CWE-377", "risk": "HIGH",     "alt": "mkstemp()",                         "cat": "temp_file"},
    "tmpnam":    {"cwe": "CWE-377", "risk": "HIGH",     "alt": "mkstemp()",                         "cat": "temp_file"},
    "tempnam":   {"cwe": "CWE-377", "risk": "HIGH",     "alt": "mkstemp()",                         "cat": "temp_file"},

    # 명령 실행 — 커맨드 인젝션
    "system":    {"cwe": "CWE-78",  "risk": "CRITICAL", "alt": "exec*() family directly",           "cat": "command_injection"},
    "popen":     {"cwe": "CWE-78",  "risk": "HIGH",     "alt": "fork()+exec()",                     "cat": "command_injection"},
    "execl":     {"cwe": "CWE-78",  "risk": "MEDIUM",   "alt": "execve() with sanitized args",      "cat": "command_injection"},
    "execlp":    {"cwe": "CWE-78",  "risk": "HIGH",     "alt": "execve() with full path",           "cat": "command_injection"},
    "execle":    {"cwe": "CWE-78",  "risk": "MEDIUM",   "alt": "execve()",                          "cat": "command_injection"},
    "execv":     {"cwe": "CWE-78",  "risk": "MEDIUM",   "alt": "execve()",                          "cat": "command_injection"},
    "execvp":    {"cwe": "CWE-78",  "risk": "HIGH",     "alt": "execve() with full path",           "cat": "command_injection"},
    "execve":    {"cwe": "CWE-78",  "risk": "MEDIUM",   "alt": "validate all args",                 "cat": "command_injection"},

    # 메모리 할당 — 반환값 미검사
    "malloc":    {"cwe": "CWE-789", "risk": "LOW",      "alt": "check return value + size",         "cat": "allocation"},
    "calloc":    {"cwe": "CWE-789", "risk": "LOW",      "alt": "check return value",                "cat": "allocation"},
    "realloc":   {"cwe": "CWE-789", "risk": "LOW",      "alt": "check return value",                "cat": "allocation"},
    "alloca":    {"cwe": "CWE-770", "risk": "HIGH",     "alt": "malloc() or VLA with limit",        "cat": "allocation"},

    # 환경변수 — 신뢰할 수 없는 입력
    "getenv":    {"cwe": "CWE-807", "risk": "MEDIUM",   "alt": "validate after getenv()",           "cat": "environment"},
    "putenv":    {"cwe": "CWE-807", "risk": "MEDIUM",   "alt": "setenv()",                          "cat": "environment"},
    "setenv":    {"cwe": "CWE-807", "risk": "LOW",      "alt": "validate value before set",         "cat": "environment"},
}


def _build_pattern():
    """호출 형태만 매치하는 정규식을 테이블에서 생성한다.

    \b(name)\s*\(  -> 'my_strcpy_wrapper' 같은 부분일치를 배제하고
                      'strcpy (' 처럼 공백이 낀 호출도 잡는다.
    """
    names = "|".join(re.escape(f) for f in BANNED_FUNCTIONS)
    return re.compile(rf"\b({names})\s*\(")


FUNC_PATTERN = _build_pattern()

SRC_EXTS = {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp"}


def scan_file(filepath, base_dir):
    """파일 하나를 스캔하여 금지함수 사용처 리스트를 반환한다.

    주석 안의 코드는 실행되지 않으므로 findings 에 포함하면 안 된다.
    블록 주석은 여러 줄에 걸치므로 상태(in_block_comment)를 들고 순회한다.
    """
    findings = []
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return findings

    in_block_comment = False

    for line_no, line in enumerate(lines, 1):
        # --- 블록 주석 처리 ---
        if in_block_comment:
            if "*/" in line:
                in_block_comment = False
                line = line[line.index("*/") + 2:]
            else:
                continue  # 주석 내부 라인 전체를 스킵

        if "/*" in line:
            before = line[:line.index("/*")]
            after = line[line.index("/*"):]
            if "*/" in after:
                # 한 줄 안에서 열고 닫힘 -> 주석 부분만 도려낸다
                line = before + after[after.index("*/") + 2:]
            else:
                in_block_comment = True
                line = before

        # --- 한 줄 주석 제거 ---
        if "//" in line:
            line = line[:line.index("//")]

        # --- 전처리기 지시문 스킵 ---
        # #define STRCPY(a,b) strcpy(a,b) 같은 매크로 정의는 사용처가 아니다
        stripped = line.strip()
        if stripped.startswith("#include") or stripped.startswith("#define"):
            continue

        for match in FUNC_PATTERN.finditer(line):
            func_name = match.group(1)
            info = BANNED_FUNCTIONS[func_name]
            rel_path = os.path.relpath(filepath, base_dir).replace("\\", "/")

            findings.append({
                "file": rel_path,
                "line": line_no,
                "function": func_name,
                "context": stripped.strip()[:120],
                "cwe": info["cwe"],
                "risk": info["risk"],
                "alternative": info["alt"],
                "category": info["cat"],
            })

    return findings


def scan_directory(directory, base_dir=None):
    """디렉터리를 재귀 스캔한다. 빌드 산출물과 VCS 디렉터리는 제외."""
    if base_dir is None:
        base_dir = directory

    all_findings = []
    for root, dirs, files in os.walk(directory):
        # in-place 수정으로 os.walk 의 순회 대상 자체를 줄인다
        dirs[:] = [d for d in dirs
                   if not d.startswith(".") and d not in ("obj", "build")]

        for fname in files:
            if os.path.splitext(fname)[1].lower() in SRC_EXTS:
                all_findings.extend(scan_file(os.path.join(root, fname), base_dir))

    return all_findings


def to_sonar_json(findings):
    """SonarQube Generic Issue Import 형식으로 변환한다."""
    risk_to_severity = {
        "CRITICAL": "CRITICAL",
        "HIGH": "MAJOR",
        "MEDIUM": "MINOR",
        "LOW": "INFO",
    }

    issues = []
    for f in findings:
        issues.append({
            "engineId": "banned-function-scanner",
            "ruleId": f"banned_{f['function']}",
            "severity": risk_to_severity.get(f["risk"], "MINOR"),
            "type": "VULNERABILITY",
            "primaryLocation": {
                # 메시지에 CWE 와 대체 함수를 함께 넣어, 대시보드에서
                # 바로 조치 방법을 알 수 있게 한다
                "message": (f"[{f['cwe']}] Banned function '{f['function']}()' used. "
                            f"Replace with: {f['alternative']}"),
                "filePath": f["file"],
                "textRange": {"startLine": f["line"]},
            },
        })

    return {"issues": issues}


def merge_with_existing(new_json, existing_path):
    """기존 리포트에 병합한다 (재실행 안전).

    핵심: 병합 전에 '자기 자신이 만든 이슈'를 먼저 제거한다.
    그렇지 않으면 재스캔할 때마다 같은 이슈가 누적되어 통계가 망가진다.
    """
    if not os.path.isfile(existing_path):
        return new_json

    with open(existing_path, "r", encoding="utf-8") as f:
        existing = json.load(f)

    existing["issues"] = [
        i for i in existing.get("issues", [])
        if i.get("engineId") != "banned-function-scanner"
    ]
    existing["issues"].extend(new_json["issues"])
    return existing


def run_flawfinder(directories, base_dir):
    """Flawfinder 를 실행해 추가 이슈를 수집한다 (선택 기능).

    외부 도구가 없거나 실패해도 전체 스캔을 중단시키지 않는다.
    """
    try:
        cmd = ["flawfinder", "--csv", "--context"] + directories
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode != 0 and not result.stdout:
            print(f"  [경고] Flawfinder 실행 실패: {result.stderr[:200]}")
            return []

        issues = []
        for line in result.stdout.strip().split("\n")[1:]:   # 헤더 스킵
            parts = line.split(",")
            if len(parts) < 4:
                continue

            filepath = parts[0].strip('"')
            line_no = int(parts[1]) if parts[1].isdigit() else 0
            level = parts[2].strip()
            func = parts[3].strip('"')
            message = parts[-1].strip('"')

            rel_path = os.path.relpath(filepath, base_dir).replace("\\", "/")
            sev = ("CRITICAL" if level in ("5", "4")
                   else "MAJOR" if level == "3"
                   else "MINOR")

            issues.append({
                "engineId": "flawfinder",
                "ruleId": f"flawfinder_{func}",
                "severity": sev,
                "type": "VULNERABILITY",
                "primaryLocation": {
                    "message": message[:200] if message else f"Flawfinder: {func}",
                    "filePath": rel_path,
                    "textRange": {"startLine": line_no},
                },
            })
        return issues

    except FileNotFoundError:
        print("  [경고] Flawfinder 가 설치되어 있지 않습니다. pip install flawfinder")
        return []
    except Exception as e:
        print(f"  [경고] Flawfinder 오류: {e}")
        return []


def main():
    p = argparse.ArgumentParser(
        description="금지 함수 검사 + SonarQube 연동",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s ./src/
  %(prog)s ./src/ -o sonar-issues.json --merge
  %(prog)s ./src/ --with-flawfinder -o sonar-issues.json --merge
        """)
    p.add_argument("dirs", nargs="+", help="스캔할 소스 디렉터리")
    p.add_argument("-o", "--output", default="banned-issues.json", help="출력 JSON 경로")
    p.add_argument("--merge", action="store_true", help="기존 리포트에 병합")
    p.add_argument("--with-flawfinder", action="store_true", help="Flawfinder 병행 실행")
    p.add_argument("--csv", default=None, help="CSV 리포트 추가 출력")
    args = p.parse_args()

    base_dir = os.path.commonpath([os.path.abspath(d) for d in args.dirs])

    print(f"\n{'=' * 60}")
    print("  금지 함수 검사")
    print(f"  대상: {', '.join(args.dirs)}")
    print(f"{'=' * 60}\n")

    all_findings = []
    for d in args.dirs:
        if not os.path.isdir(d):
            print(f"  [경고] 디렉터리 없음: {d}")
            continue
        findings = scan_directory(d, base_dir)
        all_findings.extend(findings)
        print(f"  {d}: {len(findings)}개 발견")

    # --- 통계 ---
    by_risk, by_func, by_cat = defaultdict(int), defaultdict(int), defaultdict(int)
    for f in all_findings:
        by_risk[f["risk"]] += 1
        by_func[f["function"]] += 1
        by_cat[f["category"]] += 1

    print(f"\n  총 {len(all_findings)}개 금지함수 사용 발견\n")

    print("  위험도별:")
    for risk in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        if by_risk[risk]:
            print(f"    {risk:10s}: {by_risk[risk]:5d}")

    print("\n  함수별 Top 10:")
    for func, count in sorted(by_func.items(), key=lambda x: -x[1])[:10]:
        info = BANNED_FUNCTIONS[func]
        print(f"    {func:15s}: {count:5d}  [{info['cwe']}] -> {info['alt']}")

    print("\n  카테고리별:")
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"    {cat:20s}: {count:5d}")

    # --- 리포트 생성 ---
    sonar_json = to_sonar_json(all_findings)

    if args.with_flawfinder:
        print("\n  Flawfinder 실행 중...")
        fw_issues = run_flawfinder(args.dirs, base_dir)
        sonar_json["issues"].extend(fw_issues)
        print(f"  Flawfinder: {len(fw_issues)}개 추가 이슈")

    if args.merge and os.path.isfile(args.output):
        sonar_json = merge_with_existing(sonar_json, args.output)
        print(f"\n  기존 {args.output} 에 병합")

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(sonar_json, f, indent=2, ensure_ascii=False)
    print(f"\n  JSON -> {args.output}  (총 이슈: {len(sonar_json['issues'])}개)")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["file", "line", "function", "risk", "cwe",
                        "alternative", "category", "context"])
            for x in all_findings:
                w.writerow([x["file"], x["line"], x["function"], x["risk"],
                            x["cwe"], x["alternative"], x["category"], x["context"]])
        print(f"  CSV  -> {args.csv}")

    print(f"\n{'=' * 60}")
    print("  SonarQube 반영:")
    print(f"    sonar-scanner -Dsonar.externalIssuesReportPaths={args.output}")
    print(f"{'=' * 60}\n")


if __name__ == "__main__":
    main()
