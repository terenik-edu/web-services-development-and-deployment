# Образ Етапу 3: той самий веб-сервіс, що й на Етапі 2, але в контейнері.
#
# Версія інтерпретатора зафіксована точно такою, як у локальному .venv (3.11.9),
# інакше різниця в часі між Етапами 2 і 3 частково пояснювалася б різними
# версіями Python, а не впливом контейнеризації.

FROM python:3.11.9-slim
LABEL authors="dmytro-terenyk"

# Логи сервера не буферизуються – потрібні одразу, для скріншота у звіт.
# Файли .pyc у контейнері не потрібні.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /project

# Використовується короткий перелік (requirements-service.txt) – без matplotlib і numpy,
# які потрібні лише для побудови графіків на хості.
COPY requirements-service.txt /project/
RUN pip install --no-cache-dir -r /project/requirements-service.txt

# У контейнер іде лише те, що потрібно сервісу.
COPY core.py metrics.py service.py /project/

EXPOSE 8000

# --host 0.0.0.0 – інакше сервіс слухав би лише всередині контейнера;
# --workers 1 і --log-level warning – ті самі параметри, що й на Етапі 2,
# без цього заміри двох етапів непорівнювані.
CMD ["uvicorn", "service:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "warning"]

# Збірка та запуск виконуються скриптом run_stage3.sh:
#   ./run_stage3.sh
# Обмеження ресурсів (--cpus=1.0 --memory=512m) і порт 8001 задано там.