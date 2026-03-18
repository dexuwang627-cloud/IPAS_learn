FROM python:3.12-slim

WORKDIR /app

COPY requirements.prod.txt .
RUN pip install --no-cache-dir -r requirements.prod.txt

COPY main.py database.py auth.py middleware.py config.py ./
COPY routers/ routers/
COPY services/ services/
COPY static/ static/
COPY templates/ templates/
COPY data/questions.db data/questions.db

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
RUN chown -R appuser:appgroup /app
USER appuser

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
