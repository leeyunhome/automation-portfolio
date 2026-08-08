#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
measure_latency_ocr.py
======================
영상 장비의 End-to-End(glass-to-glass) 지연을 OCR 로 자동 측정한다.

-------------------------------------------------------------------------------
측정 원리
-------------------------------------------------------------------------------
밀리초 단위 스톱워치를 띄운 화면을 두 대의 장비가 동시에 촬영하고,
그 장비들의 출력 화면과 원본 스톱워치를 한 모니터에 나란히 배치한다.
이 상태를 스크린샷으로 캡처하면, 한 장의 이미지 안에

    [원본 스톱워치]  [장비 A 출력]
                     [장비 B 출력]

세 개의 시각이 함께 찍힌다. 원본과 각 장비 화면의 시각 차이가
곧 그 장비의 파이프라인 지연(촬영 -> 인코딩 -> 전송 -> 디코딩 -> 표시)이다.

사람이 스크린샷 수백 장의 숫자를 눈으로 읽고 빼는 것은 비현실적이므로,
ROI 분할 + OCR + 파싱 + 차분을 자동화했다.

-------------------------------------------------------------------------------
설계 포인트
-------------------------------------------------------------------------------
1) ROI 를 비율(0.0~1.0)로 지정
   해상도가 다른 캡처 세션이 섞여도 같은 설정으로 동작한다.

2) --psm 7 (single text line)
   숫자 한 줄만 있는 영역이므로 페이지 세그멘테이션을 끄면 인식률이 오른다.

3) debug_roi.png 자동 생성
   OCR 자동화의 최대 위험은 "ROI 가 어긋났는데 그럴듯한 숫자가 나오는 것"이다.
   첫 이미지에 ROI 사각형과 인식 결과를 그려 파일로 남겨, 사람이 1초 만에
   영역 설정을 검증할 수 있게 했다.

4) 관용적 파싱
   OCR 은 콜론/마침표를 혼동하기 쉽다. 숫자와 구분자만 남기고
   필드 개수(HH:MM:SS / MM:SS / SS)에 따라 유연하게 해석한다.
   해석 실패 시 None 을 반환해 통계에서 자연스럽게 제외되도록 한다.

사용법
------
  # screenshots_* 폴더들이 있는 위치에서 실행
  ./measure_latency_ocr.py
"""

import glob
import os
import re

import cv2
import pandas as pd
import pytesseract

# -----------------------------------------------------------------------------
# ROI 설정: (x_start_pct, y_start_pct, x_end_pct, y_end_pct)
#
# 화면 배치 가정
#   reference : 좌상단 (기준 스톱워치)
#   device_a  : 우상단
#   device_b  : 우하단
# -----------------------------------------------------------------------------
ROIS = {
    "reference": (0.0, 0.0, 0.5, 0.5),   # 좌상단
    "device_a":  (0.5, 0.0, 1.0, 0.5),   # 우상단
    "device_b":  (0.5, 0.5, 1.0, 1.0),   # 우하단
}

OCR_CONFIG = "--psm 7"   # 단일 텍스트 라인으로 취급


def parse_time(text):
    """시각 문자열을 초 단위 float 로 변환한다.

    허용 포맷: HH:MM:SS.ms / MM:SS.ms / SS.ms
    OCR 노이즈를 고려해 숫자와 구분자 외 문자는 모두 제거한 뒤 해석한다.
    해석 불가 시 None 을 반환한다(통계에서 자동 제외).
    """
    if not text:
        return None

    # 숫자, 콜론, 마침표만 남긴다
    clean_text = re.sub(r"[^0-9:.]", "", text)

    try:
        parts = clean_text.split(":")

        if len(parts) == 3:      # HH:MM:SS.ms
            return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:      # MM:SS.ms
            return float(parts[0]) * 60 + float(parts[1])
        if len(parts) == 1:      # SS.ms
            return float(parts[0])
        return None

    except ValueError:
        return None


def process_images(base_dir):
    results = []
    dirs = sorted(glob.glob(os.path.join(base_dir, "screenshots_*")))
    debug_saved = False

    for d in dirs:
        images = sorted(glob.glob(os.path.join(d, "*.png")))
        print(f"Processing folder: {d} ({len(images)} images)")

        for img_path in images:
            img = cv2.imread(img_path)
            if img is None:
                print(f"Warning: Could not read {img_path}")
                continue

            h, w, _ = img.shape

            row = {
                "filename": os.path.basename(img_path),
                "folder": os.path.basename(d),
            }
            for name in ROIS:
                row[f"raw_{name}"] = None
                row[f"sec_{name}"] = None
            row["latency_device_a"] = None
            row["latency_device_b"] = None

            debug_img = img.copy()

            for name, (x1p, y1p, x2p, y2p) in ROIS.items():
                # 비율 -> 픽셀 좌표 (해상도 독립적)
                x1, y1 = int(x1p * w), int(y1p * h)
                x2, y2 = int(x2p * w), int(y2p * h)

                crop = img[y1:y2, x1:x2]

                # 화면 캡처는 대비가 이미 좋아 그레이스케일만으로 충분하다.
                # 과한 이진화는 오히려 얇은 숫자 획을 지워 인식률을 떨어뜨렸다.
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

                try:
                    text = pytesseract.image_to_string(gray, config=OCR_CONFIG)
                    clean_text = text.strip()
                    val = parse_time(clean_text)

                    row[f"raw_{name}"] = clean_text
                    row[f"sec_{name}"] = val

                    # 검증용 오버레이: ROI 사각형 + 인식 결과
                    cv2.rectangle(debug_img, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(debug_img, f"{name}: {clean_text} ({val}s)",
                                (x1, y1 + 30), cv2.FONT_HERSHEY_SIMPLEX,
                                0.8, (0, 0, 255), 2)

                except Exception as e:
                    print(f"OCR Error on {name} in {img_path}: {e}")

            # 기준 시각 대비 각 장비의 지연 산출
            base_time = row["sec_reference"]
            if base_time is not None:
                if row["sec_device_a"] is not None:
                    row["latency_device_a"] = row["sec_device_a"] - base_time
                if row["sec_device_b"] is not None:
                    row["latency_device_b"] = row["sec_device_b"] - base_time

            results.append(row)

            # 첫 이미지 1장만 검증용으로 저장 (ROI 오설정 조기 발견)
            if not debug_saved:
                cv2.imwrite("debug_roi.png", debug_img)
                print("Saved debug_roi.png (ROI 설정을 눈으로 확인하세요)")
                debug_saved = True

    if results:
        df = pd.DataFrame(results)
        df.to_csv("latency_results.csv", index=False)
        print(f"Successfully processed {len(results)} images.")
        print("Results saved to latency_results.csv")

        # 요약 통계
        for col in ("latency_device_a", "latency_device_b"):
            series = df[col].dropna()
            if not series.empty:
                print(f"  {col}: mean={series.mean():.3f}s  "
                      f"min={series.min():.3f}s  max={series.max():.3f}s")
    else:
        print("No results found.")


if __name__ == "__main__":
    process_images(".")
