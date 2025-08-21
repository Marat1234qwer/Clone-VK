FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install psycopg2-binary
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "app.py"]
CMD ["flask", "run", "--host=0.0.0.0", "--reload"]
