package dev.voxelscope;

import java.util.Map;
import net.minecraft.core.BlockPos;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.world.item.ItemStack;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.Blocks;
import net.minecraft.world.level.block.entity.ChestBlockEntity;
import net.neoforged.neoforge.gametest.GameTestHolder;
import net.neoforged.neoforge.gametest.PrefixGameTestTemplate;
import net.neoforged.fml.ModList;

/** Test-only fixtures; excluded from the distributable mod jar. */
@GameTestHolder("voxelscope")
@PrefixGameTestTemplate(false)
public class BridgeGameTests {
    @GameTest(template = "empty", timeoutTicks = 100)
    public static void inspectChestWithoutChangingContents(GameTestHelper helper) throws Exception {
        BlockPos relative = new BlockPos(1, 1, 1);
        helper.setBlock(relative, Blocks.CHEST);
        ChestBlockEntity chest = (ChestBlockEntity) helper.getBlockEntity(relative);
        chest.setItem(0, new ItemStack(Items.DIAMOND, 7));
        var queries = new GameQueries(helper.getLevel().getServer());
        BlockPos pos = helper.absolutePos(relative);
        Map<String, String> args = Map.of("x", "" + pos.getX(), "y", "" + pos.getY(), "z", "" + pos.getZ());
        var result = queries.execute("/v1/block", args);
        helper.assertTrue(result.get("id").getAsString().equals("minecraft:chest"), "Block identity");
        var item = result.getAsJsonObject("inventory").getAsJsonArray("items").get(0).getAsJsonObject();
        helper.assertTrue(item.get("count").getAsInt() == 7, "Count observed correctly");
        helper.assertTrue(chest.getItem(0).getCount() == 7, "Read must leave contents unchanged");
        var schema = queries.execute("/v1/data", args);
        helper.assertTrue(schema.has("children") && !schema.has("value"), "Saved data root exposes schema only");
        var selected = new java.util.HashMap<>(args);
        selected.put("path", "/Items/0/id");
        var scalar = queries.execute("/v1/data", selected);
        helper.assertTrue(scalar.get("value").getAsString().equals("minecraft:diamond"), "Selected saved scalar");
        helper.assertTrue(chest.getItem(0).getCount() == 7, "Saved snapshot must leave inventory intact");
        var absent = queries.execute("/v1/block", Map.of("x", "29000000", "y", "64", "z", "29000000"));
        helper.assertTrue(!absent.get("loaded").getAsBoolean(), "Unloaded position reported");
        helper.assertTrue(!helper.getLevel().hasChunkAt(new BlockPos(29000000, 64, 29000000)), "Query must not load chunk");
        var chunk = queries.execute("/v1/chunk", Map.of("chunk_x", "" + (pos.getX() >> 4), "chunk_z", "" + (pos.getZ() >> 4)));
        helper.assertTrue(chunk.get("loaded").getAsBoolean() && !chunk.getAsJsonArray("machines").isEmpty(), "Loaded machine listing");
        // Persist a test-only sentinel, later reopened with our mod completely absent.
        BlockPos sentinel = new BlockPos(32, 80, 32);
        helper.getLevel().getChunkAt(sentinel);
        helper.getLevel().setBlockAndUpdate(sentinel, Blocks.CHEST.defaultBlockState());
        ((ChestBlockEntity) helper.getLevel().getBlockEntity(sentinel)).setItem(0, new ItemStack(Items.DIAMOND, 7));
        helper.succeed();
    }

    // Headless GameTestServer runs ticks much faster than real time; allow HTTP/JDK startup wall time.
    @GameTest(template = "empty", timeoutTicks = 10000)
    public static void liveHttpStatus(GameTestHelper helper) {
        var response = java.util.concurrent.CompletableFuture.supplyAsync(() -> {
            try {
                var directory = net.neoforged.fml.loading.FMLPaths.GAMEDIR.get().resolve("voxelscope");
                var connection = com.google.gson.JsonParser.parseString(java.nio.file.Files.readString(
                        directory.resolve("connection.json"))).getAsJsonObject();
                String token = java.nio.file.Files.readString(directory.resolve("token.txt")).trim();
                try (var client = java.net.http.HttpClient.newBuilder()
                        .proxy(new java.net.ProxySelector() {
                            public java.util.List<java.net.Proxy> select(java.net.URI uri) {
                                return java.util.List.of(java.net.Proxy.NO_PROXY);
                            }
                            public void connectFailed(java.net.URI uri, java.net.SocketAddress address, java.io.IOException error) {}
                        }).build()) {
                    var request = java.net.http.HttpRequest.newBuilder(java.net.URI.create(
                            connection.get("url").getAsString() + "/v1/status"))
                            .header("Authorization", "Bearer " + token).timeout(java.time.Duration.ofSeconds(5)).build();
                    return client.send(request, java.net.http.HttpResponse.BodyHandlers.ofString());
                }
            } catch (Exception error) { throw new RuntimeException(error); }
        });
        helper.succeedWhen(() -> {
            helper.assertTrue(response.isDone(), "Waiting for HTTP response");
            var result = response.join();
            helper.assertTrue(result.statusCode() == 200, "Authenticated HTTP request succeeds");
            var body = com.google.gson.JsonParser.parseString(result.body()).getAsJsonObject();
            helper.assertTrue(body.get("read_only").getAsBoolean(), "Read-only status");
            helper.assertTrue(body.has("world_id"), "External index can distinguish worlds");
        });
    }

