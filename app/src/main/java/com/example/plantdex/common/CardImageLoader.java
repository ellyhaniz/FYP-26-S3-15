package com.example.plantdex.common;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.os.Handler;
import android.os.Looper;
import android.util.Log;
import android.util.LruCache;
import android.widget.ImageView;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Loads collectible card pictures from the portal (/api/collectibles/<id>/image) into
 * ImageViews, shrunk to thumbnail size and kept in a small memory cache so scrolling the
 * inventory doesn't download the same picture twice. If a picture can't be loaded, the
 * view keeps whatever icon it already shows.
 */
public final class CardImageLoader {

    private static final String TAG = "CardImageLoader";
    private static final int MAX_SIDE_PX = 480;          // plenty for a tile or thumbnail

    private static final ExecutorService POOL = Executors.newFixedThreadPool(3);
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    private static final LruCache<String, Bitmap> CACHE =
            new LruCache<String, Bitmap>((int) (Runtime.getRuntime().maxMemory() / 16)) {
                @Override
                protected int sizeOf(String key, Bitmap value) {
                    return value.getByteCount();
                }
            };

    private CardImageLoader() {}

    /** Shows the picture at {@code url} in {@code view}; {@code onShown} runs (on the UI
     *  thread) once it is displayed, e.g. to enlarge the frame around it. */
    public static void load(ImageView view, String url, Runnable onShown) {
        if (url == null || !(url.startsWith("http://") || url.startsWith("https://"))) return;
        view.setTag(url);

        Bitmap cached = CACHE.get(url);
        if (cached != null) {
            show(view, cached, onShown);
            return;
        }
        POOL.execute(() -> {
            Bitmap bitmap = download(url);
            if (bitmap == null) return;
            CACHE.put(url, bitmap);
            MAIN.post(() -> {
                if (url.equals(view.getTag())) show(view, bitmap, onShown);   // view not reused since
            });
        });
    }

    private static void show(ImageView view, Bitmap bitmap, Runnable onShown) {
        view.setImageTintList(null);
        view.setPadding(0, 0, 0, 0);
        view.setScaleType(ImageView.ScaleType.CENTER_CROP);
        view.setImageBitmap(bitmap);
        if (onShown != null) onShown.run();
    }

    private static Bitmap download(String url) {
        HttpURLConnection connection = null;
        try {
            connection = (HttpURLConnection) new URL(url).openConnection();
            connection.setConnectTimeout(10000);
            connection.setReadTimeout(10000);
            byte[] bytes;
            try (InputStream input = connection.getInputStream()) {
                bytes = readAll(input);
            }
            // Decode at a reduced size: card pictures can be several megapixels.
            BitmapFactory.Options bounds = new BitmapFactory.Options();
            bounds.inJustDecodeBounds = true;
            BitmapFactory.decodeByteArray(bytes, 0, bytes.length, bounds);
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inSampleSize = 1;
            while (Math.max(bounds.outWidth, bounds.outHeight) / (options.inSampleSize * 2) >= MAX_SIDE_PX) {
                options.inSampleSize *= 2;
            }
            return BitmapFactory.decodeByteArray(bytes, 0, bytes.length, options);
        } catch (IOException e) {
            Log.w(TAG, "Could not load card picture " + url, e);
            return null;
        } finally {
            if (connection != null) connection.disconnect();
        }
    }

    private static byte[] readAll(InputStream input) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[16384];
        int n;
        while ((n = input.read(buffer)) != -1) out.write(buffer, 0, n);
        return out.toByteArray();
    }
}
