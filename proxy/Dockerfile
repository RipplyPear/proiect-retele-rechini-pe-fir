FROM python:3.12-slim

WORKDIR /app

COPY proxy/proxy_server.py /app/proxy_server.py

ENV PROXY_HOST=0.0.0.0
ENV PROXY_PORT=9000
ENV DESTINATION_HOST=destination
ENV DESTINATION_PORT=9101
ENV PROXY_DATA_DIR=/app/proxy_data/public

RUN mkdir -p /app/proxy_data/public \
    && echo "Salut din fisierul expus de proxy" > /app/proxy_data/public/sample.txt

EXPOSE 9000

CMD ["python", "-u", "proxy_server.py"]