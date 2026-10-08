package com.enetec.lab;

import static com.enetec.lab.EnetecIdentityMain.AUDIT;

import com.hivemq.extension.sdk.api.packets.disconnect.DisconnectReasonCode;
import com.hivemq.extension.sdk.api.services.Services;
import com.hivemq.extension.sdk.api.services.subscription.TopicSubscription;

import java.io.IOException;
import java.math.BigInteger;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.stream.Collectors;

/**
 * Current policy. Every 2 s the policy files are checked; after a change the policy is reloaded
 * and applied to open connections (ENTC-63 REV-01 / ACL-14): a connection whose certificate is now
 * revoked is closed, subscriptions that are no longer permitted are removed.
 */
final class PolicyHolder {

    /** One open connection: the identity and certificate serial it authenticated with. */
    static final class Session {
        final String identity;
        final BigInteger certificateSerial;

        Session(final String identity, final BigInteger certificateSerial) {
            this.identity = identity;
            this.certificateSerial = certificateSerial;
        }
    }

    private final AtomicReference<Policy> current;
    private final Map<String, Session> sessions = new ConcurrentHashMap<>();
    private Map<Path, String> stamps;

    PolicyHolder(final Policy initial) {
        current = new AtomicReference<>(initial);
        stamps = stamps();
    }

    Policy get() {
        return current.get();
    }

    void track(final String clientId, final Session session) {
        sessions.put(clientId, session);
    }

    /** Forget a connection, unless the Client ID already belongs to a newer one. */
    void untrack(final String clientId, final BigInteger certificateSerial) {
        sessions.computeIfPresent(clientId,
                (id, session) -> session.certificateSerial.equals(certificateSerial) ? null : session);
    }

    void start() {
        Services.extensionExecutorService().scheduleWithFixedDelay(this::checkFiles, 2, 2, TimeUnit.SECONDS);
    }

    private void checkFiles() {
        final Map<Path, String> now = stamps();
        if (now.equals(stamps)) {
            return;
        }
        stamps = now;
        final Policy policy;
        try {
            policy = Policy.fromEnvironment();
        } catch (final Exception e) {
            AUDIT.error("ENETEC-AUDIT policy-reload-failed {} (previous policy stays active)", e.toString());
            return;
        }
        current.set(policy);
        AUDIT.info("ENETEC-AUDIT policy-reloaded permissions={} clientIds={} registry={} revoked={}",
                policy.permissionCount(), policy.clientIdCount(), policy.registrySize(), policy.revokedCount());
        sessions.forEach((clientId, session) -> apply(policy, clientId, session));
    }

    private static void apply(final Policy policy, final String clientId, final Session session) {
        if (policy.isRevoked(session.certificateSerial)) {
            AUDIT.warn("ENETEC-AUDIT session-terminated clientId={} certSerial={} reason=\"certificate revoked\"",
                    clientId, session.certificateSerial.toString(16));
            Services.clientService().disconnectClient(clientId, true, DisconnectReasonCode.NOT_AUTHORIZED,
                    "certificate revoked");
            return;
        }
        Services.subscriptionStore().getSubscriptions(clientId).thenAccept(subscriptions -> {
            final Set<String> withdrawn = subscriptions.stream().map(TopicSubscription::getTopicFilter)
                    .filter(filter -> !policy.allowed(session.identity, Policy.Action.SUBSCRIBE, filter))
                    .collect(Collectors.toSet());
            if (!withdrawn.isEmpty()) {
                AUDIT.warn("ENETEC-AUDIT subscription-removed clientId={} identity={} filters={}",
                        clientId, session.identity, withdrawn);
                Services.subscriptionStore().removeSubscriptions(clientId, withdrawn);
            }
        });
    }

    private static Map<Path, String> stamps() {
        final Map<Path, String> out = new HashMap<>();
        for (final Path file : Policy.files()) {
            try {
                out.put(file, Files.getLastModifiedTime(file) + "/" + Files.size(file));
            } catch (final IOException e) {
                out.put(file, "missing");
            }
        }
        return out;
    }
}
