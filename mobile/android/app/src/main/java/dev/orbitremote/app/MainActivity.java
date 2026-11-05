package dev.orbitremote.app;

import android.content.res.Configuration;
import android.graphics.Color;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.webkit.WebSettings;
import android.webkit.WebView;

import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowCompat;
import androidx.core.view.WindowInsetsCompat;
import androidx.core.view.WindowInsetsControllerCompat;

import com.getcapacitor.BridgeActivity;
import com.getcapacitor.WebViewListener;

import java.util.Locale;

/**
 * Edge-to-edge shell. System bar / display cutout insets are measured here and pushed into the
 * page as CSS variables (--orbit-inset-*), re-sent after every page load so the UI never slides
 * under the status bar. The on-screen keyboard is handled by padding the window above the IME.
 */
public class MainActivity extends BridgeActivity {
    private static final int TEXT_ZOOM_MIN = 85;
    private static final int TEXT_ZOOM_MAX = 115;

    /** Last measured insets in CSS px (dp): top, right, bottom, left. */
    static volatile int[] lastInsets = new int[] { 0, 0, 0, 0 };

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(OrbitNativePlugin.class);
        super.onCreate(savedInstanceState);
        setupWindow();
        setupWebView();
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        applyTextZoom();
        View decor = getWindow().getDecorView();
        ViewCompat.requestApplyInsets(decor);
    }

    /** The UI is dark, so system bar icons are always light. */
    private void applySystemBarIcons() {
        Window window = getWindow();
        WindowInsetsControllerCompat controller = WindowCompat.getInsetsController(window, window.getDecorView());
        controller.setAppearanceLightStatusBars(false);
        controller.setAppearanceLightNavigationBars(false);
    }

    @SuppressWarnings("deprecation")
    private void setupWindow() {
        Window window = getWindow();
        WindowCompat.setDecorFitsSystemWindows(window, false);
        window.setStatusBarColor(Color.TRANSPARENT);
        window.setNavigationBarColor(Color.TRANSPARENT);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            window.setStatusBarContrastEnforced(false);
            window.setNavigationBarContrastEnforced(false);
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            WindowManager.LayoutParams lp = window.getAttributes();
            lp.layoutInDisplayCutoutMode = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R
                ? WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS
                : WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES;
            window.setAttributes(lp);
        }
        applySystemBarIcons();

        View decor = window.getDecorView();
        ViewCompat.setOnApplyWindowInsetsListener(decor, (v, insets) -> {
            int types = WindowInsetsCompat.Type.systemBars() | WindowInsetsCompat.Type.displayCutout();
            Insets bars = insets.getInsets(types);
            boolean imeVisible = insets.isVisible(WindowInsetsCompat.Type.ime());
            Insets ime = insets.getInsets(WindowInsetsCompat.Type.ime());

            // Keep content above the keyboard (adjustResize does nothing edge-to-edge).
            v.setPadding(0, 0, 0, imeVisible ? ime.bottom : 0);

            float density = getResources().getDisplayMetrics().density;
            lastInsets = new int[] {
                Math.round(bars.top / density),
                Math.round(bars.right / density),
                imeVisible ? 0 : Math.round(bars.bottom / density),
                Math.round(bars.left / density),
            };
            pushInsets();

            // Pass zeroed bar insets on so the WebView's own env() does not double-apply them.
            // (Returning CONSUMED breaks later recalculation: https://issues.chromium.org/issues/461332423)
            return new WindowInsetsCompat.Builder(insets).setInsets(types, Insets.NONE).build();
        });
    }

    private void setupWebView() {
        applyTextZoom();
        if (bridge != null && bridge.getWebView() != null) {
            // PC sound is only played after the user turns it on in a session, so the WebView
            // may resume the remembered choice on reconnect without waiting for another tap.
            bridge.getWebView().getSettings().setMediaPlaybackRequiresUserGesture(false);
        }
        bridge.addWebViewListener(new WebViewListener() {
            @Override
            public void onPageCommitVisible(WebView view, String url) {
                pushInsets();
            }

            @Override
            public void onPageLoaded(WebView webView) {
                pushInsets();
            }
        });
        ViewCompat.requestApplyInsets(getWindow().getDecorView());
    }

    /** Respect the system font size, but within a range the layout is designed for. */
    private void applyTextZoom() {
        if (bridge == null || bridge.getWebView() == null) return;
        float scale = getResources().getConfiguration().fontScale;
        int zoom = Math.round(scale * 100f);
        zoom = Math.max(TEXT_ZOOM_MIN, Math.min(TEXT_ZOOM_MAX, zoom));
        WebSettings settings = bridge.getWebView().getSettings();
        settings.setTextZoom(zoom);
    }

    void pushInsets() {
        if (bridge == null) return;
        final WebView web = bridge.getWebView();
        if (web == null) return;
        final int[] i = lastInsets;
        final String js = String.format(
            Locale.US,
            "(function(){var s=document.documentElement&&document.documentElement.style;if(!s)return;" +
                "s.setProperty('--orbit-inset-top','%dpx');s.setProperty('--orbit-inset-right','%dpx');" +
                "s.setProperty('--orbit-inset-bottom','%dpx');s.setProperty('--orbit-inset-left','%dpx');" +
                "window.dispatchEvent(new CustomEvent('orbit:insets',{detail:{top:%d,right:%d,bottom:%d,left:%d}}));})();",
            i[0], i[1], i[2], i[3], i[0], i[1], i[2], i[3]
        );
        web.post(() -> web.evaluateJavascript(js, null));
    }
}
