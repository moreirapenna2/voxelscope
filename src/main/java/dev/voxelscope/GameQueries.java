package dev.voxelscope;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.time.Instant;
import java.util.Map;
import java.util.TreeMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.core.registries.Registries;
import net.minecraft.resources.ResourceKey;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.server.MinecraftServer;
import net.minecraft.server.level.ServerLevel;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.phys.BlockHitResult;
import net.minecraft.world.phys.HitResult;
import net.neoforged.neoforge.capabilities.Capabilities;
import net.neoforged.fml.ModList;

/** Only called on the server thread; all returned objects are detached JSON snapshots. */
public final class GameQueries implements BridgeHttp.Queries {
    private final MinecraftServer server;
    private final String session = java.util.UUID.randomUUID().toString();

    public GameQueries(MinecraftServer server) { this.server = server; }

    @Override public JsonObject execute(String route, Map<String, String> args) throws Exception {
        AtomicBoolean expired = new AtomicBoolean(false);
        var future = server.submit(() -> {
            if (expired.get() || server.isStopped()) throw new IllegalStateException("session_closed");
            JsonObject result = switch (route) {
                case "/v1/status" -> status();
                case "/v1/players" -> players();
                case "/v1/block" -> block(args);
                case "/v1/nearby" -> nearby(args);
                case "/v1/me" -> me(args);
                case "/v1/chunk" -> chunk(args);
                case "/v1/entities" -> entities(args);
                case "/v1/entity" -> entity(args);
                case "/v1/data" -> savedData(args);
                default -> throw new IllegalArgumentException("unknown_query");
            };
            result.addProperty("observed_at", Instant.now().toString());
            result.addProperty("game_tick", server.getTickCount());
            result.addProperty("session", session);
            result.addProperty("world_id", worldId());
            return result;
        });
        try {
            return future.get(3, TimeUnit.SECONDS);
        } catch (ExecutionException failure) {
            if (failure.getCause() instanceof IllegalArgumentException bad) throw bad;
            throw failure;
        } finally {
            expired.set(true);
            future.cancel(false);
        }
    }

    private JsonObject status() {
        JsonObject result = new JsonObject();
        result.addProperty("bridge_version", ModList.get().getModContainerById(VoxelScope.MOD_ID)
                .orElseThrow().getModInfo().getVersion().toString());
        result.addProperty("name", "VoxelScope");
        result.addProperty("api_version", 1);
        result.addProperty("mekanism_capabilities_integration", ModList.get().isLoaded("mekanism"));
        result.addProperty("mekanism_matrix_integration", ModList.get().isLoaded("mekanism"));
        result.addProperty("generic_saved_data", true);
        result.addProperty("generic_entity_inspection", true);
        result.addProperty("minecraft", server.getServerVersion());
        result.addProperty("read_only", true);
        result.addProperty("world_name", server.getWorldData().getLevelName());
        result.addProperty("world_id", worldId());
        result.addProperty("index_available", false);
        result.addProperty("ae2_integration", ModList.get().isLoaded("ae2"));
        result.addProperty("mekanism_integration", ModList.get().isLoaded("mekanism") && ModList.get().isLoaded("mekanismgenerators"));
        JsonArray dimensions = new JsonArray();
        for (ServerLevel level : server.getAllLevels()) dimensions.add(level.dimension().location().toString());
        result.add("dimensions", dimensions);
        return result;
    }

