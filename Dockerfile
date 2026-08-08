FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /opt/enterprise-ai-platform

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY app ./app
COPY agents ./agents
COPY migrations ./migrations
COPY alembic.ini config.yaml config.production.yaml run.py ./

EXPOSE 8000

# 数据库迁移应由发布流水线执行：alembic upgrade head。
CMD ["python", "run.py"]
