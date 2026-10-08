package com.enetec.lab;

import static com.enetec.lab.EnetecIdentityMain.AUDIT;

import com.hivemq.extension.sdk.api.events.client.ClientLifecycleEventListener;
import com.hivemq.extension.sdk.api.events.client.parameters.AuthenticationFailedInput;
import com.hivemq.extension.sdk.api.events.client.parameters.AuthenticationSuccessfulInput;
import com.hivemq.extension.sdk.api.events.client.parameters.ConnectionStartInput;
import com.hivemq.extension.sdk.api.events.client.parameters.DisconnectEventInput;

import java.math.BigInteger;
import java.nio.charset.StandardCharsets;

/** Connection lifecycle for the audit log (LOG-01 / LOG-04) and the open-connection list. */
final class AuditListener implements ClientLifecycleEventListener {

    private final PolicyHolder holder;

    AuditListener(final PolicyHolder holder) {
        this.holder = holder;
    }

    @Override
    public void onMqttConnectionStart(final ConnectionStartInput input) {
        AUDIT.info("ENETEC-AUDIT connection-start clientId={}", input.getClientInformation().getClientId());
    }

    @Override
    public void onAuthenticationSuccessful(final AuthenticationSuccessfulInput input) {
        AUDIT.info("ENETEC-AUDIT authenticated clientId={}", input.getClientInformation().getClientId());
    }

    @Override
    public void onAuthenticationFailedDisconnect(final AuthenticationFailedInput input) {
        // A rejected attempt never was an open connection (e.g. duplicate Client ID): only log it.
        log(input);
    }

    @Override
    public void onDisconnect(final DisconnectEventInput input) {
        input.getConnectionInformation().getConnectionAttributeStore()
                .get(CertificateAuthenticator.SERIAL_ATTRIBUTE)
                .map(buffer -> new BigInteger(StandardCharsets.UTF_8.decode(buffer.duplicate()).toString(), 16))
                .ifPresent(serial -> holder.untrack(input.getClientInformation().getClientId(), serial));
        log(input);
    }

    private static void log(final DisconnectEventInput input) {
        AUDIT.info("ENETEC-AUDIT disconnect clientId={} reason={} detail=\"{}\"",
                input.getClientInformation().getClientId(),
                input.getReasonCode().map(Object::toString).orElse("-"),
                input.getReasonString().orElse(""));
    }
}
