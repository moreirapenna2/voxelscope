package dev.voxelscope;

import appeng.api.networking.IInWorldGridNodeHost;
import appeng.api.networking.IGridNode;
import appeng.api.stacks.AEItemKey;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import java.util.Map;
import net.minecraft.core.Direction;
import net.minecraft.world.level.block.entity.BlockEntity;

/** Loaded only when AE2 is present. Never extracts, injects, or requests crafts. */
final class Ae2Reader {
    static JsonObject read(BlockEntity block, Map<String, String> args) {
        if (!(block instanceof IInWorldGridNodeHost host)) throw new IllegalArgumentException("not_an_ae2_node_host");
        IGridNode node = null;
        for (Direction side : Direction.values()) {
            node = host.getGridNode(side);
            if (node != null) break;
        }
        if (node == null) throw new IllegalArgumentException("ae2_node_unavailable");
        var grid = node.getGrid();
        JsonObject result = new JsonObject();
        result.addProperty("online", node.isOnline());
        result.addProperty("powered", node.isPowered());
        result.addProperty("meets_channel_requirements", node.meetsChannelRequirements());
        result.addProperty("node_used_channels", node.getUsedChannels());
        result.addProperty("node_max_channels", node.getMaxChannels());
        result.addProperty("network_nodes", grid.size());
        var power = grid.getEnergyService();
        JsonObject energy = new JsonObject();
        energy.addProperty("stored_ae", power.getStoredPower());
        energy.addProperty("capacity_ae", power.getMaxStoredPower());
        energy.addProperty("average_usage_ae_per_tick", power.getAvgPowerUsage());
        energy.addProperty("average_injection_ae_per_tick", power.getAvgPowerInjection());
        result.add("energy", energy);
        int offset = GameQueries.integer(args, "offset", 0, 0, 1000000);
        int limit = GameQueries.integer(args, "limit", 20, 1, 50);
        String filter = args.getOrDefault("filter", "").toLowerCase(java.util.Locale.ROOT);
        if (filter.length() > 128) throw new IllegalArgumentException("filter_too_long");
        JsonArray items = new JsonArray();
        int examined = 0, matching = 0;
        boolean partial = false;
        long deadline = System.nanoTime() + java.util.concurrent.TimeUnit.MILLISECONDS.toNanos(15);
        var inventory = grid.getStorageService().getCachedInventory();
        for (var entry : inventory) {
            if (examined++ >= 100000 || System.nanoTime() > deadline) { partial = true; break; }
            if (!(entry.getKey() instanceof AEItemKey item)) continue;
            String id = item.getId().toString();
            if (!id.contains(filter) || entry.getLongValue() <= 0) continue;
            if (matching++ < offset || items.size() >= limit) continue;
            JsonObject row = new JsonObject();
            row.addProperty("id", id);
            row.addProperty("count", entry.getLongValue());
            // Component-bearing variants remain separate; no raw component/NBT payloads.
            row.addProperty("has_components", item.hasComponents());
            items.add(row);
        }
        result.add("items", items);
        result.addProperty("matching_variants_observed", matching);
        result.addProperty("partial_scan", partial);
        result.addProperty("truncated", partial || matching > offset + limit);
        result.addProperty("pagination_note", "Live inventory order can change between requests; filter by item ID for precise queries.");
        return result;
    }
}
