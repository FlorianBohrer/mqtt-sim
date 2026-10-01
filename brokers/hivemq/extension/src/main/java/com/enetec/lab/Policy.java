package com.enetec.lab;

import java.io.InputStream;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.cert.CRL;
import java.security.cert.CertificateFactory;
import java.security.cert.X509CRL;
import java.security.cert.X509CRLEntry;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import javax.naming.ldap.LdapName;
import javax.naming.ldap.Rdn;

/** Immutable policy loaded at start: permissions, fingerprint registry, revoked serials. */
final class Policy {

    enum Action { PUBLISH, SUBSCRIBE }

    private final Map<String, List<String>> publish = new HashMap<>();
    private final Map<String, List<String>> subscribe = new HashMap<>();
    private final Map<String, String> registry = new HashMap<>();
    private final Set<BigInteger> revoked = new HashSet<>();
    private final boolean enforceClientId;
    private final boolean rejectDuplicateClientId;

    private Policy(final boolean enforceClientId, final boolean rejectDuplicateClientId) {
        this.enforceClientId = enforceClientId;
        this.rejectDuplicateClientId = rejectDuplicateClientId;
    }

    /**
     * ENETEC_PERMISSIONS  identity TAB publish|subscribe TAB topic-filter (required)
     * ENETEC_REGISTRY     SHA-256 fingerprint TAB gateway-id (optional, legacy certificates)
     * ENETEC_CRL          PEM CRL of the issuing CA (optional)
     * ENETEC_ENFORCE_CLIENT_ID / ENETEC_REJECT_DUPLICATE_CLIENT_ID  true|false (default true)
     */
    static Policy fromEnvironment() throws Exception {
        final Policy policy = new Policy(flag("ENETEC_ENFORCE_CLIENT_ID"), flag("ENETEC_REJECT_DUPLICATE_CLIENT_ID"));
        policy.loadPermissions(EnetecIdentityMain.path("ENETEC_PERMISSIONS",
                "/opt/hivemq/extensions/enetec-identity/conf/permissions.tsv"));
        policy.loadRegistry(EnetecIdentityMain.path("ENETEC_REGISTRY", "/opt/hivemq/lab-certs/legacy/registry.tsv"));
        policy.loadCrl(EnetecIdentityMain.path("ENETEC_CRL", "/opt/hivemq/lab-certs/negative/crl.pem"));
        return policy;
    }

    private static boolean flag(final String env) {
        final String value = System.getenv(env);
        return value == null || !value.trim().equalsIgnoreCase("false");
    }

    private void loadPermissions(final Path file) throws Exception {
        for (final String line : Files.readAllLines(file, StandardCharsets.UTF_8)) {
            if (line.isBlank() || line.startsWith("#")) {
                continue;
            }
            final String[] parts = line.split("\t");
            if (parts.length != 3) {
                throw new IllegalArgumentException("bad permission line: " + line);
            }
            final Map<String, List<String>> target = "publish".equals(parts[1]) ? publish
                    : "subscribe".equals(parts[1]) ? subscribe : null;
            if (target == null) {
                throw new IllegalArgumentException("unknown action in: " + line);
            }
            target.computeIfAbsent(parts[0], k -> new ArrayList<>()).add(parts[2]);
        }
    }

    private void loadRegistry(final Path file) throws Exception {
        if (!Files.isReadable(file)) {
            return;
        }
        for (final String line : Files.readAllLines(file, StandardCharsets.UTF_8)) {
            final String[] parts = line.split("\t");
            if (parts.length == 2) {
                registry.put(parts[0].trim().toUpperCase(Locale.ROOT), parts[1].trim());
            }
        }
    }

    private void loadCrl(final Path file) throws Exception {
        if (!Files.isReadable(file)) {
            return;
        }
        try (InputStream in = Files.newInputStream(file)) {
            for (final CRL crl : CertificateFactory.getInstance("X.509").generateCRLs(in)) {
                final Set<? extends X509CRLEntry> entries = ((X509CRL) crl).getRevokedCertificates();
                if (entries != null) {
                    entries.forEach(entry -> revoked.add(entry.getSerialNumber()));
                }
            }
        }
    }

    /** Identity from the certificate: CN, else the registry entry for its fingerprint. */
    Optional<String> identityOf(final X509Certificate certificate) throws Exception {
        final LdapName name = new LdapName(certificate.getSubjectX500Principal().getName());
        for (final Rdn rdn : name.getRdns()) {
            if ("CN".equalsIgnoreCase(rdn.getType())) {
                return Optional.of(rdn.getValue().toString());
            }
        }
        return Optional.ofNullable(registry.get(fingerprint(certificate)));
    }

    static String fingerprint(final X509Certificate certificate) throws Exception {
        final byte[] digest = MessageDigest.getInstance("SHA-256").digest(certificate.getEncoded());
        final StringBuilder out = new StringBuilder();
        for (final byte b : digest) {
            if (out.length() > 0) {
                out.append(':');
            }
            out.append(String.format("%02X", b));
        }
        return out.toString();
    }

    boolean isRevoked(final X509Certificate certificate) {
        return revoked.contains(certificate.getSerialNumber());
    }

    boolean allowed(final String identity, final Action action, final String topicOrFilter) {
        final List<String> rules = (action == Action.PUBLISH ? publish : subscribe)
                .getOrDefault(identity, Collections.emptyList());
        for (final String rule : rules) {
            if (covers(rule, topicOrFilter)) {
                return true;
            }
        }
        return false;
    }

    /**
     * True if every topic matched by {@code filter} is also matched by {@code rule}
     * (for a publish, {@code filter} is a plain topic). A '+' or '#' in the client's
     * filter is only covered by a wildcard at the same position in the rule.
     */
    static boolean covers(final String rule, final String filter) {
        final String[] r = rule.split("/", -1);
        final String[] f = filter.split("/", -1);
        for (int i = 0; i < r.length; i++) {
            if ("#".equals(r[i])) {
                return true;
            }
            if (i >= f.length || "#".equals(f[i])) {
                return false;
            }
            if ("+".equals(r[i])) {
                continue;
            }
            if (!r[i].equals(f[i])) {
                return false;
            }
        }
        return r.length == f.length;
    }

    boolean enforceClientId() {
        return enforceClientId;
    }

    boolean rejectDuplicateClientId() {
        return rejectDuplicateClientId;
    }

    int permissionCount() {
        return publish.values().stream().mapToInt(List::size).sum()
                + subscribe.values().stream().mapToInt(List::size).sum();
    }

    int registrySize() {
        return registry.size();
    }

    int revokedCount() {
        return revoked.size();
    }
}
