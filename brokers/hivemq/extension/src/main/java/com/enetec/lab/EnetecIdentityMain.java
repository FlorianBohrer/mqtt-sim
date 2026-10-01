package com.enetec.lab;

import com.hivemq.extension.sdk.api.ExtensionMain;
import com.hivemq.extension.sdk.api.parameter.ExtensionStartInput;
import com.hivemq.extension.sdk.api.parameter.ExtensionStartOutput;
import com.hivemq.extension.sdk.api.parameter.ExtensionStopInput;
import com.hivemq.extension.sdk.api.parameter.ExtensionStopOutput;
import com.hivemq.extension.sdk.api.services.Services;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.nio.file.Path;

/**
 * ENETEC lab extension for HiveMQ CE (ENTC-59 / ENTC-63).
 *
 * <ul>
 *   <li>identity = certificate CN, or the Gateway ID from the fingerprint registry for
 *       legacy certificates without CN (AWS IoT profile);</li>
 *   <li>CONNECT is rejected if the Client ID differs from that identity, if the certificate
 *       is on the revocation list, or if the Client ID already has an active connection;</li>
 *   <li>publish/subscribe are allowed only by the permissions file, everything else is denied;</li>
 *   <li>every decision is logged with the prefix ENETEC-AUDIT.</li>
 * </ul>
 * Paths and switches come from environment variables, see {@link Policy#fromEnvironment()}.
 */
public class EnetecIdentityMain implements ExtensionMain {

    static final Logger AUDIT = LoggerFactory.getLogger("ENETEC-AUDIT");

    @Override
    public void extensionStart(final ExtensionStartInput input, final ExtensionStartOutput output) {
        try {
            final Policy policy = Policy.fromEnvironment();
            final CertificateAuthenticator authenticator = new CertificateAuthenticator(policy);
            final TopicAuthorizer authorizer = new TopicAuthorizer(policy);
            Services.securityRegistry().setAuthenticatorProvider(providerInput -> authenticator);
            Services.securityRegistry().setAuthorizerProvider(providerInput -> authorizer);
            Services.eventRegistry().setClientLifecycleEventListener(providerInput -> new AuditListener());
            AUDIT.info("ENETEC-AUDIT extension-started permissions={} registry={} revoked={} "
                            + "enforceClientId={} rejectDuplicateClientId={}",
                    policy.permissionCount(), policy.registrySize(), policy.revokedCount(),
                    policy.enforceClientId(), policy.rejectDuplicateClientId());
        } catch (final Exception e) {
            AUDIT.error("ENETEC-AUDIT extension-failed {}", e.toString());
            output.preventExtensionStartup("ENETEC identity extension could not load its policy: " + e);
        }
    }

    @Override
    public void extensionStop(final ExtensionStopInput input, final ExtensionStopOutput output) {
        AUDIT.info("ENETEC-AUDIT extension-stopped");
    }

    static Path path(final String env, final String fallback) {
        final String value = System.getenv(env);
        return Path.of(value == null || value.isBlank() ? fallback : value);
    }
}
