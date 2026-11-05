package dev.orbitremote.app;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLSocket;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;

/**
 * TLS connection to an Orbit PC, authenticated by public-key pinning, exposed to the
 * WebView as a one-shot TCP listener on 127.0.0.1.
 *
 * <p>LAN PCs can't present a publicly trusted certificate, so the PC's self-signed certificate
 * carries its long-term identity key and the app pins SHA-256(SubjectPublicKeyInfo) — the same
 * fingerprint shown on the PC and phone screens. The first connection to an unknown PC is
 * trust-on-first-use: the web UI asks the user to compare fingerprints before sending anything,
 * and the encrypted application channel must be signed by the very same key.
 * Plaintext only ever travels over the loopback interface inside the phone.
 */
final class PinnedTunnel {

    static final class KeyMismatchException extends IOException {
        final String fingerprint;

        KeyMismatchException(String fingerprint) {
            super("key_mismatch:" + fingerprint);
            this.fingerprint = fingerprint;
        }
    }

    private final SSLSocket remote;
    private final ServerSocket listener;
    final String fingerprint;

    private PinnedTunnel(SSLSocket remote, ServerSocket listener, String fingerprint) {
        this.remote = remote;
        this.listener = listener;
        this.fingerprint = fingerprint;
    }

    int localPort() {
        return listener.getLocalPort();
    }

    /** Connects and completes the TLS handshake; throws {@link KeyMismatchException} if the pin fails. */
    static PinnedTunnel open(String host, int port, String pin) throws Exception {
        PinningTrustManager trust = new PinningTrustManager(pin);
        SSLContext context = SSLContext.getInstance("TLS");
        context.init(null, new TrustManager[] {trust}, new SecureRandom());

        Socket raw = new Socket();
        SSLSocket tls = null;
        try {
            raw.connect(new InetSocketAddress(host, port), 6000);
            raw.setTcpNoDelay(true);
            raw.setSoTimeout(10000);
            tls = (SSLSocket) context.getSocketFactory().createSocket(raw, host, port, true);
            List<String> protocols = new ArrayList<>();
            for (String p : tls.getSupportedProtocols()) {
                if ("TLSv1.3".equals(p) || "TLSv1.2".equals(p)) protocols.add(p);
            }
            tls.setEnabledProtocols(protocols.toArray(new String[0]));
            try {
                tls.startHandshake();
            } catch (IOException e) {
                if (trust.mismatch != null) throw new KeyMismatchException(trust.mismatch);
                throw e;
            }
            tls.setSoTimeout(0);
            ServerSocket listener = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"));
            listener.setSoTimeout(10000);
            return new PinnedTunnel(tls, listener, trust.seen);
        } catch (Exception e) {
            closeQuietly(tls);
            closeQuietly(raw);
            throw e;
        }
    }

    /** Waits for the WebView to connect, then pipes bytes both ways until either side closes. */
    void serve() {
        Socket local = null;
        try {
            local = listener.accept();
            local.setTcpNoDelay(true);
        } catch (IOException e) {
            closeQuietly(remote);
            return;
        } finally {
            closeQuietly(listener);
        }
        final Socket client = local;
        Thread up = new Thread(() -> pipe(client, remote), "orbit-tunnel-up");
        up.start();
        pipe(remote, client);
    }

    private static void pipe(Socket from, Socket to) {
        byte[] buffer = new byte[64 * 1024];
        try {
            InputStream in = from.getInputStream();
            OutputStream out = to.getOutputStream();
            int n;
            while ((n = in.read(buffer)) != -1) {
                out.write(buffer, 0, n);
                out.flush();
            }
        } catch (IOException ignored) {
            // Connection closed.
        } finally {
            closeQuietly(from);
            closeQuietly(to);
        }
    }

    static String fingerprint(byte[] spki) throws Exception {
        byte[] digest = MessageDigest.getInstance("SHA-256").digest(spki);
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < 8; i++) {
            if (i > 0 && i % 2 == 0) sb.append(' ');
            sb.append(String.format(Locale.ROOT, "%02X", digest[i]));
        }
        return sb.toString();
    }

    private static void closeQuietly(java.io.Closeable c) {
        if (c == null) return;
        try {
            c.close();
        } catch (IOException ignored) {
            // Nothing to do.
        }
    }

    /** Accepts exactly the pinned key (or, with no pin yet, records the key for the user to verify). */
    private static final class PinningTrustManager implements X509TrustManager {
        private final String pin;
        volatile String seen = "";
        volatile String mismatch;

        PinningTrustManager(String pin) {
            this.pin = pin == null ? "" : pin.trim().toUpperCase(Locale.ROOT);
        }

        @Override
        public void checkServerTrusted(X509Certificate[] chain, String authType) throws CertificateException {
            if (chain == null || chain.length == 0) throw new CertificateException("no certificate");
            String fp;
            try {
                fp = fingerprint(chain[0].getPublicKey().getEncoded());
            } catch (Exception e) {
                throw new CertificateException("cannot read certificate", e);
            }
            seen = fp;
            if (!pin.isEmpty() && !pin.equals(fp)) {
                mismatch = fp;
                throw new CertificateException("Orbit security key mismatch");
            }
        }

        @Override
        public void checkClientTrusted(X509Certificate[] chain, String authType) throws CertificateException {
            throw new CertificateException("client certificates are not used");
        }

        @Override
        public X509Certificate[] getAcceptedIssuers() {
            return new X509Certificate[0];
        }
    }
}
