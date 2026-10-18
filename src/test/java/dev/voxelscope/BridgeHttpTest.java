package dev.voxelscope;

import static org.junit.jupiter.api.Assertions.*;
import com.google.gson.JsonObject;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class BridgeHttpTest {
    @TempDir Path directory;

    @Test void authenticationReadOnlyRoutesAndCleanup() throws Exception {
        AtomicInteger reads = new AtomicInteger();
        try (BridgeHttp bridge = new BridgeHttp(directory, (route, args) -> {
            reads.incrementAndGet();
            JsonObject result = new JsonObject();
            result.addProperty("read_only", true);
            return result;
        })) {
            bridge.start();
            String url = "http://127.0.0.1:" + bridge.port();
            String token = Files.readString(directory.resolve("token.txt")).trim();
            try (HttpClient client = HttpClient.newHttpClient()) {
                assertEquals(401, request(client, url, "/v1/status", null, "GET", null).statusCode());
                assertEquals(401, request(client, url, "/v1/status", "wrong", "GET", null).statusCode());
                assertEquals(403, request(client, url, "/v1/status", token, "GET", "http://example.com").statusCode());
                assertEquals(405, request(client, url, "/v1/status", token, "POST", null).statusCode());
                assertEquals(404, request(client, url, "/v1/command", token, "GET", null).statusCode());
                assertEquals(400, request(client, url, "/v1/block?x=1&x=2", token, "GET", null).statusCode());
                var response = request(client, url, "/v1/status", token, "GET", null);
                assertEquals(200, response.statusCode());
                assertEquals("{\"read_only\":true}", response.body());
                assertEquals(1, reads.get());
            }
            assertTrue(Files.exists(directory.resolve("connection.json")));
        }
        assertFalse(Files.exists(directory.resolve("connection.json")));
        assertTrue(Files.exists(directory.resolve("token.txt")));
    }

    @Test void oversizedPayloadDoesNotEscapeResponseBudget() throws Exception {
        try (BridgeHttp bridge = new BridgeHttp(directory, (route, args) -> {
            JsonObject body = new JsonObject();
            body.addProperty("payload", "x".repeat(40000));
            return body;
        })) {
            bridge.start();
            String token = Files.readString(directory.resolve("token.txt")).trim();
            try (HttpClient client = HttpClient.newHttpClient()) {
                var response = request(client, "http://127.0.0.1:" + bridge.port(), "/v1/status", token, "GET", null);
                assertEquals(413, response.statusCode());
                assertTrue(response.body().length() < 100);
            }
        }
    }

    private HttpResponse<String> request(HttpClient client, String url, String path,
            String token, String method, String origin) throws Exception {
        var builder = HttpRequest.newBuilder(URI.create(url + path)).method(method, HttpRequest.BodyPublishers.noBody());
        if (token != null) builder.header("Authorization", "Bearer " + token);
        if (origin != null) builder.header("Origin", origin);
        return client.send(builder.build(), HttpResponse.BodyHandlers.ofString());
    }
}
