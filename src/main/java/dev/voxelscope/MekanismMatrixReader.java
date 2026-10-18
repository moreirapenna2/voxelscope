package dev.voxelscope;

import com.google.gson.JsonObject;
import mekanism.api.energy.IEnergyConversionHelper;
import mekanism.common.tile.multiblock.TileEntityInductionCasing;
import net.minecraft.world.level.block.entity.BlockEntity;

/** Loaded only with Mekanism; independent of the optional Generators module. */
final class MekanismMatrixReader {
    static void matrix(BlockEntity block, JsonObject result) {
        if (!(block instanceof TileEntityInductionCasing casing)) return;
        var matrix = casing.getMultiblock();
        JsonObject data = new JsonObject();
        data.addProperty("formed", matrix.isFormed());
        if (matrix.isFormed()) {
            var conversion = IEnergyConversionHelper.INSTANCE.feConversion();
            data.addProperty("stored_fe", conversion.convertTo(matrix.getEnergy()));
            data.addProperty("capacity_fe", conversion.convertTo(matrix.getStorageCap()));
            data.addProperty("last_input_fe_per_tick", conversion.convertTo(matrix.getLastInput()));
            data.addProperty("last_output_fe_per_tick", conversion.convertTo(matrix.getLastOutput()));
            data.addProperty("transfer_cap_fe_per_tick", conversion.convertTo(matrix.getTransferCap()));
        }
        result.add("mekanism_matrix", data);
    }

}
