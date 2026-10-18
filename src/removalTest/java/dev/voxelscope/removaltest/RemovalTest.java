package dev.voxelscope.removaltest;

import net.minecraft.core.BlockPos;
import net.minecraft.gametest.framework.GameTest;
import net.minecraft.gametest.framework.GameTestHelper;
import net.minecraft.world.item.Items;
import net.minecraft.world.level.block.entity.ChestBlockEntity;
import net.neoforged.fml.ModList;
import net.neoforged.fml.common.Mod;
import net.neoforged.neoforge.gametest.GameTestHolder;
import net.neoforged.neoforge.gametest.PrefixGameTestTemplate;

/** No dependency on the bridge, its classes, or its metadata. Not packaged for users. */
@Mod("removaltest")
@GameTestHolder("removaltest")
@PrefixGameTestTemplate(false)
public class RemovalTest {
    @GameTest(template = "empty", timeoutTicks = 1000)
    public static void reopenSavedWorldWithoutBridge(GameTestHelper helper) {
        helper.assertTrue(!ModList.get().isLoaded("voxelscope"), "Bridge must be absent from loader");
        BlockPos sentinel = new BlockPos(32, 80, 32);
        helper.getLevel().getChunkAt(sentinel);
        var block = helper.getLevel().getBlockEntity(sentinel);
        helper.assertTrue(block instanceof ChestBlockEntity, "Previously saved chest survives bridge removal");
        var stack = ((ChestBlockEntity) block).getItem(0);
        helper.assertTrue(stack.is(Items.DIAMOND) && stack.getCount() == 7, "Saved inventory survives bridge removal");
        helper.succeed();
    }
}
