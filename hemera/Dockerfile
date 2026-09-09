ARG BUILD_FROM
FROM $BUILD_FROM

# openssl provides libssl.so.3/libcrypto.so.3 that the future DTLS-PSK
# Entertainment server (hemera.services.entertainment) dlopen()s directly via
# cffi — installed now so the image doesn't need rebuilding for that step.
RUN apk add --no-cache openssl

WORKDIR /app
COPY pyproject.toml ./
COPY hemera ./hemera
RUN pip install --no-cache-dir .

# s6-overlay service definition (this base image's PID 1)
COPY rootfs /
RUN chmod a+x /etc/services.d/hemera/run /etc/services.d/hemera/finish