    @GameTest(template = "empty", timeoutTicks = 100)
    public static void optionalIntegrationReads(GameTestHelper helper) {
        if (!ModList.get().isLoaded("ae2")) { helper.succeed(); return; }
        var registry = net.minecraft.core.registries.BuiltInRegistries.BLOCK;
        BlockPos drivePos = new BlockPos(1, 1, 1);
        helper.setBlock(drivePos, registry.get(net.minecraft.resources.ResourceLocation.parse("ae2:drive")));
        helper.runAfterDelay(10, () -> {
            try {
                var queries = new GameQueries(helper.getLevel().getServer());
                var me = queries.execute("/v1/me", at(helper.absolutePos(drivePos)));
                helper.assertTrue(me.get("network_nodes").getAsInt() >= 1, "AE2 grid read");
                helper.assertTrue(me.getAsJsonArray("items").isEmpty(), "Empty drive inventory");
                helper.succeed();
            } catch (Exception error) { throw new RuntimeException(error); }
        });
    }

    @GameTest(template = "empty", timeoutTicks = 100)
    public static void matrixWithoutGenerators(GameTestHelper helper) {
        if (!ModList.get().isLoaded("mekanism")) { helper.succeed(); return; }
        BlockPos position = new BlockPos(1, 1, 1);
        helper.setBlock(position, net.minecraft.core.registries.BuiltInRegistries.BLOCK.get(
                net.minecraft.resources.ResourceLocation.parse("mekanism:induction_casing")));
        helper.runAfterDelay(5, () -> {
            try {
                var snapshot = new GameQueries(helper.getLevel().getServer()).execute("/v1/block", at(helper.absolutePos(position)));
                helper.assertTrue(snapshot.has("mekanism_matrix"), "Matrix adapter works with Mekanism independently of Generators");
                helper.assertTrue(!snapshot.getAsJsonObject("mekanism_matrix").get("formed").getAsBoolean(), "Unformed Matrix reported");
                helper.succeed();
            } catch (Exception error) { throw new RuntimeException(error); }
        });
    }

    private static Map<String, String> at(BlockPos pos) {
        return Map.of("x", "" + pos.getX(), "y", "" + pos.getY(), "z", "" + pos.getZ());
    }

    @GameTest(template = "empty", timeoutTicks = 1000)
    public static void formedReactorReadings(GameTestHelper helper) {
        if (!ModList.get().isLoaded("mekanismgenerators")) { helper.succeed(); return; }
        var registry = net.minecraft.core.registries.BuiltInRegistries.BLOCK;
        var casing = registry.get(net.minecraft.resources.ResourceLocation.parse("mekanismgenerators:fission_reactor_casing"));
        for (BlockPos pos : BlockPos.betweenClosed(0, 0, 0, 4, 4, 4)) {
            if (pos.getX() == 0 || pos.getX() == 4 || pos.getY() == 0 || pos.getY() == 4 || pos.getZ() == 0 || pos.getZ() == 4) {
                helper.setBlock(pos, casing);
            }
        }
        helper.setBlock(new BlockPos(2, 1, 2), registry.get(net.minecraft.resources.ResourceLocation.parse("mekanismgenerators:fission_fuel_assembly")));
        helper.setBlock(new BlockPos(2, 2, 2), registry.get(net.minecraft.resources.ResourceLocation.parse("mekanismgenerators:fission_fuel_assembly")));
        helper.setBlock(new BlockPos(2, 3, 2), registry.get(net.minecraft.resources.ResourceLocation.parse("mekanismgenerators:control_rod_assembly")));
        helper.succeedWhen(() -> {
            var tile = (mekanism.generators.common.tile.fission.TileEntityFissionReactorCasing) helper.getBlockEntity(new BlockPos(0, 1, 1));
            var reactor = tile.getMultiblock();
            helper.assertTrue(reactor.isFormed(), "Waiting for reactor formation");
            // Test-only fixture setup, never present in the distributed mod.
            reactor.fuelTank.setStack(new mekanism.api.chemical.ChemicalStack(
                    mekanism.common.registries.MekanismChemicals.FISSILE_FUEL, 5000));
            JsonCheck.fission(helper, tile, reactor);
        });
    }