    private String worldId() {
        try {
            String path = server.getWorldPath(net.minecraft.world.level.storage.LevelResource.ROOT)
                    .toAbsolutePath().normalize().toString();
            byte[] digest = java.security.MessageDigest.getInstance("SHA-256")
                    .digest(path.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            return java.util.HexFormat.of().formatHex(digest);
        } catch (java.security.NoSuchAlgorithmException impossible) {
            throw new IllegalStateException(impossible);
        }
    }

    private JsonObject players() {
        JsonObject result = new JsonObject();
        JsonArray players = new JsonArray();
        for (var player : server.getPlayerList().getPlayers()) {
            JsonObject entry = new JsonObject();
            entry.addProperty("name", player.getGameProfile().getName());
            entry.addProperty("uuid", player.getUUID().toString());
            entry.addProperty("dimension", player.level().dimension().location().toString());
            entry.add("position", position(player.blockPosition()));
            // The ray must never walk into an unloaded chunk.
            var start = player.getEyePosition();
            var end = start.add(player.getLookAngle().scale(6));
            boolean rayLoaded = true;
            for (int x = Math.min(BlockPos.containing(start).getX(), BlockPos.containing(end).getX()) >> 4;
                    x <= Math.max(BlockPos.containing(start).getX(), BlockPos.containing(end).getX()) >> 4; x++) {
                for (int z = Math.min(BlockPos.containing(start).getZ(), BlockPos.containing(end).getZ()) >> 4;
                        z <= Math.max(BlockPos.containing(start).getZ(), BlockPos.containing(end).getZ()) >> 4; z++) {
                    if (!player.serverLevel().hasChunk(x, z)) rayLoaded = false;
                }
            }
            if (rayLoaded) {
                BlockHitResult hit = player.level().clip(new ClipContext(start, end,
                        ClipContext.Block.OUTLINE, ClipContext.Fluid.NONE, player));
                if (hit.getType() == HitResult.Type.BLOCK) {
                    JsonObject target = position(hit.getBlockPos());
                    target.addProperty("id", BuiltInRegistries.BLOCK.getKey(
                            player.level().getBlockState(hit.getBlockPos()).getBlock()).toString());
                    entry.add("target", target);
                }
            }
            players.add(entry);
        }
        result.add("players", players);
        return result;
    }

    private ServerLevel level(Map<String, String> args) {
        ResourceLocation id = ResourceLocation.tryParse(args.getOrDefault("dimension", "minecraft:overworld"));
        if (id == null) throw new IllegalArgumentException("invalid_dimension");
        ServerLevel level = server.getLevel(ResourceKey.create(Registries.DIMENSION, id));
        if (level == null) throw new IllegalArgumentException("unknown_dimension");
        return level;
    }

    private BlockPos coordinates(Map<String, String> args) {
        return new BlockPos(integer(args, "x", null, -30000000, 30000000),
                integer(args, "y", null, -2048, 2048),
                integer(args, "z", null, -30000000, 30000000));
    }

    static int integer(Map<String, String> args, String key, Integer fallback, int min, int max) {
        if (!args.containsKey(key)) {
            if (fallback != null) return fallback;
            throw new IllegalArgumentException("missing_" + key);
        }
        try {
            int value = Integer.parseInt(args.get(key));
            if (value < min || value > max) throw new NumberFormatException();
            return value;
        } catch (NumberFormatException invalid) {
            throw new IllegalArgumentException("invalid_" + key);
        }
    }

    private JsonObject block(Map<String, String> args) {
        ServerLevel level = level(args);
        BlockPos pos = coordinates(args);
        if (level.isOutsideBuildHeight(pos)) throw new IllegalArgumentException("outside_build_height");
        JsonObject result = position(pos);
        result.addProperty("dimension", level.dimension().location().toString());
        boolean loaded = level.hasChunkAt(pos);
        result.addProperty("loaded", loaded);
        if (!loaded) return result;
        var state = level.getBlockState(pos);
        result.addProperty("id", BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString());
        JsonObject properties = new JsonObject();
        for (var value : state.getValues().entrySet()) properties.addProperty(value.getKey().getName(), value.getValue().toString());
        result.add("state", properties);
        var entity = level.getBlockEntity(pos);
        if (entity != null) result.addProperty("block_entity_type", BuiltInRegistries.BLOCK_ENTITY_TYPE.getKey(entity.getType()).toString());
        Direction side = null;
        if (args.containsKey("side")) {
            side = Direction.byName(args.get("side"));
            if (side == null) throw new IllegalArgumentException("invalid_side");
        }
        result.addProperty("capability_side", side == null ? "unsided" : side.getName());
        int limit = integer(args, "limit", 20, 1, 50);
        int offset = integer(args, "offset", 0, 0, 1000000);
        CapabilityReader.energy(level.getCapability(Capabilities.EnergyStorage.BLOCK, pos, side), result);
        CapabilityReader.inventory(level.getCapability(Capabilities.ItemHandler.BLOCK, pos, side), result, offset, limit);
        CapabilityReader.fluids(level.getCapability(Capabilities.FluidHandler.BLOCK, pos, side), result, limit);
        if (ModList.get().isLoaded("mekanism")) {
            MekanismCapabilitiesReader.read(level, pos, side, result, limit);
        }
        if (entity != null && ModList.get().isLoaded("mekanism")) {
            MekanismMatrixReader.matrix(entity, result);
        }
        if (entity != null && ModList.get().isLoaded("mekanism") && ModList.get().isLoaded("mekanismgenerators")) {
            MekanismReader.fission(entity, result);
        }
        return result;
    }

    private JsonObject me(Map<String, String> args) {
        if (!ModList.get().isLoaded("ae2")) throw new IllegalArgumentException("ae2_not_installed");
        ServerLevel level = level(args);
        BlockPos pos = coordinates(args);
        if (level.isOutsideBuildHeight(pos)) throw new IllegalArgumentException("outside_build_height");
        if (!level.hasChunkAt(pos)) throw new IllegalArgumentException("chunk_unloaded");
        JsonObject result = Ae2Reader.read(level.getBlockEntity(pos), args);
        result.addProperty("dimension", level.dimension().location().toString());
        result.add("connection_position", position(pos));
        return result;
    }

    private net.minecraft.world.entity.Entity findEntity(ServerLevel level, Map<String, String> args) {
        java.util.UUID id;
        try { id = java.util.UUID.fromString(args.getOrDefault("uuid", "")); }
        catch (IllegalArgumentException bad) { throw new IllegalArgumentException("invalid_entity_uuid"); }
        return level.getEntity(id);
    }

    private JsonObject entity(Map<String, String> args) {
        ServerLevel level = level(args);
        var entity = findEntity(level, args);
        JsonObject result = new JsonObject();
        result.addProperty("dimension", level.dimension().location().toString());
        result.addProperty("loaded", entity != null);
        result.addProperty("uuid", args.get("uuid"));
        if (entity == null) return result;
        result.addProperty("id", BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString());
        result.addProperty("x", entity.getX());
        result.addProperty("y", entity.getY());
        result.addProperty("z", entity.getZ());
        result.addProperty("alive", entity.isAlive());
        if (entity instanceof net.minecraft.world.entity.LivingEntity living) {
            result.addProperty("health", living.getHealth());
            result.addProperty("max_health", living.getMaxHealth());
            result.addProperty("armor", living.getArmorValue());
        }
        if (entity instanceof net.minecraft.world.entity.item.ItemEntity item) {
            JsonObject stack = new JsonObject();
            stack.addProperty("id", BuiltInRegistries.ITEM.getKey(item.getItem().getItem()).toString());
            stack.addProperty("count", item.getItem().getCount());
            result.add("item", stack);
        }
        Direction side = args.containsKey("side") ? Direction.byName(args.get("side")) : null;
        if (args.containsKey("side") && side == null) throw new IllegalArgumentException("invalid_side");
        int limit = integer(args, "limit", 20, 1, 50);
        int offset = integer(args, "offset", 0, 0, 1000000);
        CapabilityReader.energy(entity.getCapability(Capabilities.EnergyStorage.ENTITY, side), result);
        CapabilityReader.inventory(entity.getCapability(Capabilities.ItemHandler.ENTITY), result, offset, limit);
        CapabilityReader.fluids(entity.getCapability(Capabilities.FluidHandler.ENTITY, side), result, limit);
        return result;
    }

    private JsonObject savedData(Map<String, String> args) {
        ServerLevel level = level(args);
        int offset = integer(args, "offset", 0, 0, 1000000);
        int limit = integer(args, "limit", 16, 1, 32);
        String path = args.getOrDefault("path", "");
        // Validate request size before asking another mod to serialize a snapshot.
        if (path.length() > 512 || (!path.isEmpty() && !path.startsWith("/"))) {
            throw new IllegalArgumentException("invalid_data_path");
        }
        String target = args.getOrDefault("target", "block");
        net.minecraft.nbt.CompoundTag snapshot;
        JsonObject identity = new JsonObject();
        identity.addProperty("dimension", level.dimension().location().toString());
        if (target.equals("block")) {
            BlockPos pos = coordinates(args);
            if (level.isOutsideBuildHeight(pos)) throw new IllegalArgumentException("outside_build_height");
            identity.add("position", position(pos));
            identity.addProperty("loaded", level.hasChunkAt(pos));
            if (!level.hasChunkAt(pos)) return identity;
            identity.addProperty("id", BuiltInRegistries.BLOCK.getKey(level.getBlockState(pos).getBlock()).toString());
            var block = level.getBlockEntity(pos);
            if (block == null) throw new IllegalArgumentException("block_has_no_saved_data");
            snapshot = block.saveWithoutMetadata(level.registryAccess());
        } else if (target.equals("entity")) {
            var entity = findEntity(level, args);
            identity.addProperty("loaded", entity != null);
            identity.addProperty("uuid", args.get("uuid"));
            if (entity == null) return identity;
            identity.addProperty("id", BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString());
            snapshot = entity.saveWithoutId(new net.minecraft.nbt.CompoundTag());
        } else {
            throw new IllegalArgumentException("invalid_data_target");
        }
        JsonObject result = NbtView.inspect(snapshot, path, offset, limit);
        for (var entry : identity.entrySet()) result.add(entry.getKey(), entry.getValue());
        return result;
    }

    private JsonObject nearby(Map<String, String> args) {
        ServerLevel level = level(args);
        BlockPos center = coordinates(args);
        int radius = integer(args, "radius", 8, 1, 12);
        int limit = integer(args, "limit", 20, 1, 50);
        String filter = args.getOrDefault("filter", "");
        if (filter.length() > 128) throw new IllegalArgumentException("filter_too_long");
        Map<String, Integer> counts = new TreeMap<>();
        JsonArray matches = new JsonArray();
        int scanned = 0, skipped = 0, totalMatches = 0;
        // At most 15,625 positions, and a 15 ms cooperative scan budget.
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(15);
        boolean partial = false;
        for (BlockPos pos : BlockPos.betweenClosed(center.offset(-radius, -radius, -radius), center.offset(radius, radius, radius))) {
            if (System.nanoTime() > deadline) { partial = true; break; }
            if (level.isOutsideBuildHeight(pos) || !level.hasChunkAt(pos)) { skipped++; continue; }
            scanned++;
            var state = level.getBlockState(pos);
            if (!state.hasBlockEntity()) continue;
            String id = BuiltInRegistries.BLOCK.getKey(state.getBlock()).toString();
            counts.merge(id, 1, Integer::sum);
            if (!id.contains(filter)) continue;
            totalMatches++;
            if (matches.size() < limit) {
                JsonObject entry = position(pos);
                entry.addProperty("id", id);
                matches.add(entry);
            }
        }
        JsonObject result = new JsonObject();
        result.addProperty("dimension", level.dimension().location().toString());
        result.addProperty("scope", "blocks_with_block_entities");
        result.addProperty("radius", radius);
        result.addProperty("scanned_positions", scanned);
        result.addProperty("skipped_positions", skipped);
        result.addProperty("partial_scan", partial);
        JsonObject countData = new JsonObject();
        counts.forEach(countData::addProperty);
        result.add("counts", countData);
        result.add("matches", matches);
        result.addProperty("matching_blocks_observed", totalMatches);
        result.addProperty("matches_truncated", totalMatches > limit);
        return result;
    }

    private JsonObject chunk(Map<String, String> args) {
        ServerLevel level = level(args);
        int x = integer(args, "chunk_x", null, -1875000, 1875000);
        int z = integer(args, "chunk_z", null, -1875000, 1875000);
        int offset = integer(args, "offset", 0, 0, 1000000);
        int limit = integer(args, "limit", 50, 1, 50);
        // getChunkNow returns only an existing full chunk and never loads or generates one.
        var chunk = level.getChunkSource().getChunkNow(x, z);
        JsonObject result = new JsonObject();
        result.addProperty("dimension", level.dimension().location().toString());
        result.addProperty("chunk_x", x);
        result.addProperty("chunk_z", z);
        result.addProperty("loaded", chunk != null);
        if (chunk == null) return result;
        JsonArray machines = new JsonArray();
        int examined = 0, included = 0;
        boolean partial = false;
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(15);
        for (var entry : chunk.getBlockEntities().entrySet()) {
            if (System.nanoTime() > deadline) { partial = true; break; }
            if (examined++ < offset) continue;
            if (included >= limit) break;
            BlockPos pos = entry.getKey();
            JsonObject machine = position(pos);
            machine.addProperty("id", BuiltInRegistries.BLOCK.getKey(level.getBlockState(pos).getBlock()).toString());
            machines.add(machine);
            included++;
        }
        int next = offset + included;
        result.add("machines", machines);
        result.addProperty("block_entities", chunk.getBlockEntities().size());
        result.addProperty("offset", offset);
        result.addProperty("truncated", partial || next < chunk.getBlockEntities().size());
        if (partial || next < chunk.getBlockEntities().size()) result.addProperty("next_offset", next);
        result.addProperty("partial_scan", partial);
        return result;
    }

    private JsonObject entities(Map<String, String> args) {
        ServerLevel level = level(args);
        BlockPos center = coordinates(args);
        int radius = integer(args, "radius", 16, 1, 64);
        int limit = integer(args, "limit", 20, 1, 50);
        String filter = args.getOrDefault("filter", "");
        if (filter.length() > 128) throw new IllegalArgumentException("filter_too_long");
        JsonArray matches = new JsonArray();
        Map<String, Integer> counts = new TreeMap<>();
        int examined = 0, matching = 0;
        boolean partial = false;
        long deadline = System.nanoTime() + TimeUnit.MILLISECONDS.toNanos(15);
        for (var entity : level.getAllEntities()) {
            if (examined++ >= 10000 || System.nanoTime() > deadline) { partial = true; break; }
            if (entity.distanceToSqr(center.getX() + .5, center.getY() + .5, center.getZ() + .5) > (double) radius * radius) continue;
            String id = BuiltInRegistries.ENTITY_TYPE.getKey(entity.getType()).toString();
            counts.merge(id, 1, Integer::sum);
            if (!id.contains(filter)) continue;
            matching++;
            if (matches.size() >= limit) continue;
            JsonObject row = new JsonObject();
            row.addProperty("uuid", entity.getUUID().toString());
            row.addProperty("id", id);
            row.addProperty("x", entity.getX());
            row.addProperty("y", entity.getY());
            row.addProperty("z", entity.getZ());
            matches.add(row);
        }
        JsonObject result = new JsonObject();
        JsonObject countData = new JsonObject();
        counts.forEach(countData::addProperty);
        result.add("counts", countData);
        result.add("matches", matches);
        result.addProperty("matching_entities_observed", matching);
        result.addProperty("partial_scan", partial);
        result.addProperty("truncated", partial || matching > limit);
        result.addProperty("dimension", level.dimension().location().toString());
        return result;
    }

    private static JsonObject position(BlockPos pos) {
        JsonObject result = new JsonObject();
        result.addProperty("x", pos.getX());
        result.addProperty("y", pos.getY());
        result.addProperty("z", pos.getZ());
        return result;
    }
}
