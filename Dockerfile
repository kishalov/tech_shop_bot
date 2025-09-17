# Используем официальный Python-образ
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Скопировать requirements.txt и установить зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код в контейнер
COPY . .

# Переменные окружения (например, чтобы Python не кешировал)
ENV PYTHONUNBUFFERED=1

# Команда запуска
CMD ["python", "bot.py"]