    private static class JsonCheck {
        static void fission(GameTestHelper helper,
                mekanism.generators.common.tile.fission.TileEntityFissionReactorCasing tile,
                mekanism.generators.common.content.fission.FissionReactorMultiblockData reactor) {
            var result = new com.google.gson.JsonObject();
            MekanismReader.fission(tile, result);
            var data = result.getAsJsonObject("mekanism_fission");
            helper.assertTrue(data.get("formed").getAsBoolean(), "Formed reactor snapshot");
            helper.assertTrue(data.getAsJsonObject("fuel").get("amount_mb").getAsLong() == 5000, "Exact fuel amount");
            helper.assertTrue(data.get("max_burn_rate_mb_per_tick").getAsLong() == reactor.getMaxBurnRate(), "Burn capacity");
            helper.assertTrue(reactor.fuelTank.getStored() == 5000 && !reactor.isActive(), "Inspection leaves fuel and activity unchanged");
        }
    }

    @GameTest(template = "empty", timeoutTicks = 100)
    public static void genericEntityAndSavedDataBounds(GameTestHelper helper) throws Exception {
        var sheep = helper.spawn(net.minecraft.world.entity.EntityType.SHEEP, new BlockPos(1, 1, 1));
        var queries = new GameQueries(helper.getLevel().getServer());
        var args = Map.of("uuid", sheep.getUUID().toString());
        var entity = queries.execute("/v1/entity", args);
        helper.assertTrue(entity.get("health").getAsFloat() == sheep.getHealth(), "Generic living entity health");
        var saved = queries.execute("/v1/data", Map.of("target", "entity", "uuid", sheep.getUUID().toString(), "path", "/Health"));
        helper.assertTrue(saved.get("value").getAsFloat() == sheep.getHealth(), "Selected entity saved field");
        var root = new net.minecraft.nbt.CompoundTag();
        var nested = new net.minecraft.nbt.CompoundTag();
        nested.putLong("~quantity", 9007199254740993L);
        root.put("a/b", nested);
        root.putByteArray("big_array", new byte[10000]);
        root.putString("long_string", "x".repeat(2000));
        var number = NbtView.inspect(root, "/a~1b/~0quantity", 0, 16);
        helper.assertTrue(number.get("value").getAsLong() == 9007199254740993L, "Large integer stays exact");
        var array = NbtView.inspect(root, "/big_array", 0, 16);
        helper.assertTrue(array.getAsJsonArray("children").size() == 16 && !array.has("value"), "Arrays cannot be dumped");
        var text = NbtView.inspect(root, "/long_string", 0, 16);
        helper.assertTrue(text.get("value").getAsString().length() == 256 && text.get("value_truncated").getAsBoolean(), "String cap");
        try {
            NbtView.inspect(root, "/bad~2escape", 0, 16);
            helper.fail("Malformed pointer must be rejected");
        } catch (IllegalArgumentException expected) { }
        helper.succeed();
    }

    @GameTest(template = "empty", timeoutTicks = 100)
    public static void genericChemicalCapability(GameTestHelper helper) {
        if (!ModList.get().isLoaded("mekanism")) { helper.succeed(); return; }
        helper.setBlock(new BlockPos(1, 1, 1), net.minecraft.core.registries.BuiltInRegistries.BLOCK.get(
                net.minecraft.resources.ResourceLocation.parse("mekanism:basic_chemical_tank")));
        helper.runAfterDelay(5, () -> {
            try {
                var result = new GameQueries(helper.getLevel().getServer()).execute("/v1/block", at(helper.absolutePos(new BlockPos(1, 1, 1))));
                helper.assertTrue(!result.getAsJsonArray("chemical_tanks").isEmpty(), "Generic chemical adapter exposes tank");
                helper.assertTrue(result.getAsJsonArray("chemical_tanks").get(0).getAsJsonObject().get("amount_mb").getAsLong() == 0, "Empty tank remains empty");
                helper.succeed();
            } catch (Exception error) { throw new RuntimeException(error); }
        });
    }
}
