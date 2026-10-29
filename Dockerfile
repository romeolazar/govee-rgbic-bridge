FROM python:3.13-alpine

RUN addgroup -S bridge && adduser -S -G bridge bridge

WORKDIR /app
COPY --chown=bridge:bridge govee_bridge.py /app/govee_bridge.py

USER bridge

EXPOSE 19446/udp

ENTRYPOINT ["python3", "-u", "/app/govee_bridge.py"]
