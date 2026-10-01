package com.enetec.lab;

import static com.enetec.lab.EnetecIdentityMain.AUDIT;

import com.hivemq.extension.sdk.api.events.client.ClientLifecycleEventListener;
import com.hivemq.extension.sdk.api.events.client.parameters.AuthenticationSuccessfulInput;
import com.hivemq.extension.sdk.api.events.client.parameters.ConnectionStartInput;
import com.hivemq.extension.sdk.api.events.client.parameters.DisconnectEventInput;

/** Connection lifecycle for the audit log (LOG-01 / LOG-04). */
final class AuditListener implements ClientLifecycleEventListener {

    @Override
    public void onMqttConnectionStart(final ConnectionStartInput input) {
        AUDIT.info("ENETEC-AUDIT connection-start clientId={}", input.getClientInformation().getClientId());
    }

    @Override
    public void onAuthenticationSuccessful(final AuthenticationSuccessfulInput input) {
        AUDIT.info("ENETEC-AUDIT authenticated clientId={}", input.getClientInformation().getClientId());
    }

    @Override
    public void onDisconnect(final DisconnectEventInput input) {
        AUDIT.info("ENETEC-AUDIT disconnect clientId={} reason={} detail=\"{}\"",
                input.getClientInformation().getClientId(),
                input.getReasonCode().map(Object::toString).orElse("-"),
                input.getReasonString().orElse(""));
    }
}
