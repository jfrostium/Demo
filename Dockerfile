FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# LiveRepo's builder reads this EXPOSE line to know which port to publish.
EXPOSE 8000
CMD ["python", "app.py"]
