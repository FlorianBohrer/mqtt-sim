package com.enetec.lab;

import static com.enetec.lab.EnetecIdentityMain.AUDIT;

import com.hivemq.extension.sdk.api.async.Async;
import com.hivemq.extension.sdk.api.async.TimeoutFallback;
import com.hivemq.extension.sdk.api.auth.SimpleAuthenticator;
import com.hivemq.extension.sdk.api.auth.parameter.SimpleAuthInput;
import com.hivemq.extension.sdk.api.auth.parameter.SimpleAuthOutput;
import com.hivemq.extension.sdk.api.client.parameter.ClientTlsInformation;
import com.hivemq.extension.sdk.api.packets.connect.ConnackReasonCode;
import com.hivemq.extension.sdk.api.services.Services;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.cert.X509Certificate;
import java.time.Duration;
import java.util.Optional;

/** Decides CONNECT from the client certificate; the identity is kept as connection attribute. */
final class CertificateAuthenticator implements SimpleAuthenticator {

    static final String IDENTITY_ATTRIBUTE = "enetec.identity";

    private final Policy policy;

    CertificateAuthenticator(final Policy policy) {
        this.policy = policy;
    }

    @Override
    public void onConnect(final SimpleAuthInput input, final SimpleAuthOutput output) {
        final String clientId = input.getClientInformation().getClientId();
        final Optional<X509Certificate> certificate = input.getConnectionInformation()
                .getClientTlsInformation().flatMap(ClientTlsInformation::getClientCertificate);
        if (certificate.isEmpty()) {
            reject(output, clientId, "-", ConnackReasonCode.NOT_AUTHORIZED, "no client certificate");
            return;
        }
        final Optional<String> identity;
        try {
            identity = policy.identityOf(certificate.get());
        } catch (final Exception e) {
            reject(output, clientId, "-", ConnackReasonCode.NOT_AUTHORIZED, "unreadable certificate subject");
            return;
        }
        final String serial = certificate.get().getSerialNumber().toString(16);
        if (identity.isEmpty()) {
            reject(output, clientId, serial, ConnackReasonCode.NOT_AUTHORIZED,
                    "certificate without CN and not in registry");
            return;
        }
        if (policy.isRevoked(certificate.get())) {
            reject(output, clientId, serial, ConnackReasonCode.NOT_AUTHORIZED, "certificate revoked");
            return;
        }
        if (policy.enforceClientId() && !identity.get().equals(clientId)) {
            reject(output, clientId, serial, ConnackReasonCode.CLIENT_IDENTIFIER_NOT_VALID,
                    "client id does not match certificate identity " + identity.get());
            return;
        }
        input.getConnectionInformation().getConnectionAttributeStore()
                .put(IDENTITY_ATTRIBUTE, ByteBuffer.wrap(identity.get().getBytes(StandardCharsets.UTF_8)));
        if (!policy.rejectDuplicateClientId()) {
            accept(output, clientId, identity.get(), serial);
            return;
        }
        // ENETEC: a second connection must not take over an active session.
        final Async<SimpleAuthOutput> async = output.async(Duration.ofSeconds(5), TimeoutFallback.FAILURE);
        Services.clientService().isClientConnected(clientId).whenComplete((connected, error) -> {
            if (error != null) {
                reject(output, clientId, serial, ConnackReasonCode.SERVER_UNAVAILABLE, "duplicate check failed");
            } else if (Boolean.TRUE.equals(connected)) {
                reject(output, clientId, serial, ConnackReasonCode.CLIENT_IDENTIFIER_NOT_VALID,
                        "client id already connected, existing session kept");
            } else {
                accept(output, clientId, identity.get(), serial);
            }
            async.resume();
        });
    }

    private static void accept(final SimpleAuthOutput output, final String clientId, final String identity,
                               final String serial) {
        AUDIT.info("ENETEC-AUDIT connect-accepted clientId={} identity={} certSerial={}", clientId, identity, serial);
        output.authenticateSuccessfully();
    }

    private static void reject(final SimpleAuthOutput output, final String clientId, final String serial,
                               final ConnackReasonCode code, final String reason) {
        AUDIT.warn("ENETEC-AUDIT connect-rejected clientId={} certSerial={} code={} reason=\"{}\"",
                clientId, serial, code, reason);
        output.failAuthentication(code, reason);
    }
}
