package dev.voxelscope;

import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import mekanism.api.energy.IEnergyConversionHelper;
import mekanism.common.capabilities.Capabilities;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.server.level.ServerLevel;

/** One capability adapter covers Mekanism tanks, processing machines, pipes, and compatible addons. */
final class MekanismCapabilitiesReader {
    static void read(ServerLevel level, BlockPos pos, Direction side, JsonObject result, int limit) {
        var chemicals = level.getCapability(Capabilities.CHEMICAL.block(), pos, side);
        if (chemicals != null) {
            JsonArray tanks = new JsonArray();
            for (int i = 0; i < Math.min(chemicals.getChemicalTanks(), limit); i++) {
                var stack = chemicals.getChemicalInTank(i);
                JsonObject tank = new JsonObject();
                tank.addProperty("tank", i);
                tank.addProperty("id", stack.getChemicalHolder().unwrapKey().map(key -> key.location().toString()).orElse("unknown"));
                tank.addProperty("amount_mb", stack.getAmount());
                tank.addProperty("capacity_mb", chemicals.getChemicalTankCapacity(i));
                tanks.add(tank);
            }
            result.add("chemical_tanks", tanks);
            result.addProperty("chemical_tanks_truncated", chemicals.getChemicalTanks() > limit);
        }
        var energy = level.getCapability(Capabilities.STRICT_ENERGY.block(), pos, side);
        if (energy != null) {
            JsonArray containers = new JsonArray();
            var conversion = IEnergyConversionHelper.INSTANCE.feConversion();
            for (int i = 0; i < Math.min(energy.getEnergyContainerCount(), limit); i++) {
                JsonObject data = new JsonObject();
                data.addProperty("container", i);
                data.addProperty("stored_fe", conversion.convertTo(energy.getEnergy(i)));
                data.addProperty("capacity_fe", conversion.convertTo(energy.getMaxEnergy(i)));
                containers.add(data);
            }
            result.add("mekanism_energy_containers", containers);
            result.addProperty("mekanism_energy_containers_truncated", energy.getEnergyContainerCount() > limit);
        }
    }
}
