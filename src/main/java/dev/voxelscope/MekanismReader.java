package dev.voxelscope;

import com.google.gson.JsonObject;
import mekanism.api.chemical.IChemicalTank;
import mekanism.generators.common.tile.fission.TileEntityFissionReactorCasing;
import net.minecraft.world.level.block.entity.BlockEntity;

/** Exact-version adapter. Does not call setters, simulation, insertion, or extraction methods. */
final class MekanismReader {
    static void fission(BlockEntity block, JsonObject result) {
        if (!(block instanceof TileEntityFissionReactorCasing casing)) return;
        var reactor = casing.getMultiblock();
        JsonObject data = new JsonObject();
        data.addProperty("formed", reactor.isFormed());
        if (reactor.isFormed()) {
            data.addProperty("active", reactor.isActive());
            data.addProperty("burning", reactor.isBurning());
            data.addProperty("set_burn_rate_mb_per_tick", reactor.rateLimit);
            data.addProperty("actual_burn_rate_mb_per_tick", reactor.lastBurnRate);
            data.addProperty("max_burn_rate_mb_per_tick", reactor.getMaxBurnRate());
            data.addProperty("temperature_kelvin", reactor.heatCapacitor.getTemperature());
            data.addProperty("damage_percent", reactor.reactorDamage);
            data.addProperty("last_boil_rate_mb_per_tick", reactor.lastBoilRate);
            data.add("fuel", chemical(reactor.fuelTank));
            data.add("waste", chemical(reactor.wasteTank));
            data.add("heated_coolant", chemical(reactor.heatedCoolantTank));
            data.add("chemical_coolant", chemical(reactor.coolantTank.getChemicalTank()));
            var fluid = reactor.coolantTank.getFluidTank();
            JsonObject coolant = new JsonObject();
            coolant.addProperty("amount_mb", fluid.getFluidAmount());
            coolant.addProperty("capacity_mb", fluid.getCapacity());
            data.add("fluid_coolant", coolant);
        }
        result.add("mekanism_fission", data);
    }

    private static JsonObject chemical(IChemicalTank tank) {
        JsonObject data = new JsonObject();
        data.addProperty("id", tank.getStack().getTypeRegistryName().toString());
        data.addProperty("amount_mb", tank.getStored());
        data.addProperty("capacity_mb", tank.getCapacity());
        return data;
    }
}
