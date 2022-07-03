FROM python:3.8.13-slim

ENV PORT=7330

WORKDIR /app/
COPY / /app
RUN pip install .
CMD blobse run -p $PORT
