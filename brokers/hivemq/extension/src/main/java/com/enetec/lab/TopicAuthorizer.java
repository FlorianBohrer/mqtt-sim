package com.enetec.lab;

import static com.enetec.lab.EnetecIdentityMain.AUDIT;

import com.hivemq.extension.sdk.api.auth.PublishAuthorizer;
import com.hivemq.extension.sdk.api.auth.SubscriptionAuthorizer;
import com.hivemq.extension.sdk.api.auth.parameter.PublishAuthorizerInput;
import com.hivemq.extension.sdk.api.auth.parameter.PublishAuthorizerOutput;
import com.hivemq.extension.sdk.api.auth.parameter.SubscriptionAuthorizerInput;
import com.hivemq.extension.sdk.api.auth.parameter.SubscriptionAuthorizerOutput;
import com.hivemq.extension.sdk.api.client.parameter.ConnectionInformation;
import com.hivemq.extension.sdk.api.packets.publish.AckReasonCode;
import com.hivemq.extension.sdk.api.packets.subscribe.SubackReasonCode;

import java.nio.charset.StandardCharsets;

/** Default-deny topic permissions keyed on the certificate identity (not the Client ID). */
final class TopicAuthorizer implements PublishAuthorizer, SubscriptionAuthorizer {

    private final PolicyHolder holder;

    TopicAuthorizer(final PolicyHolder holder) {
        this.holder = holder;
    }

    @Override
    public void authorizePublish(final PublishAuthorizerInput input, final PublishAuthorizerOutput output) {
        final String identity = identity(input.getConnectionInformation());
        final String topic = input.getPublishPacket().getTopic();
        if (identity != null && holder.get().allowed(identity, Policy.Action.PUBLISH, topic)) {
            output.authorizeSuccessfully();
            return;
        }
        AUDIT.warn("ENETEC-AUDIT publish-denied clientId={} identity={} topic={}",
                input.getClientInformation().getClientId(), identity, topic);
        output.failAuthorization(AckReasonCode.NOT_AUTHORIZED, "not authorized for " + topic);
    }

    @Override
    public void authorizeSubscribe(final SubscriptionAuthorizerInput input,
                                   final SubscriptionAuthorizerOutput output) {
        final String identity = identity(input.getConnectionInformation());
        final String filter = input.getSubscription().getTopicFilter();
        if (identity != null && holder.get().allowed(identity, Policy.Action.SUBSCRIBE, filter)) {
            output.authorizeSuccessfully();
            return;
        }
        AUDIT.warn("ENETEC-AUDIT subscribe-denied clientId={} identity={} filter={}",
                input.getClientInformation().getClientId(), identity, filter);
        output.failAuthorization(SubackReasonCode.NOT_AUTHORIZED, "not authorized for " + filter);
    }

    private static String identity(final ConnectionInformation connection) {
        return connection.getConnectionAttributeStore().get(CertificateAuthenticator.IDENTITY_ATTRIBUTE)
                .map(buffer -> StandardCharsets.UTF_8.decode(buffer.duplicate()).toString())
                .orElse(null);
    }
}
