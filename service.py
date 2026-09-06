"""
service.py - STAGE 2 and STAGE 3: Service-Oriented Computing model.

The same computational core is exposed as a web service: the client sends
the array over HTTP (HyperText Transfer Protocol) as JSON (JavaScript Object
Notation), the service runs process_array() and returns the aggregates.

The handler deliberately accepts a raw Request instead of a Pydantic model:
FastAPI would parse and validate the body BEFORE entering the function, and
deserialization - one of the largest overhead components - would stay
unmeasured. The handler therefore parses the body itself, under timers.

The module is identical for Stage 2 (local process) and Stage 3 (container):
the only difference between the stages is the runtime environment.
"""

import json
import time
from typing import Any, Dict, List

from fastapi import FastAPI, Request, Response

from core import process_array
from metrics import resource_snapshot

app = FastAPI(title="Лабораторна робота 1 – обчислювальний веб-сервіс", version="1.0")

# Тип вмісту відповіді формується вручну, бо тіло серіалізується самостійно
MEDIA_TYPE = "application/json"


def _error(message: str, status_code: int) -> Response:
    """
    Формує відповідь про помилку у тому самому форматі, що й успішна.

    :param message: пояснення для клієнта
    :param status_code: код стану HTTP
    :return: готова відповідь сервісу
    """
    body = json.dumps({"error": message}, ensure_ascii=False)
    return Response(content=body, media_type=MEDIA_TYPE, status_code=status_code)


@app.get("/health")
def health() -> Dict[str, str]:
    """
    Проста перевірка готовності сервісу.

    Потрібна Етапу 3: після запуску контейнера клієнт очікує,
    поки сервіс справді почне відповідати, і лише тоді стартує заміри.

    :return: ознака готовності
    """
    return {"status": "ok"}


@app.get("/stats")
def stats() -> Dict[str, float]:
    """
    Повертає використання ресурсів САМИМ ПРОЦЕСОМ СЕРВІСУ.

    Клієнт викликає цю точку до серії вимірювань і після неї, а різницю
    рахує через metrics.resource_delta(). Знімати ресурси з процесу клієнта
    було б помилкою: обчислення виконує сервер.

    :return: процесорний час і пікова пам'ять процесу сервісу
    """
    return resource_snapshot()


@app.post("/compute")
async def compute(request: Request) -> Response:
    """
    Основна кінцева точка: обчислює статистики надісланого масиву.

    Таймери розділяють роботу обробника на три складові, які потім
    порівнюються з чистим часом обчислення з Етапу 1:
    десеріалізація -> обчислення -> серіалізація.

    :param request: сирий запит HTTP з тілом виду {"data": [...]}
    :return: відповідь із результатами та внутрішніми замірами сервера
    """
    t0 = time.perf_counter_ns()

    # Десеріалізація: зчитування тіла із сокета та розбір JSON
    raw = await request.body()
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError:
        return _error("Тіло запиту не є коректним JSON", 400)

    # Валідація навмисно мінімальна, щоб не додавати до заміру зайвої роботи
    if not isinstance(payload, dict) or "data" not in payload:
        return _error("У тілі запиту відсутній ключ 'data'", 400)
    data: List[float] = payload["data"]
    if not isinstance(data, list) or not data:
        return _error("Поле 'data' має бути непорожнім списком чисел", 400)
    t1 = time.perf_counter_ns()

    # Обчислення: ядро використовується без жодних змін (інваріант роботи)
    result = process_array(data)
    t2 = time.perf_counter_ns()

    # Серіалізація: значення власних таймерів ще невідомі на момент вимірювання,
    # тому дамп виконується двічі – перший вимірюваний, другий фінальний.
    # Відповідь містить лише шість агрегатів, тож повторний дамп коштує мікросекунди
    # і не спотворює результат.
    json.dumps({
        "result": result,
        "server_deserialize_ms": 0.0,
        "server_compute_ms": 0.0,
        "server_serialize_ms": 0.0,
        "server_total_ms": 0.0,
        "request_bytes": len(raw),
    })
    t3 = time.perf_counter_ns()

    body = json.dumps({
        "result": result,
        # Розбір тіла запиту: найдорожча складова на великих масивах
        "server_deserialize_ms": (t1 - t0) / 1_000_000.0,
        # Чисте обчислення: порівнюється з базовою лінією Етапу 1
        "server_compute_ms": (t2 - t1) / 1_000_000.0,
        # Формування тіла відповіді
        "server_serialize_ms": (t3 - t2) / 1_000_000.0,
        # Повний час усередині обробника
        "server_total_ms": (t3 - t0) / 1_000_000.0,
        # Реальний розмір тіла запиту: у JSON число займає 18–19 символів,
        # тому масив на 10 000 елементів дає приблизно 190 КБ замість «100 КБ»
        "request_bytes": len(raw),
    })
    return Response(content=body, media_type=MEDIA_TYPE)
