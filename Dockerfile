FROM python:3.8.13-slim

ENV PORT=7330
ENV SERVER_URL=http://localhost:7330
ENV REDIS_HOST=redis
ENV REDIS_PORT=6379

WORKDIR /app/
COPY / /app
RUN pip install .
CMD blobse run -p $PORT
