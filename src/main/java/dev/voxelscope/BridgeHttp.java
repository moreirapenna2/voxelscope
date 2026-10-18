package dev.voxelscope;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.Semaphore;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/** Transport knows nothing about Minecraft; only bounded, authenticated GET queries are supported. */
public final class BridgeHttp implements AutoCloseable {
    public interface Queries {
        JsonObject execute(String route, Map<String, String> args) throws Exception;
    }

    private static final Gson JSON = new Gson();
    private static final Set<String> ROUTES = Set.of("/v1/status", "/v1/players", "/v1/block", "/v1/nearby", "/v1/me", "/v1/chunk", "/v1/entities", "/v1/entity", "/v1/data");
    private final HttpServer http;
    private final ThreadPoolExecutor workers;
    private final Semaphore inFlight = new Semaphore(2);
    private final Queries queries;
    private final String token;
    private final Path connectionFile;

    public BridgeHttp(Path directory, Queries queries) throws IOException {
        this.queries = queries;
        Files.createDirectories(directory);
        Path tokenFile = directory.resolve("token.txt");
        if (Files.exists(tokenFile)) {
            token = Files.readString(tokenFile).trim();
            if (token.length() < 32) throw new IOException("Invalid bridge token file");
        } else {
            byte[] random = new byte[32];
            new SecureRandom().nextBytes(random);
            token = Base64.getUrlEncoder().withoutPadding().encodeToString(random);
            Files.writeString(tokenFile, token, StandardCharsets.UTF_8);
        }
        // Ephemeral port avoids conflicts between development and pack instances.
        http = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 8);
        workers = new ThreadPoolExecutor(2, 2, 0, TimeUnit.MILLISECONDS, new ArrayBlockingQueue<>(8), runnable -> {
            Thread thread = new Thread(runnable, "voxelscope-http");
            thread.setDaemon(true);
            return thread;
        });
        // HttpServer dispatches before our semaphore, so bound its worker queue too.
        workers.setRejectedExecutionHandler(new ThreadPoolExecutor.AbortPolicy());
        http.setExecutor(workers);
        http.createContext("/", this::handle);
        connectionFile = directory.resolve("connection.json");
    }

    public void start() throws IOException {
        JsonObject connection = new JsonObject();
        connection.addProperty("url", "http://127.0.0.1:" + port());
        connection.addProperty("token_file", "token.txt");
        connection.addProperty("api_version", 1);
        Files.writeString(connectionFile, JSON.toJson(connection));
        http.start();
    }

    public int port() { return http.getAddress().getPort(); }

    private void handle(HttpExchange exchange) throws IOException {
        boolean acquired = false;
        try {
            // No CORS and no browser-origin requests, including requests with leaked credentials.
            if (exchange.getRequestHeaders().getFirst("Origin") != null) {
                send(exchange, 403, error("browser_origin_denied"));
                return;
            }
            String auth = exchange.getRequestHeaders().getFirst("Authorization");
            if (auth == null || !MessageDigest.isEqual(
                    ("Bearer " + token).getBytes(StandardCharsets.UTF_8), auth.getBytes(StandardCharsets.UTF_8))) {
                send(exchange, 401, error("unauthorized"));
                return;
            }
            if (!exchange.getRequestMethod().equals("GET")) {
                exchange.getResponseHeaders().set("Allow", "GET");
                send(exchange, 405, error("read_only_get_required"));
                return;
            }
            String route = exchange.getRequestURI().getPath();
            if (!ROUTES.contains(route)) {
                send(exchange, 404, error("unknown_query"));
                return;
            }
            acquired = inFlight.tryAcquire();
            if (!acquired) { send(exchange, 429, error("busy")); return; }
            Map<String, String> args = parseQuery(exchange.getRequestURI().getRawQuery());
            JsonObject response = queries.execute(route, args);
            send(exchange, 200, response);
        } catch (IllegalArgumentException error) {
            send(exchange, 400, error(error.getMessage()));
        } catch (java.util.concurrent.TimeoutException error) {
            send(exchange, 503, error("game_thread_unavailable_or_paused"));
        } catch (Exception error) {
            // Do not expose arbitrary exception messages or paths to clients.
            send(exchange, 500, error("inspection_failed"));
        } finally {
            if (acquired) inFlight.release();
            exchange.close();
        }
    }

    static Map<String, String> parseQuery(String raw) {
        Map<String, String> values = new HashMap<>();
        if (raw == null || raw.isEmpty()) return values;
        if (raw.length() > 2048) throw new IllegalArgumentException("query_too_long");
        for (String pair : raw.split("&")) {
            String[] parts = pair.split("=", 2);
            if (parts.length != 2) throw new IllegalArgumentException("invalid_query");
            String key = URLDecoder.decode(parts[0], StandardCharsets.UTF_8);
            String value = URLDecoder.decode(parts[1], StandardCharsets.UTF_8);
            if (values.putIfAbsent(key, value) != null) throw new IllegalArgumentException("duplicate_parameter");
        }
        return values;
    }

    private static JsonObject error(String message) {
        JsonObject object = new JsonObject();
        object.addProperty("error", message);
        return object;
    }

    private static void send(HttpExchange exchange, int status, JsonObject body) throws IOException {
        byte[] bytes = JSON.toJson(body).getBytes(StandardCharsets.UTF_8);
        if (bytes.length > 32768) {
            status = 413;
            bytes = "{\"error\":\"response_limit_exceeded\"}".getBytes(StandardCharsets.UTF_8);
        }
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.getResponseHeaders().set("Cache-Control", "no-store");
        exchange.getResponseHeaders().set("X-Content-Type-Options", "nosniff");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
    }

    @Override public void close() {
        http.stop(0);
        workers.shutdownNow();
        try {
            if (workers.awaitTermination(2, TimeUnit.SECONDS)) { /* worker cleanup completed */ }
            Files.deleteIfExists(connectionFile);
        } catch (IOException ignored) {
            // A stale connection file is harmless: clients report connection failure.
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }
}
