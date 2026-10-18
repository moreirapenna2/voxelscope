package dev.voxelscope;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import net.minecraft.core.registries.BuiltInRegistries;
import net.neoforged.neoforge.energy.IEnergyStorage;
import net.neoforged.neoforge.fluids.capability.IFluidHandler;
import net.neoforged.neoforge.items.IItemHandler;

/** Shared across arbitrary blocks and entities exposing standard capabilities. */
final class CapabilityReader {
    static void energy(IEnergyStorage energy, JsonObject result) {
        if (energy == null) return;
        JsonObject data = new JsonObject();
        data.addProperty("stored_fe", energy.getEnergyStored());
        data.addProperty("capacity_fe", energy.getMaxEnergyStored());
        data.addProperty("note", "Generic FE readings may be clamped to 32-bit; no throughput measurement.");
        result.add("energy", data);
    }

    static void inventory(IItemHandler inventory, JsonObject result, int offset, int limit) {
        if (inventory == null) return;
        JsonObject data = new JsonObject();
        data.addProperty("slots", inventory.getSlots());
        JsonArray items = new JsonArray();
        int end = (int) Math.min((long) inventory.getSlots(), (long) offset + limit);
        for (int slot = offset; slot < end; slot++) {
            var stack = inventory.getStackInSlot(slot);
            if (stack.isEmpty()) continue;
            JsonObject item = new JsonObject();
            item.addProperty("slot", slot);
            item.addProperty("id", BuiltInRegistries.ITEM.getKey(stack.getItem()).toString());
            item.addProperty("count", stack.getCount());
            items.add(item);
        }
        data.add("items", items);
        data.addProperty("offset", offset);
        data.addProperty("truncated", end < inventory.getSlots());
        if (end < inventory.getSlots()) data.addProperty("next_offset", end);
        result.add("inventory", data);
    }

    static void fluids(IFluidHandler fluids, JsonObject result, int limit) {
        if (fluids == null) return;
        JsonArray tanks = new JsonArray();
        for (int tank = 0; tank < Math.min(fluids.getTanks(), limit); tank++) {
            var stack = fluids.getFluidInTank(tank);
            JsonObject data = new JsonObject();
            data.addProperty("tank", tank);
            data.addProperty("id", BuiltInRegistries.FLUID.getKey(stack.getFluid()).toString());
            data.addProperty("amount_mb", stack.getAmount());
            data.addProperty("capacity_mb", fluids.getTankCapacity(tank));
            tanks.add(data);
        }
        result.add("fluid_tanks", tanks);
        result.addProperty("fluid_tanks_truncated", fluids.getTanks() > limit);
    }
}
