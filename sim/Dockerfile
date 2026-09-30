# Runtime for python -m enetec_sim (make fleet/simulate/identity-tests/sim-test).
FROM python:3.12-alpine
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV PYTHONPATH=/lab/sim PYTHONUNBUFFERED=1
WORKDIR /lab
ENTRYPOINT ["python", "-m", "enetec_sim"]
