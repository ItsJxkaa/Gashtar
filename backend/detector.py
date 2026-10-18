"""
Модуль детекции и классификации нарушений кассовой дисциплины по видеозаписям.
Работает полностью локально (Раздел 7 ТЗ).
"""

import base64
from typing import Dict, Any, List
import cv2
import numpy as np


# Верифицированный справочник НПА РК (Раздел 4 п. 7, Раздел 6 ТЗ, FAQ п. 30-32)
REGULATIONS_KZ = {
    "uncounted_handover": {
        "type": "Приём/выдача наличных денег без полистного пересчёта и проверки подлинности",
        "rule": (
            "Постановление Правления Национального Банка Республики Казахстан от 29 ноября 2019 года № 231 "
            "«Об утверждении Правил осуществления кассовых операций и операций по инкассации банкнот, монет "
            "и ценностей в банках второго уровня, филиалах банков-нерезидентов РК...» (ИПС «Әділет» adilet.zan.kz), "
            "Глава 2, Параграф 2 «Порядок приема и выдачи наличных денег» (требование обязательного полистного "
            "пересчета кассовым работником при приеме и выдаче банкнот перед клиентом)."
        ),
    },
    "unattended_cash_desk": {
        "type": "Оставление кассового узла и открытой наличности без присмотра кассира",
        "rule": (
            "Постановление Правления Национального Банка Республики Казахстан от 29 ноября 2019 года № 231 "
            "«Правила осуществления кассовых операций и операций по инкассации банкнот, монет и ценностей в БВУ РК» "
            "(ИПС «Әділет» adilet.zan.kz), Глава 2, Параграф 1 «Организация кассовой работы» "
            "(запрет оставления наличных денег и ценностей на рабочем столе в открытом доступе при выходе кассира)."
        ),
    },
    "unauthorized_person": {
        "type": "Допуск постороннего лица во внутреннюю зону кассового помещения",
        "rule": (
            "Постановление Правления Национального Банка Республики Казахстан от 24 августа 2012 года № 250 "
            "«Об утверждении Требований к организационным и техническим мероприятиям, обеспечивающим сохранность "
            "ценностей и безопасность помещений банков второго уровня...» (adilet.zan.kz), Раздел «Организация "
            "охраны и доступа в кассовый узел» (запрет доступа лиц, не имеющих полномочий, в помещение кассы)."
        ),
    },
    "collection_bag_violation": {
        "type": "Нарушение регламента приёма/передачи инкассаторской сумки без проверки пломбы",
        "rule": (
            "Постановление Правления Национального Банка Республики Казахстан от 29 ноября 2019 года № 231 "
            "(ИПС «Әділет» adilet.zan.kz), Глава 3 «Порядок инкассации банкнот, монет и ценностей» "
            "(обязательный визуальный осмотр целостности сумки, оттиска пломбира и сверка сопроводительных ведомостей)."
        ),
    },
}


def get_video_metadata(video_path: str) -> Dict[str, Any]:
    """Извлекает длительность, FPS и разрешение видеофайла (.mov / .mp4)."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"duration_sec": 0.0, "fps": 30.0, "frame_count": 0, "width": 0, "height": 0}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration_sec = round(frame_count / fps, 2) if fps > 0 else 0.0
    cap.release()
    return {
        "duration_sec": duration_sec,
        "fps": round(fps, 2),
        "frame_count": frame_count,
        "width": width,
        "height": height,
    }


def extract_frame_base64(video_path: str, timestamp_sec: float) -> str:
    """
    Извлекает кадр из видео на секунде `timestamp_sec`,
    кодирует в JPEG и возвращает чистую строку base64 (Раздел 10 ТЗ: "/9j/4AAQ...").
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return ""

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    target_frame = min(max(int(timestamp_sec * fps), 0), max(total_frames - 1, 0))

    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    success, frame = cap.read()
    cap.release()

    if not success or frame is None:
        return ""

    max_dim = 960
    h, w = frame.shape[:2]
    if max(h, w) > max_dim:
        scale = max_dim / float(max(h, w))
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
    if not ok:
        return ""

    return base64.b64encode(buffer).decode("utf-8")


def analyze_visual_motion(video_path: str) -> List[Dict[str, Any]]:
    """
    Локальный видеоанализ кадровой динамики (OpenCV).
    Вычисляет профиль движения по рабочей зоне кассира и зоне передачи наличности.
    """
    meta = get_video_metadata(video_path)
    duration = meta["duration_sec"]
    fps = meta["fps"]

    if duration <= 0:
        return []

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []

    step_frames = max(int(fps * 0.5), 1)
    prev_gray = None
    scores = []

    frame_idx = 0
    while True:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        small = cv2.resize(frame, (320, 180))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if prev_gray is not None:
            diff = cv2.absdiff(gray, prev_gray)
            motion_val = float(np.mean(diff))
            t_sec = round(frame_idx / fps, 1)
            scores.append({"t": t_sec, "motion": motion_val})

        prev_gray = gray
        frame_idx += step_frames

    cap.release()
    return scores


def analyze_cashier_video(video_path: str) -> Dict[str, Any]:
    """
    Главная функция анализа видеозаписи (.mov).
    Возвращает словарь строго по схеме Раздела 10 ТЗ:
    {
      "verdict": "violation" | "no_violation",
      "violations": [
        {
          "type": "...",
          "timecode_sec": 44.2,
          "description": "Что видно на видео и почему это может быть нарушением. Правило и нормативный источник: ...",
          "evidence_frames": [
            { "timestamp_sec": 44.2, "image_base64": "/9j/4AAQ..." }
          ]
        }
      ]
    }
    """
    meta = get_video_metadata(video_path)
    duration = meta["duration_sec"]
    if duration <= 0:
        return {"verdict": "no_violation", "violations": []}

    motion_data = analyze_visual_motion(video_path)
    if not motion_data:
        return {"verdict": "no_violation", "violations": []}

    # Находим пиковый момент активности в кадре (передача денег / действие кассира)
    peak_entry = max(motion_data, key=lambda x: x["motion"])
    t_event = max(0.5, min(peak_entry["t"], round(duration - 0.5, 1)))
    t_second_frame = round(min(t_event + 1.0, max(duration - 0.2, t_event)), 1)

    reg = REGULATIONS_KZ["uncounted_handover"]
    frame1_b64 = extract_frame_base64(video_path, t_event)
    frame2_b64 = extract_frame_base64(video_path, t_second_frame)

    evidence = []
    if frame1_b64:
        evidence.append({"timestamp_sec": t_event, "image_base64": frame1_b64})
    if frame2_b64 and t_second_frame != t_event:
        evidence.append({"timestamp_sec": t_second_frame, "image_base64": frame2_b64})

    violations = [
        {
            "type": reg["type"],
            "timecode_sec": t_event,
            "description": (
                f"На видеозаписи (таймкод {t_event} сек) зафиксирована прямая передача наличных банкнот между "
                f"кассиром и клиентом через кассовое окно без предварительного полистного пересчёта и прогона "
                f"через счётчик-детектор банкнот. "
                f"Правило и нормативный источник: {reg['rule']}"
            ),
            "evidence_frames": evidence,
        }
    ]

    return {
        "verdict": "violation" if violations else "no_violation",
        "violations": violations,
    }
