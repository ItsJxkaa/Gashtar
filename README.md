# GASH.Контроль — AI Cash Compliance Studio
> Проект для ForteBank Datathon 26 (Кейс: Автоматизированный видеоконтроль кассовых операций)

Автономный сервис видеоаналитики кассовой дисциплины, работающий полностью локально (On-Premise) без внешних облачных API.

---

## 📊 Презентация проекта (12 слайдов)
- 🖥️ **PowerPoint-презентация (.pptx):** [`GASH_Control_Pitch_Deck.pptx`](GASH_Control_Pitch_Deck.pptx)

---

## 🚀 Быстрый запуск

### 1. Требования
- Python 3.10+ (рекомендуется 3.12)
- Windows / Linux / macOS

### 2. Установка зависимостей
```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r backend/requirements.txt
```

### 3. Запуск сервера
**Windows:**
Просто запустите скрипт:
```cmd
run_server.bat
```
Или вручную:
```bash
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Интерфейс доступен в браузере: **http://localhost:8000**  
Интерактивная документация API (Swagger): **http://localhost:8000/docs**

---

## ☁️ Круглосуточный облачный деплой 24/7 (Render / Railway / Koyeb)

В репозитории подготовлены `Dockerfile` и `render.yaml`. Чтобы сайт работал 24/7 без включенного ПК:

### Вариант 1. Render.com (Бесплатно, самый простой способ):
1. Зайдите на [render.com](https://render.com) и войдите через свой GitHub-аккаунт.
2. Нажмите **New +** -> **Web Service**.
3. Выберите репозиторий `Gashtar`.
4. Render автоматически увидит `Dockerfile` и `render.yaml`.
5. Нажмите **Deploy Web Service**.
6. Через 2-3 минуты сервис получит постоянный глобальный HTTPS-адрес: `https://gash-kontrol.onrender.com`.

### Вариант 2. Railway.app:
1. Зайдите на [railway.app](https://railway.app), нажмите **New Project** -> **Deploy from GitHub repo** -> `Gashtar`.
2. Сервис развернется автоматически.

---

## 🧠 Как подключить натренированную модель ИИ

Вся интеграция модели сосредоточена в одном месте — в файле [`backend/detector.py`](backend/detector.py):

1. Поместите файл весов вашей модели (например, `best.pt`, `model.onnx` или `.pth`) в каталог `backend/weights/`.
2. В файле [`backend/detector.py`](backend/detector.py) найдите функцию `analyze_cashier_video(video_path: str)`:
```python
# Пример для YOLO:
from ultralytics import YOLO
model = YOLO("weights/best.pt")

def analyze_cashier_video(video_path: str) -> dict:
    # 1. Инференс вашей модели
    results = model(video_path)
    
    # 2. Возвращаемый словарь строго по схеме Раздела 10 ТЗ:
    return {
        "verdict": "violation" if has_violation else "no_violation",
        "violations": [
            {
                "type": "Приём/выдача наличных денег без полистного пересчёта",
                "timecode_sec": 44.2,  # секунда инцидента
                "description": "Описание инцидента и ссылка на норму НБРК",
                "evidence_frames": [
                    { "timestamp_sec": 44.2, "image_base64": "/9j/4AAQ..." }
                ]
            }
        ]
    }
```
*Функция извлечения кадров в base64 `extract_frame_base64(video_path, timestamp_sec)` уже написана в `detector.py` и готова к использованию.*

---

## 📡 API для проверки жюри (Раздел 10 ТЗ)

- **Ключ авторизации:** `X-API-Key: forte-datathon-2026-key`
- `POST /api/v1/analyze` — загрузка `.mov` в multipart-форме (поле `file`), возвращает `{"job_id": "...", "status": "processing"}`
- `GET /api/v1/jobs/{job_id}` — получение статуса и итогового JSON с кадрами-доказательствами

---

## 👥 Команда GASH.Контроль
- **ML / Computer Vision** — Madi Zhassymbek
- **Backend FastAPI** — Amire Kaliya
- **Frontend UI/UX** — Zhankerey Askaruly
- **Data Analyst** — Damir Ibatullin
