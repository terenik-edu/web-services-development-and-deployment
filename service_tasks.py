"""
service_tasks.py - LAB 2: computational task service (local run and Azure App Service).

Each POST /tasks creates a task: the array is processed by the unchanged
core.process_array() and only task metadata (no input array) is kept in an
in-memory history that can be listed, read and deleted.

Timers and the raw Request handling follow service.py (LR1), so that
server_compute_ms is the algorithm latency and the rest of the client-side
request latency is the overhead.
"""

import itertools
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query, Request, Response

from core import process_array
from metrics import resource_snapshot

app = FastAPI(title="Лабораторна робота 2 – сервіс обчислювальних задач", version="2.0")

MEDIA_TYPE = "application/json"

# Захист пам'яті на B1: при переповненні видаляється найстаріший запис
MAX_HISTORY = 10_000

# Сховище без блокувань: один воркер, а всі обробники сховища – async,
# тобто виконуються в одному потоці циклу подій і не перетинаються.
TASKS: Dict[int, Dict[str, Any]] = {}
_task_ids = itertools.count(1)

# Схема тіла для Swagger: без моделі Pydantic FastAPI сам її не знає
TASK_REQUEST_BODY: Dict[str, Any] = {
    "required": True,
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "required": ["data"],
                "properties": {
                    "data": {"type": "array", "items": {"type": "number"}, "minItems": 1},
                },
            },
            "example": {"data": [12.5, 3.0, 47.25, 8.0, 19.75, 31.0, 5.5, 26.0, 14.25, 40.0]},
        }
    },
}


def _error(message: str, status_code: int) -> Response:
    """Повертає помилку у форматі ЛР1: {"error": "..."}."""
    body = json.dumps({"error": message}, ensure_ascii=False)
    return Response(content=body, media_type=MEDIA_TYPE, status_code=status_code)


@app.get("/health")
def health() -> Dict[str, str]:
    """Перевірка готовності: клієнт чекає на неї перед замірами (холодний старт у хмарі)."""
    return {"status": "ok"}


@app.get("/stats")
def stats() -> Dict[str, float]:
    """Ресурси процесу сервісу; різницю до/після серії рахує клієнт."""
    return resource_snapshot()


@app.post("/tasks", status_code=201, openapi_extra={"requestBody": TASK_REQUEST_BODY})
async def create_task(request: Request) -> Response:
    """
    Створює задачу: обчислює статистики масиву і зберігає метадані.

    Таймери як у ЛР1: десеріалізація -> обчислення -> серіалізація.
    Збереження в історію – після t3, у заміри не входить.

    :param request: сирий запит з тілом {"data": [...]}
    :return: 201 із записом задачі та замірами сервера, заголовок Location
    """
    t0 = time.perf_counter_ns()

    raw = await request.body()
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError:
        return _error("Тіло запиту не є коректним JSON", 400)

    # Валідація мінімальна, щоб не додавати зайвої роботи до заміру
    if not isinstance(payload, dict) or "data" not in payload:
        return _error("У тілі запиту відсутній ключ 'data'", 400)
    data: List[float] = payload["data"]
    if not isinstance(data, list) or not data:
        return _error("Поле 'data' має бути непорожнім списком чисел", 400)
    t1 = time.perf_counter_ns()

    result = process_array(data)
    t2 = time.perf_counter_ns()

    # Вимірюваний дамп тієї самої структури; id і час ще не відомі – заглушки
    json.dumps({
        "id": 0,
        "created_at": "",
        "size": len(data),
        "result": result,
        "server_deserialize_ms": 0.0,
        "server_compute_ms": 0.0,
        "server_serialize_ms": 0.0,
        "server_total_ms": 0.0,
        "request_bytes": len(raw),
    })
    t3 = time.perf_counter_ns()

    task_id = next(_task_ids)
    record: Dict[str, Any] = {
        "id": task_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "size": len(data),
        "result": result,
        "server_deserialize_ms": (t1 - t0) / 1_000_000.0,
        # Algorithm latency
        "server_compute_ms": (t2 - t1) / 1_000_000.0,
        "server_serialize_ms": (t3 - t2) / 1_000_000.0,
        "server_total_ms": (t3 - t0) / 1_000_000.0,
        "request_bytes": len(raw),
    }

    # Словник зберігає порядок вставки, тож перший ключ – найстаріший
    if len(TASKS) >= MAX_HISTORY:
        del TASKS[next(iter(TASKS))]
    TASKS[task_id] = record

    return Response(
        content=json.dumps(record),
        media_type=MEDIA_TYPE,
        status_code=201,
        headers={"Location": f"/tasks/{task_id}"},
    )


@app.get("/tasks")
async def list_tasks(
    limit: Optional[int] = Query(None, ge=0, description="Кількість останніх задач; без параметра – усі"),
) -> Dict[str, Any]:
    """
    Історія виконаних задач (лише метадані), від старіших до новіших.

    :param limit: скільки останніх задач повернути
    :return: загальна кількість у сховищі та перелік задач
    """
    tasks = list(TASKS.values())
    if limit is not None:
        tasks = tasks[max(0, len(tasks) - limit):]
    return {"total": len(TASKS), "tasks": tasks}


@app.get("/tasks/{task_id}")
async def get_task(task_id: int) -> Response:
    """Повертає одну задачу або 404."""
    record = TASKS.get(task_id)
    if record is None:
        return _error(f"Задачу {task_id} не знайдено", 404)
    return Response(content=json.dumps(record), media_type=MEDIA_TYPE)


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int) -> Response:
    """Видаляє задачу з історії: 204 без тіла або 404."""
    if TASKS.pop(task_id, None) is None:
        return _error(f"Задачу {task_id} не знайдено", 404)
    return Response(status_code=204)