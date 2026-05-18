FROM python:3.12-slim

WORKDIR /app

COPY destination/destination_server.py /app/destination_server.py

ENV DESTINATION_HOST=0.0.0.0
ENV DESTINATION_PORT=9101

EXPOSE 9101

CMD ["python", "-u", "destination_server.py"]