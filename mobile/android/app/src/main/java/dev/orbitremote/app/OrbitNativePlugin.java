package dev.orbitremote.app;

import android.content.Context;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.provider.Settings;
import android.view.HapticFeedbackConstants;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;

import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import org.json.JSONObject;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.net.InterfaceAddress;
import java.net.NetworkInterface;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * Native bridge for the Orbit web UI: pinned TLS tunnel to the PC, LAN discovery,
 * screen wake lock, immersive mode, haptics and a friendly device name.
 */
@CapacitorPlugin(name = "OrbitNative")
public class OrbitNativePlugin extends Plugin {

    private static final int DISCOVERY_PORT = 47801;
    private static final int DEFAULT_PORT = 47800;
    private static final byte[] QUERY = "ORBIT_DISCOVER_V1".getBytes(StandardCharsets.US_ASCII);

    @PluginMethod
    public void openTunnel(PluginCall call) {
        final String host = call.getString("host", "");
        final int port = call.getInt("port", DEFAULT_PORT);
        final String pin = call.getString("pin", "");
        if (host == null || host.isEmpty() || port < 1 || port > 65535) {
            call.reject("bad_address");
            return;
        }
        new Thread(() -> {
            PinnedTunnel tunnel;
            try {
                tunnel = PinnedTunnel.open(host, port, pin);
            } catch (PinnedTunnel.KeyMismatchException e) {
                call.reject(e.getMessage(), "KEY_MISMATCH");
                return;
            } catch (Exception e) {
                call.reject("unreachable", "UNREACHABLE");
                return;
            }
            JSObject result = new JSObject();
            result.put("port", tunnel.localPort());
            result.put("fingerprint", tunnel.fingerprint);
            call.resolve(result);
            tunnel.serve();
        }, "orbit-tunnel").start();
    }

    @PluginMethod
    public void discover(PluginCall call) {
        final int timeout = Math.max(300, Math.min(call.getInt("timeout", 1600), 6000));
        new Thread(() -> {
            JSArray devices = new JSArray();
            Set<String> seen = new HashSet<>();
            WifiManager.MulticastLock lock = null;
            try (DatagramSocket socket = new DatagramSocket()) {
                socket.setBroadcast(true);
                socket.setSoTimeout(200);
                WifiManager wifi = (WifiManager) getContext().getApplicationContext().getSystemService(Context.WIFI_SERVICE);
                if (wifi != null) {
                    lock = wifi.createMulticastLock("orbit-discovery");
                    lock.setReferenceCounted(false);
                    lock.acquire();
                }
                List<InetAddress> targets = broadcastTargets();
                byte[] buffer = new byte[4096];
                long deadline = System.currentTimeMillis() + timeout;
                long nextSend = 0;
                while (System.currentTimeMillis() < deadline) {
                    long now = System.currentTimeMillis();
                    if (now >= nextSend) {
                        for (InetAddress target : targets) {
                            try {
                                socket.send(new DatagramPacket(QUERY, QUERY.length, target, DISCOVERY_PORT));
                            } catch (Exception ignored) {
                                // Some interfaces reject broadcasts; try the others.
                            }
                        }
                        nextSend = now + 450;
                    }
                    DatagramPacket packet = new DatagramPacket(buffer, buffer.length);
                    try {
                        socket.receive(packet);
                    } catch (SocketTimeoutException e) {
                        continue;
                    }
                    try {
                        JSONObject info = new JSONObject(new String(packet.getData(), 0, packet.getLength(), StandardCharsets.UTF_8));
                        if (info.optInt("orbit") != 1) continue;
                        String id = info.optString("id", "");
                        if (id.isEmpty() || !seen.add(id)) continue;
                        JSObject device = new JSObject();
                        device.put("id", id);
                        device.put("name", info.optString("name", "PC"));
                        device.put("address", packet.getAddress().getHostAddress());
                        device.put("port", info.optInt("port", DEFAULT_PORT));
                        device.put("version", info.optString("version", ""));
                        device.put("os", info.optString("os", ""));
                        devices.put(device);
                    } catch (Exception ignored) {
                        // Not an Orbit reply.
                    }
                }
            } catch (Exception ignored) {
                // Return whatever was found.
            } finally {
                if (lock != null && lock.isHeld()) lock.release();
            }
            JSObject result = new JSObject();
            result.put("devices", devices);
            call.resolve(result);
        }, "orbit-discovery").start();
    }

    private static List<InetAddress> broadcastTargets() {
        List<InetAddress> out = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (InterfaceAddress address : ni.getInterfaceAddresses()) {
                    InetAddress broadcast = address.getBroadcast();
                    if (broadcast != null && !out.contains(broadcast)) out.add(broadcast);
                }
            }
        } catch (Exception ignored) {
            // Fall back to the limited broadcast address below.
        }
        try {
            InetAddress limited = InetAddress.getByName("255.255.255.255");
            if (!out.contains(limited)) out.add(limited);
        } catch (Exception ignored) {
            // Not reachable on a real device.
        }
        return out;
    }

    @PluginMethod
    public void keepAwake(PluginCall call) {
        final boolean enabled = call.getBoolean("enabled", true);
        getActivity().runOnUiThread(() -> {
            Window window = getActivity().getWindow();
            if (enabled) window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            else window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
            call.resolve();
        });
    }

    @PluginMethod
    public void setImmersive(PluginCall call) {
        final boolean enabled = call.getBoolean("enabled", true);
        getActivity().runOnUiThread(() -> {
            Window window = getActivity().getWindow();
            WindowInsetsControllerCompat controller = WindowCompat.getInsetsController(window, window.getDecorView());
            controller.setAppearanceLightStatusBars(false);
            controller.setAppearanceLightNavigationBars(false);
            if (enabled) {
                controller.setSystemBarsBehavior(WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
                controller.hide(WindowInsetsCompat.Type.systemBars());
            } else {
                controller.show(WindowInsetsCompat.Type.systemBars());
            }
            call.resolve();
        });
    }

    @PluginMethod
    public void haptic(PluginCall call) {
        final String kind = call.getString("kind", "light");
        getActivity().runOnUiThread(() -> {
            View view = getBridge().getWebView();
            int constant = "heavy".equals(kind) ? HapticFeedbackConstants.LONG_PRESS : HapticFeedbackConstants.KEYBOARD_TAP;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && "light".equals(kind)) {
                constant = HapticFeedbackConstants.CONTEXT_CLICK;
            }
            view.performHapticFeedback(constant);
            call.resolve();
        });
    }

    @PluginMethod
    public void deviceInfo(PluginCall call) {
        String name = null;
        try {
            name = Settings.Global.getString(getContext().getContentResolver(), "device_name");
        } catch (Exception ignored) {
            // Not available on every vendor build.
        }
        if (name == null || name.trim().isEmpty()) {
            String maker = Build.MANUFACTURER == null ? "" : Build.MANUFACTURER;
            String model = Build.MODEL == null ? "Android phone" : Build.MODEL;
            if (!maker.isEmpty() && !model.toLowerCase(Locale.ROOT).startsWith(maker.toLowerCase(Locale.ROOT))) {
                model = Character.toUpperCase(maker.charAt(0)) + maker.substring(1) + " " + model;
            }
            name = model;
        }
        JSObject result = new JSObject();
        result.put("name", name.trim());
        result.put("model", Build.MODEL);
        result.put("sdk", Build.VERSION.SDK_INT);
        call.resolve(result);
    }
}
