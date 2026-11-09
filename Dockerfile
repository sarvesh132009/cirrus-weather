FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

# Run as a normal user, not root
RUN useradd --create-home --uid 10001 cirrus
COPY --chown=cirrus:cirrus . /app
USER cirrus

# Most hosts inject their own PORT; run.py reads it. 8000 is the fallback.
ENV PORT=8000
EXPOSE 8000

CMD ["python", "run.py"]
