# Runtime for python -m enetec_sim and the certificate scripts 12/15
# (OpenSSL 3 instead of the host's LibreSSL on macOS).
FROM python:3.12-alpine
RUN apk add --no-cache openssl
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
ENV PYTHONPATH=/lab/sim PYTHONUNBUFFERED=1
WORKDIR /lab
ENTRYPOINT ["python", "-m", "enetec_sim"]
