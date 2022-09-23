FROM python:3.10.2

WORKDIR /app

COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip \
  && pip install --no-cache-dir -r requirements.txt

COPY /src/sample_app_moco_playground.py /app/sample_app.py

CMD ["python3", "sample_app.py"]