# HiveMQ CE with the ENETEC lab extension (built from extension/ in a Maven stage).
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY extension/pom.xml .
RUN mvn -q -B dependency:go-offline
COPY extension/src src
RUN mvn -q -B package

FROM hivemq/hivemq-ce:2026.5
ENV HIVEMQ_ALLOW_ALL_CLIENTS=false \
    ENETEC_KEYSTORE=/opt/hivemq/lab-certs/hivemq/broker.p12 \
    ENETEC_TRUSTSTORE=/opt/hivemq/data/enetec-truststore.p12 \
    ENETEC_PERMISSIONS=/opt/hivemq/extensions/enetec-identity/conf/permissions.tsv \
    ENETEC_CLIENT_IDS=/opt/hivemq/extensions/enetec-identity/conf/client_ids.tsv \
    ENETEC_REGISTRY=/opt/hivemq/lab-certs/legacy/registry.tsv \
    ENETEC_CRL=/opt/hivemq/lab-certs/negative/crl.pem
COPY --chown=10000:0 extension/src/main/resources/hivemq-extension.xml /opt/hivemq/extensions/enetec-identity/
COPY --chown=10000:0 --from=build /src/target/enetec-identity-1.0.0.jar /opt/hivemq/extensions/enetec-identity/
COPY --chown=10000:0 config.xml /opt/hivemq/conf/config.xml
COPY --chown=10000:0 --chmod=755 start.sh /opt/enetec-start.sh
CMD ["/opt/enetec-start.sh"]
